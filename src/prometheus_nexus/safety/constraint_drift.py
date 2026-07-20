"""ConstraintDriftDetector — Detects when constitution constraint violations shift pattern over time.

This module monitors ConstitutionViolation events from the 22-principle constitution
and detects drift in per-rule violation rates using PSI (Population Stability Index).
It also tracks severity escalation (e.g. sustained S-level violations) as a precursor
to system degradation.
"""
from __future__ import annotations

import logging
import math
import time
from collections import defaultdict

logger = logging.getLogger(__name__)


class ConstraintDriftDetector:
    """Detects drift in constitution constraint violation patterns over time.

    For each rule in the constitution, maintains a sliding window of violation
    rates, computes a baseline from the first N samples, and periodically checks
    whether the current window has drifted from baseline using PSI.

    Attributes:
        _violation_history: Timestamped violation records.
        _rule_rates: Per-rule sliding window of violation rates (0.0-1.0).
        _baseline: Expected violation rate per rule (from first N samples).
        _drift_alerts: Alerts generated when drift is detected.
        _window_size: Sliding window size for rate computation.
        _baseline_samples: Number of samples to establish baseline.
        _psi_threshold: PSI threshold for declaring drift.
        _severity_escalation_counter: Consecutive windows with elevated S-level violations.
    """

    def __init__(
        self,
        window_size: int = 50,
        baseline_samples: int = 30,
        psi_threshold: float = 0.25,
    ) -> None:
        self._violation_history: list[dict] = []
        self._rule_rates: dict[str, list[float]] = defaultdict(list)
        self._baseline: dict[str, float] = {}
        self._drift_alerts: list[dict] = []
        self._window_size: int = window_size
        self._baseline_samples: int = baseline_samples
        self._psi_threshold: float = psi_threshold
        self._severity_escalation_counter: int = 0
        self._total_observations: int = 0
        self._severity_escalation_active: bool = False
        self._s_level_baseline: float = 0.0
        self._s_level_rates: list[float] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def observe(self, violations: list) -> None:
        """Record a batch of constitution violations from a single evaluation.

        Args:
            violations: List of ConstitutionViolation objects (those that failed).
                        Each object has at least .gate_name and .severity attributes.
        """
        self._total_observations += 1
        timestamp = time.time()

        # Record history
        record: dict = {
            "timestamp": timestamp,
            "violation_count": len(violations),
            "rule_names": [v.gate_name for v in violations],
            "severities": [v.severity for v in violations],
        }
        self._violation_history.append(record)

        # Update per-rule violation rates (sliding window)
        for v in violations:
            self._rule_rates[v.gate_name].append(1.0)
        # Also record a 0.0 for every observed window for rules that were NOT violated
        # — we need the full window of 0s and 1s per rule
        # Mark non-violated rules by noting all known rule names
        violated_names = {v.gate_name for v in violations}
        for rule_name in list(self._rule_rates.keys()):
            if rule_name not in violated_names:
                self._rule_rates[rule_name].append(0.0)

        # Track S-level violations for severity escalation
        s_count = sum(1 for v in violations if getattr(v, "severity", "") == "critical" or "S" in (v.gate_name or ""))
        self._s_level_rates.append(1.0 if s_count > 0 else 0.0)

        # Trim windows
        for rule_name in list(self._rule_rates.keys()):
            if len(self._rule_rates[rule_name]) > self._window_size:
                self._rule_rates[rule_name] = self._rule_rates[rule_name][-self._window_size:]

        if len(self._s_level_rates) > self._window_size:
            self._s_level_rates = self._s_level_rates[-self._window_size:]

        # Check baseline computation
        if self._total_observations == self._baseline_samples:
            self._compute_baseline()
        elif not self._baseline and len(self._rule_rates) > 0:
            # Also compute baseline if it hasn't been done yet (e.g. all-empty phase 1)
            adjusted = self._total_observations
            self._total_observations = self._baseline_samples
            self._compute_baseline()
            self._total_observations = adjusted

        # If baseline is established, check drift
        if self._baseline:
            self.detect()

    def detect(self) -> list[dict]:
        """Check for drift across all rules and severity escalation.

        Returns:
            Current list of drift alerts (non-destructive read).
        """
        current_alerts: list[dict] = []

        for rule_name in list(self._rule_rates.keys()):
            rates = self._rule_rates.get(rule_name, [])
            # Need at least 5 data points for a meaningful PSI
            if len(rates) < 5:
                continue

            # Get baseline rate (default 0.0 for rules not seen during baseline)
            baseline_rate = self._baseline.get(rule_name, 0.0)

            # Compute current rate from the most recent baseline_samples worth of data
            current_window = rates[-self._baseline_samples:]
            current_rate = sum(current_window) / max(len(current_window), 1)

            # Only check drift if we have enough data for PSI computation
            if len(current_window) < 5:
                continue

            # Compute PSI between baseline distribution and current window
            psi = self._compute_psi_for_rule(baseline_rate, current_window)

            # Drift threshold: PSI > threshold AND worsening (current > baseline * 1.5)
            if psi > self._psi_threshold and current_rate > baseline_rate * 1.5:
                # Check severity shift
                baseline_severity = self._baseline.get(f"{rule_name}_severity", "low")
                current_severity = self._get_current_severity(rule_name)

                # Only add alert if not already active for this rule
                already_active = any(
                    a.get("type") == "constraint_drift" and a.get("rule_name") == rule_name
                    for a in self._drift_alerts[-5:]  # check last 5
                )
                if not already_active:
                    alert: dict = {
                        "rule_name": rule_name,
                        "baseline_rate": round(baseline_rate, 4),
                        "current_rate": round(current_rate, 4),
                        "psi": round(psi, 4),
                        "severity_shift": current_severity if current_severity != baseline_severity else "none",
                    }
                    current_alerts.append(alert)
                    self._drift_alerts.append({
                        **alert,
                        "timestamp": time.time(),
                        "type": "constraint_drift",
                    })

        # Severity escalation check: S-level violations rate > 2x S-level baseline
        # for 3+ consecutive windows
        if len(self._s_level_rates) >= self._baseline_samples:
            recent_s = self._s_level_rates[-self._baseline_samples:]
            current_s_rate = sum(recent_s) / max(len(recent_s), 1)
            # If baseline is 0, any positive rate means infinite relative increase
            threshold = 0.0 if self._s_level_baseline == 0 else self._s_level_baseline * 2.0
            if current_s_rate > threshold and current_s_rate > 0.0:
                self._severity_escalation_counter += 1
            else:
                self._severity_escalation_counter = 0

            if self._severity_escalation_counter >= 3:
                if not self._severity_escalation_active:
                    self._severity_escalation_active = True
                    critical_alert: dict = {
                        "type": "severity_escalation",
                        "baseline_s_rate": round(self._s_level_baseline, 4),
                        "current_s_rate": round(current_s_rate, 4),
                        "consecutive_windows": self._severity_escalation_counter,
                        "timestamp": time.time(),
                    }
                    current_alerts.append(critical_alert)
                    self._drift_alerts.append(critical_alert)
            else:
                self._severity_escalation_active = False

        return current_alerts

    def get_stats(self) -> dict:
        """Return summary statistics about the detector state.

        Returns:
            Dict with total_observations, drifts_detected, current_alert_count,
            per_rule_rates, severity_escalation_active.
        """
        per_rule = {}
        for rule_name, rates in self._rule_rates.items():
            if rates:
                per_rule[rule_name] = round(sum(rates) / len(rates), 4)
            else:
                per_rule[rule_name] = 0.0

        return {
            "total_observations": self._total_observations,
            "drifts_detected": len([a for a in self._drift_alerts if a.get("type") == "constraint_drift"]),
            "current_alert_count": len(self._drift_alerts),
            "per_rule_rates": per_rule,
            "severity_escalation_active": self._severity_escalation_active,
        }

    def get_alerts(self) -> list[dict]:
        """Return the full drift alert history (non-destructive)."""
        return list(self._drift_alerts)

    def reset_baseline(self) -> None:
        """Clear baseline and recompute from recent observations."""
        self._baseline.clear()
        self._s_level_baseline = 0.0
        self._severity_escalation_counter = 0
        self._severity_escalation_active = False
        # Recompute from most recent baseline_samples worth of data
        if self._total_observations >= self._baseline_samples:
            self._compute_baseline()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_baseline(self) -> None:
        """Compute baseline violation rates from the first baseline_samples observations."""
        # Track when each rule first appeared to determine baseline coverage
        rule_first_obs: dict[str, int] = {}
        for idx, record in enumerate(self._violation_history):
            for name, sev in zip(record["rule_names"], record["severities"]):
                if name not in rule_first_obs:
                    rule_first_obs[name] = idx

        for rule_name, rates in self._rule_rates.items():
            first_obs = rule_first_obs.get(rule_name, 0)
            if first_obs >= self._baseline_samples:
                # Rule first appeared AFTER baseline period — its baseline rate is 0.0
                self._baseline[rule_name] = 0.0
            else:
                baseline_window = rates[:self._baseline_samples]
                if baseline_window:
                    self._baseline[rule_name] = sum(baseline_window) / len(baseline_window)

        # Compute S-level baseline
        if self._s_level_rates:
            s_baseline = self._s_level_rates[:self._baseline_samples]
            if s_baseline:
                self._s_level_baseline = sum(s_baseline) / len(s_baseline)

        logger.info(
            "ConstraintDriftDetector baseline computed from %d samples: %d rules, S-level baseline=%.4f",
            self._baseline_samples,
            len(self._baseline),
            self._s_level_baseline,
        )

    def _compute_psi_for_rule(self, baseline_rate: float, current_window: list[float]) -> float:
        """Compute PSI between a baseline rate and a current window of 0/1 values.

        Uses a two-bin discretization (violated / not violated) with Laplace smoothing.

        Args:
            baseline_rate: The expected violation rate (from baseline).
            current_window: List of 0.0 and 1.0 values from the current sliding window.

        Returns:
            PSI value (>= 0). Higher values indicate more drift.
        """
        n = len(current_window)
        if n == 0:
            return 0.0

        current_rate = sum(current_window) / n

        # Two bins: violated (1) and not violated (0)
        # Apply Laplace smoothing (add 1 to each bin) to avoid division by zero
        ref_violated = baseline_rate
        ref_not_violated = 1.0 - baseline_rate

        cur_violated = current_rate
        cur_not_violated = 1.0 - current_rate

        # PSI = sum( (cur - ref) * ln(cur / ref) ) for each bin
        # Add small epsilon to avoid log(0)
        eps = 1e-10

        psi = 0.0
        for ref_p, cur_p in [(ref_violated, cur_violated), (ref_not_violated, cur_not_violated)]:
            ref_p = max(ref_p, eps)
            cur_p = max(cur_p, eps)
            psi += (cur_p - ref_p) * math.log(cur_p / ref_p)

        return psi

    def _get_current_severity(self, rule_name: str) -> str:
        """Get the most recent severity level for a given rule."""
        # Walk violation history in reverse
        for record in reversed(self._violation_history):
            for name, sev in zip(record["rule_names"], record["severities"]):
                if name == rule_name:
                    return sev
        return "low"
