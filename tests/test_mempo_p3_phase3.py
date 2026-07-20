"""Tests for MemPO P3 Phase 3 enhancement: RIMRULE-guided policy boosting (X1)."""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from prometheus_nexus.memory.mempo import MemPO


class TestApplyRuleGuidance:
    """apply_rule_guidance: boost utilities of nodes related to a RIMRULE rule."""

    def test_boosts_utilities_of_specified_nodes(self):
        """apply_rule_guidance should increase utility for each given node."""
        mempo = MemPO()
        rule = {"confidence": 0.8}

        # Set some initial utility values
        mempo._utility_scores["node_a"] = 0.3
        mempo._utility_scores["node_b"] = 0.5
        mempo._utility_scores["node_c"] = 0.7

        result = mempo.apply_rule_guidance(rule, ["node_a", "node_b", "node_c"])

        assert result["boosted_count"] == 3
        assert mempo.get_utility("node_a") > 0.3
        assert mempo.get_utility("node_b") > 0.5
        assert mempo.get_utility("node_c") > 0.7

    def test_higher_confidence_yields_higher_boost(self):
        """Higher rule confidence should produce a larger utility bump."""
        mempo = MemPO()

        mempo._utility_scores["node_low"] = 0.0
        mempo._utility_scores["node_high"] = 0.0

        # Apply low confidence rule
        result_low = mempo.apply_rule_guidance(
            {"confidence": 0.3}, ["node_low"]
        )

        # Apply high confidence rule on a different node
        result_high = mempo.apply_rule_guidance(
            {"confidence": 0.9}, ["node_high"]
        )

        assert result_low["max_boost"] < result_high["max_boost"]
        assert mempo.get_utility("node_low") < mempo.get_utility("node_high")

    def test_missing_confidence_uses_default(self):
        """When confidence key is absent, the default (0.5) gives a small boost."""
        mempo = MemPO()

        mempo._utility_scores["node_z"] = 0.0
        result = mempo.apply_rule_guidance({}, ["node_z"])

        # confidence missing → default 0.5 → boost = 0.5 * 0.2 = 0.1
        assert result["max_boost"] == pytest.approx(0.1)
        assert mempo.get_utility("node_z") == pytest.approx(0.1)

    def test_zero_confidence_yields_no_boost(self):
        """When confidence is explicitly 0, boost should be 0."""
        mempo = MemPO()

        mempo._utility_scores["node_z"] = 0.0
        result = mempo.apply_rule_guidance({"confidence": 0.0}, ["node_z"])

        assert result["max_boost"] == 0.0

    def test_boost_capped_at_1_0(self):
        """Utility should never exceed 1.0 even with a large boost."""
        mempo = MemPO()

        mempo._utility_scores["node_max"] = 0.99
        result = mempo.apply_rule_guidance(
            {"confidence": 1.0}, ["node_max"]
        )
        # boost = 1.0 * 0.2 = 0.2, so 0.99 + 0.2 = 1.19 → clamped to 1.0
        assert mempo.get_utility("node_max") == 1.0
        assert result["avg_boost"] == pytest.approx(0.01, abs=1e-4)

    def test_returns_correct_stats(self):
        """Result dict should contain boosted_count, avg_boost, max_boost."""
        mempo = MemPO()

        mempo._utility_scores["node_x"] = 0.0
        mempo._utility_scores["node_y"] = 0.0

        result = mempo.apply_rule_guidance(
            {"confidence": 1.0}, ["node_x", "node_y"]
        )

        assert result["boosted_count"] == 2
        assert result["max_boost"] == pytest.approx(0.2)
        # Both start at 0.0 and get +0.2 → avg_boost = 0.2
        assert result["avg_boost"] == pytest.approx(0.2)

    def test_empty_related_nodes_returns_zero_stats(self):
        """Calling with an empty list should return zero boost stats."""
        mempo = MemPO()
        result = mempo.apply_rule_guidance({"confidence": 1.0}, [])
        assert result == {"boosted_count": 0, "avg_boost": 0.0, "max_boost": 0.0}

    def test_increments_usage_count(self):
        """Each boosted node should have its usage count incremented."""
        mempo = MemPO()
        mempo._usage_count["node_a"] = 5
        mempo.apply_rule_guidance({"confidence": 0.8}, ["node_a", "node_b"])
        assert mempo._usage_count["node_a"] == 6
        assert mempo._usage_count["node_b"] == 1


class TestGetUtilityForCondition:
    """get_utility_for_condition: hash-based pseudo-node utility lookup."""

    def test_same_condition_returns_same_utility(self):
        """Calling get_utility_for_condition twice with same string returns same value."""
        mempo = MemPO()
        u1 = mempo.get_utility_for_condition("user_said_hello")
        u2 = mempo.get_utility_for_condition("user_said_hello")
        assert u1 == u2

    def test_different_conditions_return_values(self):
        """Different conditions may return different or same initial utilities."""
        mempo = MemPO()
        u1 = mempo.get_utility_for_condition("condition_alpha")
        u2 = mempo.get_utility_for_condition("condition_beta")
        # Each returns a value — they may or may not collide on pseudo_id,
        # but both should be valid floats in [0.0, 1.0]
        assert 0.0 <= u1 <= 1.0
        assert 0.0 <= u2 <= 1.0

    def test_empty_condition_returns_neutral(self):
        """Empty or None-ish condition should return 0.5."""
        mempo = MemPO()
        assert mempo.get_utility_for_condition("") == 0.5

    def test_initial_call_creates_pseudo_node(self):
        """First call for a condition should create and track a pseudo-node."""
        mempo = MemPO()
        # Ensure no prior state
        pseudo_id = f"_cond_{hash('new_condition') % (2**31)}"
        assert pseudo_id not in mempo._utility_scores
        _ = mempo.get_utility_for_condition("new_condition")
        assert pseudo_id in mempo._utility_scores

    def test_pseudo_node_utility_persists_after_set(self):
        """Manually setting a pseudo-node's utility should be reflected by get_utility_for_condition."""
        mempo = MemPO()
        # Access once to create it
        _ = mempo.get_utility_for_condition("persist_check")
        pseudo_id = f"_cond_{hash('persist_check') % (2**31)}"
        # Overwrite utility
        mempo._utility_scores[pseudo_id] = 0.9
        assert mempo.get_utility_for_condition("persist_check") == 0.9
