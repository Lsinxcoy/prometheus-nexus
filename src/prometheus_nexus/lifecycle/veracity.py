"""VeracityBayesian — Bayesian truth confidence merging.

基于:
- "Bayesian Truth Discovery" (Nguyen et al., 2016, SIGKDD)
  - 后验计算: P(H|E) = P(E|H)×P(H) / [P(E|H)×P(H) + P(E|¬H)×P(¬H)]
  - 似然估计: source_confidence × consistency + corroboration_boost
  - 六级置信度: UNVERIFIED/LOW/MODERATE/HIGH/VERY_HIGH/CERTAIN

算法:
    compute_posterior(prior, evidence):
        1. base_likelihood = source_confidence × consistency
        2. corroboration_boost = corroboration × 0.2
        3. posterior = (likelihood × prior) / denominator

来源: Omega系统 veracity 贝叶斯真实度验证模块
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


from dataclasses import dataclass


@dataclass
class Evidence:
    """Evidence for Bayesian update."""
    source_confidence: float = 0.5
    consistency: float = 0.5
    corroboration: float = 0.5


class VeracityBayesian:
    """Bayesian truth confidence merging.

    Usage:
        vb = VeracityBayesian()

        # Single evidence update
        p = vb.compute_posterior(0.5, Evidence(0.8, 0.7, 0.6))

        # Multiple evidence updates
        p1 = vb.compute_posterior(0.5, Evidence(0.9, 0.8, 0.7))
        p2 = vb.compute_posterior(p1, Evidence(0.7, 0.6, 0.5))

        # Get confidence level
        level = vb.get_confidence_level(p2)

        # Get all posteriors
        stats = vb.get_stats()
    """

    # Confidence levels
    LEVELS = [
        (0.0, 0.2, "UNVERIFIED"),
        (0.2, 0.4, "LOW"),
        (0.4, 0.6, "MODERATE"),
        (0.6, 0.8, "HIGH"),
        (0.8, 0.95, "VERY_HIGH"),
        (0.95, 1.0, "CERTAIN"),
    ]

    def __init__(self):
        self._posteriors: list[float] = []

    def compute_posterior(self, prior: float, evidence: Evidence) -> float:
        """Compute Bayesian posterior probability.

        Uses source_confidence, consistency, AND corroboration.
        Corroboration acts as a multiplier on the likelihood.

        Args:
            prior: Prior probability P(H) [0, 1].
            evidence: Evidence with source_confidence, consistency, corroboration.

        Returns:
            Posterior probability P(H|E) [0, 1].
        """
        base_likelihood = evidence.source_confidence * evidence.consistency
        corroboration_boost = evidence.corroboration * 0.2
        likelihood = min(1.0, base_likelihood + corroboration_boost)
        posterior = (likelihood * prior) / max(likelihood * prior + (1 - likelihood) * (1 - prior), 0.001)
        self._posteriors.append(posterior)
        return posterior

    def compute_posterior_compat(self, prior: float, evidence: Evidence) -> float:
        """Compute posterior (backward-compatible method)."""
        return self.compute_posterior(prior, evidence)

    def get_confidence_level(self, posterior: float) -> str:
        """Get confidence level string from posterior value."""
        for low, high, level in self.LEVELS:
            if low <= posterior < high:
                return level
        return "CERTAIN"

    def get_last_posterior(self) -> float:
        """Get the most recent posterior value."""
        return self._posteriors[-1] if self._posteriors else 0.5

    def get_posterior_history(self) -> list[float]:
        """Get history of posterior values."""
        return list(self._posteriors)

    def get_stats(self) -> dict:
        return {
            "posteriors": len(self._posteriors),
            "avg": sum(self._posteriors) / max(len(self._posteriors), 1),
            "last": self.get_last_posterior(),
            "last_level": self.get_confidence_level(self.get_last_posterior()),
        }
