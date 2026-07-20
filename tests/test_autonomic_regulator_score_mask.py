"""AutonomicRegulator composite_score 假零掩码薄弱点 (cycle-30).

根因: _on_reflect() 中 `score = data.get("composite_score", 0.5) or 0.5`
将合法的 0.0(最差反思分, five_view.py 默认即 0.0) 误掩为 0.5,
使 `score < 0.4` 的退化检测分支对真实零分永不触发 —— Omega 自我保护核的
监控盲区(类型边界/假零掩码)。

修复后: composite_score=0.0 应被如实保留为 0.0(可检出), 仅缺失/显式 None 才回退 0.5。
"""
import pytest

from prometheus_nexus.lifecycle.autonomic_regulator import AutonomicRegulator


def _make() -> AutonomicRegulator:
    return AutonomicRegulator(omega=None)


def test_zero_composite_score_triggers_decline_detection():
    """真实零分(0.0)必须被检出为退化, 而非被 `or 0.5` 掩成 0.5 绕过检测。"""
    reg = _make()
    event = {"data": {"composite_score": 0.0, "drift_alerts": [1, 2, 3, 4]}}
    reg._on_reflect(event)
    reg._on_reflect(event)
    # 修复前: score 被掩成 0.5 -> 0.5 不 < 0.4 -> _consecutive_zero_gain 保持 0 -> 断言失败
    assert reg._consecutive_zero_gain >= 2


def test_legitimate_zero_score_preserved_not_masked():
    """单次 0.0 分(伴高 drift)即应记一次退化, 证明 0.0 未被 `or 0.5` 误掩成 0.5。"""
    reg = _make()
    reg._on_reflect({"data": {"composite_score": 0.0, "drift_alerts": [1, 2, 3, 4]}})
    assert reg._consecutive_zero_gain == 1


def test_missing_composite_score_keeps_default_no_false_decline():
    """缺失键回退 0.5, 不应误触发退化(0.5 不 < 0.4)。"""
    reg = _make()
    reg._on_reflect({"data": {"drift_alerts": [1, 2, 3, 4]}})
    assert reg._consecutive_zero_gain == 0


def test_normal_score_unchanged_no_false_decline():
    """正常高分(0.7)不应触发退化, 行为不变。"""
    reg = _make()
    reg._on_reflect({"data": {"composite_score": 0.7, "drift_alerts": [1, 2, 3, 4]}})
    assert reg._consecutive_zero_gain == 0
