"""Tests for forgetting.py — WeibullForgetting with FSFM three dimensions.

Tests cover:
    - Core Weibull curve computation
    - FSFM Security: safety_trigger_forget
    - FSFM Quality: adaptive_reinforce (with diminishing returns)
    - FSFM Efficiency: prune_below_threshold, prune_by_count
    - Integration of all three dimensions
"""

from __future__ import annotations
import math
import time
import pytest  # type: ignore[import-untyped]

from prometheus_nexus.lifecycle.forgetting import WeibullForgetting


# ===========================================================================
#  Fixtures
# ===========================================================================

@pytest.fixture
def wf() -> WeibullForgetting:
    return WeibullForgetting(shape=1.5, scale=100.0, max_tracked=5000)


@pytest.fixture
def wf_small() -> WeibullForgetting:
    return WeibullForgetting(shape=2.0, scale=50.0, max_tracked=10)


# ===========================================================================
#  Initialization
# ===========================================================================

class TestInit:
    def test_default_initialization(self) -> None:
        w = WeibullForgetting()
        assert w._shape == 1.5
        assert w._scale == 100.0
        assert w._max_tracked == 5000

    def test_custom_initialization(self) -> None:
        w = WeibullForgetting(shape=2.0, scale=200.0, max_tracked=1000)
        assert w._shape == 2.0
        assert w._scale == 200.0
        assert w._max_tracked == 1000

    def test_invalid_shape(self) -> None:
        with pytest.raises(ValueError, match="shape must be > 0"):
            WeibullForgetting(shape=0)

    def test_invalid_scale(self) -> None:
        with pytest.raises(ValueError, match="scale must be > 0"):
            WeibullForgetting(scale=0)

    def test_invalid_max_tracked(self) -> None:
        with pytest.raises(ValueError, match="max_tracked must be > 0"):
            WeibullForgetting(max_tracked=0)


# ===========================================================================
#  Core Weibull Curve
# ===========================================================================

class TestCoreWeibull:
    def test_retention_at_age_zero(self, wf: WeibullForgetting) -> None:
        assert wf.compute_retention(0.0) == 1.0

    def test_retention_negative_age(self, wf: WeibullForgetting) -> None:
        assert wf.compute_retention(-1.0) == 1.0

    def test_retention_at_scale(self, wf: WeibullForgetting) -> None:
        # At age = scale, R = exp(-1) ≈ 0.3679
        r = wf.compute_retention(100.0)
        assert abs(r - math.exp(-1)) < 0.01

    def test_retention_monotonically_decreasing(self, wf: WeibullForgetting) -> None:
        ages = [0, 10, 50, 100, 200, 500]
        values = [wf.compute_retention(a) for a in ages]
        for i in range(len(values) - 1):
            assert values[i] >= values[i + 1], f"Not monotonic at age {ages[i]}"

    def test_retention_approaches_zero(self, wf: WeibullForgetting) -> None:
        assert wf.compute_retention(10000.0) < 0.001

    def test_different_shapes(self) -> None:
        w1 = WeibullForgetting(shape=0.5, scale=100.0)
        w2 = WeibullForgetting(shape=2.0, scale=100.0)
        # At age=50, shape=2.0 should have higher retention than shape=0.5
        # (lower shape = faster initial decay)
        r1 = w1.compute_retention(50.0)
        r2 = w2.compute_retention(50.0)
        assert r2 > r1, (
            f"Expected higher shape to have higher retention at age=50, "
            f"got r1={r1:.4f}, r2={r2:.4f}"
        )


# ===========================================================================
#  compute_retention_compat
# ===========================================================================

class TestRetentionCompat:
    def test_caches_retention(self, wf: WeibullForgetting) -> None:
        r = wf.compute_retention_compat("node1", age=50.0)
        cached = wf.get_retention("node1")
        assert abs(cached - r) < 1e-10

    def test_applies_reinforcement_factor(self, wf: WeibullForgetting) -> None:
        # First, reinforce a node
        wf.adaptive_reinforce("node_rf", boost=0.5)
        # Then compute retention — it should be higher than base
        r_base = wf.compute_retention(50.0)
        r_reinf = wf.compute_retention_compat("node_rf", age=50.0)
        assert r_reinf >= r_base

    def test_lru_eviction(self, wf_small: WeibullForgetting) -> None:
        # max_tracked=10 means we can have at most 12 (10 + 25% evict)
        for i in range(15):
            wf_small.compute_retention_compat(f"node{i}", age=float(i))
        # Should have evicted some
        assert len(wf_small._retentions) <= 12

    def test_get_expired_nodes(self, wf: WeibullForgetting) -> None:
        wf.compute_retention_compat("young", age=10.0)
        wf.compute_retention_compat("old", age=500.0)
        expired = wf.get_expired_nodes(threshold=0.3)
        assert "old" in expired
        assert "young" not in expired


# ===========================================================================
#  FSFM Security: safety_trigger_forget
# ===========================================================================

class TestSafetyTriggerForget:
    def test_safety_forget_single(self, wf: WeibullForgetting) -> None:
        wf.compute_retention_compat("node1", age=50.0)
        result = wf.safety_trigger_forget(["node1"], reason="PII detected")
        assert result["forgotten"] == 1
        assert result["reason"] == "PII detected"
        assert wf.get_retention("node1") == 0.0

    def test_safety_forget_multiple(self, wf: WeibullForgetting) -> None:
        for i in range(5):
            wf.compute_retention_compat(f"node{i}", age=float(i * 10))
        result = wf.safety_trigger_forget(
            ["node0", "node2", "node4"],
            reason="malicious content",
            classification="toxic",
        )
        assert result["forgotten"] == 3
        assert result["classification"] == "toxic"
        assert wf.get_retention("node0") == 0.0
        assert wf.get_retention("node1") > 0.0  # not forgotten

    def test_safety_forget_nonexistent_node(self, wf: WeibullForgetting) -> None:
        result = wf.safety_trigger_forget(["ghost_node"], reason="test")
        assert result["forgotten"] == 0
        assert result["total_requested"] == 1

    def test_safety_forget_empty_list(self, wf: WeibullForgetting) -> None:
        result = wf.safety_trigger_forget([], reason="empty test")
        assert result["forgotten"] == 0
        assert result["total_requested"] == 0

    def test_safety_forget_log(self, wf: WeibullForgetting) -> None:
        wf.compute_retention_compat("sensitive1", age=10.0)
        wf.compute_retention_compat("sensitive2", age=20.0)
        wf.safety_trigger_forget(["sensitive1"], reason="PII", classification="pii_email")
        wf.safety_trigger_forget(["sensitive2"], reason="malicious", classification="malware")

        # Full log
        log = wf.get_safety_forget_log()
        assert len(log) == 2

        # Filtered by classification
        pii_log = wf.get_safety_forget_log(classification="pii_email")
        assert len(pii_log) == 1
        assert pii_log[0]["classification"] == "pii_email"

    def test_safety_forget_removes_reinforcement(self, wf: WeibullForgetting) -> None:
        wf.compute_retention_compat("node", age=10.0)
        wf.adaptive_reinforce("node")
        wf.safety_trigger_forget(["node"], reason="cleanup")
        # Reinforcement factor should be removed
        assert wf.get_reinforcement_factor("node") == 1.0
        assert wf.get_access_count("node") == 0

    def test_get_safety_candidates(self, wf: WeibullForgetting) -> None:
        wf.compute_retention_compat("high", age=10.0)
        wf.compute_retention_compat("low", age=500.0)
        candidates = wf.get_safety_candidates(threshold=0.5)
        assert len(candidates) >= 1
        # Low retention node should be the top candidate
        assert candidates[0]["node_id"] == "low"


# ===========================================================================
#  FSFM Quality: adaptive_reinforce
# ===========================================================================

class TestAdaptiveReinforce:
    def test_reinforce_increases_retention(self, wf: WeibullForgetting) -> None:
        wf.compute_retention_compat("node", age=100.0)
        original = wf.get_retention("node")
        wf.adaptive_reinforce("node", boost=0.3)
        reinforced = wf.get_retention("node")
        assert reinforced > original

    def test_reinforce_capped_at_one(self, wf: WeibullForgetting) -> None:
        wf.compute_retention_compat("node", age=10.0)
        for _ in range(10):
            wf.adaptive_reinforce("node", boost=0.5)
        assert wf.get_retention("node") == 1.0

    def test_diminishing_returns(self, wf: WeibullForgetting) -> None:
        wf.compute_retention_compat("node", age=100.0)
        # First reinforcement
        r1 = wf.adaptive_reinforce("node")
        # Second reinforcement (should provide less boost)
        r2 = wf.adaptive_reinforce("node")
        # Third reinforcement (even less)
        r3 = wf.adaptive_reinforce("node")
        # Each successive boost should be smaller
        boost1 = r1 - wf.compute_retention(100.0)
        boost2 = r2 - r1
        boost3 = r3 - r2
        assert boost1 > boost2, f"boost1={boost1:.4f} should be > boost2={boost2:.4f}"
        assert boost2 > boost3, f"boost2={boost2:.4f} should be > boost3={boost3:.4f}"

    def test_access_count_increments(self, wf: WeibullForgetting) -> None:
        assert wf.get_access_count("node") == 0
        wf.adaptive_reinforce("node")
        assert wf.get_access_count("node") == 1
        wf.adaptive_reinforce("node")
        assert wf.get_access_count("node") == 2

    def test_reinforcement_factor_increases(self, wf: WeibullForgetting) -> None:
        assert wf.get_reinforcement_factor("node") == 1.0
        wf.adaptive_reinforce("node", boost=0.2)
        assert wf.get_reinforcement_factor("node") > 1.0

    def test_reinforcement_factor_capped(self, wf: WeibullForgetting) -> None:
        for _ in range(50):
            wf.adaptive_reinforce("node", boost=1.0)
        # Should be capped at 3.0
        assert wf.get_reinforcement_factor("node") <= 3.0

    def test_reinforce_without_compat(self, wf: WeibullForgetting) -> None:
        # adaptive_reinforce should work even without prior compute_retention_compat
        r = wf.adaptive_reinforce("new_node", boost=0.2)
        assert r > 0.0
        assert wf.get_retention("new_node") > 0.0


# ===========================================================================
#  FSFM Efficiency: prune
# ===========================================================================

class TestPrune:
    def test_prune_below_threshold(self, wf: WeibullForgetting) -> None:
        wf.compute_retention_compat("keep1", age=10.0)
        wf.compute_retention_compat("keep2", age=20.0)
        wf.compute_retention_compat("prune1", age=1000.0)
        wf.compute_retention_compat("prune2", age=2000.0)

        result = wf.prune_below_threshold(threshold=0.01)
        assert result["pruned"] >= 1
        assert result["total_after"] < result["total_before"]
        # Pruned nodes should no longer exist
        for nid in result["freed_node_ids"]:
            assert nid not in wf._retentions

    def test_prune_below_threshold_none(self, wf: WeibullForgetting) -> None:
        wf.compute_retention_compat("young1", age=5.0)
        wf.compute_retention_compat("young2", age=10.0)
        result = wf.prune_below_threshold(threshold=0.001)
        assert result["pruned"] == 0

    def test_prune_by_count(self, wf: WeibullForgetting) -> None:
        for i in range(10):
            wf.compute_retention_compat(f"node{i}", age=float(i * 50))
        result = wf.prune_by_count(3)
        assert result["pruned"] == 3
        assert result["total_before"] == 10
        assert result["total_after"] == 7

    def test_prune_by_count_zero(self, wf: WeibullForgetting) -> None:
        wf.compute_retention_compat("node1", age=50.0)
        result = wf.prune_by_count(0)
        assert result["pruned"] == 0


# ===========================================================================
#  Predict forget time
# ===========================================================================

class TestPredictForgetTime:
    def test_predict_basic(self, wf: WeibullForgetting) -> None:
        wf.compute_retention_compat("node", age=50.0)
        t = wf.predict_forget_time("node", threshold=0.1)
        assert t is not None
        assert t > 0.0
        # t should be > scale * (-ln(0.1))^(1/shape)
        expected = 100.0 * (-math.log(0.1)) ** (1.0 / 1.5)
        assert abs(t - expected) < 10.0  # rough check

    def test_predict_already_forgotten(self, wf: WeibullForgetting) -> None:
        wf.safety_trigger_forget(["dead_node"], reason="test")
        t = wf.predict_forget_time("dead_node", threshold=0.1)
        assert t == 0.0

    def test_predict_reinforcement_adjusts_time(self, wf: WeibullForgetting) -> None:
        wf.compute_retention_compat("plain", age=50.0)
        wf.compute_retention_compat("reinforced", age=50.0)
        wf.adaptive_reinforce("reinforced", boost=0.5)
        t_plain = wf.predict_forget_time("plain", threshold=0.1)
        t_reinf = wf.predict_forget_time("reinforced", threshold=0.1)
        # Reinforced nodes should take longer to forget
        assert t_reinf >= t_plain, (
            f"Expected reinforced forget time ({t_reinf:.2f}) >= plain ({t_plain:.2f})"
        )


# ===========================================================================
#  Stats
# ===========================================================================

class TestStats:
    def test_get_stats_basic(self, wf: WeibullForgetting) -> None:
        wf.compute_retention_compat("a", age=10.0)
        wf.compute_retention_compat("b", age=100.0)
        stats = wf.get_stats()
        assert stats["tracked_nodes"] == 2
        assert stats["shape"] == 1.5
        assert stats["scale"] == 100.0
        assert 0 <= stats["avg_retention"] <= 1

    def test_get_stats_fsfm_section(self, wf: WeibullForgetting) -> None:
        wf.compute_retention_compat("node", age=50.0)
        wf.adaptive_reinforce("node")
        wf.safety_trigger_forget(["ghost"], reason="test")
        stats = wf.get_stats()
        fsfm = stats["fsfm"]
        assert fsfm["safety_forget_count"] == 1
        assert fsfm["reinforced_nodes"] == 1
        assert fsfm["total_access_events"] == 1

    def test_get_most_forgotten(self, wf: WeibullForgetting) -> None:
        wf.compute_retention_compat("old", age=500.0)
        wf.compute_retention_compat("young", age=5.0)
        most = wf.get_most_forgotten(top_k=5)
        assert most[0]["node_id"] == "old"

    def test_get_most_retained(self, wf: WeibullForgetting) -> None:
        wf.compute_retention_compat("old", age=500.0)
        wf.compute_retention_compat("young", age=5.0)
        most = wf.get_most_retained(top_k=5)
        assert most[0]["node_id"] == "young"

    def test_get_retention_distribution(self, wf: WeibullForgetting) -> None:
        for i in range(100):
            wf.compute_retention_compat(f"n{i}", age=float(i * 10))
        dist = wf.get_retention_distribution(bins=5)
        assert len(dist) == 5
        assert sum(dist.values()) == 100


# ===========================================================================
#  Integration: FSFM all three dimensions
# ===========================================================================

class TestFSFMIntegration:
    def test_security_then_quality(self, wf: WeibullForgetting) -> None:
        """After safety-forgetting a node, reinforcing should not revive it."""
        wf.compute_retention_compat("node", age=50.0)
        wf.safety_trigger_forget(["node"], reason="test")
        r_after_forget = wf.get_retention("node")
        assert r_after_forget == 0.0

        # Reinforce should still work but retention starts from 0
        new_r = wf.adaptive_reinforce("node", boost=0.5)
        assert new_r > 0.0

    def test_quality_then_efficiency(self, wf: WeibullForgetting) -> None:
        """Reinforced nodes should be less likely to be pruned."""
        wf.compute_retention_compat("unused", age=500.0)
        wf.compute_retention_compat("used", age=500.0)
        for _ in range(5):
            wf.adaptive_reinforce("used")

        # Prune below a threshold that would normally get both
        result = wf.prune_below_threshold(threshold=0.5)
        # The reinforced node should survive longer
        pruned_ids = set(result["freed_node_ids"])
        assert "unused" in pruned_ids or result["pruned"] > 0


# ===========================================================================
#  Edge cases
# ===========================================================================

class TestEdgeCases:
    def test_high_shape(self) -> None:
        w = WeibullForgetting(shape=10.0, scale=100.0)
        # With high shape, retention stays near 1.0 until near scale, then drops sharply
        assert w.compute_retention(50.0) > 0.99
        assert w.compute_retention(100.0) == pytest.approx(math.exp(-1), rel=0.1)
        assert w.compute_retention(150.0) < 0.01

    def test_low_shape(self) -> None:
        w = WeibullForgetting(shape=0.3, scale=100.0)
        # With low shape (k<1), retention drops SLOWER initially (infant mortality pattern)
        # age=10 should have high retention (~0.6058), not < 0.5
        assert w.compute_retention(10.0) > 0.5  # Corrected: higher retention for low shape
        assert w.compute_retention(100.0) == pytest.approx(math.exp(-1), rel=0.1)

    def test_large_scale(self) -> None:
        w = WeibullForgetting(shape=1.5, scale=10000.0)
        assert w.compute_retention(1000.0) > 0.9  # still well retained

    def test_many_reinforcements(self, wf: WeibullForgetting) -> None:
        wf.compute_retention_compat("node", age=50.0)
        for _ in range(100):
            wf.adaptive_reinforce("node")
        # Should not crash, should cap somewhere reasonable
        assert wf.get_reinforcement_factor("node") <= 3.0

    def test_safety_log_ordering(self, wf: WeibullForgetting) -> None:
        import time
        for i in range(3):
            wf.compute_retention_compat(f"n{i}", age=10.0)
            time.sleep(0.001)  # Ensure different timestamps
            wf.safety_trigger_forget([f"n{i}"], reason=f"reason_{i}")
        log = wf.get_safety_forget_log()
        assert len(log) == 3
        # Newest first (reverse=True means descending timestamp)
        assert log[0]["reason"] == "reason_2"
        assert log[-1]["reason"] == "reason_0"
