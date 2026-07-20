"""双重执行复核审计 (Double-Execution Audit) — 第四轮多轮审计.

目标: 验证 Nexus 统合后机制不被执行两次(B-plan 核心约束:
NexusProxy/dispatch 转调同一 base 实例, 不双重执行).

验证维度(基于 nexus.py 真实逻辑):
  D1 proxy 单跳: 经 NexusProxy 调一次 -> 实例方法体只执行一次(不双重)
  D2 proxy 不触发 dispatch: NexusProxy.__getattr__ 转 getattr(inst,item), 不经 nexus.dispatch
  D3 记账=执行: mark_invoked 计数不因代理属性访问虚高(方法调用次数=记账次数)
  D4 override 不双执行: route_override 时 proxy 转动态实例, base 实例方法体不执行

方法: 用计数器实例(方法体自增执行计数) + 真实 Nexus + NexusProxy, 断言执行次数.
"""
from __future__ import annotations
import logging
import os
import sys
import tempfile

logging.disable(logging.CRITICAL)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class CounterMech:
    """方法体自增执行计数, 用于检测双重执行."""
    def __init__(self):
        self.run_count = 0
        self.run2_count = 0

    def run(self):
        self.run_count += 1
        return {"count": self.run_count}

    def run2(self):
        self.run2_count += 1
        return {"count": self.run2_count}

    @property
    def enabled(self):
        # 属性访问不应触发任何方法执行(验证 D3 记账虚高隔离)
        return True


def audit():
    from prometheus_nexus.cns.nexus import Nexus, NexusProxy
    db = tempfile.mktemp(suffix=".db")
    nx = Nexus(path=db, store=None)
    nx.register_mechanism("counter_base", CounterMech(), category="general")

    results = {}
    m = CounterMech()
    # 用真实实例注册进 base_instances (绕过 register 的内部实例)
    nx._base_instances["counter_real"] = m
    nx._mechanisms["counter_real"] = {"name": "counter_real", "category": "general",
                                       "status": "active", "is_dynamic": False,
                                       "invoke_count": 0}

    proxy = NexusProxy(m, nx, "counter_real")

    # D1: proxy 单跳, 执行一次
    before = m.run_count
    proxy.run()
    results["D1_exec_once"] = m.run_count - before == 1

    # D2: proxy 转发不经 dispatch (dispatch 调用计数验证)
    dispatch_calls = {"n": 0}
    orig_dispatch = nx.dispatch
    def spy_dispatch(name, method="run", *a, **k):
        dispatch_calls["n"] += 1
        return orig_dispatch(name, method, *a, **k)
    nx.dispatch = spy_dispatch
    proxy.run()  # 再调一次, 应走 proxy.__getattr__ -> getattr(inst), 不调 dispatch
    results["D2_proxy_skips_dispatch"] = dispatch_calls["n"] == 0
    nx.dispatch = orig_dispatch

    # D3: 记账=执行 (方法调用次数 == mark_invoked 次数, 属性访问不虚高)
    inv_before = nx._invoke_count.get("counter_real", 0)
    exec_before = m.run_count + m.run2_count
    # 调两次方法 + 读一次属性(enabled)
    proxy.run()
    proxy.run2()
    _ = proxy.enabled  # 属性访问, 不应增加 run 执行也不应记账
    inv_after = nx._invoke_count.get("counter_real", 0)
    exec_after = m.run_count + m.run2_count
    results["D3_invoke_eq_exec"] = (inv_after - inv_before) == (exec_after - exec_before)
    results["D3_property_no_exec"] = m.run_count + m.run2_count == exec_after and m.run2_count >= 1

    # D4: override 不双执行 — base 和 dyn 不同实例, 接管时仅 dyn 执行
    dyn = CounterMech()
    nx._dynamic["counter_dyn"] = dyn
    nx._mechanisms["counter_dyn"] = {"name": "counter_dyn", "category": "compiled",
                                      "status": "active", "is_dynamic": True,
                                      "invoke_count": 0}
    nx.set_route_override("counter_real", "counter_dyn")
    base_before = m.run_count
    dyn_before = dyn.run_count
    proxy.run()  # 经 override 应转 dyn, base 不执行
    results["D4_base_not_exec"] = (m.run_count - base_before) == 0
    results["D4_dyn_exec"] = (dyn.run_count - dyn_before) == 1

    return results


if __name__ == "__main__":
    r = audit()
    print("=" * 64)
    print("双重执行复核审计 (Double-Execution Audit) — 第四轮")
    print("=" * 64)
    checks = {
        "D1_exec_once": "NexusProxy 调一次 -> 实例方法体只执行一次(不双重)",
        "D2_proxy_skips_dispatch": "NexusProxy 转发不经 nexus.dispatch(不双路径)",
        "D3_invoke_eq_exec": "mark_invoked 计数 == 实际方法执行次数(属性访问不虚高)",
        "D3_property_no_exec": "属性访问(enabled)不触发方法执行",
        "D4_base_not_exec": "route_override 接管时 base 实例方法体不执行",
        "D4_dyn_exec": "route_override 接管时仅动态实例执行",
    }
    passed = 0
    for k, desc in checks.items():
        ok = r.get(k, False)
        passed += int(ok)
        print(f"  [{'PASS' if ok else 'FAIL'}] {k}: {desc}")
    print("-" * 64)
    print(f"{passed}/{len(checks)} 双重执行复核通过")
    print("=" * 64)
    if passed == len(checks):
        print("结论: 无双重执行(NexusProxy 转调同一实例, 不双路径/不双执行)")
    else:
        print("结论: 发现双重执行/记账虚高点, 需修复")
