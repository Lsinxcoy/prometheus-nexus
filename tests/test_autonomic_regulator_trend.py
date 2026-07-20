"""AutonomicRegulator 趋势判定专项测试 (cycle-24 薄弱点修复).

根因: _fitness_log 累积多种事件类型的合成 fitness 值
(evolve 真实 fitness ~0.3-0.9 / capability 合成 0.45|0.55 / rumination 合成 ~0.5+),
而连续下降→降级、恢复判定直接取 self._fitness_log[-5:]/[-3:] 混合值,
导致 capability 被接受等噪声可伪造"连续下降"误触降级+熔断, 或污染恢复信号。

修复: 趋势判定仅基于 type=="evolve" 的真实 fitness; 并限定 _fitness_log 上限防内存无界增长。

本文件同时充当"非假绿"反向验证: test_capability_noise_does_not_fake_decline
在修复前(旧代码)必失败。
"""

import pytest

from prometheus_nexus.lifecycle.autonomic_regulator import AutonomicRegulator

try:
    from prometheus_nexus.lifecycle.autonomic_regulator import MAX_FITNESS_HISTORY
except ImportError:  # 兼容旧代码(修复前无此常量); 实际值固定为 200
    MAX_FITNESS_HISTORY = 200


class _FakeBus:
    def __init__(self):
        self.published = []

    def publish(self, event):
        self.published.append(event)

    def subscribe(self, *a, **k):
        pass


class _FakeUCB1:
    def update(self, *a, **k):
        pass


class _FakeAntiEvo:
    def record_score(self, *a, **k):
        pass


class _FakeSignalFusion:
    def get_chain_context(self):
        return None

    def push_feedback(self, *a, **k):
        pass


class _FakeThermo:
    def observe_action(self, *a, **k):
        pass


class _FakeHealing:
    def heal(self, *a, **k):
        return {}


class _FakeCompiler:
    pass


class _FakeRegistry:
    def get_enabled(self):
        return []

    def deactivate(self, name):
        return True

    def register(self, *a, **k):
        pass


class _FakeOmega:
    """最小化 Omega 替身, 仅实现 AutonomicRegulator 实际访问的属性/方法。"""

    def __init__(self):
        self.event_bus = _FakeBus()
        self.ucb1 = _FakeUCB1()
        self.anti_evolution = _FakeAntiEvo()
        self.signal_fusion = _FakeSignalFusion()
        self.thermodynamic = _FakeThermo()
        self.self_healing = _FakeHealing()
        self.mechanism_registry = _FakeRegistry()
        self.focus_topics = {}
        self.mechanism_extractor = None
        self.mechanism_compiler = _FakeCompiler()


def _evolve_event(before, after, strategy="s"):
    return {"data": {"fitness_before": before, "fitness_after": after, "strategy": strategy}}


def test_capability_noise_does_not_fake_decline():
    """capability 噪声(机制被接受=0.55)夹在两次 evolve 之间, 不能伪造连续下降触发降级。"""
    omega = _FakeOmega()
    ar = AutonomicRegulator(omega)
    ar._on_evolve(_evolve_event(0.6, 0.6))
    ar._on_capability({"data": {"accepted": True}})  # 合成 0.55, type=capability
    ar._on_evolve(_evolve_event(0.6, 0.5))

    downgrades = [e for e in omega.event_bus.published if e.get("type") == "system_downgrade"]
    assert not downgrades, "capability 噪声不应伪造连续下降触发降级/熔断"


def test_real_evolve_decline_triggers_downgrade():
    """真实 evolve 连续下降(0.6→0.5→0.4)必须仍触发降级 (正向对照, 确保修复未禁用真实检测)。"""
    omega = _FakeOmega()
    ar = AutonomicRegulator(omega)
    for after in [0.6, 0.5, 0.4]:
        ar._on_evolve(_evolve_event(after + 0.1, after))

    downgrades = [e for e in omega.event_bus.published if e.get("type") == "system_downgrade"]
    assert downgrades, "真实 evolve 连续下降应触发降级"


def test_recovery_gated_on_evolve_fitness():
    """恢复信号仅基于 evolve 真实 fitness, 纯 capability 噪声不得伪造 system_recovered。"""
    omega = _FakeOmega()
    ar = AutonomicRegulator(omega)

    # 纯 capability 噪声(即使数值上升), 无 evolve 数据 → 不应报恢复
    ar._fitness_log = [
        (0.9, 0.0, "capability"),
        (0.55, 0.0, "capability"),
    ]
    ar._on_maintain({})
    recovered_from_noise = [e for e in omega.event_bus.published if e.get("type") == "system_recovered"]
    assert not recovered_from_noise, "纯 capability 噪声不应伪造 system_recovered"

    # 真实 evolve fitness 上升 → 才报恢复
    ar._fitness_log = [
        (0.4, 0.0, "evolve"),
        (0.5, 0.0, "evolve"),
    ]
    ar._on_maintain({})
    recovered = [e for e in omega.event_bus.published if e.get("type") == "system_recovered"]
    assert recovered, "evolve fitness 上升应触发 system_recovered"
    assert recovered[-1]["fitness"] == 0.5


def test_fitness_log_bounded():
    """长时运行实例: _fitness_log 不得超过 MAX_FITNESS_HISTORY, 防止内存无界增长。"""
    omega = _FakeOmega()
    ar = AutonomicRegulator(omega)
    for i in range(MAX_FITNESS_HISTORY + 100):
        ar._on_evolve(_evolve_event(0.5, 0.5, strategy="s"))
    assert len(ar._fitness_log) <= MAX_FITNESS_HISTORY, (
        f"_fitness_log 应被截断到 <= {MAX_FITNESS_HISTORY}, 实际 {len(ar._fitness_log)}"
    )
    # 仍保留最近窗口, 不影响趋势判定
    assert ar._fitness_log[-1][2] == "evolve"
