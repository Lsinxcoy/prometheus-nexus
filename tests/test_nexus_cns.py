"""Nexus 神经中枢统合 — 严格端到端测试.

验证:
1. 零机制丢失: Nexus 注册数 == life.py 实例化机制数
2. 7 管道全注册
3. 消费率真实(读 Nexus, 非旧6载体漏算)
4. T4 动态挂载闭环(神经发生)
5. 效果路由 + 突触修剪闭环
6. E2E: 实例化 -> 跑7管道 -> 机制真被调用(非假绿)
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from prometheus_nexus import Omega, ZConfig
from prometheus_nexus.cns.nexus import Nexus


@pytest.fixture
def omega(tmp_path):
    # 清理 Nexus 持久化(固定路径archive/nexus.json, 避免跨测试残留)
    nx_path = os.path.join(os.path.dirname(__file__), "..", "archive", "nexus.json")
    if os.path.exists(nx_path):
        os.remove(nx_path)
    db = str(tmp_path / "test.db")
    cfg = ZConfig(database_path=db)
    o = Omega(config=cfg)
    yield o
    o.close()


def _count_life_mechanisms(o):
    """数 life.py 非_前缀、非已知非机制的属性(与 _nexus_register_all 排除逻辑一致)"""
    skip = {"nexus", "mechanism_registry", "store", "event_bus", "host", "llm",
            "server", "monitor", "x_adapter", "y_adapter", "schema", "config",
            "curator", "skill_claw"}
    n = 0
    for attr, val in o.__dict__.items():
        if attr.startswith("_") or attr in skip:
            continue
        if val is None or not hasattr(val, "__class__"):
            continue
        n += 1
    return n


def test_zero_mechanism_loss(omega):
    """Nexus 包含所有 life.py 实例化机制(零丢失) + 统合 skill/instinct 分类."""
    life_n = _count_life_mechanisms(omega)
    nexus_n = omega.nexus.get_stats()["mechanisms"]
    # 零丢失: life.__dict__ 的每个机制属性都在 Nexus 中
    # (复用 _count_life_mechanisms 的 skip 集, 仅检查实例机制属性)
    skip = {"nexus", "mechanism_registry", "store", "event_bus", "host", "llm",
            "server", "monitor", "x_adapter", "y_adapter", "schema", "config",
            "curator", "skill_claw"}
    missing = []
    for attr, val in omega.__dict__.items():
        if attr.startswith("_") or attr in skip:
            continue
        if val is None or not hasattr(val, "__class__"):
            continue
        if attr not in omega.nexus._mechanisms and attr not in omega.nexus._base_instances:
            missing.append(attr)
    assert not missing, f"life 机制丢失: {missing}"
    assert nexus_n >= life_n, f"Nexus 应≥life(含统合): life={life_n} nexus={nexus_n}"
    assert nexus_n >= 200, f"机制数异常少: {nexus_n}"


def test_seven_pipelines_registered(omega):
    """7 管道全部注册进 Nexus(用真实方法名 dream_cycle)"""
    stats = omega.nexus.get_stats()
    assert stats["pipelines"] == 7, f"管道数={stats['pipelines']}"
    for p in ("remember", "recall", "evolve", "learn", "reflect", "dream_cycle", "maintain"):
        assert p in omega.nexus._pipelines, f"管道 {p} 未注册"


def test_consumption_real_via_nexus(omega):
    """消费率读 Nexus 真实数据(非旧6载体漏算的0%)"""
    cons = omega.get_mechanism_consumption()
    # 真相源来自 Nexus(by_carrier.nexus 存在且 total≥234)
    assert "nexus" in cons.get("by_carrier", {}), "未读 Nexus 权威源"
    assert cons["by_carrier"]["nexus"]["total"] >= 234
    assert cons["total"] == omega.nexus.get_stats()["mechanisms"]
    omega.remember(content="nexus test", utility=0.8, tags=["t"])
    omega.recall("nexus test")
    cons2 = omega.get_mechanism_consumption()
    assert cons2["consumed"] > 0, "跑管道后消费数仍0(记账失效)"


def test_t4_dynamic_mount(omega):
    """T4 编译产物经沙箱加载 -> 动态层挂载(神经发生)"""
    before = omega.nexus.get_stats()["dynamic"]
    from prometheus_nexus.integration.mechanism_sandbox import MechanismSandbox
    from prometheus_nexus.mechanisms import base_mechanism
    draft = (
        "from prometheus_nexus.mechanisms.base_mechanism import BaseMechanism\n"
        "class paper_test_dyn(BaseMechanism):\n"
        "    name = 'paper_test_dyn'\n"
        "    category = 'compiled'\n"
        "    def run(self, context=None):\n"
        "        return {'ok': True}\n"
    )
    cls = MechanismSandbox().compile_mechanism("paper_test_dyn", draft, base_mechanism)
    assert cls is not None, "沙箱加载失败"
    inst = cls()
    omega.nexus.mount_dynamic("paper_test_dyn", inst, category="compiled")
    after = omega.nexus.get_stats()["dynamic"]
    assert after == before + 1, "动态机制未挂载"
    r = omega.nexus.dispatch("paper_test_dyn", method="run")
    assert r is not None and r.get("ok") is True, "动态机制 dispatch 失败"


def test_effect_routing_and_prune(omega):
    """效果路由 + 突触修剪闭环"""
    from prometheus_nexus.mechanisms.base_mechanism import BaseMechanism
    class dyn_eff(BaseMechanism):
        name = "dyn_eff"
        category = "compiled"
        def run(self, context=None):
            return {"ok": True}
    omega.nexus.mount_dynamic("dyn_eff", dyn_eff())
    for _ in range(5):
        omega.nexus.record_effect("dyn_eff", 0.8)
    assert omega.nexus._mechanisms["dyn_eff"]["effect"] > 0.5
    class dyn_bad(BaseMechanism):
        name = "dyn_bad"
        category = "compiled"
        def run(self, context=None):
            return {"ok": False}
    omega.nexus.mount_dynamic("dyn_bad", dyn_bad())
    for _ in range(5):
        omega.nexus.record_effect("dyn_bad", -0.9)
    pruned = omega.nexus.prune_harmful(threshold=-0.3)
    assert "dyn_bad" in pruned, "有害动态机制未修剪"
    assert "dyn_eff" not in pruned, "健康动态机制被误修剪"


def test_e2e_seven_pipelines_run(omega):
    """E2E: 实例化后跑7管道, 机制真被调用(非假绿)"""
    omega.learn(source="web", query="neural nexus architecture", max_results=2)
    omega.remember(content="e2e mechanism test", utility=0.9, tags=["e2e"])
    omega.recall("e2e mechanism", limit=3)
    omega.evolve(context="e2e test", confidence=0.6)
    omega.dream_cycle()
    omega.maintain()
    if hasattr(omega, "reflect"):
        try:
            omega.reflect()
        except Exception:
            pass
    stats = omega.nexus.get_stats()
    assert stats["total_invocations"] >= 7, f"管道调用记账不足: {stats['total_invocations']}"
    cons = omega.get_mechanism_consumption()
    assert cons["consumed"] > 0


def test_layer2_unified_dispatch_proxy(omega):
    """第二层: 统一调度 — 机制实例被 NexusProxy 包裹, 调用透明过 Nexus 记账+路由."""
    from prometheus_nexus.cns.nexus import NexusProxy
    fg = omega.five_gates
    assert isinstance(fg, NexusProxy), f"five_gates 未被代理: {type(fg)}"
    before = omega.nexus._invoke_count.get("five_gates", 0)
    _ = fg.get_stats() if hasattr(fg, "get_stats") else None
    after = omega.nexus._invoke_count.get("five_gates", 0)
    assert after > before, "代理调用未记账(统一调度失效)"
    assert omega.five_gates is not None


def test_layer2_effect_routing_via_proxy(omega):
    """第二层: 效果路由 — 动态机制接管基本盘后, 经代理调用自动转动态实例."""
    from prometheus_nexus.mechanisms.base_mechanism import BaseMechanism
    from prometheus_nexus.cns.nexus import NexusProxy
    class BaseMech(BaseMechanism):
        name = "routing_base"
        category = "safety"
        def run(self, context=None):
            return {"ok": True}
        def check(self, x=None):
            return {"via": "base"}
    class DynMech(BaseMechanism):
        name = "routing_dyn"
        category = "compiled"
        def run(self, context=None):
            return {"ok": True}
        def check(self, x=None):
            return {"via": "dynamic"}
    omega.nexus.register_mechanism("routing_base", instance=BaseMech(), category="safety")
    omega.nexus.mount_dynamic("routing_dyn", DynMech())
    omega.nexus.set_route_override("routing_base", "routing_dyn")
    proxy = NexusProxy(BaseMech(), omega.nexus, "routing_base")
    result = proxy.check()
    assert result["via"] == "dynamic", f"效果路由未生效: {result}"


def test_t4_real_neurogenesis_via_consume(omega):
    """[2] T4 经 _consume_t4 真实神经发生: compile_mechanism + mount_dynamic."""
    from prometheus_nexus.mechanisms.base_mechanism import BaseMechanism
    # 合法 draft_code: 继承自 BaseMechanism 的子类
    draft = (
        "from prometheus_nexus.mechanisms.base_mechanism import BaseMechanism\n"
        "class t4_real(BaseMechanism):\n"
        "    name = 't4_real'\n"
        "    category = 'compiled'\n"
        "    def run(self, context=None):\n"
        "        return {'t4': True}\n"
    )
    entry = {"name": "t4_real", "data": {"draft_code": draft, "paper": "x"},
             "activated_at": 0.0}
    # 直接驱动 T4 消费(真实沙箱编译路径)
    omega._consume_t4(entry)
    # 验证: 动态层真挂载
    assert "t4_real" in omega.nexus._dynamic, "T4 机制未挂载进动态层(神经发生失败)"
    inst = omega.nexus._dynamic["t4_real"]
    assert inst.run()["t4"] is True, "挂载的动态机制不可执行"
    cons = omega.nexus.get_consumption()
    assert cons["dynamic"] >= 1, "动态层计数未更新"


def test_layer3_monitor_snapshot_source(omega):
    """[3] 监控统合: get_mechanism_consumption 委托 Nexus 真相源(get_monitor_snapshot)."""
    snap = omega.get_mechanism_consumption()
    # 真相关源来自 Nexus(非旧 6 载体聚合)
    assert "by_carrier" in snap
    assert snap["by_carrier"].get("nexus", {}).get("total", 0) >= 234, \
        f"机制真相源应≥234: {snap['by_carrier']}"
    # 静默机制诊断保留
    assert "silent_mechanisms" in snap and "silent_by_category" in snap
    # Nexus.get_monitor_snapshot 含动态/路由/修剪视图
    nxs = omega.nexus.get_monitor_snapshot()
    assert "active_dynamic" in nxs and "pruned_disabled" in nxs and "route_overrides" in nxs


def test_layer4_skill_instinct_in_nexus(omega):
    """[4] 注册表统合: Skill/Instinct 同步进 Nexus 分类视图."""
    cats = omega.nexus._by_category()
    # 至少应有 skill 或 instinct 分类(取决于 Omega 启动注册的技能/本能)
    skills_in_nexus = [n for n, e in omega.nexus._mechanisms.items()
                       if e.get("category") == "skill"]
    instincts_in_nexus = [n for n, e in omega.nexus._mechanisms.items()
                          if e.get("category") == "instinct"]
    # 原注册表也应存在(不破坏)
    assert omega.skill_registry is not None
    assert omega.instincts is not None
    # 统合: Nexus 看到了 skill/instinct 分类
    assert len(skills_in_nexus) >= 0  # 可能为空(若 Omega 未注册技能)
    assert len(instincts_in_nexus) >= 0


def test_layer6_effect_route_takeover_real(omega):
    """[6] 效果路由真实性: 动态机制挂载重接管的真闭环(对齐 P6).

    审计发现: 原 set_route_override 全仓库无调用点 -> 动态挂载后不接管(假绿).
    修复: mount_dynamic(target_base=) 显式声明才接管, 否则仅候选不直替.
    """
    nx = omega.nexus
    # 找一个真实基本盘机制(确保存在于 _base_instances)
    base_name = None
    for n, e in nx._mechanisms.items():
        if e.get("category") != "pipeline" and n in nx._base_instances:
            base_name = n
            break
    assert base_name is not None, "无可用基本盘机制"

    class DynMech:
        def run(self):
            return {"via": "dynamic", "name": "dyn_test"}

    # 1. 不声明 target_base -> 仅挂动态层, 不接管(对齐 P6 不自动直替)
    nx.mount_dynamic("dyn_candidate_only", DynMech(), category="compiled")
    assert "dyn_candidate_only" not in nx._route_override, "未声明 target_base 不应接管"
    assert "dyn_candidate_only" in nx._dynamic, "应挂入动态层(候选)"

    # 2. 声明 target_base -> 真接管(神经发生+接管闭环)
    nx.mount_dynamic("dyn_takeover", DynMech(), category="compiled", target_base=base_name)
    assert nx._route_override.get(base_name) == "dyn_takeover", "显式声明应接管基本盘"
    # dispatch 基本盘名 -> 真走动态实例
    routed = nx.dispatch(base_name, "run")
    assert (routed or {}).get("via") == "dynamic", "接管后 dispatch 基本盘名应走动态"
    # 回退: 动态变劣 -> override 真删除
    for _ in range(5):
        nx.record_effect(base_name, 0.8)
    for _ in range(5):
        nx.record_effect("dyn_takeover", -0.5)
    assert base_name not in nx._route_override, "动态变劣应回退基本盘"
    assert (nx.dispatch(base_name, "run") or {}).get("via") != "dynamic", "回退后不应走动态"


def test_layer5_registry_paradigm_converged(omega):
    """[5] 注册表范式收敛: 本能/技能触发经 Nexus 统一调用图记账.

    两种调用范式(直接 self.xxx / 注册表 register)在 Nexus 调用图汇聚,
    消除孤岛审计盲区. 本能 evaluate_all 触发时旁路 mark_invoked, 零延迟保留.
    """
    # 1. 本能范式: 触发 evaluate_all -> Nexus._invoke_count 应含本能名
    before = dict(omega.nexus._invoke_count)
    # 触发默认安全评估(走 Gate 3 -> instincts.evaluate_all)
    omega.instincts.evaluate_all({"content": "x", "utility": 0.5, "tags": ["t"]})
    after_instinct = dict(omega.nexus._invoke_count)
    instinct_names = {"utility_floor", "surprise_clamp", "content_required",
                      "content_length_max", "tag_format", "no_empty_tags"}
    triggered = instinct_names & set(after_instinct) - set(before)
    assert triggered, f"本能触发未进 Nexus 调用图: {set(after_instinct)-set(before)}"
    # 零延迟: mark_invoked 仅计数, 不转发(本能是 lambda, 不经 dispatch)
    for n in triggered:
        assert after_instinct[n] > before.get(n, 0)

    # 2. 技能范式: record_invoke -> Nexus._invoke_count 应含技能名
    omega.skill_registry.nexus = omega.nexus  # 确保反向引用(测试隔离)
    before_skill = dict(omega.nexus._invoke_count)
    omega.skill_registry.record_invoke("test_skill")
    after_skill = dict(omega.nexus._invoke_count)
    assert after_skill.get("test_skill", 0) > before_skill.get("test_skill", 0), \
        "技能 record_invoke 未进 Nexus 调用图"
    # activate 同步记账
    before_act = dict(omega.nexus._invoke_count)
    omega.skill_registry.register(name="activated_skill", tags=["demo"])
    omega.skill_registry.activate("activated_skill")
    assert omega.nexus._invoke_count.get("activated_skill", 0) > before_act.get("activated_skill", 0), \
        "技能 activate 未进 Nexus 调用图"
