"""Tests for RIMRULE Phase 3: Observation Weighting by Utility (R4)."""
from __future__ import annotations

import os
import sys

# Ensure the source is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from prometheus_nexus.evolution.rimrule import RIMRULE


def _make_data(
    condition: str, outcome: str, count: int, utility: float | None = 0.5
) -> list[dict]:
    """Helper to produce a list of observation dicts."""
    return [
        {"condition": condition, "outcome": outcome, "utility": utility}
        for _ in range(count)
    ]


# ---------------------------------------------------------------------------
# Test 1: High-weight conditions produce lower MDL
# ---------------------------------------------------------------------------


def test_high_weight_lower_mdl():
    """High-weight conditions should produce lower MDL scores."""
    rim = RIMRULE()
    # Both conditions have support=10, exceptions=10 (same structure)
    data = (
        _make_data("cond_a", "outcome_1", 10)
        + _make_data("cond_a", "other_outcome", 10)
        + _make_data("cond_b", "outcome_2", 10)
        + _make_data("cond_b", "other_outcome", 10)
    )
    for d in data:
        rim.add_observation(d)

    rules = rim.extract_rules(
        min_support=5, observation_weights={"cond_a": 0.9, "cond_b": 0.1}
    )
    m = {r["condition"]: r for r in rules}
    assert "cond_a" in m, "cond_a should produce a rule"
    assert "cond_b" in m, "cond_b should produce a rule"
    assert m["cond_a"]["mdl_score"] < m["cond_b"]["mdl_score"], (
        f"High-weight cond_a ({m['cond_a']['mdl_score']}) should have lower MDL "
        f"than low-weight cond_b ({m['cond_b']['mdl_score']})"
    )


# ---------------------------------------------------------------------------
# Test 2: Low-weight conditions produce higher MDL (more penalty)
# ---------------------------------------------------------------------------


def test_low_weight_higher_mdl():
    """Low-weight conditions should produce higher MDL (more penalty)."""
    rim = RIMRULE()
    data = (
        _make_data("cond_low", "outcome", 10)
        + _make_data("cond_low", "other", 10)
        + _make_data("cond_high", "outcome2", 10)
        + _make_data("cond_high", "other2", 10)
    )
    for d in data:
        rim.add_observation(d)

    rules = rim.extract_rules(
        min_support=5,
        observation_weights={"cond_low": 0.1, "cond_high": 0.9},
    )
    m = {r["condition"]: r for r in rules}
    assert m["cond_low"]["mdl_score"] > m["cond_high"]["mdl_score"], (
        f"Low-weight cond_low ({m['cond_low']['mdl_score']}) should have higher "
        f"MDL than high-weight cond_high ({m['cond_high']['mdl_score']})"
    )


# ---------------------------------------------------------------------------
# Test 3: Mixed weights — verify relative ordering
# ---------------------------------------------------------------------------


def test_mixed_weights_relative_ordering():
    """MDL ordering should match weight ordering (higher weight -> lower MDL)."""
    rim = RIMRULE()
    data = []
    for cond in ("w_high", "w_med", "w_low"):
        data.extend(_make_data(cond, f"out_{cond}", 10))
        data.extend(_make_data(cond, "other", 10))
    for d in data:
        rim.add_observation(d)

    rules = rim.extract_rules(
        min_support=5,
        observation_weights={"w_high": 0.9, "w_med": 0.5, "w_low": 0.1},
    )
    m = {r["condition"]: r for r in rules}
    assert m["w_high"]["mdl_score"] < m["w_med"]["mdl_score"] < m["w_low"]["mdl_score"], (
        f"MDL ordering should follow weight ordering:\n"
        f"  w_high (0.9): {m['w_high']['mdl_score']}\n"
        f"  w_med  (0.5): {m['w_med']['mdl_score']}\n"
        f"  w_low  (0.1): {m['w_low']['mdl_score']}"
    )


# ---------------------------------------------------------------------------
# Test 4: No weights = same as before (default behavior)
# ---------------------------------------------------------------------------


def test_no_weights_default_behavior():
    """Without observation_weights, extract_rules() should still work (backward-compatible)."""
    rim = RIMRULE()
    data = (
        _make_data("cond_x", "outcome", 10)
        + _make_data("cond_x", "other", 10)
        + _make_data("cond_y", "outcome", 10)
        + _make_data("cond_y", "other", 10)
    )
    for d in data:
        rim.add_observation(d)

    # No weights passed
    rules_no_arg = rim.extract_rules(min_support=5)
    # weights=None explicitly
    rules_none = rim.extract_rules(min_support=5, observation_weights=None)

    assert len(rules_no_arg) > 0
    assert len(rules_no_arg) == len(rules_none)
    for r1, r2 in zip(rules_no_arg, rules_none):
        assert r1["mdl_score"] == r2["mdl_score"]
        assert r1["support"] == r2["support"]
        assert r1["confidence"] == r2["confidence"]


# ---------------------------------------------------------------------------
# Test 5: Weighted exceptions appears in rule dict
# ---------------------------------------------------------------------------


def test_weighted_exceptions_in_rule_dict():
    """'weighted_exceptions' and 'avg_observation_weight' should appear in each rule dict."""
    # --- With observation_weights ---
    rim = RIMRULE()
    data = _make_data("cond", "outcome", 10, utility=0.9) + _make_data(
        "cond", "other", 10, utility=0.9
    )
    for d in data:
        rim.add_observation(d)

    rules = rim.extract_rules(min_support=5, observation_weights={"cond": 0.8})
    for r in rules:
        assert "weighted_exceptions" in r, f"Rule {r['id']} missing weighted_exceptions"
        assert isinstance(r["weighted_exceptions"], float)
        assert "avg_observation_weight" in r, f"Rule {r['id']} missing avg_observation_weight"
        assert r["avg_observation_weight"] == 0.8, (
            f"avg_observation_weight should be 0.8 (from weights), "
            f"got {r['avg_observation_weight']}"
        )

    # --- Without observation_weights ---
    rim2 = RIMRULE()
    for d in _make_data("cond2", "outcome", 10) + _make_data("cond2", "other", 10):
        rim2.add_observation(d)
    rules2 = rim2.extract_rules(min_support=5)
    for r in rules2:
        assert "weighted_exceptions" in r
        assert "avg_observation_weight" in r
        # No utility set -> defaults to 0.5
        assert r["avg_observation_weight"] == 0.5


# ---------------------------------------------------------------------------
# Test 6: Empty weights dict doesn't crash
# ---------------------------------------------------------------------------


def test_empty_weights_dict():
    """Passing an empty observation_weights dict should not crash."""
    rim = RIMRULE()
    data = _make_data("cond", "outcome", 10) + _make_data("cond", "other", 10)
    for d in data:
        rim.add_observation(d)

    rules_empty = rim.extract_rules(min_support=5, observation_weights={})
    rules_none = rim.extract_rules(min_support=5, observation_weights=None)
    assert len(rules_empty) > 0
    assert len(rules_empty) == len(rules_none)
    for r1, r2 in zip(rules_empty, rules_none):
        assert r1["mdl_score"] == r2["mdl_score"]


# ---------------------------------------------------------------------------
# Test get_stats includes avg_observation_weight when available
# ---------------------------------------------------------------------------


def test_get_stats_avg_observation_weight():
    """get_stats() should include avg_observation_weight when rules have it."""
    rim = RIMRULE()
    data = (
        _make_data("cond_a", "outcome_a", 10, utility=0.9)
        + _make_data("cond_a", "other", 5)
        + _make_data("cond_b", "outcome_b", 8, utility=0.3)
        + _make_data("cond_b", "other", 7)
    )
    for d in data:
        rim.add_observation(d)

    rim.extract_rules(min_support=5)
    stats = rim.get_stats()

    assert "avg_observation_weight" in stats, (
        "get_stats() should include avg_observation_weight when rules are present"
    )
    assert isinstance(stats["avg_observation_weight"], float)
    assert 0.0 <= stats["avg_observation_weight"] <= 1.0


# ---------------------------------------------------------------------------
# Smoke test: Full pipeline with weights
# ---------------------------------------------------------------------------


def test_full_pipeline_with_weights():
    """End-to-end: add_observation -> extract_rules(weights) -> predict."""
    rim = RIMRULE()
    data = (
        _make_data("error_rate>0.1", "rollback", 15, utility=0.9)
        + _make_data("error_rate>0.1", "retry", 5, utility=0.1)
        + _make_data("cpu>90", "gc_run", 12, utility=0.7)
        + _make_data("cpu>90", "oom_kill", 8, utility=0.3)
    )
    for d in data:
        rim.add_observation(d)

    rules = rim.extract_rules(min_support=5, observation_weights={"error_rate>0.1": 0.95})
    assert len(rules) >= 2

    pred = rim.predict("error_rate>0.1")
    assert pred["prediction"] != "unknown"
    assert pred["confidence"] > 0
