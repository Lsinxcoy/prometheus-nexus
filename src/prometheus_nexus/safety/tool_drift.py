"""ToolDriftDetector — Detects memory-induced tool drift.

Based on: MiMo Full Knowledge #17 (Memory-Induced Tool-Drift)

Key insight: "记忆 ≠ 中性存储 = 隐式行为指令"
Memory is not neutral storage — it implicitly directs agent behavior.
Stored knowledge can unconsciously change tool selection and behavior patterns.

Detection:
    - Track tool usage patterns over time
    - Compare current patterns against baseline
    - Detect drift when patterns shift significantly
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import time
from collections import Counter
from dataclasses import dataclass


@dataclass
class DriftAlert:
    metric: str = ""
    baseline_value: float = 0.0
    current_value: float = 0.0
    drift_magnitude: float = 0.0
    severity: str = "low"


class ToolDriftDetector:
    """Detects memory-induced tool drift.

    Based on MiMo Knowledge #17.

    Usage:
        detector = ToolDriftDetector()
        detector.record_baseline({"search": 10, "write": 5, "read": 8})
        detector.record_current({"search": 3, "write": 12, "read": 5})
        alerts = detector.detect_drift()
    """

    def __init__(self, drift_threshold: float = 0.3):
        self._threshold = drift_threshold
        self._baseline: dict[str, float] = {}
        self._current: dict[str, float] = {}
        self._history: list[dict] = []
        self._alerts: list[DriftAlert] = []

    def record_baseline(self, tool_counts: dict[str, float]):
        """Record baseline tool usage pattern."""
        total = sum(tool_counts.values())
        if total > 0:
            self._baseline = {k: v / total for k, v in tool_counts.items()}

    def record_current(self, tool_counts: dict[str, float]):
        """Record current tool usage pattern."""
        total = sum(tool_counts.values())
        if total > 0:
            self._current = {k: v / total for k, v in tool_counts.items()}

    def record_tool_use(self, tool_name: str):
        """Record a single tool usage."""
        self._current[tool_name] = self._current.get(tool_name, 0) + 1
        total = sum(self._current.values())
        if total > 0:
            self._current = {k: v / total for k, v in self._current.items()}

    def detect_drift(self) -> list[DriftAlert]:
        """Detect drift between baseline and current patterns."""
        if not self._baseline or not self._current:
            return []

        alerts = []

        all_tools = set(self._baseline.keys()) | set(self._current.keys())
        for tool in all_tools:
            baseline_val = self._baseline.get(tool, 0)
            current_val = self._current.get(tool, 0)
            drift = abs(current_val - baseline_val)

            if drift > self._threshold:
                severity = "high" if drift > 0.5 else "medium" if drift > 0.3 else "low"
                alert = DriftAlert(
                    metric=tool,
                    baseline_value=baseline_val,
                    current_value=current_val,
                    drift_magnitude=drift,
                    severity=severity,
                )
                alerts.append(alert)
                self._alerts.append(alert)

        self._history.append({
            "tools_drifted": len(alerts),
            "timestamp": time.time(),
        })

        return alerts

    def get_stats(self) -> dict:
        return {
            "baseline_tools": len(self._baseline),
            "current_tools": len(self._current),
            "total_alerts": len(self._alerts),
            "drift_threshold": self._threshold,
        }
