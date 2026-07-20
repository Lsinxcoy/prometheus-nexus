"""Phase 0 共享脊柱单元测试: EffectTracker + SelectionGate.

不依赖重系统(life/Nexus 全量), 纯单元验证效果量化与 A/B 选择逻辑.
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from prometheus_nexus.evolution.effect_tracker import EffectTracker, snapshot_system
from prometheus_nexus.evolution.selection_gate import SelectionGate


def test_measure_side_effects_positive():
    t = EffectTracker()
    before = {"write_count": 0, "output": None}
    after = {"write_count": 3, "output": {"ok": True, "x": 1}}
    score = t.measure_side_effects(before, after)
    assert score > 0, f"有副作用应>0, 实得 {score}"
    assert score <= 1.0


def test_measure_side_effects_error_penalty():
    t = EffectTracker()
    before = {"write_count": 0, "output": None}
    after = {"write_count": 0, "output": None, "error": "boom"}
    score = t.measure_side_effects(before, after)
    assert score < 0, f"异常应<0, 实得 {score}"


def test_measure_side_effects_no_change():
    t = EffectTracker()
    before = {"write_count": 0, "output": None}
    after = {"write_count": 0, "output": None}
    assert t.measure_side_effects(before, after) == 0.0


def test_measure_side_effects_clamped():
    t = EffectTracker()
    before = {"write_count": 0, "output": None}
    # 制造远超上限的写入 + 异常, 验证截断到 [-1,1]
    after = {"write_count": 1000, "output": None, "error": "x"}
    score = t.measure_side_effects(before, after)
    assert -1.0 <= score <= 1.0


def test_selection_gate_hold_until_min_samples():
    g = SelectionGate(margin=0.05, min_samples=3, prune_below=-0.1)
    assert g.observe("m", 0.5, 0.1) == "hold"   # len=1
    assert g.observe("m", 0.6, 0.1) == "hold"   # len=2
    assert g.observe("m", 0.7, 0.1) == "promote"  # len=3 -> 持续优


def test_selection_gate_prune_on_inferior():
    g = SelectionGate(margin=0.05, min_samples=3, prune_below=-0.1)
    for _ in range(3):
        g.observe("n", -0.2, 0.3)
    assert g.decision_for("n") == "prune"


def test_selection_gate_serialize_roundtrip():
    g = SelectionGate(margin=0.05, min_samples=3, prune_below=-0.1)
    g.observe("m", 0.5, 0.1)
    g.observe("m", 0.6, 0.1)
    g.observe("m", 0.7, 0.1)
    data = g.serialize()
    g2 = SelectionGate.deserialize(data)
    # 样本足够且持续优 -> promote
    assert g2.decision_for("m") == "promote"
    # 新 Gate 无样本 -> hold
    assert g2.decision_for("unknown") == "hold"


def test_selection_gate_margin_not_met():
    """candidate 略优但未超 margin, 且样本足 -> hold(不误 promote)."""
    g = SelectionGate(margin=0.5, min_samples=2, prune_below=-0.1)
    g.observe("x", 0.3, 0.1)  # 差 0.2 < 0.5
    g.observe("x", 0.32, 0.1)
    assert g.decision_for("x") == "hold"
