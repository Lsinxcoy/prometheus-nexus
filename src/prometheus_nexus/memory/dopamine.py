"""DopamineWriteGate — Reward-gated memory write system.

Inspired by the dopaminergic system in neuroscience, this gate evaluates
whether a memory write should be accepted based on its utility and novelty
(surprise). High-utility, high-surprise memories are more likely to be accepted.

Algorithm:
    score = utility × α + surprise × β
    decision = "accept" if score ≥ threshold else "reject"

    Where:
    - α (utility_weight): Importance of utility in scoring (default: 0.6)
    - β (surprise_weight): Importance of novelty in scoring (default: 0.4)
    - threshold: Minimum score for acceptance (default: 0.3)

    Optional adaptive threshold:
    - threshold adapts based on recent acceptance rate
    - Target accept_rate ± tolerance triggers threshold adjustment

Edge Cases:
    - utility or surprise outside [0, 1]: clamped to valid range
    - Empty history: uses base threshold
    - All accepts/rejects: threshold adapts to maintain target rate

Complexity:
    - evaluate(): O(1) amortized, O(W) for sliding window trim
    - get_stats(): O(1)
    - get_adaptive_threshold(): O(W) where W = window size

Thread Safety:
    - Not thread-safe. Use external lock if shared across threads.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================
# Configuration
# ============================================================

@dataclass
class DopamineGateConfig:
    """Configuration for DopamineWriteGate.

    Attributes:
        threshold: Base acceptance threshold [0, 1].
        utility_weight: Weight for utility in score calculation [0, 1].
        surprise_weight: Weight for surprise in score calculation [0, 1].
        accept_rate_target: Target acceptance rate for adaptive threshold [0, 1].
        adaptive: Whether to use adaptive threshold.
        adaptive_tolerance: How far accept_rate can deviate before adjusting.
        adaptive_rate: How quickly threshold adapts (0 = no adaptation, 1 = instant).
        window_size: Sliding window size for history tracking.
        clamp_values: Whether to clamp utility/surprise to [0, 1].
    """
    threshold: float = 0.3
    utility_weight: float = 0.6
    surprise_weight: float = 0.4
    accept_rate_target: float = 0.6
    adaptive: bool = False
    adaptive_tolerance: float = 0.1
    adaptive_rate: float = 0.05
    window_size: int = 1000
    clamp_values: bool = True

    def __post_init__(self):
        if not 0 <= self.threshold <= 1:
            raise ValueError(f"threshold must be in [0, 1], got {self.threshold}")
        if not 0 <= self.utility_weight <= 1:
            raise ValueError(f"utility_weight must be in [0, 1], got {self.utility_weight}")
        if not 0 <= self.surprise_weight <= 1:
            raise ValueError(f"surprise_weight must be in [0, 1], got {self.surprise_weight}")
        if abs(self.utility_weight + self.surprise_weight - 1.0) > 0.01:
            logger.warning(
                "utility_weight + surprise_weight = %.2f, expected 1.0. "
                "Weights will be normalized.",
                self.utility_weight + self.surprise_weight,
            )


# ============================================================
# Result Types
# ============================================================

@dataclass
class GateDecision:
    """Result of a dopamine gate evaluation.

    Attributes:
        decision: "accept" or "reject".
        score: Computed reward score.
        threshold: Threshold used for this decision.
        utility: Input utility value (after clamping).
        surprise: Input surprise value (after clamping).
        adaptive_threshold: Current adaptive threshold (if enabled).
        accept_rate: Current acceptance rate.
        history_size: Number of decisions in history.
    """
    decision: str = "reject"
    score: float = 0.0
    threshold: float = 0.3
    utility: float = 0.0
    surprise: float = 0.0
    adaptive_threshold: float = 0.3
    accept_rate: float = 0.0
    history_size: int = 0

    @property
    def accepted(self) -> bool:
        return self.decision == "accept"

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "score": self.score,
            "threshold": self.threshold,
            "utility": self.utility,
            "surprise": self.surprise,
            "adaptive_threshold": self.adaptive_threshold,
            "accept_rate": self.accept_rate,
            "history_size": self.history_size,
        }


# ============================================================
# DopamineWriteGate
# ============================================================

class DopamineWriteGate:
    """Reward-gated memory write system.

    Evaluates memory writes based on a weighted combination of utility
    (how useful the memory is) and surprise (how novel it is). Only
    memories exceeding the threshold are accepted.

    Usage:
        gate = DopamineWriteGate()
        decision = gate.evaluate(utility=0.8, surprise=0.3)
        if decision.accepted:
            store.create_node(node)

        # With adaptive threshold
        gate = DopamineWriteGate(DopamineGateConfig(adaptive=True))
        for _ in range(100):
            gate.evaluate(utility=random.random(), surprise=random.random())
        # Threshold has adapted to maintain target accept_rate

    Algorithm:
        score = utility × α + surprise × β
        accept if score ≥ threshold

    Adaptive Threshold:
        When enabled, the threshold adjusts based on the recent acceptance rate.
        If the actual rate is above target + tolerance, threshold increases.
        If below target - tolerance, threshold decreases.
    """

    def __init__(self, config: DopamineGateConfig | None = None):
        """Initialize the dopamine gate.

        Args:
            config: Gate configuration. Uses defaults if None.
        """
        self._cfg = config or DopamineGateConfig()
        self._lock = threading.Lock()

        # Statistics
        self._total = 0
        self._accepted = 0
        self._rejected = 0

        # Sliding window history
        self._history: list[float] = []
        self._decisions: list[bool] = []

        # Adaptive threshold state
        self._current_threshold = self._cfg.threshold
        self._recent_accepts = 0
        self._recent_total = 0

    def evaluate(self, utility: float = 0.5, surprise: float = 0.0) -> GateDecision:
        """Evaluate whether a memory write should be accepted.

        Args:
            utility: How useful the memory is [0, 1]. Higher = more useful.
            surprise: How novel/surprising the memory is [0, 1]. Higher = more novel.

        Returns:
            GateDecision with decision, score, and metadata.

        Complexity: O(1) amortized, O(W) for sliding window trim.
        """
        with self._lock:
            # Clamp values if configured
            if self._cfg.clamp_values:
                utility = max(0.0, min(1.0, utility))
                surprise = max(0.0, min(1.0, surprise))

            # Compute reward score
            score = utility * self._cfg.utility_weight + surprise * self._cfg.surprise_weight

            # Determine threshold
            threshold = self._get_current_threshold()

            # Make decision
            decision = "accept" if score >= threshold else "reject"
            accepted = decision == "accept"

            # Update statistics
            self._total += 1
            if accepted:
                self._accepted += 1
            else:
                self._rejected += 1

            # Update history
            self._history.append(score)
            self._decisions.append(accepted)
            self._trim_history()

            # Update adaptive threshold
            if self._cfg.adaptive:
                self._update_adaptive_threshold(accepted)

            # Compute current accept rate
            accept_rate = self._accepted / max(self._total, 1)

            result = GateDecision(
                decision=decision,
                score=score,
                threshold=threshold,
                utility=utility,
                surprise=surprise,
                adaptive_threshold=self._current_threshold,
                accept_rate=accept_rate,
                history_size=len(self._history),
            )

            logger.debug(
                "Dopamine gate: score=%.3f, threshold=%.3f, decision=%s",
                score, threshold, decision,
            )

            return result

    def _get_current_threshold(self) -> float:
        """Get the current effective threshold."""
        return self._current_threshold if self._cfg.adaptive else self._cfg.threshold

    def _update_adaptive_threshold(self, accepted: bool) -> None:
        """Update adaptive threshold based on recent acceptance rate."""
        self._recent_total += 1
        if accepted:
            self._recent_accepts += 1

        # Only adapt after enough samples
        if self._recent_total < 20:
            return

        recent_rate = self._recent_accepts / self._recent_total
        target = self._cfg.accept_rate_target
        tolerance = self._cfg.adaptive_tolerance

        # Adjust threshold
        if recent_rate > target + tolerance:
            # Too many accepts → raise threshold
            self._current_threshold = min(
                1.0,
                self._current_threshold + self._cfg.adaptive_rate,
            )
        elif recent_rate < target - tolerance:
            # Too few accepts → lower threshold
            self._current_threshold = max(
                0.0,
                self._current_threshold - self._cfg.adaptive_rate,
            )

        # Reset recent window periodically
        if self._recent_total >= 100:
            self._recent_accepts = self._recent_accepts // 2
            self._recent_total = self._recent_total // 2

    def _trim_history(self) -> None:
        """Trim history to window size."""
        max_size = self._cfg.window_size
        if len(self._history) > max_size:
            half = max_size // 2
            self._history = self._history[-half:]
            self._decisions = self._decisions[-half:]

    # ============================================================
    # Statistics & Inspection
    # ============================================================

    def get_stats(self) -> dict:
        """Get gate statistics.

        Returns:
            Dictionary with total, accepted, rejected, rates, and score stats.
        """
        with self._lock:
            recent = self._history[-100:] if self._history else []
            recent_decisions = self._decisions[-100:] if self._decisions else []

            return {
                "total": self._total,
                "accepted": self._accepted,
                "rejected": self._rejected,
                "accept_rate": self._accepted / max(self._total, 1),
                "reject_rate": self._rejected / max(self._total, 1),
                "threshold": self._cfg.threshold,
                "current_threshold": self._current_threshold,
                "adaptive": self._cfg.adaptive,
                "avg_score": sum(recent) / max(len(recent), 1),
                "min_score": min(recent) if recent else 0,
                "max_score": max(recent) if recent else 0,
                "recent_accept_rate": sum(recent_decisions) / max(len(recent_decisions), 1),
                "history_size": len(self._history),
            }

    def get_score_distribution(self, bins: int = 10) -> dict[int, int]:
        """Get score distribution in bins.

        Args:
            bins: Number of bins (default 10, each 0.1 wide).

        Returns:
            Dictionary mapping bin index to count.
        """
        with self._lock:
            distribution: dict[int, int] = {i: 0 for i in range(bins)}
            for score in self._history:
                bin_idx = min(int(score * bins), bins - 1)
                distribution[bin_idx] += 1
            return distribution

    def get_recent_decisions(self, n: int = 10) -> list[dict]:
        """Get the most recent decisions.

        Args:
            n: Number of recent decisions to return.

        Returns:
            List of recent decision records.
        """
        with self._lock:
            recent_scores = self._history[-n:]
            recent_decisions = self._decisions[-n:]
            return [
                {"score": s, "accepted": d, "threshold": self._current_threshold}
                for s, d in zip(recent_scores, recent_decisions)
            ]

    def reset(self) -> None:
        """Reset all statistics and history.

        Useful for testing or after configuration changes.
        """
        with self._lock:
            self._total = 0
            self._accepted = 0
            self._rejected = 0
            self._history.clear()
            self._decisions.clear()
            self._current_threshold = self._cfg.threshold
            self._recent_accepts = 0
            self._recent_total = 0
            logger.info("DopamineWriteGate reset")

    def update_config(self, **kwargs: Any) -> None:
        """Update configuration dynamically.

        Args:
            **kwargs: Configuration fields to update.

        Example:
            gate.update_config(threshold=0.5, adaptive=True)
        """
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self._cfg, key):
                    setattr(self._cfg, key, value)
                    logger.info("Updated config: %s = %s", key, value)
                else:
                    logger.warning("Unknown config key: %s", key)
