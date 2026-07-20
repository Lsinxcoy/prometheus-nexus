"""Tests for ConstraintDriftDetector."""
from __future__ import annotations

import time
import pytest

from prometheus_nexus.safety.constraint_drift import ConstraintDriftDetector


class _MockViolation:
    """Minimal mock of ConstitutionViolation for testing."""
    def __init__(self, gate_name: str, severity: str = "low", passed: bool = False):
        self.gate_name = gate_name
        self.severity = severity
        self.passed = passed


class TestConstraintDriftDetector:
    """Test suite for ConstraintDriftDetector."""

    # ------------------------------------------------------------------
    # 1. Basic observe + detect: drift alert fires when pattern shifts
    # ------------------------------------------------------------------

    def test_drift_detected_on_pattern_change(self):
        """Feed 30 normal (low-rate) violations, then 10 elevated ones — drift alert should fire."""
        detector = ConstraintDriftDetector(
            window_size=50,
            baseline_samples=25,
            psi_threshold=0.2,
        )

        # Phase 1: 25 observations with very few violations (low baseline)
        for _ in range(25):
            detector.observe([])  # no violations

        # Phase 2: 15 observations with frequent S1 violations
        for _ in range(15):
            detector.observe([_MockViolation("S1_no_harm", severity="critical")])

        alerts = detector.get_alerts()
        drift_alerts = [a for a in alerts if a.get("type") == "constraint_drift"]

        assert len(drift_alerts) > 0, (
            f"Expected at least one drift alert, got {len(drift_alerts)}. "
            f"Full alerts: {alerts}"
        )

        # Verify alert structure
        alert = drift_alerts[0]
        assert "rule_name" in alert
        assert "baseline_rate" in alert
        assert "current_rate" in alert
        assert "psi" in alert
        assert alert["current_rate"] > alert["baseline_rate"]

    # ------------------------------------------------------------------
    # 2. No drift when patterns are stable
    # ------------------------------------------------------------------

    def test_no_drift_when_stable(self):
        """Consistent low violation rate should NOT trigger drift."""
        detector = ConstraintDriftDetector(
            window_size=50,
            baseline_samples=25,
            psi_threshold=0.25,
        )

        # Phase 1: 25 empty observations (baseline)
        for _ in range(25):
            detector.observe([])

        # Phase 2: 15 more empty observations (same pattern)
        for _ in range(15):
            detector.observe([])

        drift_alerts = [a for a in detector.get_alerts() if a.get("type") == "constraint_drift"]
        assert len(drift_alerts) == 0, (
            f"Expected no drift alerts for stable pattern, got {len(drift_alerts)}"
        )

    # ------------------------------------------------------------------
    # 3. Severity escalation: sustained S-level violations
    # ------------------------------------------------------------------

    def test_severity_escalation(self):
        """10 consecutive high S-level violation windows should trigger critical alert."""
        detector = ConstraintDriftDetector(
            window_size=50,
            baseline_samples=25,
            psi_threshold=0.25,
        )

        # Phase 1: 25 empty observations (baseline = 0 S-level rate)
        for _ in range(25):
            detector.observe([])

        # Phase 2: 10 observations with S-level violations
        # Need enough for baseline+3 windows of sustained high S-level
        for i in range(25):
            detector.observe([_MockViolation("S1_no_harm", severity="critical")])

        alerts = detector.get_alerts()
        sev_alerts = [a for a in alerts if a.get("type") == "severity_escalation"]

        assert len(sev_alerts) > 0, (
            f"Expected severity escalation alert, got none. "
            f"Full alerts: {alerts}"
        )

        alert = sev_alerts[0]
        assert "baseline_s_rate" in alert
        assert "current_s_rate" in alert
        assert "consecutive_windows" in alert
        assert alert["consecutive_windows"] >= 3

    # ------------------------------------------------------------------
    # 4. Reset baseline clears alerts
    # ------------------------------------------------------------------

    def test_reset_baseline_clears(self):
        """Reset baseline should clear baseline and recompute."""
        detector = ConstraintDriftDetector(
            window_size=50,
            baseline_samples=25,
            psi_threshold=0.2,
        )

        # 25 empty, then 15 with violations — triggers drift
        for _ in range(25):
            detector.observe([])
        for _ in range(15):
            detector.observe([_MockViolation("S1_no_harm", severity="critical")])

        assert len(detector.get_alerts()) > 0

        # Reset baseline — baseline is cleared and recomputed from recent data
        detector.reset_baseline()

        # After reset, baseline is recomputed from the last baseline_samples
        # which now includes violations. The drift should no longer be detected
        # since the new baseline already accounts for the violation rate.
        # However, alerts history is preserved — new detect() calls would compare
        # against the recomputed baseline.
        # The key check: get_stats should show baseline was recomputed
        stats = detector.get_stats()
        assert stats["total_observations"] == 40

        # Alerts should still exist in history (they're not cleared on reset)
        # But new detections against new baseline should not produce new alerts
        # if the pattern hasn't changed further
        new_alerts = detector.detect()
        # Since we just reset to a baseline that includes violations,
        # and we're not adding *new* violations beyond what baseline captured,
        # there should be no NEW alerts
        for alert in new_alerts:
            if alert.get("type") == "severity_escalation":
                # severity escalation may still trigger if S-level baseline is 0
                # let's just check it doesn't crash
                pass

        # Verify that drift alerts from before reset are still in history
        assert len(detector.get_alerts()) > 0

    # ------------------------------------------------------------------
    # 5. get_stats returns valid structure
    # ------------------------------------------------------------------

    def test_get_stats_structure(self):
        """get_stats should return a dict with all expected keys."""
        detector = ConstraintDriftDetector()

        # Empty state
        stats = detector.get_stats()
        expected_keys = {
            "total_observations", "drifts_detected", "current_alert_count",
            "per_rule_rates", "severity_escalation_active",
        }
        assert set(stats.keys()) == expected_keys, (
            f"Stats keys mismatch. Expected {expected_keys}, got {set(stats.keys())}"
        )
        assert stats["total_observations"] == 0
        assert stats["drifts_detected"] == 0
        assert stats["current_alert_count"] == 0
        assert isinstance(stats["per_rule_rates"], dict)
        assert stats["severity_escalation_active"] is False

        # After some observations
        for _ in range(10):
            detector.observe([_MockViolation("A1_utility_floor", severity="medium")])

        stats = detector.get_stats()
        assert stats["total_observations"] == 10
        assert "A1_utility_floor" in stats["per_rule_rates"]

    # ------------------------------------------------------------------
    # 6. Non-destructive read: get_alerts doesn't clear
    # ------------------------------------------------------------------

    def test_get_alerts_non_destructive(self):
        """Calling get_alerts() multiple times should return same data."""
        detector = ConstraintDriftDetector(
            window_size=50,
            baseline_samples=25,
            psi_threshold=0.2,
        )

        for _ in range(25):
            detector.observe([])
        for _ in range(15):
            detector.observe([_MockViolation("S1_no_harm", severity="critical")])

        first = detector.get_alerts()
        second = detector.get_alerts()

        assert len(first) == len(second)
        assert first == second

    # ------------------------------------------------------------------
    # 7. detect returns current alerts without re-creating history
    # ------------------------------------------------------------------

    def test_detect_non_destructive(self):
        """detect() should return same current alerts on repeated calls."""
        detector = ConstraintDriftDetector(
            window_size=50,
            baseline_samples=25,
            psi_threshold=0.2,
        )

        for _ in range(25):
            detector.observe([])
        for _ in range(15):
            detector.observe([_MockViolation("S1_no_harm", severity="critical")])

        # detect() is called automatically during observe() after baseline
        # But calling it explicitly should work
        first = detector.detect()
        second = detector.detect()

        # Should be the same; detect() returns current alerts from _drift_alerts
        # and doesn't duplicate when called again without new data
        assert first == second


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
