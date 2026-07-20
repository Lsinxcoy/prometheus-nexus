"""Tests for MemPO P3 Phase 2 enhancements: per-node adaptive alpha (M3)
and negative reinforcement from usage (M4)."""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from prometheus_nexus.memory.mempo import MemPO


class TestPerNodeAlpha:
    """M3: Per-Node Adaptive Alpha."""

    def test_node_alpha_differs_between_nodes_with_different_volatility(self):
        """Nodes with volatile reward patterns get higher per-node alpha
        than nodes with stable reward patterns."""
        mempo = MemPO()
        # Node A: stable rewards (0.5, 0.5, 0.5, 0.5, 0.5)
        for _ in range(5):
            mempo.observe_reinforcement("node_stable", reward=0.5)
        # Node B: volatile rewards (1.0, 0.0, 1.0, 0.0, 1.0)
        for r in [1.0, 0.0, 1.0, 0.0, 1.0]:
            mempo.observe_reinforcement("node_volatile", reward=r)

        alpha_stable = mempo._get_node_alpha("node_stable")
        alpha_volatile = mempo._get_node_alpha("node_volatile")

        # Volatile node should have higher per-node alpha
        assert alpha_volatile > alpha_stable, (
            f"Expected volatile node alpha ({alpha_volatile}) > "
            f"stable node alpha ({alpha_stable})"
        )
        # Both should be at least the base alpha
        assert alpha_stable >= mempo._policy_params["alpha"]
        assert alpha_volatile >= mempo._policy_params["alpha"]

    def test_node_alpha_starts_at_base_with_insufficient_data(self):
        """With fewer than 3 signals, _get_node_alpha returns the base."""
        mempo = MemPO()
        # 0 signals
        alpha = mempo._get_node_alpha("node_fresh")
        assert alpha == mempo._policy_params["alpha"]

        # 2 signals — still < 3
        mempo.observe_reinforcement("node_fresh", reward=0.5)
        mempo.observe_reinforcement("node_fresh", reward=0.5)
        alpha = mempo._get_node_alpha("node_fresh")
        assert alpha == mempo._policy_params["alpha"]

    def test_node_alpha_converges_after_sufficient_data(self):
        """Per-node alpha stabilises as more consistent signals arrive."""
        mempo = MemPO()
        # Feed consistent rewards — volatility should trend to 0
        for _ in range(10):
            mempo.observe_reinforcement("node_converge", reward=0.5)

        alpha = mempo._get_node_alpha("node_converge")
        # With 10 identical rewards, range = 0 → volatility = 0
        # adjusted = base * (1.0 + 0 * 0.5) = base
        # So alpha should be close to base_alpha
        assert alpha == pytest.approx(mempo._policy_params["alpha"], abs=0.01), (
            f"Expected alpha close to {mempo._policy_params['alpha']}, got {alpha}"
        )

    def test_node_alpha_capped_at_09(self):
        """Per-node alpha should never exceed 0.9."""
        mempo = MemPO()
        # Extreme volatility: alternating 1.0 and -1.0
        for _ in range(5):
            mempo.observe_reinforcement("node_wild", reward=1.0)
            mempo.observe_reinforcement("node_wild", reward=-1.0)

        alpha = mempo._get_node_alpha("node_wild")
        assert alpha <= 0.9, f"Expected alpha <= 0.9, got {alpha}"
        # With max volatility it should be pushed high
        assert alpha > mempo._policy_params["alpha"], (
            f"Expected alpha > base, got {alpha}"
        )


class TestNegativeReinforcement:
    """M4: Negative Reinforcement from Usage."""

    def test_negative_reinforcement_decreases_utility(self):
        """Negative reward should decrease a node's utility."""
        mempo = MemPO()
        # Start with utility = 0.5
        mempo._utility_scores["node_neg"] = 0.5

        # Apply negative reinforcement
        result = mempo.observe_reinforcement("node_neg", reward=-0.5)
        assert result["utility_after"] < result["utility_before"], (
            f"Utility should decrease with negative reward, got "
            f"{result['utility_before']} -> {result['utility_after']}"
        )

    def test_negative_reinforcement_can_drive_utility_to_zero(self):
        """Consistent negative reinforcement can drive utility to 0."""
        mempo = MemPO()
        mempo._utility_scores["node_zero"] = 0.8

        for _ in range(20):
            mempo.observe_reinforcement("node_zero", reward=-1.0)

        utility = mempo.get_utility("node_zero")
        assert utility == pytest.approx(0.0, abs=0.01), (
            f"Expected utility near 0, got {utility}"
        )

    def test_mixed_reinforcement_batch_update(self):
        """batch_update_utilities with mixed positive/negative scores."""
        mempo = MemPO()
        # Set some initial utilities
        mempo._utility_scores["node_a"] = 0.5
        mempo._utility_scores["node_b"] = 0.5
        mempo._utility_scores["node_c"] = 0.5

        # Positive, neutral, negative
        result = mempo.batch_update_utilities(
            ["node_a", "node_b", "node_c"],
            [0.8, 0.0, -0.5],
        )

        assert result["updated"] == 3
        util_a = mempo.get_utility("node_a")
        util_b = mempo.get_utility("node_b")
        util_c = mempo.get_utility("node_c")

        # Positive reinforcement should increase or maintain
        assert util_a >= 0.5, f"Expected node_a utility >= 0.5, got {util_a}"
        # Neutral should be close to initial (slight drift is OK)
        # Negative should decrease
        assert util_c < 0.5, f"Expected node_c utility < 0.5, got {util_c}"
        # Positive > neutral > negative
        assert util_a > util_c, (
            f"Expected node_a ({util_a}) > node_c ({util_c})"
        )

    def test_backward_compat_bool_to_float_conversion(self):
        """batch_update_utilities with bool values should work with warning."""
        mempo = MemPO()
        mempo._utility_scores["node_bool1"] = 0.3
        mempo._utility_scores["node_bool2"] = 0.3

        # Pass booleans (old API style)
        import logging
        logger = logging.getLogger("prometheus_nexus.memory.mempo")
        original_level = logger.level
        logger.setLevel(logging.DEBUG)

        result = mempo.batch_update_utilities(
            ["node_bool1", "node_bool2"],
            [True, False],
        )

        logger.setLevel(original_level)

        assert result["updated"] == 2
        # True → reward=1.0 should increase utility
        assert mempo.get_utility("node_bool1") > 0.3, (
            f"Expected node_bool1 > 0.3, got {mempo.get_utility('node_bool1')}"
        )
        # False → reward=0.0 should not increase (may decrease slightly)
        assert mempo.get_utility("node_bool2") <= 0.3, (
            f"Expected node_bool2 <= 0.3, got {mempo.get_utility('node_bool2')}"
        )


class TestM3M4Combined:
    """M3 and M4 working together."""

    def test_per_node_alpha_affects_batch_update(self):
        """Nodes with volatile patterns should learn faster (higher alpha)
        during batch updates."""
        mempo = MemPO()
        # Set initial utilities
        mempo._utility_scores["node_stable"] = 0.5
        mempo._utility_scores["node_volatile"] = 0.5

        # Build up history for both nodes
        for _ in range(5):
            mempo.observe_reinforcement("node_stable", reward=0.5)
        for r in [1.0, 0.0, 1.0, 0.0, 1.0]:
            mempo.observe_reinforcement("node_volatile", reward=r)

        alpha_volatile = mempo._get_node_alpha("node_volatile")
        alpha_stable = mempo._get_node_alpha("node_stable")
        assert alpha_volatile > alpha_stable, "Volatile node should have higher alpha"

        effective_volatile = mempo.observe_reinforcement("node_volatile", reward=1.0)[
            "effective_alpha"
        ]
        effective_stable = mempo.observe_reinforcement("node_stable", reward=1.0)[
            "effective_alpha"
        ]
        # Volatile node's effective alpha should be >= stable node's
        assert effective_volatile >= effective_stable, (
            f"Expected volatile eff_alpha ({effective_volatile}) >= "
            f"stable eff_alpha ({effective_stable})"
        )

    def test_full_flow_with_effective_alpha_in_return(self):
        """The return dict from observe_reinforcement includes all alphas."""
        mempo = MemPO()
        for _ in range(5):
            mempo.observe_reinforcement("node_full", reward=0.5)

        result = mempo.observe_reinforcement("node_full", reward=0.5)
        # Should include adaptive_alpha, surprise, effective_alpha
        assert "adaptive_alpha" in result
        assert "surprise" in result
        assert "effective_alpha" in result
        # With consistent rewards, surprise should be 0.0
        assert result["surprise"] == 0.0
        # effective_alpha should be >= adaptive_alpha
        assert result["effective_alpha"] >= result["adaptive_alpha"]
