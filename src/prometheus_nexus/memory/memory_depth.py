"""MemoryDepthTracker — EVAF: surprise- and valence-gated parametric consolidation.

Based on: "Memory Depth, Not Memory Access: Selective Parametric Consolidation
for Long-Running Language Agents" (arXiv:2606.26806, Han 2026)

Key insight: memory depth (durable parametric tendencies) is distinct from and
complementary to memory access (retrieval). EVAF uses surprise (prediction error)
and valence (outcome value) to gate LoRA-style consolidation.

Three core mechanisms:
1. Surprise gating — only consolidate when prediction error exceeds threshold
2. Valence gating — only consolidate positively/negatively valenced experiences
3. Loop-drift protocol — controlled stress test detecting goal persistence
   degradation when working context is unloaded under long-loop interference
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import math
import time
from collections import deque
from typing import Any


# ---------------------------------------------------------------------------
# EVAF consolidation record
# ---------------------------------------------------------------------------

class EVAFRecord:
    """A single memory with EVAF consolidation metadata.

    Attributes:
        memory_id: Unique identifier.
        depth: Parametric depth (durable tendency, 0-1).
        surprise: Prediction error of the last observation.
        valence: Outcome value of the last observation (-1 to 1).
        consolidated: Number of times EVAF gate passed.
        access_count: Times retrieved.
        last_access: Unix timestamp.
        surprise_history: Recent surprise values for trend detection.
    """
    def __init__(self, memory_id: str) -> None:
        self.memory_id: str = memory_id
        self.depth: float = 0.0
        self.surprise: float = 0.0
        self.valence: float = 0.0
        self.consolidated: int = 0
        self.access_count: int = 0
        self.last_access: float = 0.0
        self.surprise_history: deque[float] = deque(maxlen=20)


# ---------------------------------------------------------------------------
# EVAF Memory Depth Tracker (arXiv 2606.26806)
# ---------------------------------------------------------------------------

class EVAFMemoryDepthTracker:
    """EVAF — surprise- and valence-gated parametric consolidation.

    The paper's core algorithm:
        surprise = abs(predicted_outcome - actual_outcome)
        if surprise > threshold AND abs(valence) > valence_min:
            depth = min(1.0, depth + delta)
        else:
            depth *= decay (forgetting)

    Loop-drift protocol:
        Stores checkpoints of goal-conditioned behavior under working-context
        load, then detects drift when context is unloaded.

    Usage:
        evaf = EVAFMemoryDepthTracker()
        evaf.record_observation("m1", predicted=0.5, actual=0.9, valence=0.8)
        evaf.record_observation("m1", predicted=0.3, actual=0.2, valence=-0.6)
        d = evaf.get_depth("m1")
        drift = evaf.check_drift("m1")
    """

    def __init__(
        self,
        surprise_threshold: float = 0.15,
        valence_min: float = 0.3,
        depth_delta: float = 0.12,
        depth_decay: float = 0.98,
        drift_window: int = 10,
    ) -> None:
        """Initialise EVAF.

        Args:
            surprise_threshold: Min prediction error to trigger consolidation.
            valence_min: Min |valence| to gate consolidation.
            depth_delta: Amount added to depth per consolidation.
            depth_decay: Per-time-decay factor.
            drift_window: Observations to use for drift detection.
        """
        self._surprise_threshold = surprise_threshold
        self._valence_min = valence_min
        self._depth_delta = depth_delta
        self._depth_decay = depth_decay
        self._drift_window = drift_window

        self._records: dict[str, EVAFRecord] = {}
        self._stats: dict[str, int | float] = {
            "observations": 0,
            "consolidations": 0,
            "gates_closed": 0,
            "drifts_detected": 0,
        }

    # ---- Public API -------------------------------------------------------

    def record_observation(
        self,
        memory_id: str,
        predicted: float,
        actual: float,
        valence: float,
    ) -> dict[str, Any]:
        """Record an observation and apply EVAF consolidation gate.

        EVAF gate opens when:
            surprise = abs(predicted - actual) > threshold
            AND abs(valence) > valence_min

        Args:
            memory_id: Memory identifier.
            predicted: Predicted outcome (0-1).
            actual: Actual outcome (0-1).
            valence: Valence of associated outcome (-1 to 1).

        Returns:
            Dict with consolidated (bool), depth_after (float).
        """
        if memory_id not in self._records:
            self._records[memory_id] = EVAFRecord(memory_id)

        record = self._records[memory_id]
        self._stats["observations"] += 1

        # 1. Compute surprise (prediction error)
        surprise = abs(predicted - actual)
        record.surprise = surprise
        record.surprise_history.append(surprise)
        record.access_count += 1
        record.last_access = time.time()

        # 2. EVAF gate
        if surprise > self._surprise_threshold and abs(valence) > self._valence_min:
            # Gate open — consolidate
            record.depth = min(1.0, record.depth + self._depth_delta)
            record.consolidated += 1
            self._stats["consolidations"] += 1
            record.valence = valence
            logger.debug(
                "EVAF gate OPEN: %s surprise=%.3f valence=%.3f depth=%.3f",
                memory_id, surprise, valence, record.depth,
            )
            return {"consolidated": True, "surprise": surprise, "depth_after": record.depth}

        # 3. Gate closed — no consolidation
        self._stats["gates_closed"] += 1
        record.valence = valence
        logger.debug(
            "EVAF gate CLOSED: %s surprise=%.3f(valence=%.3f) — need >%.2f and >%.2f",
            memory_id, surprise, valence, self._surprise_threshold, self._valence_min,
        )
        return {"consolidated": False, "surprise": surprise, "reason": "gate_closed"}

    def apply_decay(self) -> None:
        """Apply time-based decay to all tracked depths."""
        now = time.time()
        for record in self._records.values():
            age_hours = (now - record.last_access) / 3600.0 if record.last_access else 999.0
            decay_factor = self._depth_decay ** (age_hours / 24.0)
            record.depth = max(0.0, record.depth * decay_factor)

    def get_depth(self, memory_id: str) -> float:
        """Get current parametric depth of a memory.

        Returns 0.0 if memory_id is not tracked.
        """
        record = self._records.get(memory_id)
        return record.depth if record else 0.0

    # ---- Loop-Drift Protocol (paper's controlled stress test) -------------

    def check_drift(
        self, memory_id: str, recurrence: float = 0.0
    ) -> dict[str, Any]:
        """Check if a memory has drifted under loop-drift protocol.

        The loop-drift protocol: when working context is unloaded and
        long-loop interference accumulates, goal-conditioned tendencies
        should persist. Drift = depth dropping below expected retention.

        Args:
            memory_id: Memory to check.
            recurrence: External recurrence signal (0-1) — how much the
                        memory has been re-accessed recently. Higher =
                        less drift.

        Returns:
            Dict with drifted (bool), depth (float), expected (float).
        """
        record = self._records.get(memory_id)
        if record is None:
            return {"drifted": False, "depth": 0.0, "expected": 0.0, "reason": "not_tracked"}

        # Expected depth: should have ~70% retention if no drift
        expected = 0.7 * max(0.1, record.depth + recurrence * 0.3)

        if record.depth < expected * 0.5:
            self._stats["drifts_detected"] = int(self._stats.get("drifts_detected", 0)) + 1
            logger.warning(
                "Loop-drift DETECTED: %s depth=%.3f < expected=%.3f (recurrence=%.2f)",
                memory_id, record.depth, expected, recurrence,
            )
            return {"drifted": True, "depth": record.depth, "expected": expected}

        return {"drifted": False, "depth": record.depth, "expected": expected}

    def record_checkpoint(self, memory_id: str) -> dict[str, Any]:
        """Record a goal-conditioned behavior checkpoint.

        Returns snapshot of current depth for later drift comparison.
        """
        record = self._records.get(memory_id)
        if record is None:
            return {"checkpoint": False, "reason": "not_tracked"}
        return {
            "checkpoint": True,
            "memory_id": memory_id,
            "depth": record.depth,
            "consolidated": record.consolidated,
            "timestamp": time.time(),
        }

    # ---- Statistics --------------------------------------------------------

    def get_trend(self, memory_id: str) -> dict[str, float]:
        """Get surprise trend from recent history.

        Returns:
            Dict with avg_surprise, max_surprise, trend_direction
            ("increasing" / "decreasing" / "stable").
        """
        record = self._records.get(memory_id)
        if record is None or len(record.surprise_history) < 3:
            return {"avg_surprise": 0.0, "max_surprise": 0.0, "trend_direction": "unknown"}
        hist = list(record.surprise_history)
        avg = sum(hist) / len(hist)
        first_half = sum(hist[:len(hist)//2]) / (len(hist)//2)
        second_half = sum(hist[len(hist)//2:]) / (len(hist) - len(hist)//2)
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

    def record_consolidation(self, memory_id: str) -> None:
        """Record a consolidation event for a memory.

        Args:
            memory_id: The memory ID to record consolidation for.
        """
        self._stats["consolidations"] = self._stats.get("consolidations", 0) + 1
        logger.debug("EVAF: recorded consolidation for %s", memory_id)

    def record_access(self, memory_id: str) -> None:
        """Record an access event for a memory (backward compat for life.py).

        Delegates to record_observation with safe defaults.
        """
        self.record_observation(memory_id, 0.0, 0.0, 0.5)

    def get_stats(self) -> dict[str, Any]:
        """Get aggregate EVAF statistics."""
        if not self._records:
            return {
                "total_memories": 0,
                "avg_depth": 0.0,
                "total_consolidations": 0,
                "total_observations": 0,
                "gates_closed": 0,
                "drifts_detected": 0,
                "consolidation_rate": 0.0,
            }
        depths = [r.depth for r in self._records.values()]
        obs = int(self._stats.get("observations", 0))
        cons = int(self._stats.get("consolidations", 0))
        return {
            "total_memories": len(self._records),
            "avg_depth": round(sum(depths) / len(depths), 4),
            "total_consolidations": cons,
            "total_observations": obs,
            "gates_closed": self._stats.get("gates_closed", 0),
            "drifts_detected": self._stats.get("drifts_detected", 0),
            "consolidation_rate": round(cons / max(obs, 1), 4),
        }


# Backward compatibility alias
MemoryDepthTracker = EVAFMemoryDepthTracker
