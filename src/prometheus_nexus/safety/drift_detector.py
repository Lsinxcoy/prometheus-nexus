"""DriftDetector — Concept drift detection with PSI and KL divergence."""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import math
from collections import Counter


class DriftDetector:
    def __init__(self, window: int = 50, psi_threshold: float = 0.2):
        self._window = window
        self._psi_threshold = psi_threshold
        self._semantic: list[float] = []
        self._behavioral: list[float] = []
        self._reference_dist: Counter = Counter()
        self._current_dist: Counter = Counter()
        self._drift_events: list[dict] = []

    def observe_semantic(self, value: float):
        self._semantic.append(value)
        if len(self._semantic) > self._window * 2:
            self._semantic = self._semantic[-self._window:]

    def observe_behavioral(self, value: float):
        self._behavioral.append(value)
        if len(self._behavioral) > self._window * 2:
            self._behavioral = self._behavioral[-self._window:]

    def detect(self) -> list[dict]:
        alerts = []
        if len(self._semantic) >= self._window:
            psi = self._compute_psi(self._semantic)
            if psi > self._psi_threshold:
                alerts.append({"type": "concept_drift", "psi": psi})
                self._drift_events.append({"type": "concept_drift", "psi": psi})
        if len(self._behavioral) >= 10:
            mean = sum(self._behavioral) / len(self._behavioral)
            variance = sum((x - mean) ** 2 for x in self._behavioral) / len(self._behavioral)
            if variance > 0.3:
                alerts.append({"type": "behavioral_drift", "variance": variance})
        return alerts

    def _compute_psi(self, values: list[float]) -> float:
        n = len(values)
        half = n // 2
        reference, current = values[:half], values[half:]
        n_bins = 5
        all_vals = reference + current
        min_v, max_v = min(all_vals), max(all_vals)
        if max_v == min_v:
            return 0.0
        bin_width = (max_v - min_v) / n_bins
        def histogram(vals):
            counts = [0] * n_bins
            for v in vals:
                idx = min(int((v - min_v) / bin_width), n_bins - 1)
                counts[idx] += 1
            total = max(len(vals), 1)
            return [c / total + 1e-6 for c in counts]
        ref_hist, cur_hist = histogram(reference), histogram(current)
        return sum((c - r) * math.log(c / r) for c, r in zip(cur_hist, ref_hist))

    def get_stats(self) -> dict:
        return {"semantic_samples": len(self._semantic), "behavioral_samples": len(self._behavioral),
                "drift_events": len(self._drift_events)}
