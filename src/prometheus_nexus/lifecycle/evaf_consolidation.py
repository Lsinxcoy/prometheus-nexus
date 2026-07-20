"""EVAF — Surprise-valence gated parametric consolidation.

Based on: "Memory Depth, Not Memory Access" (arXiv:2606.26806, Han 2026)

Key insight: memory depth (durable tendencies) vs memory access (retrieval).
EVAF selects which memories to consolidate based on surprise and valence.
Only 2-3 parametric writes per 200 events needed.

Wired to match memory_depth.py's EVAFMemoryDepthTracker parameters for
consistent consolidation behavior across the system.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import math
import time
from dataclasses import dataclass
from typing import Any


# Default parameters matching memory_depth.py's EVAFMemoryDepthTracker
_DEFAULT_SURPRISE_THRESHOLD: float = 0.15
_DEFAULT_VALENCE_MIN: float = 0.3
_DEFAULT_DEPTH_DELTA: float = 0.12
_DEFAULT_DEPTH_DECAY: float = 0.98
_DEFAULT_DRIFT_WINDOW: int = 10


@dataclass
class ConsolidationCandidate:
    memory_id: str = ""
    surprise: float = 0.0
    valence: float = 0.0
    score: float = 0.0
    should_consolidate: bool = False
    depth_after: float = 0.0


@dataclass
class EVAFParametricRecord:
    """Internal parametric record for EVAF consolidation tracking.

    Mirrors memory_depth.py's EVAFRecord fields.
    """
    memory_id: str = ""
    depth: float = 0.0
    surprise: float = 0.0
    valence: float = 0.0
    consolidated: int = 0
    access_count: int = 0
    last_access: float = 0.0
    surprise_history: list[float] | None = None

    def __post_init__(self) -> None:
        if self.surprise_history is None:
            self.surprise_history = []


class EVAFConsolidation:
    """Surprise-valence gated consolidation with full EVAF parametric update.

    Based on Memory Depth paper (arXiv:2606.26806).

    Three core extensions beyond the basic gate:
      1. loop_drift_test() — controlled stress test detecting goal
         persistence degradation under long-loop interference.
      2. depth_decay() — time-based depth decay matching
         memory_depth.py's apply_decay().
      3. _apply_consolidation() — full EVAF parametric depth update
         with surprise+valence gating, delta increment, and decay.

    Wired to match memory_depth.py's EVAFMemoryDepthTracker parameters:
        surprise_threshold=0.15
        valence_min=0.3
        depth_delta=0.12
        depth_decay=0.98

    Usage:
        evaf = EVAFConsolidation()
        # Basic gate
        candidate = evaf.evaluate(memory_id="m1", surprise=0.8, valence=0.5)
        if candidate.should_consolidate:
            evaf._apply_consolidation(candidate)

        # Loop-drift test
        drift = evaf.loop_drift_test("m1")

        # Depth decay
        evaf.depth_decay()
    """

    def __init__(self, surprise_threshold: float = _DEFAULT_SURPRISE_THRESHOLD,
                 valence_threshold: float = _DEFAULT_VALENCE_MIN,
                 max_consolidations_per_window: int = 3,
                 window_size: int = 200,
                 depth_delta: float = _DEFAULT_DEPTH_DELTA,
                 depth_decay: float = _DEFAULT_DEPTH_DECAY,
                 drift_window: int = _DEFAULT_DRIFT_WINDOW):
        self._surprise_threshold = surprise_threshold
        self._valence_threshold = valence_threshold
        self._max_per_window = max_consolidations_per_window
        self._window_size = window_size
        self._depth_delta = depth_delta
        self._depth_decay = depth_decay
        self._drift_window = drift_window

        self._window_count = 0
        self._consolidation_count = 0

        # Parametric records (mirrors memory_depth.py's _records)
        self._records: dict[str, EVAFParametricRecord] = {}

        self._stats: dict[str, int | float] = {
            "evaluated": 0,
            "consolidated": 0,
            "gates_closed": 0,
            "drifts_detected": 0,
            "loop_drift_tests": 0,
            "depth_decay_applied": 0,
        }

    # ------------------------------------------------------------------
    # Basic EVAF gate (original)
    # ------------------------------------------------------------------

    def evaluate(self, memory_id: str, surprise: float,
                 valence: float) -> ConsolidationCandidate:
        """Evaluate whether a memory should be consolidated.

        EVAF gate opens when:
            surprise >= threshold
            AND abs(valence) >= valence_threshold
            AND consolidation budget not exceeded for this window

        Returns a ConsolidationCandidate with should_consolidate flag.
        """
        self._stats["evaluated"] += 1
        self._window_count += 1

        if self._window_count >= self._window_size:
            self._window_count = 0
            self._consolidation_count = 0

        score = surprise * 0.6 + abs(valence) * 0.4
        should_consolidate = (
            surprise >= self._surprise_threshold
            and abs(valence) >= self._valence_threshold
            and self._consolidation_count < self._max_per_window
        )

        depth_after = 0.0
        if should_consolidate:
            # Track in parametric records
            self._ensure_record(memory_id)
            record = self._records[memory_id]
            record.surprise = surprise
            record.valence = valence
            record.access_count += 1
            record.last_access = time.time()
            record.surprise_history.append(surprise)

            depth_after = self._parametric_update(record, surprise, valence)

            self._consolidation_count += 1
            # NOTE: consolidated counter is incremented in _apply_consolidation
            # to avoid double-counting when both evaluate() and
            # _apply_consolidation() are called.
        else:
            self._stats["gates_closed"] += 1

        return ConsolidationCandidate(
            memory_id=memory_id,
            surprise=surprise,
            valence=valence,
            score=score,
            should_consolidate=should_consolidate,
            depth_after=depth_after,
        )

    # ------------------------------------------------------------------
    # Full EVAF parametric consolidation (arXiv 2606.26806 §3.2)
    # ------------------------------------------------------------------

    def _apply_consolidation(self, candidate: ConsolidationCandidate) -> dict[str, Any]:
        """Apply full EVAF parametric consolidation to a candidate.

        Implements the paper's core parametric update:

            1. Ensure parametric record exists for the memory.
            2. If candidate passes EVAF gate (surprise + valence thresholds):
               - depth = min(1.0, depth + delta)   [consolidation]
               - Track surprise in history.
            3. If gate is closed:
               - depth *= decay  [parametric forgetting]
            4. Update last_access and access_count.

        Args:
            candidate: A ConsolidationCandidate from evaluate().

        Returns:
            Dict with:
              - memory_id: The consolidated memory.
              - depth_before: Depth before consolidation.
              - depth_after: Depth after consolidation.
              - consolidated: Whether consolidation occurred.
              - delta: Change in depth.
              - surprise: Candidate surprise.
              - valence: Candidate valence.
        """
        mid = candidate.memory_id
        self._ensure_record(mid)
        record = self._records[mid]

        depth_before = record.depth

        if candidate.should_consolidate:
            # EVAF gate open — consolidate
            record.depth = min(1.0, record.depth + self._depth_delta)
            record.surprise = candidate.surprise
            record.valence = candidate.valence
            record.consolidated += 1

            if candidate.surprise > 0:
                record.surprise_history.append(candidate.surprise)

            logger.debug(
                "EVAF consolidate: %s depth=%.3f->%.3f surprise=%.3f valence=%.3f",
                mid, depth_before, record.depth, candidate.surprise, candidate.valence,
            )
            self._stats["consolidated"] += 1
        else:
            # Gate closed — no consolidation, but track stats
            logger.debug(
                "EVAF skip consolidate: %s (surprise=%.3f<thresh=%.2f "
                "or valence=%.3f<thresh=%.2f)",
                mid, candidate.surprise, self._surprise_threshold,
                abs(candidate.valence), self._valence_threshold,
            )

        record.last_access = time.time()
        record.access_count += 1

        return {
            "memory_id": mid,
            "depth_before": round(depth_before, 4),
            "depth_after": round(record.depth, 4),
            "consolidated": candidate.should_consolidate,
            "delta": round(record.depth - depth_before, 4),
            "surprise": round(candidate.surprise, 4),
            "valence": round(candidate.valence, 4),
        }

    def _parametric_update(self, record: EVAFParametricRecord,
                           surprise: float, valence: float) -> float:
        """Core EVAF parametric depth update.

        Args:
            record: Parametric record to update.
            surprise: Current prediction error.
            valence: Current outcome valence.

        Returns:
            Depth after update.
        """
        if surprise > self._surprise_threshold and abs(valence) > self._valence_threshold:
            record.depth = min(1.0, record.depth + self._depth_delta)
        else:
            # Gate closed — decay
            record.depth *= self._depth_decay

        return record.depth

    # ------------------------------------------------------------------
    # Loop-drift protocol (arXiv 2606.26806 §4.2)
    # ------------------------------------------------------------------

    def loop_drift_test(self, memory_id: str,
                        working_context_unloaded: bool = True,
                        loop_iterations: int = 100,
                        recurrence: float = 0.0) -> dict[str, Any]:
        """Run the loop-drift protocol on a memory.

        The loop-drift protocol is a controlled stress test from the
        Memory Depth paper (§4.2). It detects whether goal-conditioned
        tendencies persist when working context is unloaded under
        long-loop interference.

        Algorithm:
          1. Record a goal-conditioned checkpoint (depth snapshot).
          2. Simulate long-loop interference by iterating through
             ``loop_iterations`` of synthetic observations, each with
             decreasing recurrence.
          3. After context is unloaded, check if depth has drifted
             below expected retention.
          4. Drift detected when depth < expected * 0.5.

        Args:
            memory_id: Memory to stress-test.
            working_context_unloaded: Simulate context unloading (default: True).
            loop_iterations: Number of interference iterations.
            recurrence: External recurrence signal (0-1). Higher = less drift.

        Returns:
            Dict with:
              - drifted: Whether drift was detected.
              - depth_before: Depth at checkpoint.
              - depth_after: Depth after loop interference.
              - expected: Expected retention threshold.
              - iterations: Number of loop iterations.
              - drift_ratio: depth_after / expected (lower = more drift).
        """
        self._stats["loop_drift_tests"] += 1
        self._ensure_record(memory_id)
        record = self._records[memory_id]
        depth_before = record.depth

        if not working_context_unloaded or loop_iterations <= 0:
            return {
                "drifted": False,
                "depth_before": round(depth_before, 4),
                "depth_after": round(record.depth, 4),
                "expected": round(depth_before, 4),
                "iterations": 0,
                "drift_ratio": 1.0,
                "reason": "context_loaded" if not working_context_unloaded else "no_iterations",
            }

        # Simulate long-loop interference: apply decay per iteration
        decay_per_iter = self._depth_decay ** (1.0 / self._drift_window)
        for _ in range(loop_iterations):
            record.depth = max(0.0, record.depth * decay_per_iter)

        depth_after = record.depth

        # Expected: ~70% retention with recurrence boost
        expected = 0.7 * max(0.1, depth_before + recurrence * 0.3)

        drifted = depth_after < expected * 0.5
        if drifted:
            self._stats["drifts_detected"] = int(self._stats.get("drifts_detected", 0)) + 1
            logger.warning(
                "EVAF loop-drift DETECTED: %s depth=%.3f < expected=%.3f "
                "(iter=%d, recurrence=%.2f)",
                memory_id, depth_after, expected, loop_iterations, recurrence,
            )

        drift_ratio = depth_after / max(expected, 1e-10)

        return {
            "drifted": drifted,
            "depth_before": round(depth_before, 4),
            "depth_after": round(depth_after, 4),
            "expected": round(expected, 4),
            "iterations": loop_iterations,
            "drift_ratio": round(drift_ratio, 4),
            "recurrence": recurrence,
        }

    # ------------------------------------------------------------------
    # Depth decay (arXiv 2606.26806 §3.4)
    # ------------------------------------------------------------------

    def depth_decay(self, hours: float = 24.0) -> dict[str, Any]:
        """Apply time-based decay to all tracked parametric depths.

        Matches memory_depth.py's apply_decay() semantics:
            decay_factor = depth_decay ** (hours / 24.0)
            depth = max(0.0, depth * decay_factor)

        Args:
            hours: Simulated elapsed time in hours (default: 24).

        Returns:
            Dict with:
              - memories_affected: Count of records with non-zero depth.
              - avg_depth_before: Average depth before decay.
              - avg_depth_after: Average depth after decay.
              - decay_factor: The multiplier applied.
        """
        self._stats["depth_decay_applied"] += 1

        if not self._records:
            return {
                "memories_affected": 0,
                "avg_depth_before": 0.0,
                "avg_depth_after": 0.0,
                "decay_factor": 1.0,
            }

        decay_factor = self._depth_decay ** (hours / 24.0)
        depths_before = [r.depth for r in self._records.values()]
        avg_before = sum(depths_before) / len(depths_before)

        affected = 0
        for record in self._records.values():
            if record.depth > 0.0:
                record.depth = max(0.0, record.depth * decay_factor)
                affected += 1

        depths_after = [r.depth for r in self._records.values()]
        avg_after = sum(depths_after) / len(depths_after)

        logger.debug(
            "EVAF depth_decay: factor=%.4f hours=%.1f affected=%d "
            "avg_depth %.4f -> %.4f",
            decay_factor, hours, affected, avg_before, avg_after,
        )

        return {
            "memories_affected": affected,
            "avg_depth_before": round(avg_before, 4),
            "avg_depth_after": round(avg_after, 4),
            "decay_factor": round(decay_factor, 4),
            "hours": hours,
        }

    # ------------------------------------------------------------------
    # Depth query (wired to memory_depth.py style)
    # ------------------------------------------------------------------

    def get_depth(self, memory_id: str) -> float:
        """Get current parametric depth of a memory.

        Returns 0.0 if memory_id is not tracked.

        Matches memory_depth.py's get_depth() signature.
        """
        record = self._records.get(memory_id)
        return record.depth if record else 0.0

    def batch_get_depths(self, memory_ids: list[str]) -> dict[str, float]:
        """Get depths for multiple memories at once."""
        return {mid: self.get_depth(mid) for mid in memory_ids}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_record(self, memory_id: str) -> EVAFParametricRecord:
        """Get or create a parametric record for a memory ID."""
        if memory_id not in self._records:
            self._records[memory_id] = EVAFParametricRecord(memory_id=memory_id)
        return self._records[memory_id]

    def get_trend(self, memory_id: str) -> dict[str, Any]:
        """Get surprise trend from recent history (memory_depth.py compat).

        Returns:
            Dict with avg_surprise, max_surprise, trend_direction.
        """
        record = self._records.get(memory_id)
        if record is None or not record.surprise_history or len(record.surprise_history) < 3:
            return {
                "avg_surprise": 0.0,
                "max_surprise": 0.0,
                "trend_direction": "unknown",
            }
        hist = record.surprise_history
        avg = sum(hist) / len(hist)
        mid = len(hist) // 2
        first_half = sum(hist[:mid]) / max(mid, 1)
        second_half = sum(hist[mid:]) / max(len(hist) - mid, 1)
        trend = "stable"
        if second_half > first_half * 1.1:
            trend = "increasing"
        elif second_half < first_half * 0.9:
            trend = "decreasing"
        return {
            "avg_surprise": round(avg, 4),
            "max_surprise": round(max(hist), 4),
            "trend_direction": trend,
        }

    def get_stats(self) -> dict:
        """Get aggregate EVAF statistics (enhanced)."""
        n = len(self._records)
        if n > 0:
            avg_depth = sum(r.depth for r in self._records.values()) / n
        else:
            avg_depth = 0.0

        cons_val = int(self._stats.get("consolidated", 0))
        eval_val = int(self._stats.get("evaluated", 0))

        return {
            "total_memories": n,
            "avg_depth": round(avg_depth, 4),
            "total_evaluated": eval_val,
            "total_consolidated": cons_val,
            "consolidation_rate": round(cons_val / max(eval_val, 1), 4),
            "gates_closed": self._stats.get("gates_closed", 0),
            "drifts_detected": self._stats.get("drifts_detected", 0),
            "loop_drift_tests": self._stats.get("loop_drift_tests", 0),
            "depth_decay_applied": self._stats.get("depth_decay_applied", 0),
            "surprise_threshold": self._surprise_threshold,
            "valence_threshold": self._valence_threshold,
            "depth_delta": self._depth_delta,
            "depth_decay": self._depth_decay,
            "drift_window": self._drift_window,
            "window_size": self._window_size,
            "max_per_window": self._max_per_window,
            "current_window_consolidations": self._consolidation_count,
        }
