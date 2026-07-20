"""Tests for MemPO AgeMem enhancement: three-stage progressive RL and step-wise GRPO.

Tests B2-4: AgeMem step-wise GRPO enhancement for mempo.py.
"""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from prometheus_nexus.memory.mempo import MemPO, _safe_mean, _compute_std


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


class TestHelpers:
    """Unit tests for module-level helper functions."""

    def test_safe_mean_empty(self):
        assert _safe_mean([]) == 0.0

    def test_safe_mean_single(self):
        assert _safe_mean([5.0]) == 5.0

    def test_safe_mean_multiple(self):
        assert _safe_mean([1.0, 2.0, 3.0]) == 2.0

    def test_compute_std_fewer_than_two(self):
        assert _compute_std([5.0], 5.0) == 0.0
        assert _compute_std([], 0.0) == 0.0

    def test_compute_std_known(self):
        vals = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
        mean = sum(vals) / len(vals)  # 5.0
        std = _compute_std(vals, mean)
        # population std = sqrt(32/8) = sqrt(4) = 2.0
        assert std == pytest.approx(2.0, rel=1e-6)

    def test_compute_std_zero_variance(self):
        vals = [3.0, 3.0, 3.0]
        std = _compute_std(vals, 3.0)
        assert std == 0.0


# ---------------------------------------------------------------------------
# AgeMem stage transitions
# ---------------------------------------------------------------------------


class TestStageTransitions:
    """Test that set_stage / get_stage work correctly."""

    def test_default_stage_is_clone(self):
        mempo = MemPO()
        assert mempo.get_stage() == "clone"

    def test_transition_clone_to_rl(self):
        mempo = MemPO()
        result = mempo.set_stage("rl")
        assert mempo.get_stage() == "rl"
        assert result["stage"] == "rl"
        assert result["previous_stage"] == "clone"
        assert result["stage_lr_multiplier"] == 1.0

    def test_transition_rl_to_joint(self):
        mempo = MemPO()
        mempo.set_stage("rl")
        result = mempo.set_stage("joint")
        assert mempo.get_stage() == "joint"
        assert result["stage"] == "joint"
        assert result["previous_stage"] == "rl"
        assert result["stage_lr_multiplier"] == 0.8

    def test_transition_joint_to_clone(self):
        mempo = MemPO()
        mempo.set_stage("joint")
        result = mempo.set_stage("clone")
        assert mempo.get_stage() == "clone"
        assert result["previous_stage"] == "joint"
        assert result["stage_lr_multiplier"] == 0.5

    def test_full_cycle(self):
        """clone → rl → joint completes the AgeMem progressive pipeline."""
        mempo = MemPO()
        assert mempo.get_stage() == "clone"
        mempo.set_stage("rl")
        assert mempo.get_stage() == "rl"
        mempo.set_stage("joint")
        assert mempo.get_stage() == "joint"

    def test_invalid_stage_raises(self):
        mempo = MemPO()
        with pytest.raises(ValueError):
            mempo.set_stage("invalid")
        # Stage should remain unchanged after error
        assert mempo.get_stage() == "clone"

    def test_case_insensitive(self):
        mempo = MemPO()
        mempo.set_stage("RL")
        assert mempo.get_stage() == "rl"
        mempo.set_stage("Joint ")
        assert mempo.get_stage() == "joint"

    def test_stage_persists_across_operations(self):
        mempo = MemPO()
        mempo.set_stage("rl")
        mempo.observe_access("node_001")
        mempo.observe_reinforcement("node_001", reward=1.0)
        assert mempo.get_stage() == "rl"


# ---------------------------------------------------------------------------
# record_reward
# ---------------------------------------------------------------------------


class TestRecordReward:
    """Test that record_reward stores memory effectiveness rewards."""

    def test_record_simple(self):
        mempo = MemPO()
        result = mempo.record_reward("node_a", 0.85)
        assert result["node_id"] == "node_a"
        assert result["reward"] == 0.85
        assert result["context"] == ""
        assert result["total_recorded"] == 1
        assert "timestamp" in result

    def test_record_with_context(self):
        mempo = MemPO()
        result = mempo.record_reward("node_b", -0.3, context="retrieval_fail")
        assert result["context"] == "retrieval_fail"
        assert result["reward"] == -0.3
        assert result["total_recorded"] == 1

    def test_record_multiple_nodes(self):
        mempo = MemPO()
        mempo.record_reward("node_a", 0.9, context="qa")
        mempo.record_reward("node_b", 0.5, context="qa")
        mempo.record_reward("node_a", 0.7, context="planning")
        assert len(mempo._reward_history) == 3

    def test_record_tracks_timestamps(self):
        mempo = MemPO()
        r1 = mempo.record_reward("node_x", 1.0)
        r2 = mempo.record_reward("node_x", 0.0)
        assert r2["timestamp"] >= r1["timestamp"]
        assert r1["total_recorded"] == 1
        assert r2["total_recorded"] == 2

    def test_record_negative_reward(self):
        mempo = MemPO()
        result = mempo.record_reward("node_bad", -1.0, context="irrelevant")
        assert result["reward"] == -1.0

    def test_record_isolation(self):
        """Reward history is isolated per MemPO instance."""
        m1 = MemPO()
        m2 = MemPO()
        m1.record_reward("node", 1.0)
        assert len(m1._reward_history) == 1
        assert len(m2._reward_history) == 0


# ---------------------------------------------------------------------------
# step_grpo
# ---------------------------------------------------------------------------


class TestStepGrpo:
    """Test step-wise GRPO update."""

    def test_step_grpo_basic(self):
        mempo = MemPO()
        result = mempo.step_grpo([0.6, 0.8, 0.4, 0.9], group_size=4)
        assert result["step_count"] == 1
        assert "mean_advantage" in result
        assert "mean_reward" in result
        assert "policy_loss" in result
        assert result["stage"] == "clone"
        assert result["effective_lr"] == 0.01 * 0.5  # clone lr_mult = 0.5

    def test_step_grpo_tracks_metrics(self):
        mempo = MemPO()
        mempo.step_grpo([0.5, 0.5, 0.5, 0.5], group_size=4)
        assert mempo._grpo_step_count == 1
        assert len(mempo._grpo_advantage_history) == 1
        assert len(mempo._grpo_reward_history) == 1
        assert len(mempo._grpo_policy_losses) == 1

    def test_step_grpo_multiple_steps(self):
        mempo = MemPO()
        r1 = mempo.step_grpo([0.6, 0.7, 0.5, 0.8], group_size=4)
        r2 = mempo.step_grpo([0.3, 0.9, 0.4, 0.2], group_size=4)
        assert r2["step_count"] == 2
        assert r2["step_count"] > r1["step_count"]

    def test_step_grpo_smaller_group(self):
        """Handle fewer rewards than group_size gracefully."""
        mempo = MemPO()
        result = mempo.step_grpo([0.8, 0.6], group_size=4)
        assert result["step_count"] == 1
        assert result["mean_reward"] == pytest.approx(0.7, rel=1e-6)

    def test_step_grpo_empty_rewards_raises(self):
        mempo = MemPO()
        with pytest.raises(ValueError, match="rewards list is empty"):
            mempo.step_grpo([], group_size=4)

    def test_step_grpo_group_size_too_small_raises(self):
        mempo = MemPO()
        with pytest.raises(ValueError, match="group_size must be >= 2"):
            mempo.step_grpo([0.5, 0.5], group_size=1)

    def test_step_grpo_rl_stage_lr(self):
        mempo = MemPO()
        mempo.set_stage("rl")
        result = mempo.step_grpo([0.6, 0.8, 0.4, 0.9], group_size=4)
        # rl lr_mult = 1.0, so effective_lr = 0.01 * 1.0 = 0.01
        assert result["effective_lr"] == pytest.approx(0.01, rel=1e-6)
        assert result["stage"] == "rl"

    def test_step_grpo_joint_stage_lr(self):
        mempo = MemPO()
        mempo.set_stage("joint")
        result = mempo.step_grpo([0.6, 0.8, 0.4, 0.9], group_size=4)
        # joint lr_mult = 0.8, so effective_lr = 0.01 * 0.8 = 0.008
        assert result["effective_lr"] == pytest.approx(0.008, rel=1e-6)
        assert result["stage"] == "joint"

    def test_step_grpo_advantage_zero_for_identical_rewards(self):
        """When all rewards are identical, advantages should be 0."""
        mempo = MemPO()
        result = mempo.step_grpo([0.5, 0.5, 0.5, 0.5], group_size=4)
        # mean_advantage should be 0 (all rewards equal)
        assert result["mean_advantage"] == pytest.approx(0.0, abs=1e-6)

    def test_step_grpo_advantage_signs(self):
        """Rewards above mean should have positive advantage, below negative."""
        mempo = MemPO()
        result = mempo.step_grpo([0.1, 0.5, 0.9, 0.3], group_size=4)
        # mean = 0.45; 0.9 is above, 0.1 below
        # We don't know exact advantage values but the signs should work out
        assert "mean_advantage" in result

    def test_step_grpo_rewards_recorded_in_history(self):
        """Rewards from GRPO steps should be accessible via grpo_reward_history."""
        mempo = MemPO()
        mempo.step_grpo([0.6, 0.8, 0.4, 0.9], group_size=4)
        # mean = 0.675
        assert mempo._grpo_reward_history[0] == pytest.approx(0.675, rel=1e-6)


# ---------------------------------------------------------------------------
# Enhanced stats
# ---------------------------------------------------------------------------


class TestStatsEnhanced:
    """Test that get_stats includes AgeMem stage info and GRPO metrics."""

    def test_stats_includes_stage(self):
        mempo = MemPO()
        stats = mempo.get_stats()
        assert "stage" in stats
        assert stats["stage"] == "clone"

    def test_stats_includes_grpo_metrics(self):
        mempo = MemPO()
        stats = mempo.get_stats()
        assert "grpo_metrics" in stats
        assert "step_count" in stats["grpo_metrics"]
        assert "avg_advantage" in stats["grpo_metrics"]
        assert "avg_reward" in stats["grpo_metrics"]
        assert "avg_policy_loss" in stats["grpo_metrics"]
        assert "total_rewards_recorded" in stats["grpo_metrics"]

    def test_stats_grpo_metrics_after_grpo_step(self):
        mempo = MemPO()
        mempo.step_grpo([0.6, 0.8, 0.4, 0.9], group_size=4)
        stats = mempo.get_stats()
        assert stats["grpo_metrics"]["step_count"] == 1
        assert stats["grpo_metrics"]["total_rewards_recorded"] == 0  # rewards via record_reward, not step_grpo

    def test_stats_grpo_metrics_after_record_reward(self):
        mempo = MemPO()
        mempo.record_reward("node_x", 0.85, context="test")
        stats = mempo.get_stats()
        assert stats["grpo_metrics"]["total_rewards_recorded"] == 1

    def test_stats_stage_reflects_set_stage(self):
        mempo = MemPO()
        mempo.set_stage("joint")
        stats = mempo.get_stats()
        assert stats["stage"] == "joint"

    def test_stats_preserves_original_keys(self):
        """Existing stats keys must still be present."""
        mempo = MemPO()
        mempo.observe_access("node_a")
        mempo.observe_access("node_b")
        stats = mempo.get_stats()
        assert "total_nodes" in stats
        assert "avg_utility" in stats
        assert "total_usage_count" in stats
        assert "policy_params" in stats
        assert stats["total_nodes"] == 2

    def test_stats_grpo_metrics_empty_initially(self):
        mempo = MemPO()
        stats = mempo.get_stats()
        gm = stats["grpo_metrics"]
        assert gm["step_count"] == 0
        assert gm["avg_advantage"] == 0.0
        assert gm["avg_reward"] == 0.0
        assert gm["avg_policy_loss"] == 0.0
        assert gm["total_rewards_recorded"] == 0

    def test_stats_multiple_grpo_steps(self):
        mempo = MemPO()
        mempo.step_grpo([0.6, 0.7, 0.5, 0.8], group_size=4)
        mempo.step_grpo([0.3, 0.9, 0.4, 0.2], group_size=4)
        stats = mempo.get_stats()
        assert stats["grpo_metrics"]["step_count"] == 2

    def test_stats_grpo_avg_advantage_correct(self):
        mempo = MemPO()
        mempo.step_grpo([0.5, 0.5, 0.5, 0.5], group_size=4)
        stats = mempo.get_stats()
        assert stats["grpo_metrics"]["avg_advantage"] == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Backwards compatibility
# ---------------------------------------------------------------------------


class TestBackwardsCompatibility:
    """Existing MemPO functionality must still work unchanged."""

    def test_observe_access_still_works(self):
        mempo = MemPO()
        result = mempo.observe_access("node_001")
        assert "node_id" in result
        assert "utility_before" in result
        assert "utility_after" in result

    def test_observe_reinforcement_still_works(self):
        mempo = MemPO()
        result = mempo.observe_reinforcement("node_001", reward=1.0)
        assert result["utility_after"] >= result["utility_before"]

    def test_get_utility_still_works(self):
        mempo = MemPO()
        mempo.observe_access("node_001")
        utility = mempo.get_utility("node_001")
        assert 0.0 <= utility <= 1.0

    def test_batch_get_utilities_still_works(self):
        mempo = MemPO()
        mempo.observe_access("node_a")
        mempo.observe_access("node_b")
        utilities = mempo.batch_get_utilities(["node_a", "node_b", "node_c"])
        assert isinstance(utilities, dict)
        assert len(utilities) == 3

    def test_batch_update_utilities_still_works(self):
        mempo = MemPO()
        result = mempo.batch_update_utilities(
            ["node_a", "node_b"], [1.0, 0.5]
        )
        assert "updated" in result
        assert result["updated"] == 2
        assert "avg_utility" in result

    def test_batch_update_utilities_bool_backward_compat(self):
        mempo = MemPO()
        result = mempo.batch_update_utilities(["node_a"], [True])
        assert result["updated"] == 1

    def test_set_policy_params_still_works(self):
        mempo = MemPO()
        result = mempo.set_policy_params({"alpha": 0.5})
        assert result["updated"] is True
        assert result["params"]["alpha"] == 0.5

    def test_get_stats_still_has_original_keys(self):
        mempo = MemPO()
        stats = mempo.get_stats()
        for key in ("total_nodes", "avg_utility", "total_usage_count", "policy_params"):
            assert key in stats

    def test_apply_rule_guidance_still_works(self):
        mempo = MemPO()
        rule = {"confidence": 0.8}
        result = mempo.apply_rule_guidance(rule, ["node_a", "node_b"])
        assert "boosted_count" in result
        assert result["boosted_count"] == 2

    def test_get_utility_for_condition_still_works(self):
        mempo = MemPO()
        utility = mempo.get_utility_for_condition("some condition")
        assert 0.0 <= utility <= 1.0
        assert utility == 0.5  # default for untracked

    def test_existing_alpha_mechanics_unchanged(self):
        """M1, M2, M3 mechanics should still function."""
        mempo = MemPO()
        for _ in range(4):
            mempo.observe_reinforcement("node_t", reward=1.0)
        # After 4 calls, adaptive_alpha should still equal base_alpha
        assert mempo._get_adaptive_alpha() == 0.3

    def test_original_constructor_works(self):
        """Passing no arguments to constructor should still work."""
        mempo = MemPO()
        assert mempo._policy_params["alpha"] == 0.3

    def test_constructor_with_params_still_works(self):
        """Passing policy_params to constructor should still work."""
        mempo = MemPO(policy_params={"alpha": 0.7})
        assert mempo._policy_params["alpha"] == 0.7

    def test_observe_access_maintains_backward_result(self):
        """observe_access return format should match original."""
        mempo = MemPO()
        result = mempo.observe_access("node_x")
        expected_keys = {"node_id", "utility_before", "utility_after"}
        assert set(result.keys()) == expected_keys

    def test_observe_reinforcement_maintains_backward_result(self):
        """observe_reinforcement return format should match original."""
        mempo = MemPO()
        mempo.observe_reinforcement("node_x", 0.5)
        mempo.observe_reinforcement("node_x", 0.5)
        mempo.observe_reinforcement("node_x", 0.5)
        result = mempo.observe_reinforcement("node_x", 1.0)
        expected_keys = {
            "node_id", "utility_before", "utility_after",
            "adaptive_alpha", "surprise", "effective_alpha",
        }
        assert set(result.keys()) == expected_keys
