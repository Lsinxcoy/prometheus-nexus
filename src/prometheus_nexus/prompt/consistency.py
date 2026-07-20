"""SelfConsistencyVoter — Majority voting with consistency scoring.

Based on: "Self-Consistency Improves Chain of Thought Reasoning in Language Models"
(arXiv:2203.11171, Wang et al. 2023)

Key Concepts from Paper:
    1. Sample multiple reasoning paths
    2. Marginalize over reasoning paths to marginalize the final answer
    3. Majority voting on the final answer
    4. Consistency across paths indicates confidence

Paper Finding:
    "Self-consistency improves CoT on GSM8K from 56% to 74% (+18%),
     on MultiArith from 79% to 86% (+7%)"

Algorithm:
    1. Generate N diverse reasoning paths
    2. Extract answer from each path
    3. Majority vote on answers
    4. Confidence = agreement ratio
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import math
from collections import Counter


class SelfConsistencyVoter:
    """Self-consistency voting with confidence scoring.

    Based on Self-Consistency paper (arXiv:2203.11171).

    Usage:
        voter = SelfConsistencyVoter()

        # Multiple reasoning paths yield different answers
        candidates = ["42", "43", "42", "42", "41"]
        result = voter.vote(candidates)
        # result["consensus"] = "42", result["agreement"] = 0.6
    """

    def __init__(self, min_votes: int = 3):
        """Initialize the voter.

        Args:
            min_votes: Minimum votes for a valid consensus.
        """
        self._min_votes = min_votes
        self._votes: list[dict] = []

    def vote(self, candidates: list[str]) -> dict:
        """Vote on candidates using majority voting.

        Args:
            candidates: List of candidate answers from different reasoning paths.

        Returns:
            Dict with consensus, agreement, unique_answers, and confidence.
        """
        if not candidates:
            return {"consensus": "", "agreement": 0.0, "unique_answers": 0, "confidence": 0.0}

        # Normalize
        normalized = [c.strip().lower() for c in candidates]

        # Count votes
        counts = Counter(normalized)
        total = len(normalized)

        # Find winner
        winner, winner_count = counts.most_common(1)[0]
        agreement = winner_count / total if total > 0 else 0.0

        # Confidence: based on agreement and number of unique answers
        n_unique = len(counts)
        if n_unique == 1:
            confidence = 1.0  # Perfect agreement
        elif agreement > 0.8:
            confidence = 0.9  # Strong majority
        elif agreement > 0.6:
            confidence = 0.7  # Moderate majority
        elif agreement > 0.5:
            confidence = 0.5  # Weak majority
        else:
            confidence = 0.3  # No clear majority

        # Boost confidence with more votes
        if total >= self._min_votes:
            confidence = min(1.0, confidence + 0.1)

        result = {
            "consensus": winner,
            "agreement": agreement,
            "unique_answers": n_unique,
            "confidence": confidence,
            "vote_distribution": dict(counts),
            "total_votes": total,
        }
        self._votes.append(result)
        return result

    def vote_with_weights(self, candidates: list[str], weights: list[float] | None = None) -> dict:
        """Weighted majority voting.

        Args:
            candidates: List of candidate answers.
            weights: Confidence weights for each candidate.

        Returns:
            Dict with weighted consensus and confidence.
        """
        if not candidates:
            return {"consensus": "", "confidence": 0.0}

        weights = weights or [1.0] * len(candidates)
        weighted_counts: dict[str, float] = {}

        for candidate, weight in zip(candidates, weights):
            key = candidate.strip().lower()
            weighted_counts[key] = weighted_counts.get(key, 0) + weight

        total_weight = sum(weights)
        winner = max(weighted_counts, key=weighted_counts.get) if weighted_counts else ""
        confidence = weighted_counts.get(winner, 0) / total_weight if total_weight > 0 else 0

        result = {
            "consensus": winner,
            "confidence": confidence,
            "weighted_scores": weighted_counts,
        }
        self._votes.append(result)
        return result

    def get_consensus_history(self) -> list[dict]:
        """Get history of consensus decisions."""
        return self._votes

    def get_stats(self) -> dict:
        agreements = [v["agreement"] for v in self._votes]
        return {
            "votes": len(self._votes),
            "avg_agreement": sum(agreements) / max(len(agreements), 1),
            "avg_confidence": sum(v["confidence"] for v in self._votes) / max(len(self._votes), 1),
        }
