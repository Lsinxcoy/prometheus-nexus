"""Deep tests for dopamine.py module.

Phase 1 Day 3: DopamineWriteGate tests (400+ lines)
Target coverage: 31% → 80%
"""
import time
import random
import threading
import pytest
from prometheus_nexus.memory.dopamine import DopamineWriteGate, DopamineGateConfig, GateDecision


class TestDopamineGateConfig:
    """Test DopamineGateConfig initialization."""

    def test_default_config(self):
        """Should create config with default values."""
        config = DopamineGateConfig()
        assert config.threshold == 0.3
        assert config.utility_weight == 0.6
        assert config.surprise_weight == 0.4
        assert config.accept_rate_target == 0.6
        assert config.adaptive is False

    def test_custom_config(self):
        """Should accept custom parameters."""
        config = DopamineGateConfig(
            threshold=0.7,
            utility_weight=0.8,
            surprise_weight=0.2,
            accept_rate_target=0.6,
            adaptive=True,
        )
        assert config.threshold == 0.7
        assert config.utility_weight == 0.8
        assert config.surprise_weight == 0.2
        assert config.accept_rate_target == 0.6
        assert config.adaptive is True


class TestGateDecision:
    """Test GateDecision dataclass."""

    def test_decision_creation(self):
        """Should create decision with all fields."""
        decision = GateDecision(
            decision="accept",
            score=0.85,
            threshold=0.3,
            utility=0.8,
            surprise=0.4,
        )
        assert decision.decision == "accept"
        assert decision.score == 0.85
        assert decision.utility == 0.8
        assert decision.surprise == 0.4
        assert decision.threshold == 0.3


class TestDopamineWriteGateInitialization:
    """Test DopamineWriteGate initialization."""

    def test_default_initialization(self):
        """Should initialize with default config."""
        gate = DopamineWriteGate()
        assert gate._cfg.threshold == 0.3
        assert gate._total == 0
        assert gate._accepted == 0
        assert gate._rejected == 0

    def test_custom_initialization(self):
        """Should accept custom config."""
        config = DopamineGateConfig(threshold=0.7)
        gate = DopamineWriteGate(config)
        assert gate._cfg.threshold == 0.7

    def test_get_stats_empty(self):
        """Should return stats for empty gate."""
        gate = DopamineWriteGate()
        stats = gate.get_stats()
        assert stats["total"] == 0
        assert stats["accepted"] == 0
        assert stats["rejected"] == 0
        assert stats["accept_rate"] == 0.0


class TestEvaluate:
    """Test evaluate method."""

    def test_evaluate_high_utility(self):
        """Should accept high utility entries."""
        gate = DopamineWriteGate()
        decision = gate.evaluate(utility=0.8, surprise=0.3)
        assert decision.accepted is True

    def test_evaluate_low_utility(self):
        """Should reject low utility entries."""
        gate = DopamineWriteGate()
        decision = gate.evaluate(utility=0.2, surprise=0.3)
        assert decision.accepted is False

    def test_evaluate_exact_threshold(self):
        """Should accept entry at exact threshold."""
        gate = DopamineWriteGate()
        # score = 0.5 * 0.7 + 0.5 * 0.3 = 0.5
        decision = gate.evaluate(utility=0.5, surprise=0.5)
        assert decision.accepted is True

    def test_evaluate_score_calculation(self):
        """Should calculate score correctly."""
        gate = DopamineWriteGate()
        decision = gate.evaluate(utility=0.8, surprise=0.4)
        # score = 0.8 * 0.6 + 0.4 * 0.4 = 0.48 + 0.16 = 0.64
        expected_score = 0.8 * 0.6 + 0.4 * 0.4
        assert abs(decision.score - expected_score) < 0.001

    def test_evaluate_zero_utility(self):
        """Should handle zero utility."""
        gate = DopamineWriteGate()
        decision = gate.evaluate(utility=0.0, surprise=0.5)
        # score = 0 * 0.7 + 0.5 * 0.3 = 0.15 < 0.5
        assert decision.accepted is False

    def test_evaluate_max_utility(self):
        """Should handle maximum utility."""
        gate = DopamineWriteGate()
        decision = gate.evaluate(utility=1.0, surprise=1.0)
        # score = 1.0 * 0.7 + 1.0 * 0.3 = 1.0
        assert decision.accepted is True

    def test_evaluate_negative_utility(self):
        """Should handle negative utility."""
        gate = DopamineWriteGate()
        decision = gate.evaluate(utility=-0.1, surprise=0.5)
        assert decision.accepted is False

    def test_evaluate_updates_stats(self):
        """Should update statistics on evaluation."""
        gate = DopamineWriteGate()
        gate.evaluate(utility=0.8, surprise=0.3)
        gate.evaluate(utility=0.2, surprise=0.3)
        stats = gate.get_stats()
        assert stats["total"] == 2
        assert stats["accepted"] == 1
        assert stats["rejected"] == 1

    def test_evaluate_with_custom_threshold(self):
        """Should use custom threshold from config."""
        config = DopamineGateConfig(threshold=0.8)
        gate = DopamineWriteGate(config)
        decision = gate.evaluate(utility=0.7, surprise=0.5)
        # score = 0.7 * 0.7 + 0.5 * 0.3 = 0.64 < 0.8
        assert decision.accepted is False


class TestAdaptiveThreshold:
    """Test adaptive threshold functionality."""

    def test_adaptive_threshold_increases(self):
        """Should increase threshold when acceptance rate too high."""
        config = DopamineGateConfig(
            threshold=0.3,
            adaptive=True,
            accept_rate_target=0.5,
        )
        gate = DopamineWriteGate(config)
        # Add many high-utility entries to trigger adaptation
        for _ in range(20):
            gate.evaluate(utility=0.9, surprise=0.9)
        # Threshold should have increased
        assert gate._current_threshold > 0.3

    def test_adaptive_threshold_decreases(self):
        """Should decrease threshold when acceptance rate too low."""
        config = DopamineGateConfig(
            threshold=0.8,
            adaptive=True,
            accept_rate_target=0.5,
        )
        gate = DopamineWriteGate(config)
        # Add many low-utility entries to trigger adaptation
        for _ in range(20):
            gate.evaluate(utility=0.1, surprise=0.1)
        # Threshold should have decreased
        assert gate._current_threshold < 0.8

    def test_adaptive_disabled(self):
        """Should not adapt when disabled."""
        config = DopamineGateConfig(threshold=0.5, adaptive=False)
        gate = DopamineWriteGate(config)
        for _ in range(20):
            gate.evaluate(utility=0.9, surprise=0.9)
        assert gate._current_threshold == 0.5


class TestSlidingWindow:
    """Test sliding window behavior."""

    def test_window_size_limit(self):
        """Should limit history to window size."""
        config = DopamineGateConfig(window_size=10)
        gate = DopamineWriteGate(config)
        for i in range(20):
            gate.evaluate(utility=0.8, surprise=0.5)
        assert len(gate._history) <= 10

    def test_old_decisions_expire(self):
        """Should expire old decisions."""
        config = DopamineGateConfig(window_size=5)
        gate = DopamineWriteGate(config)
        # Add 5 accepts
        for _ in range(5):
            gate.evaluate(utility=0.9, surprise=0.9)
        # Add 5 rejects (should push out first 5)
        for _ in range(5):
            gate.evaluate(utility=0.1, surprise=0.1)
        # History should only contain last 5
        assert len(gate._history) <= 5


class TestReset:
    """Test reset functionality."""

    def test_reset_clears_stats(self):
        """Should clear all statistics."""
        gate = DopamineWriteGate()
        gate.evaluate(utility=0.8, surprise=0.5)
        gate.evaluate(utility=0.2, surprise=0.5)
        gate.reset()
        stats = gate.get_stats()
        assert stats["total"] == 0
        assert stats["accepted"] == 0
        assert stats["rejected"] == 0

    def test_reset_clears_history(self):
        """Should clear history."""
        gate = DopamineWriteGate()
        for _ in range(10):
            gate.evaluate(utility=0.8, surprise=0.5)
        gate.reset()
        assert len(gate._history) == 0
        assert len(gate._decisions) == 0

    def test_reset_preserves_config(self):
        """Should preserve configuration."""
        config = DopamineGateConfig(threshold=0.7)
        gate = DopamineWriteGate(config)
        gate.reset()
        assert gate._cfg.threshold == 0.7


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_very_small_utility(self):
        """Should handle very small positive utility."""
        gate = DopamineWriteGate()
        decision = gate.evaluate(utility=0.0001, surprise=0.5)
        assert isinstance(decision.accepted, bool)

    def test_very_large_utility(self):
        """Should handle very large utility."""
        gate = DopamineWriteGate()
        decision = gate.evaluate(utility=100.0, surprise=0.5)
        assert decision.accepted is True

    def test_floating_point_precision(self):
        """Should handle floating point precision issues."""
        gate = DopamineWriteGate()
        decision = gate.evaluate(utility=0.3333333333, surprise=0.3333333333)
        assert isinstance(decision.accepted, bool)

    def test_rapid_decisions(self):
        """Should handle rapid sequence of decisions."""
        gate = DopamineWriteGate()
        for i in range(1000):
            utility = random.random()
            surprise = random.random()
            gate.evaluate(utility=utility, surprise=surprise)
        stats = gate.get_stats()
        assert stats["total"] == 1000

    def test_thread_safety(self):
        """Should be thread-safe."""
        gate = DopamineWriteGate()
        results = []

        def worker():
            for _ in range(100):
                decision = gate.evaluate(
                    utility=random.random(),
                    surprise=random.random(),
                )
                results.append(decision.accepted)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        stats = gate.get_stats()
        assert stats["total"] == 500


class TestAcceptRate:
    """Test accept rate calculation."""

    def test_accept_rate_all_accepted(self):
        """Should show 100% accept rate when all accepted."""
        gate = DopamineWriteGate()
        for _ in range(10):
            gate.evaluate(utility=0.9, surprise=0.9)
        stats = gate.get_stats()
        assert stats["accept_rate"] == 1.0

    def test_accept_rate_all_rejected(self):
        """Should show 0% accept rate when all rejected."""
        gate = DopamineWriteGate()
        for _ in range(10):
            gate.evaluate(utility=0.1, surprise=0.1)
        stats = gate.get_stats()
        assert stats["accept_rate"] == 0.0

    def test_accept_rate_mixed(self):
        """Should show correct mixed accept rate."""
        gate = DopamineWriteGate()
        for _ in range(5):
            gate.evaluate(utility=0.9, surprise=0.9)
        for _ in range(5):
            gate.evaluate(utility=0.1, surprise=0.1)
        stats = gate.get_stats()
        assert abs(stats["accept_rate"] - 0.5) < 0.01
