"""回归测试: MechanismRegistry.verify_and_activate 的安全门失败关闭(fail-closed).

根因: 三道安全验证门(IronLaw / AntiEvo / FGGM)若执行时抛异常, 原代码在
except 中把该门记为 passed=True (note='unavailable'), 并以 logger.debug 降级。
而 verify_and_activate 仅在 passed is False 时阻断(全部通过才激活), 于是
"未能验证"的机制被静默激活并接生产 —— 与安全契约"全部通过才激活"直接矛盾。

修复: 失败关闭。安全门执行异常 = 未能验证 = passed=False, 并记录 error、
以 logger.warning 暴露。机制被阻断, 不进 _enabled, 不接生产。

测试验证:
- IronLaw 门异常 -> 机制不被激活, gate.passed=False, 不在 _enabled
- AntiEvo 门异常 -> 同上
- 安全门正常运行且通过 -> 机制照常激活(确保修复未误伤 happy path)
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from prometheus_nexus.mechanisms.registry import MechanismRegistry
import prometheus_nexus.evolution.iron_law as iron_law_mod
import prometheus_nexus.evolution.anti_evolution_gate as anti_evo_mod


class _Boom:
    """模拟安全门在执行时抛异常(导入成功但实例化/运行崩溃)。"""

    def __init__(self, *a, **k):
        raise RuntimeError("gate crashed (simulated)")

    def verify(self, *a, **k):
        raise RuntimeError("gate crashed (simulated)")

    def check(self, *a, **k):
        raise RuntimeError("gate crashed (simulated)")


def test_ironlaw_error_blocks_activation(monkeypatch):
    """IronLaw 安全门异常 -> 失败关闭, 机制不被激活。"""
    monkeypatch.setattr(iron_law_mod, "VerificationIronLaw", _Boom)
    reg = MechanismRegistry()
    reg.register("unsafe_a", {}, pending=True)
    res = reg.verify_and_activate("unsafe_a", claim="x", hypothesis="h")
    assert res["activated"] is False, "IronLaw 门异常时不应激活未验证机制"
    assert "iron_law" in res["reason"], f"应报 iron_law 门失败, got {res['reason']}"
    assert res["gates"]["iron_law"]["passed"] is False
    assert res["gates"]["iron_law"]["note"] == "gate_error"
    assert "unsafe_a" not in reg.get_enabled(), "未验证机制不得进 _enabled"


def test_antievo_error_blocks_activation(monkeypatch):
    """AntiEvo 安全门异常 -> 失败关闭, 机制不被激活。"""
    monkeypatch.setattr(anti_evo_mod, "AntiEvolutionGate", _Boom)
    reg = MechanismRegistry()
    reg.register("unsafe_b", {}, pending=True)
    res = reg.verify_and_activate("unsafe_b", claim="x", hypothesis="h")
    assert res["activated"] is False, "AntiEvo 门异常时不应激活未验证机制"
    assert "anti_evo" in res["reason"], f"应报 anti_evo 门失败, got {res['reason']}"
    assert res["gates"]["anti_evo"]["passed"] is False
    assert "unsafe_b" not in reg.get_enabled(), "未验证机制不得进 _enabled"


def test_gates_pass_still_activates():
    """健全性: 安全门正常运行且通过时, 机制照常激活(修复未误伤 happy path)。"""
    reg = MechanismRegistry()
    reg.register("safe_mech", {}, pending=True)
    res = reg.verify_and_activate(
        "safe_mech",
        claim="A mechanism that improves parameter evolution fitness via adaptive learning rate scheduling",
        hypothesis="safe_mech from paper 2607.00000",
    )
    assert res["activated"] is True, f"正常门应通过并激活, got {res}"
    assert "safe_mech" in reg.get_enabled()
