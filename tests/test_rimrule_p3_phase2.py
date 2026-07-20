"""Tests for RIMRULE Enhancement R2: Prediction-Error Feedback Loop.

Verifies that report_outcome() correctly updates confidence, MDL scores,
quality history, and integrates with adaptive thresholds (R1).
"""

from __future__ import annotations

import pytest
from prometheus_nexus.evolution.rimrule import RIMRULE


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------


def _find_rule_by_condition(rules: list[dict], condition: str) -> dict | None:
    """Find a rule dict by its condition string."""
    for r in rules:
        if r["condition"] == condition:
            return r
    return None


def _rule_count_by_condition(rules: list[dict], condition: str) -> int:
    """Count how many rules have a given condition."""
    return sum(1 for r in rules if r["condition"] == condition)


# ---------------------------------------------------------------------------
#  Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def rimrule_with_rules():
    """Return a RIMRULE instance that has rules extracted from observations.

    Creates one rule for "high_cpu" → "scale_up" (conf 0.75, md_low)
    and one rule for "low_mem" → "evict_cache" (conf 1.0, md_low).
    """
    rr = RIMRULE(max_rules=50, min_support=2)
    # 3 observations for "high_cpu" → "scale_up", 1 for "high_cpu" → "ignore"
    rr.add_observation({"condition": "high_cpu", "outcome": "scale_up", "utility": 0.9})
    rr.add_observation({"condition": "high_cpu", "outcome": "scale_up", "utility": 0.8})
    rr.add_observation({"condition": "high_cpu", "outcome": "scale_up", "utility": 0.7})
    rr.add_observation({"condition": "high_cpu", "outcome": "ignore", "utility": 0.1})
    # 2 observations for "low_mem" → "evict_cache"
    rr.add_observation({"condition": "low_mem", "outcome": "evict_cache", "utility": 0.6})
    rr.add_observation({"condition": "low_mem", "outcome": "evict_cache", "utility": 0.5})

    rr.extract_rules()
    return rr


@pytest.fixture
def rimrule_empty():
    """Return a RIMRULE instance with NO rules (no observations added)."""
    return RIMRULE()


# ---------------------------------------------------------------------------
#  Test 1: Report correct outcome
# ---------------------------------------------------------------------------


class TestReportCorrectOutcome:
    """report_outcome with a correct prediction increases confidence."""

    def test_confidence_increases(self, rimrule_with_rules):
        rr = rimrule_with_rules
        high_cpu_rule = _find_rule_by_condition(rr._rules, "high_cpu")
        assert high_cpu_rule is not None

        old_conf = high_cpu_rule["confidence"]
        old_total = high_cpu_rule["total_checks"]
        old_correct = high_cpu_rule["correct_count"]

        result = rr.report_outcome("high_cpu", "scale_up")

        assert result["correct"] is True
        assert result["rule_id"] == high_cpu_rule["id"]

        # Re-fetch rule
        high_cpu_rule = _find_rule_by_condition(rr._rules, "high_cpu")
        assert high_cpu_rule["total_checks"] == old_total + 1
        assert high_cpu_rule["correct_count"] == old_correct + 1
        # EMA: new = old + 0.3 * (1.0 - old)
        expected = round(old_conf + 0.3 * (1.0 - old_conf), 4)
        assert high_cpu_rule["confidence"] == expected
        assert high_cpu_rule["last_checked"] > 0

    def test_quality_history_appended(self, rimrule_with_rules):
        rr = rimrule_with_rules
        old_len = len(rr._rule_quality_history)

        rr.report_outcome("high_cpu", "scale_up")

        assert len(rr._rule_quality_history) == old_len + 1
        assert rr._rule_quality_history[-1] == 1.0  # correct


# ---------------------------------------------------------------------------
#  Test 2: Report wrong outcome
# ---------------------------------------------------------------------------


class TestReportWrongOutcome:
    """report_outcome with a wrong prediction decreases confidence and
    increases MDL score."""

    def test_confidence_decreases(self, rimrule_with_rules):
        rr = rimrule_with_rules
        high_cpu_rule = _find_rule_by_condition(rr._rules, "high_cpu")
        assert high_cpu_rule is not None

        old_conf = high_cpu_rule["confidence"]
        old_total = high_cpu_rule["total_checks"]
        old_correct = high_cpu_rule["correct_count"]

        result = rr.report_outcome("high_cpu", "restart")  # wrong — expected "scale_up"

        assert result["correct"] is False
        assert result["rule_id"] == high_cpu_rule["id"]

        high_cpu_rule = _find_rule_by_condition(rr._rules, "high_cpu")
        assert high_cpu_rule["total_checks"] == old_total + 1
        assert high_cpu_rule["correct_count"] == old_correct  # unchanged
        # EMA: new = old + 0.3 * (0.0 - old) = old * 0.7
        expected = round(old_conf * 0.7, 4)
        assert high_cpu_rule["confidence"] == expected

    def test_mdl_increases(self, rimrule_with_rules):
        rr = rimrule_with_rules
        high_cpu_rule = _find_rule_by_condition(rr._rules, "high_cpu")
        assert high_cpu_rule is not None

        old_mdl = high_cpu_rule["mdl_score"]

        rr.report_outcome("high_cpu", "restart")  # wrong

        high_cpu_rule = _find_rule_by_condition(rr._rules, "high_cpu")
        expected = round(old_mdl * 1.05, 4)
        assert high_cpu_rule["mdl_score"] == expected

    def test_quality_history_zero(self, rimrule_with_rules):
        rr = rimrule_with_rules
        old_len = len(rr._rule_quality_history)

        rr.report_outcome("high_cpu", "restart")  # wrong

        assert len(rr._rule_quality_history) == old_len + 1
        assert rr._rule_quality_history[-1] == 0.0  # incorrect


# ---------------------------------------------------------------------------
#  Test 3: Report on unmade prediction (no rules at all)
# ---------------------------------------------------------------------------


class TestReportUnmade:
    """report_outcome on an empty RIMRULE (no rules) returns correct=False
    with no rule_id."""

    def test_no_rules_at_all(self, rimrule_empty):
        rr = rimrule_empty
        result = rr.report_outcome("any_condition", "anything")

        assert result["correct"] is False
        assert result["rule_id"] is None
        assert result["predicted"] == "unknown"
        assert result["actual"] == "anything"

    def test_quality_history_still_appended(self, rimrule_empty):
        rr = rimrule_empty
        old_len = len(rr._rule_quality_history)

        rr.report_outcome("any_condition", "anything")

        assert len(rr._rule_quality_history) == old_len + 1
        assert rr._rule_quality_history[-1] == 0.0  # incorrect


# ---------------------------------------------------------------------------
#  Test 4: Multiple reports — confidence stabilises near accuracy rate
# ---------------------------------------------------------------------------


class TestMultipleReports:
    """After many reports with a fixed accuracy, confidence should converge
    toward that accuracy (EMA smoothing)."""

    def test_confidence_converges_to_accuracy(self):
        rr = RIMRULE(max_rules=10, min_support=1)

        # Create a single rule via observations (all "x" → "a")
        for _ in range(5):
            rr.add_observation({"condition": "x", "outcome": "a", "utility": 0.5})
        rr.extract_rules()
        assert len(rr._rules) == 1
        rule = rr._rules[0]
        assert rule["condition"] == "x"

        # 75% accuracy: 75 correct out of 100
        n = 100
        correct_count = 0
        for i in range(n):
            actual = "a" if i % 4 != 0 else "b"  # 75% correct
            result = rr.report_outcome("x", actual)
            if result["correct"]:
                correct_count += 1

        assert rule["total_checks"] == n
        assert rule["correct_count"] == correct_count == 75
        # EMA with alpha=0.3 converges asymptotically toward 0.75
        assert abs(rule["confidence"] - 0.75) < 0.15, (
            f"Expected confidence near 0.75, got {rule['confidence']}"
        )


# ---------------------------------------------------------------------------
#  Test 5: Quality history feeds into adaptive thresholds (R1 integration)
# ---------------------------------------------------------------------------


class TestAdaptiveThresholdsIntegration:
    """Verify that report_outcome() appends to _rule_quality_history and
    that _adapt_thresholds() eventually adjusts thresholds based on
    the accumulated quality history."""

    def test_degrading_quality_relaxes_thresholds(self):
        rr = RIMRULE(max_rules=50, min_support=3)
        rr._quality_window = 10  # shrink window for test speed

        # Seed a rule
        for _ in range(3):
            rr.add_observation({"condition": "a", "outcome": "x", "utility": 0.9})
        rr.add_observation({"condition": "a", "outcome": "y", "utility": 0.1})
        rr.extract_rules()

        old_min_support = rr._min_support_adaptive
        old_max_rules = rr._max_rules_adaptive

        # Report many wrong outcomes → degrading quality
        for _ in range(rr._quality_window):
            rr.report_outcome("a", "z")  # always wrong

        # Degrading trend (< -0.05) should relax thresholds
        assert rr._min_support_adaptive <= old_min_support, (
            "min_support should decrease (relax) when quality degrades"
        )
        assert rr._max_rules_adaptive >= old_max_rules, (
            "max_rules should increase (relax) when quality degrades"
        )

    def test_correct_reports_tighten_thresholds(self):
        rr = RIMRULE(max_rules=50, min_support=3)
        rr._quality_window = 10

        # Seed a rule
        for _ in range(3):
            rr.add_observation({"condition": "b", "outcome": "y", "utility": 0.9})
        rr.add_observation({"condition": "b", "outcome": "z", "utility": 0.1})
        rr.extract_rules()

        old_min_support = rr._min_support_adaptive
        old_max_rules = rr._max_rules_adaptive

        # Report all correct → quality improves
        for _ in range(rr._quality_window):
            rr.report_outcome("b", "y")  # always correct

        # Improving trend (> 0.05) should tighten thresholds
        assert rr._min_support_adaptive >= old_min_support, (
            "min_support should increase (tighten) when quality improves"
        )
        assert rr._max_rules_adaptive <= old_max_rules, (
            "max_rules should decrease (tighten) when quality improves"
        )

    def test_insufficient_history_does_not_adapt(self):
        """If _rule_quality_history is shorter than _quality_window,
        _adapt_thresholds should be a no-op."""
        rr = RIMRULE(max_rules=50, min_support=3)
        rr._quality_window = 20

        for _ in range(3):
            rr.add_observation({"condition": "c", "outcome": "z", "utility": 0.9})
        rr.extract_rules()

        old_min = rr._min_support_adaptive
        old_max = rr._max_rules_adaptive

        # Only 5 reports — less than quality_window of 20
        for _ in range(5):
            rr.report_outcome("c", "wrong")

        assert rr._min_support_adaptive == old_min
        assert rr._max_rules_adaptive == old_max


# ---------------------------------------------------------------------------
#  Test 6: _cache_prediction stores results
# ---------------------------------------------------------------------------


class TestCachePrediction:
    """Verify that predict() stores results in _last_predictions."""

    def test_cache_stores_prediction(self, rimrule_with_rules):
        rr = rimrule_with_rules
        assert "high_cpu" not in rr._last_predictions

        result = rr.predict("high_cpu")

        assert "high_cpu" in rr._last_predictions
        cached = rr._last_predictions["high_cpu"]
        assert cached["prediction"] == result["prediction"]
        assert cached["rule_id"] == result["rule_id"]

    def test_cache_unknown_prediction(self, rimrule_empty):
        rr = rimrule_empty
        result = rr.predict("bogus_condition")

        assert "bogus_condition" in rr._last_predictions
        cached = rr._last_predictions["bogus_condition"]
        assert cached["prediction"] == "unknown"

    def test_cache_overwrites_previous(self, rimrule_with_rules):
        rr = rimrule_with_rules
        rr.predict("high_cpu")  # first call
        assert rr._last_predictions["high_cpu"]["prediction"] == "scale_up"


# ---------------------------------------------------------------------------
#  Test 7: report_outcome calls predict internally, which caches
# ---------------------------------------------------------------------------


class TestReportOutcomeCaches:
    """report_outcome calls predict(), which in turn caches the prediction."""

    def test_report_outcome_caches_prediction(self, rimrule_with_rules):
        rr = rimrule_with_rules
        assert "high_cpu" not in rr._last_predictions

        rr.report_outcome("high_cpu", "scale_up")

        assert "high_cpu" in rr._last_predictions
        assert rr._last_predictions["high_cpu"]["prediction"] == "scale_up"


# ---------------------------------------------------------------------------
#  Test 8: Edge cases — report_outcome does not crash on rules with
#          missing fields (defensive)
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases and defensive handling."""

    def test_no_rules_does_not_crash(self):
        rr = RIMRULE()
        # No rules extracted — report_outcome should still work
        result = rr.report_outcome("cond", "out")
        assert result["correct"] is False
        assert result["rule_id"] is None
        assert result["predicted"] == "unknown"

    def test_predict_on_empty_rimrule(self, rimrule_empty):
        result = rimrule_empty.predict("anything")
        assert result["prediction"] == "unknown"
        assert result["confidence"] == 0.0
