"""Tests for MemPO P3 enhancements: adaptive learning rate (M1) and
surprise-based adjustment (M2)."""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from prometheus_nexus.memory.mempo import MemPO


class TestAdaptiveAlpha:
    """M1: Adaptive Learning Rate — prediction-error-driven alpha adjustment."""

    def test_adaptive_alpha_starts_at_base(self):
        """With fewer than 5 prediction errors, alpha should equal base_alpha."""
        mempo = MemPO()
        # 4 calls → still < 5 → returns base_alpha (0.3)
        for i in range(4):
            result = mempo.observe_reinforcement("node_a", reward=1.0)
        # After 4 calls, _get_adaptive_alpha still returns base_alpha
        assert mempo._get_adaptive_alpha() == 0.3
        assert mempo._base_alpha == 0.3

    def test_adaptive_alpha_rises_with_high_errors(self):
        """After enough high prediction errors, adaptive alpha rises above base."""
        mempo = MemPO()
        # Use a fresh node so utility starts at 0.0.
        # Each call pushes utility closer to 1.0, reducing subsequent errors.
        for i in range(10):
            mempo.observe_reinforcement("node_x", reward=1.0)
        # With 10 entries of declining error (1.0 → ~0.0), mean_error < 1.0,
        # so alpha should be > 0.3 but < 0.6
        adaptive = mempo._get_adaptive_alpha()
        assert adaptive > 0.3, f"Expected alpha > 0.3, got {adaptive}"
        assert adaptive < 0.6, f"Expected alpha < 0.6, got {adaptive}"

    def test_adaptive_alpha_returns_to_base_with_low_errors(self):
        """After a run of low errors, alpha should return toward base."""
        mempo = MemPO()
        # Pump high errors first
        for _ in range(10):
            mempo.observe_reinforcement("node_high", reward=1.0)
        # Then low errors — use a node where utility ≈ reward so error ≈ 0
        # First give it utility ≈ 0.2
        mempo._utility_scores["node_low"] = 0.2
        for _ in range(10):
            mempo.observe_reinforcement("node_low", reward=0.2)
        # The prediction_error_history is global, so it now includes low errors
        adaptive = mempo._get_adaptive_alpha()
        # Should be lower than the 0.6 peak but can't go below base_alpha
        assert adaptive >= 0.3
        # With mixed history, it should be somewhere between 0.3 and 0.6
        assert adaptive < 0.6

    def test_adaptive_alpha_clamped(self):
        """Adaptive alpha should never exceed 0.9 or go below 0.05."""
        mempo = MemPO()
        # Push extreme high errors
        mempo._base_alpha = 0.3
        for _ in range(10):
            mempo.observe_reinforcement("node_extreme", reward=1.0)
        # Manually inject extreme error values to test clamping
        mempo._prediction_error_history = [3.0] * 10
        alpha = mempo._get_adaptive_alpha()
        # 0.3 * (1.0 + 3.0) = 1.2 → clamped to 0.9
        assert alpha == 0.9, f"Expected 0.9, got {alpha}"

        # Test low clamp
        mempo._prediction_error_history = [-0.8] * 10
        alpha = mempo._get_adaptive_alpha()
        # 0.3 * (1.0 + (-0.8)) = 0.06 → above 0.05, so 0.06
        assert alpha == pytest.approx(0.06), f"Expected 0.06, got {alpha}"

        mempo._prediction_error_history = [-2.0] * 10
        alpha = mempo._get_adaptive_alpha()
        # 0.3 * (1.0 + (-2.0)) = -0.3 → clamped to 0.05
        assert alpha == 0.05, f"Expected 0.05, got {alpha}"


class TestSurpriseDetection:
    """M2: Surprise-Based Adjustment."""

    def test_surprise_zero_with_insufficient_history(self):
        """Surprise is 0.0 when fewer than 3 signals exist for a node."""
        mempo = MemPO()
        result = mempo.observe_reinforcement("node_s", reward=0.5)
        assert result["surprise"] == 0.0

        result = mempo.observe_reinforcement("node_s", reward=0.5)
        assert result["surprise"] == 0.0

    def test_surprise_zero_with_consistent_rewards(self):
        """Surprise is near-zero when rewards are consistent."""
        mempo = MemPO()
        for _ in range(3):
            mempo.observe_reinforcement("node_c", reward=0.5)
        # 4th call: recent=[0.5, 0.5, 0.5], mean=0.5, surprise=0.0
        result = mempo.observe_reinforcement("node_c", reward=0.5)
        assert result["surprise"] == 0.0

    def test_surprise_detects_deviation(self):
        """Surprise is > 0 when a reward deviates from the recent mean."""
        mempo = MemPO()
        for _ in range(3):
            mempo.observe_reinforcement("node_d", reward=0.5)
        # 4th call: recent=[0.5, 0.5, 1.0], mean≈0.667, surprise≈0.333
        result = mempo.observe_reinforcement("node_d", reward=1.0)
        assert result["surprise"] > 0.0, "Expected surprise > 0"

    def test_surprise_triggers_alpha_boost(self):
        """When surprise > 0.3, effective_alpha should exceed adaptive_alpha."""
        mempo = MemPO()
        for _ in range(3):
            mempo.observe_reinforcement("node_b", reward=0.5)
        # 4th call: recent=[0.5, 0.5, 1.0], mean=~0.667, surprise=~0.333 > 0.3
        result = mempo.observe_reinforcement("node_b", reward=1.0)
        # boosted = 0.3 * (1.0 + 0.333 * 0.5) ≈ 0.35
        assert result["surprise"] > 0.3
        assert result["effective_alpha"] > result["adaptive_alpha"], (
            f"effective_alpha ({result['effective_alpha']}) should be > "
            f"adaptive_alpha ({result['adaptive_alpha']})"
        )


class TestCombined:
    """Both M1 and M2 working together."""

    def test_adaptive_and_surprise_both_contribute(self):
        """With high prediction error history AND surprise, effective_alpha
        should reflect M1, M2, and M3 contributions."""
        mempo = MemPO()
        # Build up prediction error history with high errors
        for _ in range(10):
            mempo.observe_reinforcement("node_p", reward=1.0)
        # Now adaptive_alpha should be elevated (≈0.6)
        adaptive_before = mempo._get_adaptive_alpha()
        assert adaptive_before > 0.3

        # Feed consistent rewards to node_s for 3 calls
        mempo.observe_reinforcement("node_s", reward=0.5)
        mempo.observe_reinforcement("node_s", reward=0.5)
        mempo.observe_reinforcement("node_s", reward=0.5)
        # 4th call with deviating reward
        result = mempo.observe_reinforcement("node_s", reward=1.0)

        # effective_alpha should be max(adaptive_alpha, boosted, per_node_alpha)
        # adaptive_alpha ≈ 0.36 (global, from node_p's errors)
        # boosted = 0.3 * (1.0 + surprise * 0.5), surprise ≈ 0.333 → ≈ 0.35
        # per_node_alpha = volatility-based from node_s's [0.5,0.5,0.5,1.0]
        #   volatility = 0.5 / 0.625 = 0.8 → adjusted = 0.3 * 1.4 = 0.42
        # So effective_alpha should be 0.42 (dominated by per-node alpha)
        assert result["effective_alpha"] > 0.3
        assert result["surprise"] > 0.0
        # effective_alpha is the max of all three sources
        assert result["effective_alpha"] >= result["adaptive_alpha"]

    def test_surprise_dominates_when_adaptive_still_low(self):
        """When adaptive alpha is still at base (few errors), surprise
        boost drives effective_alpha."""
        mempo = MemPO()
        # No prediction errors yet — adaptive_alpha = base = 0.3
        # Feed 3 consistent rewards, then a surprise
        for _ in range(3):
            mempo.observe_reinforcement("node_t", reward=0.0)
        # 4th call: recent=[0.0, 0.0, 1.0], mean=0.333, surprise=0.667
        result = mempo.observe_reinforcement("node_t", reward=1.0)
        # adaptive_alpha = 0.3 (still < 5 entries for node, but
        # prediction_error_history is global — actually we made 4 calls
        # total across all nodes, so < 5)
        # boosted = 0.3 * (1.0 + 0.667 * 0.5) ≈ 0.3 * 1.333 ≈ 0.4
        # effective_alpha = max(0.3, 0.4) = 0.4
        assert result["effective_alpha"] > result["adaptive_alpha"]

    def test_utility_update_uses_effective_alpha(self):
        """The actual utility update should reflect the effective_alpha."""
        mempo = MemPO()
        mempo._utility_scores["node_u"] = 0.5

        # 3 consistent rewards
        for _ in range(3):
            mempo.observe_reinforcement("node_u", reward=0.5)
        # 4th call: surprise deviates → effective_alpha > base
        result = mempo.observe_reinforcement("node_u", reward=1.0)

        utility_before = result["utility_before"]
        utility_after = result["utility_after"]
        effective = result["effective_alpha"]

        # Manual check: utility_after = 0.5 + eff * (1.0 - 0.5)
        expected = max(0.0, min(1.0, utility_before + effective * (1.0 - utility_before)))
        assert utility_after == pytest.approx(expected, rel=1e-6), (
            f"Expected {expected}, got {utility_after}"
        )
