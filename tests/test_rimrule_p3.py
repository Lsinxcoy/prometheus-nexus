"""Tests for RIMRULE enhancements R1 (Adaptive MDL Thresholds) and R3 (Rule Aging and Pruning)."""

from __future__ import annotations

import time

import pytest

from src.prometheus_nexus.evolution.rimrule import RIMRULE


class TestAdaptiveThresholds:
    """R1: Adaptive MDL Thresholds — _adapt_thresholds adjusts min_support / max_rules."""

    def test_degrading_quality_relaxes_thresholds(self):
        """When rule_quality_history shows degrading trend, thresholds should relax
        (min_support decreases, max_rules increases)."""
        rimrule = RIMRULE(max_rules=50, min_support=3)
        assert rimrule._min_support_adaptive == 3
        assert rimrule._max_rules_adaptive == 50

        # Simulate a degrading quality trend: fill quality_window with declining values
        window = rimrule._quality_window  # 20
        # Start at 0.9, drop to 0.1 linearly -> trend is (0.1 - 0.9) / 20 = -0.04 -> NOT below -0.05
        # Need a steeper drop: ~0.9 -> 0.0 gives trend (0 - 0.9) / 20 = -0.045, still not enough
        # Make it big: 1.0 down to 0.0 = (0 - 1)/20 = -0.05, exactly -0.05 (not < -0.05)
        # Drop from 1.0 to -0.01: (-0.01 - 1)/20 = -0.0505 < -0.05 ✓
        for i in range(window):
            rimrule._rule_quality_history.append(1.0 - (i / (window - 1)) * 1.01)

        rimrule._adapt_thresholds()

        # Thresholds should have relaxed
        assert rimrule._min_support_adaptive < 3
        assert rimrule._max_rules_adaptive > 50

    def test_improving_quality_tightens_thresholds(self):
        """When rule_quality_history shows improving trend, thresholds should tighten
        (min_support increases, max_rules decreases)."""
        rimrule = RIMRULE(max_rules=50, min_support=3)
        assert rimrule._min_support_adaptive == 3
        assert rimrule._max_rules_adaptive == 50

        # Simulate an improving trend: 0.0 -> 1.0: trend = (1 - 0) / 20 = 0.05 (exactly 0.05, not > 0.05)
        # Need > 0.05: 0.0 -> 1.1: (1.1 - 0) / 20 = 0.055 > 0.05 ✓
        window = rimrule._quality_window
        for i in range(window):
            rimrule._rule_quality_history.append((i / (window - 1)) * 1.1)

        rimrule._adapt_thresholds()

        assert rimrule._min_support_adaptive > 3
        assert rimrule._max_rules_adaptive < 50

    def test_no_change_when_quality_stable(self):
        """When quality trend is within [-0.05, 0.05], thresholds should not change."""
        rimrule = RIMRULE(max_rules=50, min_support=5)
        original_min = rimrule._min_support_adaptive
        original_max = rimrule._max_rules_adaptive

        # Flat quality: 0.5 repeated 20 times -> trend = (0.5 - 0.5) / 20 = 0.0
        window = rimrule._quality_window
        for _ in range(window):
            rimrule._rule_quality_history.append(0.5)

        rimrule._adapt_thresholds()

        assert rimrule._min_support_adaptive == original_min
        assert rimrule._max_rules_adaptive == original_max

    def test_thresholds_clamped_within_bounds(self):
        """min_support_adaptive clamped to [1, 10], max_rules_adaptive to [10, 200]."""
        rimrule = RIMRULE(max_rules=5, min_support=10)
        # Manually set to extremes and call adapt with degrading trend
        rimrule._min_support_adaptive = 1
        rimrule._max_rules_adaptive = 200

        # Already at bounds; even with an improving trend, clamping keeps them there
        window = rimrule._quality_window
        for i in range(window):
            rimrule._rule_quality_history.append((i / (window - 1)) * 1.1)

        rimrule._adapt_thresholds()

        assert rimrule._min_support_adaptive >= 1
        assert rimrule._min_support_adaptive <= 10
        assert rimrule._max_rules_adaptive >= 10
        assert rimrule._max_rules_adaptive <= 200

    def test_not_enough_history_does_nothing(self):
        """With fewer than quality_window entries, _adapt_thresholds is a no-op."""
        rimrule = RIMRULE(max_rules=50, min_support=3)
        for _ in range(5):
            rimrule._rule_quality_history.append(0.0)

        rimrule._adapt_thresholds()

        assert rimrule._min_support_adaptive == 3
        assert rimrule._max_rules_adaptive == 50

    def test_extract_rules_records_mdl_trend(self):
        """extract_rules should populate _mdl_trend with avg MDL score."""
        rimrule = RIMRULE()
        for c in ["a", "b", "c"]:
            rimrule.add_observation({"condition": c, "outcome": "x", "utility": 0.5})
            rimrule.add_observation({"condition": c, "outcome": "x", "utility": 0.5})
            rimrule.add_observation({"condition": c, "outcome": "x", "utility": 0.5})

        assert len(rimrule._mdl_trend) == 0
        rimrule.extract_rules()
        assert len(rimrule._mdl_trend) == 1
        assert isinstance(rimrule._mdl_trend[0], float)

    def test_new_rules_have_aging_fields(self):
        """Rules created by extract_rules must have last_checked, correct_count, total_checks."""
        rimrule = RIMRULE()
        for c in ["a", "b"]:
            rimrule.add_observation({"condition": c, "outcome": "x", "utility": 0.5})
            rimrule.add_observation({"condition": c, "outcome": "x", "utility": 0.5})
            rimrule.add_observation({"condition": c, "outcome": "x", "utility": 0.5})

        rules = rimrule.extract_rules()
        for r in rules:
            assert "last_checked" in r
            assert "correct_count" in r
            assert "total_checks" in r
            assert r["correct_count"] == 0
            assert r["total_checks"] == 0


class TestPruning:
    """R3: Rule Aging and Pruning — prune_rules removes stale / low-confidence rules."""

    def test_prune_old_rules_with_enough_checks(self):
        """Rules that are old (last_checked far in past) AND have >=5 checks should be pruned."""
        rimrule = RIMRULE()
        old_time = time.time() - 700000  # > 7 days ago

        # Add observations so extract_rules produces rules
        for c in ["a", "b", "c", "d"]:
            for _ in range(5):
                rimrule.add_observation({"condition": c, "outcome": "x", "utility": 0.5})

        rules = rimrule.extract_rules()
        assert len(rules) >= 4

        # Manually age the rules: set last_checked far back, total_checks >= 5
        for r in rimrule._rules:
            r["last_checked"] = old_time
            r["total_checks"] = 5

        pruned = rimrule.prune_rules(max_age_seconds=604800, min_confidence=0.0)
        assert pruned == 4
        assert len(rimrule._rules) == 0

    def test_preserve_rules_with_few_checks(self):
        """Rules with <5 total_checks should NOT be pruned even if old or low-confidence."""
        rimrule = RIMRULE(min_support=1)
        old_time = time.time() - 700000

        for c in ["a"]:
            for _ in range(3):
                rimrule.add_observation({"condition": c, "outcome": "x", "utility": 0.5})

        rules = rimrule.extract_rules()
        assert len(rules) >= 1

        # Set old timestamp but only 2 checks (below threshold of 5)
        for r in rimrule._rules:
            r["last_checked"] = old_time
            r["total_checks"] = 2

        pruned = rimrule.prune_rules(max_age_seconds=604800, min_confidence=0.0)
        assert pruned == 0
        assert len(rimrule._rules) >= 1

    def test_preserve_recent_rules_with_enough_checks(self):
        """Recent rules (last_checked within age) with enough checks should be preserved."""
        rimrule = RIMRULE(min_support=1)
        now = time.time()

        for c in ["a", "b"]:
            for _ in range(5):
                rimrule.add_observation({"condition": c, "outcome": "x", "utility": 0.5})

        rules = rimrule.extract_rules()
        assert len(rules) >= 2

        # Set current timestamp and 5 checks — should survive pruning
        for r in rimrule._rules:
            r["last_checked"] = now
            r["total_checks"] = 5

        pruned = rimrule.prune_rules(max_age_seconds=604800, min_confidence=0.0)
        assert pruned == 0
        assert len(rimrule._rules) >= 2

    def test_prune_low_confidence_with_enough_checks(self):
        """Low-confidence rules with >=5 checks should be pruned."""
        rimrule = RIMRULE(min_support=1)
        now = time.time()

        for c in ["a", "b", "c", "d"]:
            for _ in range(3):
                rimrule.add_observation({"condition": c, "outcome": "x", "utility": 0.5})

        rules = rimrule.extract_rules()
        assert len(rules) >= 4

        # Make one rule very low confidence
        rimrule._rules[0]["confidence"] = 0.01
        rimrule._rules[0]["total_checks"] = 5
        rimrule._rules[0]["last_checked"] = now

        # Keep others recent + high confidence
        for r in rimrule._rules[1:]:
            r["total_checks"] = 5
            r["last_checked"] = now

        pruned = rimrule.prune_rules(max_age_seconds=604800, min_confidence=0.2)
        assert pruned == 1
        for r in rimrule._rules:
            assert r["confidence"] >= 0.2

    def test_training_data_truncation(self):
        """prune_rules should trim training_data when it exceeds 10000."""
        rimrule = RIMRULE()

        # Add 12001 observations
        for i in range(12001):
            rimrule.add_observation({"condition": f"c{i}", "outcome": "x", "utility": 0.5})

        assert len(rimrule._training_data) == 12001

        rimrule.prune_rules()

        assert len(rimrule._training_data) <= 5000

    def test_prune_return_count(self):
        """prune_rules returns correct count of pruned rules."""
        rimrule = RIMRULE(min_support=1)
        old_time = time.time() - 700000

        for c in ["a", "b", "c", "d", "e"]:
            for _ in range(5):
                rimrule.add_observation({"condition": c, "outcome": "x", "utility": 0.5})

        rimrule.extract_rules()

        # Age half of them
        for i, r in enumerate(rimrule._rules):
            r["total_checks"] = 5
            if i < 3:
                r["last_checked"] = old_time
            else:
                r["last_checked"] = time.time()

        pruned = rimrule.prune_rules(max_age_seconds=604800, min_confidence=0.0)
        assert pruned == 3


if __name__ == "__main__":
    pytest.main([__file__])
