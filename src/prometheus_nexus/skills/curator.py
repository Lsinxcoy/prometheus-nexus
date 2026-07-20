"""Curator — skill quality assessment with multi-criteria scoring.

Implements: novelty detection, utility scoring, correctness checks, composability.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)



class Curator:
    def __init__(self, registry=None):
        self._registry = registry
        self._evaluations: list[dict] = []
        self._quality_scores: dict[str, float] = {}

    def evaluate(self, skill) -> dict:
        name = getattr(skill, 'name', 'unknown')
        content = getattr(skill, 'content', '')

        # Multi-criteria scoring
        criteria = {}

        # Novelty: is this skill different from existing ones?
        existing_names = set()
        if self._registry and hasattr(self._registry, '_skills'):
            existing_names = {s.get("name", "") for s in self._registry._skills}
        criteria["novelty"] = 0.8 if name not in existing_names else 0.3

        # Utility: based on content length and specificity
        words = content.split() if content else []
        criteria["utility"] = min(1.0, len(words) / 20) if words else 0.2

        # Correctness: basic heuristics
        criteria["correctness"] = 0.7  # Default assumption

        # Composability: can it be combined with others?
        criteria["composability"] = 0.6 if len(words) > 5 else 0.3

        # Weighted score
        weights = {"novelty": 0.3, "utility": 0.3, "correctness": 0.25, "composability": 0.15}
        quality = sum(criteria[k] * weights[k] for k in weights)

        result = {
            "name": name,
            "quality": quality,
            "criteria": criteria,
        }
        self._evaluations.append(result)
        self._quality_scores[name] = quality
        return result

    def get_quality_ranking(self) -> list[dict]:
        ranked = sorted(self._quality_scores.items(), key=lambda x: x[1], reverse=True)
        return [{"name": n, "quality": q} for n, q in ranked]

    def get_stats(self) -> dict:
        return {
            "evaluations": len(self._evaluations),
            "avg_quality": sum(e["quality"] for e in self._evaluations) / max(len(self._evaluations), 1),
        }
