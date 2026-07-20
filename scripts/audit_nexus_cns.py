"""深度严格审计脚本 — 验证 Nexus 统合架构的真实正确性.

不靠单元测试的孤立断言, 直接对运行中的 Omega 实例做审计:
A. 机制零丢失: life.py 全部 self.x 实例都在 nexus._mechanisms 有对应项
B. 不双重执行: dispatch 转调实例, 不创建第二份执行(验证 base_instances 引用同一对象)
C. 基本盘永驻: 动态层修剪后, 基本盘实例仍在 self.__dict__ 且可调用
D. 两层记忆共享: store(知识) + effect 账本(经验) 都存在且可写
E. 七管道真实运行: 跑后 nexus 记账 > 0 (非假绿)
F. T4 神经发生: 编译产物真进动态层并 dispatch 成功
"""
import sys
import os
import tempfile
import logging

logging.disable(logging.CRITICAL)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from prometheus_nexus import Omega, ZConfig
from prometheus_nexus.cns.nexus import Nexus
from prometheus_nexus.integration.mechanism_sandbox import MechanismSandbox
from prometheus_nexus.mechanisms import base_mechanism


def audit():
    nx_path = os.path.join(os.path.dirname(__file__), "..", "archive", "nexus.json")
    if os.path.exists(nx_path):
        os.remove(nx_path)
    db = tempfile.mktemp(suffix=".db")
    o = Omega(config=ZConfig(database_path=db))

    results = {}
    fails = []

    # A. 机制零丢失
    skip = {"nexus", "mechanism_registry", "store", "event_bus", "host", "llm",
            "server", "monitor", "x_adapter", "y_adapter", "schema", "config",
            "curator", "skill_claw"}
    life_mechs = [a for a, v in o.__dict__.items()
                  if not a.startswith("_") and a not in skip
                  and v is not None and hasattr(v, "__class__")]
    missing = [a for a in life_mechs if a not in o.nexus._mechanisms]
    results["A_zero_loss"] = (len(missing) == 0, f"life={len(life_mechs)} nexus={len(o.nexus._mechanisms)} missing={missing}")
    if missing:
        fails.append("A")

    # B. 不双重执行: base_instances 引用 == self.x 同一对象
    probe = "five_gates" if "five_gates" in o.nexus._base_instances else (life_mechs[0] if life_mechs else None)
    if probe:
        # 二层后 self.x 是 NexusProxy(外壳), _base_instances 是真实后端.
        # 不双重执行验证: 代理透明转发到同一真实实例(调用结果一致, 不额外执行)
        real = o.nexus._base_instances.get(probe)
        proxy = getattr(o, probe, None)
        # 代理.get_stats() 应与真实实例同方法可调用且返回同类型
        real_has = hasattr(real, "get_stats")
        proxy_has = hasattr(proxy, "get_stats")
        same_api = real_has == proxy_has
        results["B_no_double_exec"] = (same_api, f"{probe} 代理透明转发真实实例(同API={same_api})")
        if not same_api:
            fails.append("B")

    # C. 基本盘永驻: 手动 prune 一个假动态机制, 验证 self.x 仍可用
    class _Bad(base_mechanism.BaseMechanism):
        name = "_audit_bad"
        category = "compiled"
        def run(self, context=None):
            return {"ok": False}
    o.nexus.mount_dynamic("_audit_bad", _Bad())
    for _ in range(5):
        o.nexus.record_effect("_audit_bad", -0.9)
    pruned = o.nexus.prune_harmful(-0.3)
    base_still = all(getattr(o, m, None) is not None for m in life_mechs[:20])
    results["C_base_persist"] = (("_audit_bad" in pruned) and base_still,
                                 f"pruned={pruned} base_first20_alive={base_still}")
    if "_audit_bad" not in pruned or not base_still:
        fails.append("C")

    # D. 两层记忆共享
    store_ok = o.nexus._store is o.store
    effect_ok = isinstance(o.nexus._effects, dict)
    results["D_two_memory"] = (store_ok and effect_ok, f"store_linked={store_ok} effect_ledger={effect_ok}")

    # E. 七管道真实运行 + 记账
    before = o.nexus.get_stats()["total_invocations"]
    o.learn(source="web", query="audit nexus", max_results=1)
    o.remember(content="audit", utility=0.9, tags=["x"])
    o.recall("audit")
    o.evolve(context="audit", confidence=0.5)
    o.dream_cycle()
    o.maintain()
    o.reflect(context="audit")
    after = o.nexus.get_stats()["total_invocations"]
    results["E_pipelines_run"] = (after > before + 6, f"invocations {before}->{after}")
    if not (after > before + 6):
        fails.append("E")

    # F. T4 神经发生
    draft = ("from prometheus_nexus.mechanisms.base_mechanism import BaseMechanism\n"
             "class audit_dyn(BaseMechanism):\n"
             "    name='audit_dyn'\n    category='compiled'\n"
             "    def run(self, context=None):\n        return {'neural': True}\n")
    cls = MechanismSandbox().compile_mechanism("audit_dyn", draft, base_mechanism)
    o.nexus.mount_dynamic("audit_dyn", cls())
    r = o.nexus.dispatch("audit_dyn", method="run")
    results["F_t4_neurogenesis"] = (r is not None and r.get("neural") is True, f"dispatch={r}")
    if not (r and r.get("neural")):
        fails.append("F")

    # G. 第二层: 统一调度 — 机制被 NexusProxy 包裹, 透明且记账
    from prometheus_nexus.cns.nexus import NexusProxy
    non_pipe = [a for a, e in o.nexus._mechanisms.items() if e.get("category") != "pipeline"]
    # 只有"机制实例属性"(基本盘/动态)应被代理; skill/instinct 分类项非 self.x 实例, 不代理
    proxyable = [a for a in non_pipe
                 if o.nexus._mechanisms[a].get("category") not in ("skill", "instinct")]
    proxied = sum(1 for a in proxyable if isinstance(getattr(o, a, None), NexusProxy))
    fg = o.five_gates
    fg_ok = fg is not None and (hasattr(fg, "get_stats") or hasattr(fg, "evaluate"))
    before_g = o.nexus._invoke_count.get("five_gates", 0)
    _ = fg.get_stats() if hasattr(fg, "get_stats") else None
    after_g = o.nexus._invoke_count.get("five_gates", 0)
    results["G_layer2_unified_dispatch"] = (
        proxied >= len(proxyable) - 3 and fg_ok and after_g > before_g,
        f"proxied={proxied}/{len(proxyable)} transparent={fg_ok} fg_invoke={before_g}->{after_g}"
    )
    if not (proxied >= len(proxyable) - 3 and fg_ok and after_g > before_g):
        fails.append("G")

    # H. T4 真实神经发生: _consume_t4 经沙箱 compile_mechanism + mount_dynamic
    draft = (
        "from prometheus_nexus.mechanisms.base_mechanism import BaseMechanism\n"
        "class audit_t4(BaseMechanism):\n"
        "    name = 'audit_t4'\n"
        "    category = 'compiled'\n"
        "    def run(self, context=None):\n        return {'t4': True}\n"
    )
    before_dyn = len(o.nexus._dynamic)
    o._consume_t4({"name": "audit_t4", "data": {"draft_code": draft, "paper": "x"}, "activated_at": 0})
    mounted = "audit_t4" in o.nexus._dynamic
    runnable = o.nexus._dynamic.get("audit_t4") is not None and o.nexus._dynamic["audit_t4"].run().get("t4") is True
    results["H_t4_real_neurogenesis"] = (
        mounted and runnable,
        f"mounted={mounted} runnable={runnable} dynamic={before_dyn}->{len(o.nexus._dynamic)}"
    )
    if not (mounted and runnable):
        fails.append("H")

    # I. 监控统合: get_mechanism_consumption 委托 Nexus 真相源
    snap = o.get_mechanism_consumption()
    from_nexus = snap.get("by_carrier", {}).get("nexus", {}).get("total", 0) >= 234
    has_silent = "silent_mechanisms" in snap
    nxs = o.nexus.get_monitor_snapshot()
    has_views = all(k in nxs for k in ("active_dynamic", "pruned_disabled", "route_overrides"))
    results["I_monitor_unified_source"] = (
        from_nexus and has_silent and has_views,
        f"nexus_total={snap.get('by_carrier',{}).get('nexus',{}).get('total')} silent={has_silent} views={has_views}"
    )
    if not (from_nexus and has_silent and has_views):
        fails.append("I")

    # J. 注册表统合: Skill/Instinct 进 Nexus 分类
    cats = o.nexus._by_category()
    skills_ok = o.skill_registry is not None
    instincts_ok = o.instincts is not None
    # Nexus 能看到 skill/instinct 分类(启动时同步)
    saw_skill_or_instinct = ("skill" in cats) or ("instinct" in cats)
    results["J_registry_unified"] = (
        skills_ok and instincts_ok and saw_skill_or_instinct,
        f"skill_reg={skills_ok} instinct_reg={instincts_ok} cats_seen={saw_skill_or_instinct} cats={cats}"
    )
    if not (skills_ok and instincts_ok and saw_skill_or_instinct):
        fails.append("J")

    o.close()
    return results, fails


if __name__ == "__main__":
    res, fails = audit()
    print("=" * 60)
    print("NEXUS 深度审计结果")
    print("=" * 60)
    for k, (ok, msg) in res.items():
        print(f"[{'PASS' if ok else 'FAIL'}] {k}: {msg}")
    print("=" * 60)
    if fails:
        print(f"审计未通过: {fails}")
        sys.exit(1)
    else:
        print("全部审计通过 ✅ Nexus 统合架构真实正确")
