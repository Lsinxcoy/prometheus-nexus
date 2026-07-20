"""Tests for thermodynamic.py — Thermodynamic module.

Target coverage increase from 35% to 60%+.
Tests cover all public methods including edge cases.
"""
import time
from collections import deque

import pytest

from prometheus_nexus.lifecycle.thermodynamic import (
    ThermodynamicIntelligence,
)


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def engine():
    """Create a default ThermodynamicIntelligence instance."""
    return ThermodynamicIntelligence()


# =============================================================================
# Test Initialization
# =============================================================================

class TestInit:
    """Test ThermodynamicIntelligence initialization."""

    def test_default_initialization(self):
        """Should initialize with default values."""
        engine = ThermodynamicIntelligence()
        assert engine is not None
        assert engine._total_observations == 0
        assert engine._total_rare_observations == 0
        assert engine._rare_valid_hits == 0

    def test_custom_initialization(self):
        """Should accept custom parameters."""
        engine = ThermodynamicIntelligence(history_size=500, rare_threshold=0.2)
        assert engine._history_size == 500
        assert engine._rare_threshold == 0.2


# =============================================================================
# Test Energy
# =============================================================================

class TestEnergy:
    """Test energy calculations."""

    def test_get_energy(self, engine):
        """Should return current energy level."""
        energy = engine.get_energy()
        assert isinstance(energy, float)
        assert 0 <= energy <= 1

    def test_get_energy_at_boundaries(self, engine):
        """Should handle energy at boundaries."""
        # At temperature 0 or 1, energy should be 1.0
        engine._temperature = 0.0
        assert engine.get_energy() == 1.0
        engine._temperature = 1.0
        assert engine.get_energy() == 1.0

    def test_get_energy_in_range(self, engine):
        """Should calculate energy correctly in range."""
        engine._temperature = 0.3
        energy = engine.get_energy()
        assert 0 <= energy <= 1

    def test_get_rare_valid_ratio(self, engine):
        """Should return rare-valid ratio."""
        ratio = engine.get_rare_valid_ratio()
        assert isinstance(ratio, float)
        assert 0 <= ratio <= 1

    def test_get_rare_valid_ratio_empty(self, engine):
        """Should return 0 for empty observations."""
        assert engine.get_rare_valid_ratio() == 0.0

    def test_get_validity_rate(self, engine):
        """Should return validity rate."""
        rate = engine.get_validity_rate()
        assert isinstance(rate, float)
        assert 0 <= rate <= 1

    def test_get_validity_rate_empty(self, engine):
        """Should return 0 for no rare observations."""
        assert engine.get_validity_rate() == 0.0


# =============================================================================
# Test Observe Action
# =============================================================================

class TestObserveAction:
    """Test observing actions."""

    def test_observe_basic_action(self, engine):
        """Should record a basic action."""
        engine.observe_action("test action", outcome_valid=True, rarity=0.5)
        assert engine._total_observations == 1

    def test_observe_rare_action(self, engine):
        """Should count rare observations."""
        # rarity=0.05 < rare_threshold=0.1, so it's rare
        engine.observe_action("test action", outcome_valid=True, rarity=0.05)
        assert engine._total_observations == 1
        assert engine._total_rare_observations == 1

    def test_observe_valid_rare_action(self, engine):
        """Should count valid rare hits."""
        # rarity=0.05 < rare_threshold=0.1, so it's rare and valid
        engine.observe_action("test action", outcome_valid=True, rarity=0.05)
        assert engine._rare_valid_hits == 1

    def test_observe_invalid_rare_action(self, engine):
        """Should count invalid rare misses."""
        # rarity=0.05 < rare_threshold=0.1, so it's rare but invalid
        engine.observe_action("test action", outcome_valid=False, rarity=0.05)
        assert engine._rare_valid_misses == 1

    def test_observe_multiple_actions(self, engine):
        """Should record multiple actions."""
        for i in range(10):
            # Use rarity below threshold to trigger rare tracking
            engine.observe_action(f"action {i}", outcome_valid=True, rarity=0.05 if i % 2 == 0 else 0.5)
        assert engine._total_observations == 10
        # Only half should be rare (rarity=0.05)
        assert engine._total_rare_observations == 5

    def test_observe_baseline(self, engine):
        """Should record baseline probability."""
        engine.observe_baseline(0.01)
        assert len(engine._baseline_probs) == 1


# =============================================================================
# Test Edge Cases
# =============================================================================

class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_zero_temperature(self, engine):
        """Should handle zero temperature."""
        engine._temperature = 0.0
        assert engine.get_energy() == 1.0

    def test_one_temperature(self, engine):
        """Should handle one temperature."""
        engine._temperature = 1.0
        assert engine.get_energy() == 1.0

    def test_very_low_temperature(self, engine):
        """Should handle very low temperature."""
        engine._temperature = 0.01
        energy = engine.get_energy()
        assert 0 <= energy <= 1

    def test_very_high_temperature(self, engine):
        """Should handle very high temperature."""
        engine._temperature = 0.99
        energy = engine.get_energy()
        assert 0 <= energy <= 1

    def test_mid_temperature(self, engine):
        """Should handle mid temperature."""
        engine._temperature = 0.5
        energy = engine.get_energy()
        assert 0 <= energy <= 1


# =============================================================================
# Test Compute Intelligence
# =============================================================================

class TestComputeIntelligence:
    """Test intelligence computation."""

    def test_compute_intelligence_empty(self, engine):
        """Should return 0 for empty observations."""
        intelligence = engine.compute_intelligence()
        assert intelligence == 0.0

    def test_compute_intelligence_with_observations(self, engine):
        """Should compute intelligence correctly."""
        # Add some rare-valid observations
        engine.observe_action("test", outcome_valid=True, rarity=0.05)
        engine.observe_action("test2", outcome_valid=True, rarity=0.03)
        intelligence = engine.compute_intelligence()
        assert isinstance(intelligence, float)
        assert intelligence >= 0

    def test_compute_intelligence_custom_delta(self, engine):
        """Should accept custom delta parameter."""
        engine.observe_action("test", outcome_valid=True, rarity=0.05)
        intelligence = engine.compute_intelligence(delta=0.1)
        assert isinstance(intelligence, float)


# =============================================================================
# Test Get Rare Valid Fidelity
# =============================================================================

class TestGetRareValidFidelity:
    """Test fidelity computation."""

    def test_get_rare_valid_fidelity_empty(self, engine):
        """Should return 0 for no rare observations."""
        fidelity = engine.get_rare_valid_fidelity()
        assert fidelity == 0.0

    def test_get_rare_valid_fidelity_with_observations(self, engine):
        """Should compute fidelity correctly."""
        engine.observe_action("test", outcome_valid=True, rarity=0.05)
        fidelity = engine.get_rare_valid_fidelity()
        assert isinstance(fidelity, float)
        assert 0 <= fidelity <= 1


# =============================================================================
# Test Get Compressed Scale
# =============================================================================

class TestGetCompressedScale:
    """Test compressed scale computation."""

    def test_get_compressed_scale_empty(self, engine):
        """Should return 0 for empty observations."""
        scale = engine.get_compressed_scale()
        assert scale == 0.0

    def test_get_compressed_scale_with_observations(self, engine):
        """Should compute scale correctly."""
        engine.observe_action("test", outcome_valid=True, rarity=0.05)
        scale = engine.get_compressed_scale()
        assert isinstance(scale, float)
        assert scale >= 0


# =============================================================================
# Test Get Stats
# =============================================================================

class TestGetStats:
    """Test statistics reporting."""

    def test_get_stats_empty(self, engine):
        """Should return stats for empty state."""
        stats = engine.get_stats()
        assert "total_observations" in stats
        assert "rare_valid_hits" in stats
        assert "intelligence" in stats

    def test_get_stats_with_observations(self, engine):
        """Should update stats after observations."""
        engine.observe_action("test", outcome_valid=True, rarity=0.05)
        stats = engine.get_stats()
        assert stats["total_observations"] == 1
        assert stats["rare_valid_hits"] == 1


# =============================================================================
# Test Get Trajectory Summary
# =============================================================================

class TestGetTrajectorySummary:
    """Test trajectory summary computation."""

    def test_get_trajectory_summary_empty(self, engine):
        """Should return empty summary for no observations."""
        summary = engine.get_trajectory_summary()
        assert summary["count"] == 0

    def test_get_trajectory_summary_with_observations(self, engine):
        """Should compute summary correctly."""
        engine.observe_action("test", outcome_valid=True, rarity=0.05)
        engine.observe_action("test2", outcome_valid=False, rarity=0.5)
        summary = engine.get_trajectory_summary()
        assert summary["count"] == 2
        assert "valid_count" in summary
        assert "validity_rate" in summary

    def test_get_trajectory_summary_includes_lift(self, engine):
        """Should include lift metric."""
        engine.observe_action("test", outcome_valid=True, rarity=0.05)
        summary = engine.get_trajectory_summary()
        assert "avg_lift" in summary


# =============================================================================
# Test Edge Cases - Advanced
# =============================================================================

class TestEdgeCasesAdvanced:
    """Test advanced edge cases and boundary conditions."""

    def test_very_high_rarity_observations(self, engine):
        """Should handle very high rarity (not rare)."""
        engine.observe_action("test", outcome_valid=True, rarity=0.9)
        assert engine._total_observations == 1
        assert engine._total_rare_observations == 0

    def test_exactly_threshold_rarity(self, engine):
        """Should handle exactly threshold rarity."""
        # rarity=0.1 equals rare_threshold=0.1, should NOT be rare
        engine.observe_action("test", outcome_valid=True, rarity=0.1)
        assert engine._total_rare_observations == 0

    def test_just_below_threshold_rarity(self, engine):
        """Should handle just below threshold rarity."""
        # rarity=0.09 < rare_threshold=0.1, should be rare
        engine.observe_action("test", outcome_valid=True, rarity=0.09)
        assert engine._total_rare_observations == 1

    def test_baseline_prob_triggers_rare(self, engine):
        """Should trigger rare based on baseline probability."""
        # baseline_prob=0.05 < rare_threshold=0.1, should be rare
        engine.observe_action("test", outcome_valid=True, rarity=0.5, baseline_prob=0.05)
        assert engine._total_rare_observations == 1

    def test_induced_prob_estimation(self, engine):
        """Should estimate induced probability from validity."""
        engine.observe_action("test", outcome_valid=True, rarity=0.05, baseline_prob=0.5)
        # For valid outcome, induced_prob = baseline_prob * 2.0
        assert len(engine._induced_probs) == 1
        assert engine._induced_probs[-1] == 1.0  # 0.5 * 2.0

    def test_invalid_outcome_reduces_induced_prob(self, engine):
        """Should reduce induced probability for invalid outcomes."""
        engine.observe_action("test", outcome_valid=False, rarity=0.05, baseline_prob=0.5)
        # For invalid outcome, induced_prob = baseline_prob * 0.5
        assert len(engine._induced_probs) == 1
        assert engine._induced_probs[-1] == 0.25  # 0.5 * 0.5

    def test_custom_induced_prob(self, engine):
        """Should accept custom induced probability."""
        engine.observe_action("test", outcome_valid=True, rarity=0.05, induced_prob=0.8)
        assert len(engine._induced_probs) == 1
        assert engine._induced_probs[-1] == 0.8

    def test_history_size_limit(self, engine):
        """Should respect history size limit."""
        small_engine = ThermodynamicIntelligence(history_size=5)
        for i in range(10):
            small_engine.observe_action(f"test {i}", outcome_valid=True, rarity=0.05)
        assert len(small_engine._observations) <= 5

    def test_temperature_update_valid_rare(self, engine):
        """Should update temperature for valid rare observations."""
        initial_temp = engine._temperature
        engine.observe_action("test", outcome_valid=True, rarity=0.05)
        # Temperature should move away from 0.5 for valid rare
        assert engine._temperature != initial_temp

    def test_temperature_update_invalid(self, engine):
        """Should update temperature for invalid observations."""
        engine._temperature = 0.3  # Set to non-0.5 value
        initial_temp = engine._temperature
        engine.observe_action("test", outcome_valid=False, rarity=0.5)
        # Temperature should move toward 0.5 for invalid
        assert engine._temperature != initial_temp


# =============================================================================
# Test Get Trajectory Summary (continued)
# =============================================================================

class TestGetTrajectorySummaryAdvanced:
    """Test advanced trajectory summary computation."""

    def test_get_trajectory_summary_includes_rare_count(self, engine):
        """Should include rare count in summary."""
        engine.observe_action("test", outcome_valid=True, rarity=0.05)
        summary = engine.get_trajectory_summary()
        assert "rare_count" in summary
        assert summary["rare_count"] == 1

    def test_get_trajectory_summary_includes_rare_valid_count(self, engine):
        """Should include rare-valid count in summary."""
        engine.observe_action("test", outcome_valid=True, rarity=0.05)
        summary = engine.get_trajectory_summary()
        assert "rare_valid_count" in summary
        assert summary["rare_valid_count"] == 1

    def test_get_trajectory_summary_includes_avg_baseline(self, engine):
        """Should include average baseline probability."""
        engine.observe_action("test", outcome_valid=True, rarity=0.05, baseline_prob=0.5)
        summary = engine.get_trajectory_summary()
        assert "avg_baseline_prob" in summary

    def test_get_trajectory_summary_includes_avg_induced(self, engine):
        """Should include average induced probability."""
        engine.observe_action("test", outcome_valid=True, rarity=0.05, baseline_prob=0.5)
        summary = engine.get_trajectory_summary()
        assert "avg_induced_prob" in summary


# =============================================================================
# Test Reset
# =============================================================================

class TestReset:
    """Test reset functionality."""

    def test_reset_clears_all_state(self, engine):
        """Should clear all tracking state."""
        engine.observe_action("test", outcome_valid=True, rarity=0.05)
        engine.reset()
        assert engine._total_observations == 0
        assert engine._total_rare_observations == 0
        assert engine._rare_valid_hits == 0
        assert engine._rare_valid_misses == 0
        assert len(engine._observations) == 0

    def test_reset_resets_temperature(self, engine):
        """Should reset temperature to default."""
        engine._temperature = 0.8
        engine.reset()
        assert engine._temperature == 0.5

    def test_reset_clears_distributions(self, engine):
        """Should clear probability distributions."""
        engine.observe_action("test", outcome_valid=True, rarity=0.05)
        engine.reset()
        assert engine._p0_distribution == {}
        assert engine._p_distribution == {}


# =============================================================================
# Test Get State
# =============================================================================

class TestGetState:
    """Test state serialization."""

    def test_get_state_returns_dict(self, engine):
        """Should return a dictionary."""
        state = engine.get_state()
        assert isinstance(state, dict)

    def test_get_state_includes_required_keys(self, engine):
        """Should include required state keys."""
        state = engine.get_state()
        assert "_temperature" in state
        assert "_rare_valid_hits" in state
        assert "_rare_valid_misses" in state
        assert "_total_observations" in state
        assert "_total_rare_observations" in state

    def test_get_state_values_are_scalars(self, engine):
        """Should contain only scalar values (no history)."""
        engine.observe_action("test", outcome_valid=True, rarity=0.05)
        state = engine.get_state()
        for key, value in state.items():
            assert isinstance(value, (int, float))

    def test_get_state_after_observations(self, engine):
        """Should reflect current state after observations."""
        engine.observe_action("test", outcome_valid=True, rarity=0.05)
        state = engine.get_state()
        assert state["_total_observations"] == 1
        assert state["_rare_valid_hits"] == 1


# =============================================================================
# Test Set State
# =============================================================================

class TestSetState:
    """Test state restoration."""

    def test_set_state_restore_values(self, engine):
        """Should restore state from dictionary."""
        state = {
            "_temperature": 0.7,
            "_rare_valid_hits": 5,
            "_rare_valid_misses": 2,
            "_total_observations": 10,
            "_total_rare_observations": 7,
            "_actual_rare_valid": 6,
            "_correct_identifications": 4,
        }
        engine.set_state(state)
        assert engine._temperature == 0.7
        assert engine._rare_valid_hits == 5
        assert engine._total_observations == 10

    def test_set_state_empty_dict(self, engine):
        """Should handle empty dict gracefully."""
        engine.set_state({})
        # Should not change any values
        assert engine._temperature == 0.5

    def test_set_state_partial_dict(self, engine):
        """Should handle partial dict with defaults."""
        engine.set_state({"_temperature": 0.9})
        assert engine._temperature == 0.9
        # Other values should remain at defaults
        assert engine._rare_valid_hits == 0


# =============================================================================
# Test Update Method
# =============================================================================

class TestUpdateMethod:
    """Test backward-compatible update method."""

    def test_update_with_positive_delta(self, engine):
        """Should adjust temperature with positive delta."""
        engine._temperature = 0.3  # Set below 0.5
        initial_temp = engine._temperature
        engine.update(0.1)
        # With temp=0.3, delta=0.1: new = 0.3 + 0.1*(0.5-0.3) = 0.3 + 0.02 = 0.32
        assert engine._temperature != initial_temp

    def test_update_with_negative_delta(self, engine):
        """Should adjust temperature with negative delta."""
        engine._temperature = 0.7  # Set above 0.5
        initial_temp = engine._temperature
        engine.update(-0.1)
        # With temp=0.7, delta=-0.1: new = 0.7 + (-0.1)*(0.5-0.7) = 0.7 + 0.02 = 0.72
        assert engine._temperature != initial_temp

    def test_update_default_delta(self, engine):
        """Should use default delta of 0.1."""
        engine._temperature = 0.3  # Set below 0.5
        initial_temp = engine._temperature
        engine.update()
        assert engine._temperature != initial_temp