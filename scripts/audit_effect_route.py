"""效果路由真实性审计 (Effect-Route Audit) — 第三轮多轮审计.

目标: 验证"动态层优于基本盘则接管"是真闭环, 不是假绿.

验证维度(基于 nexus.py 真实逻辑):
  R1 接管真生效: set_route_override(base,dyn) 后 dispatch(base) 真走 dyn 实例
  R2 回退真生效: record_effect 动态变劣(-0.1) 后 override 真删除, dispatch 回基本盘
  R3 代理层路由: NexusProxy 转发 dispatch 时 route_override 真生效(不绕过)
  R4 接管稳定: 动态持续更优(+0.05) 时 override 保持(不误删)

方法: 用真实 Nexus 实例 + 真实机制类, 触发路由, 断言 dispatch 返回来自正确后端.
"""
from __future__ import annotations
import logging
import os
import sys
import tempfile

logging.disable(logging.CRITICAL)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class BaseMech:
    def run(self):
        return {"via": "base"}


class DynMech:
    def run(self):
        return {"via": "dynamic"}


def audit():
    from prometheus_nexus.cns.nexus import Nexus
    db = tempfile.mktemp(suffix=".db")
    nx = Nexus(path=db, store=None)

    # 注册基本盘 + 动态层
    nx.register_mechanism("routing_base", BaseMech(), category="general")
    nx.mount_dynamic("routing_dyn", DynMech(), category="compiled")

    results = {}

    # R1: 接管真生效
    nx.set_route_override("routing_base", "routing_dyn")
    r1_disp = nx.dispatch("routing_base", "run")
    results["R1_override_set"] = nx._route_override.get("routing_base") == "routing_dyn"
    results["R1_dispatch_via_dynamic"] = (r1_disp or {}).get("via") == "dynamic"
    # 直接调基本盘名也应走动态(经 override)
    results["R1_base_name_routes_to_dyn"] = (nx.dispatch("routing_base", "run") or {}).get("via") == "dynamic"

    # R3: 代理层路由(用 NexusProxy 包裹基本盘, dispatch 经代理)
    from prometheus_nexus.cns.nexus import NexusProxy
    proxy = NexusProxy(BaseMech(), nx, "routing_base")
    # proxy 透明转发到 nexus.dispatch -> 应走动态实例
    r3 = proxy.run()
    results["R3_proxy_routes_to_dynamic"] = (r3 or {}).get("via") == "dynamic"

    # R2: 回退真生效 — 动态变劣
    # 先给基本盘一个正效果基线
    for _ in range(5):
        nx.record_effect("routing_base", 0.8)
    # 动态持续负效果 (< base - 0.1)
    for _ in range(5):
        nx.record_effect("routing_dyn", -0.5)
    results["R2_override_removed"] = "routing_base" not in nx._route_override
    # 回退后 dispatch 应走基本盘
    r2_disp = nx.dispatch("routing_base", "run")
    results["R2_dispatch_via_base"] = (r2_disp or {}).get("via") == "base"

    # R4: 接管稳定 — 动态持续更优时 override 保持
    nx2 = Nexus(path=tempfile.mktemp(suffix=".db"), store=None)
    nx2.register_mechanism("stable_base", BaseMech(), category="general")
    nx2.mount_dynamic("stable_dyn", DynMech(), category="compiled")
    nx2.set_route_override("stable_base", "stable_dyn")
    # 基本盘基线 + 动态更优
    for _ in range(5):
        nx2.record_effect("stable_base", 0.4)
    for _ in range(5):
        nx2.record_effect("stable_dyn", 0.9)  # > base + 0.05
    results["R4_override_held"] = nx2._route_override.get("stable_base") == "stable_dyn"
    results["R4_dispatch_still_dynamic"] = (nx2.dispatch("stable_base", "run") or {}).get("via") == "dynamic"

    return results


if __name__ == "__main__":
    r = audit()
    print("=" * 64)
    print("效果路由真实性审计 (Effect-Route Audit) — 第三轮")
    print("=" * 64)
    checks = {
        "R1_override_set": "set_route_override 真写入 override",
        "R1_dispatch_via_dynamic": "dispatch(base) 真走动态实例(接管生效)",
        "R1_base_name_routes_to_dyn": "基本盘名经 override 路由到动态",
        "R3_proxy_routes_to_dynamic": "NexusProxy 转发经 override 路由动态(代理不绕过)",
        "R2_override_removed": "动态变劣后 override 真删除(回退生效)",
        "R2_dispatch_via_base": "回退后 dispatch(base) 真走基本盘",
        "R4_override_held": "动态持续更优时 override 保持(接管稳定)",
        "R4_dispatch_still_dynamic": "持续更优时 dispatch 仍走动态",
    }
    passed = 0
    for k, desc in checks.items():
        ok = r.get(k, False)
        passed += int(ok)
        print(f"  [{'PASS' if ok else 'FAIL'}] {k}: {desc}")
    print("-" * 64)
    print(f"{passed}/{len(checks)} 路由真实性检查通过")
    print("=" * 64)
    if passed == len(checks):
        print("结论: 效果路由是真闭环(接管/回退/代理/稳定均真实生效, 非假绿)")
    else:
        print("结论: 发现路由假绿/断裂点, 需修复")
