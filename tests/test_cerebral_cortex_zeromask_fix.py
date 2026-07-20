"""CerebralCortex 假零掩码薄弱点 (cycle-41, 循环深化 cycle-30).

根因: CerebralCortex._on_outcome() 中两处沿用了与 cycle-30 完全相同的
反模式 `data.get("<field>", 0.5) or 0.5`:
  - reflect_completed: `score = data.get("composite_score", 0.5) or 0.5`
    composite_score 合法取 0.0(最差反思分, five_view 默认即 0.0) 会被误掩成 0.5,
    污染 回路 C 历史感知熔断 对该管道 fitness 的统计。
  - remember_completed: `utility = data.get("utility", 0.5) or 0.5`
    utility 合法取 0.0(最差记忆效用) 被误掩成 0.5, delta = utility - 0.3 失真(-0.3 变 0.2)。

cycle-30 仅在 autonomic_regulator.py 修了同款, 此模块的 sibling 实例被遗漏。
修复后: 仅当字段缺失或显式为 None 才回退 0.5, 合法 0.0 如实保留。
"""
import pytest

from prometheus_nexus.lifecycle.cerebral_cortex import CerebralCortex


class _DummyOmega:
    """无需真实引擎: reflect/remember 分支不触碰 omega, _record_outcome 仅 getattr signal_fusion(None 即跳过)。"""


def _make() -> CerebralCortex:
    return CerebralCortex(_DummyOmega())


def test_reflect_composite_score_zero_not_masked():
    """真实零分(0.0)必须被如实保留为 0.0, 而非被 `or 0.5` 误掩成 0.5。"""
    cc = _make()
    cc._on_outcome({"topic": "reflect_completed",
                    "data": {"composite_score": 0.0, "drift_alerts": []}})
    rec = cc._trigger_outcomes["reflect"][-1]
    # 修复前: score = 0.0 or 0.5 = 0.5 -> 此断言失败
    assert rec[0] == 0.0


def test_reflect_composite_score_missing_defaults_to_05():
    """缺失键回退 0.5, 行为不变。"""
    cc = _make()
    cc._on_outcome({"topic": "reflect_completed", "data": {"drift_alerts": []}})
    assert cc._trigger_outcomes["reflect"][-1][0] == 0.5


def test_reflect_composite_score_explicit_none_defaults_to_05():
    cc = _make()
    cc._on_outcome({"topic": "reflect_completed",
                    "data": {"composite_score": None, "drift_alerts": []}})
    assert cc._trigger_outcomes["reflect"][-1][0] == 0.5


def test_reflect_composite_score_positive_preserved():
    cc = _make()
    cc._on_outcome({"topic": "reflect_completed",
                    "data": {"composite_score": 0.7, "drift_alerts": []}})
    assert cc._trigger_outcomes["reflect"][-1][0] == 0.7


def test_remember_utility_zero_not_masked():
    """真实零效用(0.0)必须被如实保留, delta = 0.0 - 0.3 == -0.3(非误掩后的 0.2)。"""
    cc = _make()
    cc._on_outcome({"topic": "remember_completed", "data": {"utility": 0.0}})
    rec = cc._trigger_outcomes["remember"][-1]
    assert rec[0] == 0.0
    assert rec[1] == -0.3


def test_remember_utility_missing_defaults_to_05():
    cc = _make()
    cc._on_outcome({"topic": "remember_completed", "data": {}})
    rec = cc._trigger_outcomes["remember"][-1]
    assert rec[0] == 0.5
    assert rec[1] == 0.2
