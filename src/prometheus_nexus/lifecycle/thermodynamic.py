"""ThermodynamicIntelligence — Thermodynamic measure of intelligence.

Based on: "Thermodynamic Measure of Intelligence" (arXiv:2606.20231, Chattopadhyay 2026)

Core Definition:
    Thermodynamic Intelligence = rare-valid probability lift:
        I_δ(P; P0, Vδ) = (P(Vδ) - δ) / δ
    Where:
    - P: trajectory distribution induced by the system
    - P0: passive baseline distribution
    - Vδ: rare-valid set with passive mass δ = P0(Vδ)

Key Concepts:
    1. Rare-Valid Futures: trajectories unlikely under passive dynamics but valid
       under domain constraints
    2. Recursive Self-Simulation: system models itself in the world
    3. Rare-Valid Fidelity (Φ̂): how accurately the simulation identifies targets
    4. Compressed Scale: Λ = log10(log10(I+1)+1)

Theorems (from paper):
    Theorem 1: High intelligence requires high rare-valid fidelity
        I_δ ≤ (α_max - 1) × Φ̂
    Theorem 2: High fidelity + effective actuation → high intelligence
        I_δ ≥ α_min × Φ̂ + β_min × (1 - Φ̂) - 1

For AI agent systems:
    - P0 = random/baseline action distribution
    - P = agent's actual action distribution
    - Vδ = actions that achieve rare but valid outcomes
    - δ = baseline probability of achieving those outcomes

Complexity:
    update(): O(1)
    compute_intelligence(): O(N) where N = trajectory history
    get_rare_valid_fidelity(): O(N)

Edge Cases:
    - No history: intelligence = 0
    - All actions identical: low fidelity
    - Perfect rare-valid identification: Φ̂ = 1

Usage:
    ti = ThermodynamicIntelligence()
    ti.observe_action(action, outcome_valid=True, rarity=0.1)
    ti.observe_baseline(baseline_probability=0.01)
    intelligence = ti.compute_intelligence()
    fidelity = ti.get_rare_valid_fidelity()
    scale = ti.get_compressed_scale()
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import math
from collections import deque
from dataclasses import dataclass, field


@dataclass
class TrajectoryObservation:
    """A single trajectory observation."""
    action: str = ""
    outcome_valid: bool = True
    rarity: float = 0.5
    baseline_prob: float = 0.5
    induced_prob: float = 0.5
    timestamp: float = 0.0
    metadata: dict = field(default_factory=dict)


class ThermodynamicIntelligence:
    """Thermodynamic measure of intelligence based on rare-valid probability lift.

    Implements the framework from Chattopadhyay (2026):
    - Tracks rare-valid futures and their probabilities
    - Computes thermodynamic intelligence (rare-valid lift)
    - Measures rare-valid self-simulation fidelity
    - Provides compressed intelligence scale (Λ)

    Usage:
        ti = ThermodynamicIntelligence()

        # Observe actions and outcomes
        ti.observe_action("solve难题", outcome_valid=True, rarity=0.05)
        ti.observe_action("随机尝试", outcome_valid=False, rarity=0.5)
        ti.observe_baseline(baseline_prob=0.01)

        # Compute intelligence metrics
        I = ti.compute_intelligence()
        phi = ti.get_rare_valid_fidelity()
        lam = ti.get_compressed_scale()
        energy = ti.get_energy()

        # Get comprehensive stats
        stats = ti.get_stats()
    """

    def __init__(self, history_size: int = 1000, rare_threshold: float = 0.1):
        """Initialize thermodynamic intelligence tracker.

        Args:
            history_size: Maximum observations to keep.
            rare_threshold: Probability below which an outcome is considered "rare".
        """
        self._history_size = history_size
        self._rare_threshold = rare_threshold

        # Trajectory history
        self._observations: deque[TrajectoryObservation] = deque(maxlen=history_size)
        self._baseline_probs: deque[float] = deque(maxlen=history_size)
        self._induced_probs: deque[float] = deque(maxlen=history_size)

        # Rare-valid tracking
        self._rare_valid_hits: int = 0
        self._rare_valid_misses: int = 0
        self._total_rare_observations: int = 0
        self._total_observations: int = 0

        # Fidelity tracking
        self._identified_rare_valid: int = 0
        self._actual_rare_valid: int = 0
        self._correct_identifications: int = 0

        # Temperature dynamics (from original simplified model, now enhanced)
        self._temperature = 0.5
        self._delta_accumulator = 0.0

        # Probability distributions
        self._p0_distribution: dict[str, float] = {}
        self._p_distribution: dict[str, float] = {}

    def observe_action(self, action: str, outcome_valid: bool = True,
                       rarity: float = 0.5, baseline_prob: float = 0.5,
                       induced_prob: float | None = None) -> None:
        """Observe an action and its outcome.

        Args:
            action: The action taken.
            outcome_valid: Whether the outcome is valid under domain constraints.
            rarity: How rare this outcome is under passive dynamics [0, 1].
            baseline_prob: P0 probability of this trajectory.
            induced_prob: P probability (induced by agent). If None, estimated from validity.
        """
        if induced_prob is None:
            # Agent's induced probability is higher for valid, rare outcomes
            induced_prob = baseline_prob * (2.0 if outcome_valid else 0.5)

        obs = TrajectoryObservation(
            action=action, outcome_valid=outcome_valid, rarity=rarity,
            baseline_prob=baseline_prob, induced_prob=induced_prob,
        )
        self._observations.append(obs)
        self._baseline_probs.append(baseline_prob)
        self._induced_probs.append(induced_prob)
        self._total_observations += 1

        # Track rare-valid
        is_rare = rarity < self._rare_threshold or baseline_prob < self._rare_threshold
        if is_rare:
            self._total_rare_observations += 1
            if outcome_valid:
                self._rare_valid_hits += 1
            else:
                self._rare_valid_misses += 1

        # Track fidelity
        agent_identifies_as_rare = induced_prob < baseline_prob * 0.5
        if is_rare:
            self._actual_rare_valid += 1
            if agent_identifies_as_rare or outcome_valid:
                self._correct_identifications += 1
        if agent_identifies_as_rare:
            self._identified_rare_valid += 1

        # Update distributions
        self._p0_distribution[action] = baseline_prob
        self._p_distribution[action] = induced_prob

        # Temperature update (enhanced from paper's thermodynamic framework)
        self._update_temperature(baseline_prob, induced_prob, outcome_valid)

    def observe_baseline(self, baseline_prob: float) -> None:
        """Observe a baseline probability for temperature dynamics."""
        self._baseline_probs.append(baseline_prob)

    def _update_temperature(self, p0: float, p: float, valid: bool) -> None:
        """Update temperature based on probability shift and validity.
        
        Temperature reflects system deviation from passive equilibrium (0.5).
        - Valid rare-valid outcomes → temperature moves AWAY from 0.5 (intelligent)
        - Invalid or low-lift outcomes → temperature moves TOWARD 0.5 (random/failing)
        """
        lift = (p - p0) / max(p0, 1e-10)
        if valid and lift > 0:
            # Valid rare-valid: push temperature away from 0.5 toward 0.0
            delta = -0.1 * lift * self._temperature
        else:
            # Invalid/no lift: push temperature toward 0.5
            delta = 0.05 * (0.5 - self._temperature)
        self._temperature = max(0.01, min(0.99, self._temperature + delta))

    def compute_intelligence(self, delta: float | None = None) -> float:
        """Compute thermodynamic intelligence (rare-valid lift).

        From paper Eq. (25):
            I_δ = (P(Vδ) - δ) / δ

        Returns:
            Intelligence value I_δ. 0 = passive, >0 = intelligent.
        """
        if self._total_rare_observations == 0:
            return 0.0

        # δ = average baseline probability of rare-valid observations
        if delta is None:
            rare_obs = [o for o in self._observations
                        if o.baseline_prob < self._rare_threshold or o.rarity < self._rare_threshold]
            if not rare_obs:
                return 0.0
            delta = sum(o.baseline_prob for o in rare_obs) / len(rare_obs)

        if delta <= 0:
            return 0.0

        # P(Vδ) = fraction of rare-valid observations that are valid and induced
        p_vdelta = self._rare_valid_hits / max(self._total_rare_observations, 1)

        # I_δ = (P(Vδ) - δ) / δ
        intelligence = (p_vdelta - delta) / delta

        return max(0.0, intelligence)

    def get_rare_valid_fidelity(self) -> float:
        """Compute rare-valid self-simulation fidelity (Φ̂).

        From paper Eq. (14):
            Φ̂ = P0(Â ∩ Vδ) / δ

        Measures how accurately the system identifies rare-valid futures.
        Returns:
            Fidelity Φ̂ ∈ [0, 1]. 1 = perfect identification.
        """
        if self._actual_rare_valid == 0:
            return 0.0
        return self._correct_identifications / self._actual_rare_valid

    def get_compressed_scale(self) -> float:
        """Compute compressed intelligence scale (Λ).

        From paper Eq. (140):
            Λ = log10(log10(I + 1) + 1)

        Returns:
            Compressed scale Λ. 0 = passive, higher = more intelligent.
        """
        I = self.compute_intelligence()
        L = math.log10(I + 1) if I >= 0 else 0
        lam = math.log10(L + 1) if L >= 0 else 0
        return lam

    def get_energy(self) -> float:
        """Compute thermodynamic energy (1 - entropy/ln(2)).

        Returns:
            Energy ∈ [0, 1]. Higher = more ordered/intelligent.
        """
        p = self._temperature
        if p <= 0 or p >= 1:
            return 1.0
        entropy = -p * math.log(p) - (1 - p) * math.log(1 - p)
        return 1.0 - entropy / math.log(2)

    def get_rare_valid_ratio(self) -> float:
        """Get the ratio of rare-valid observations."""
        if self._total_observations == 0:
            return 0.0
        return self._total_rare_observations / self._total_observations

    def get_validity_rate(self) -> float:
        """Get the validity rate of rare observations."""
        if self._total_rare_observations == 0:
            return 0.0
        return self._rare_valid_hits / self._total_rare_observations

    # ============================================================
    # Statistics
    # ============================================================

    def get_stats(self) -> dict:
        """Get comprehensive thermodynamic intelligence statistics.

        Returns:
            Dictionary with all metrics from the paper.
        """
        I = self.compute_intelligence()
        phi = self.get_rare_valid_fidelity()
        lam = self.get_compressed_scale()
        energy = self.get_energy()

        return {
            # Core intelligence metrics (from paper)
            "intelligence": I,
            "rare_valid_fidelity": phi,
            "compressed_scale": lam,
            "energy": energy,
            "temperature": self._temperature,

            # Trajectory statistics
            "total_observations": self._total_observations,
            "total_rare_observations": self._total_rare_observations,
            "rare_valid_hits": self._rare_valid_hits,
            "rare_valid_misses": self._rare_valid_misses,

            # Fidelity components
            "identified_rare_valid": self._identified_rare_valid,
            "actual_rare_valid": self._actual_rare_valid,
            "correct_identifications": self._correct_identifications,

            # Derived rates
            "rare_ratio": self.get_rare_valid_ratio(),
            "validity_rate": self.get_validity_rate(),

            # Paper equation references
            "formula": "I_δ = (P(Vδ) - δ) / δ",
            "compressed_formula": "Λ = log10(log10(I+1) + 1)",
            "fidelity_formula": "Φ̂ = P0(Â ∩ Vδ) / δ",
        }

    def get_trajectory_summary(self) -> dict:
        """Get summary of trajectory observations."""
        if not self._observations:
            return {"count": 0}

        valid_count = sum(1 for o in self._observations if o.outcome_valid)
        rare_count = sum(1 for o in self._observations
                         if o.rarity < self._rare_threshold or o.baseline_prob < self._rare_threshold)
        rare_valid_count = sum(1 for o in self._observations
                               if (o.rarity < self._rare_threshold or o.baseline_prob < self._rare_threshold)
                               and o.outcome_valid)

        avg_baseline = sum(o.baseline_prob for o in self._observations) / len(self._observations)
        avg_induced = sum(o.induced_prob for o in self._observations) / len(self._observations)
        avg_lift = (avg_induced - avg_baseline) / max(avg_baseline, 1e-10)

        return {
            "count": len(self._observations),
            "valid_count": valid_count,
            "validity_rate": valid_count / max(len(self._observations), 1),
            "rare_count": rare_count,
            "rare_valid_count": rare_valid_count,
            "avg_baseline_prob": avg_baseline,
            "avg_induced_prob": avg_induced,
            "avg_lift": avg_lift,
        }

    def get_intelligence_breakdown(self) -> dict:
        """Get intelligence breakdown by action type."""
        action_stats: dict[str, dict] = {}
        for obs in self._observations:
            if obs.action not in action_stats:
                action_stats[obs.action] = {"count": 0, "valid": 0, "rare": 0, "rare_valid": 0}
            stats = action_stats[obs.action]
            stats["count"] += 1
            if obs.outcome_valid:
                stats["valid"] += 1
            if obs.rarity < self._rare_threshold:
                stats["rare"] += 1
                if obs.outcome_valid:
                    stats["rare_valid"] += 1

        # Compute per-action intelligence
        for action, stats in action_stats.items():
            if stats["rare"] > 0:
                delta = sum(o.baseline_prob for o in self._observations
                           if o.action == action and o.rarity < self._rare_threshold) / stats["rare"]
                p_vdelta = stats["rare_valid"] / stats["rare"]
                stats["intelligence"] = (p_vdelta - delta) / max(delta, 1e-10)
            else:
                stats["intelligence"] = 0.0

        return action_stats

    def reset(self) -> None:
        """Reset all tracking state."""
        self._observations.clear()
        self._baseline_probs.clear()
        self._induced_probs.clear()
        self._rare_valid_hits = 0
        self._rare_valid_misses = 0
        self._total_rare_observations = 0
        self._total_observations = 0
        self._identified_rare_valid = 0
        self._actual_rare_valid = 0
        self._correct_identifications = 0
        self._temperature = 0.5
        self._p0_distribution.clear()
        self._p_distribution.clear()

    def get_state(self) -> dict:
        """获取可持久化的状态快照（5 个标量，不包含 1000 条观测历史）。"""
        return {
            "_temperature": self._temperature,
            "_rare_valid_hits": self._rare_valid_hits,
            "_rare_valid_misses": self._rare_valid_misses,
            "_total_observations": self._total_observations,
            "_total_rare_observations": self._total_rare_observations,
            "_actual_rare_valid": self._actual_rare_valid,
            "_correct_identifications": self._correct_identifications,
        }

    def set_state(self, state: dict) -> None:
        """从持久化快照恢复状态。"""
        if not state:
            return
        self._temperature = state.get("_temperature", 0.5)
        self._rare_valid_hits = state.get("_rare_valid_hits", 0)
        self._rare_valid_misses = state.get("_rare_valid_misses", 0)
        self._total_observations = state.get("_total_observations", 0)
        self._total_rare_observations = state.get("_total_rare_observations", 0)
        self._actual_rare_valid = state.get("_actual_rare_valid", 0)
        self._correct_identifications = state.get("_correct_identifications", 0)

    def update(self, delta: float = 0.1) -> None:
        """Update temperature with a delta (backward-compatible method).

        Args:
            delta: Temperature adjustment delta.
        """
        self._temperature = max(0.01, min(0.99, self._temperature + delta * (0.5 - self._temperature)))
