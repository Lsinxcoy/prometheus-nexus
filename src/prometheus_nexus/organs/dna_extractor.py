"""DNAExtractor — feature extraction from memories and patterns.

Implements: dimensionality reduction, pattern mining, feature scoring.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

from collections import Counter


class DNAExtractor:
    def __init__(self):
        self._extractions: list[dict] = []
        self._feature_memory: list[dict] = []

    def extract(self, data: dict | None = None) -> dict:
        data = data or {}
        features = {}

        # Feature 1: Content complexity (word diversity)
        memories = data.get("memories", [])
        if isinstance(memories, int):
            features["memory_count"] = memories
            memories = []
        if memories:
            all_words = []
            for m in memories:
                content = m.get("content", "") if isinstance(m, dict) else ""
                all_words.extend(content.split())
            if all_words:
                unique_ratio = len(set(all_words)) / max(len(all_words), 1)
                features["word_diversity"] = unique_ratio

        # Feature 2: Pattern density
        patterns = data.get("patterns", 0)
        features["pattern_density"] = min(1.0, patterns / 20)

        # Feature 3: Tag coverage
        all_tags = Counter()
        for m in memories:
            if isinstance(m, dict):
                for tag in m.get("tags", []):
                    all_tags[tag] += 1
        features["tag_coverage"] = min(1.0, len(all_tags) / 10)

        # Feature 4: Utility distribution
        utilities = [m.get("utility", 0.5) for m in memories if isinstance(m, dict)]
        if utilities:
            features["avg_utility"] = sum(utilities) / len(utilities)
            features["utility_variance"] = sum((u - features["avg_utility"])**2 for u in utilities) / len(utilities)
        else:
            features["avg_utility"] = 0
            features["utility_variance"] = 0

        extraction = {"features": features, "feature_count": len(features)}
        self._extractions.append(extraction)
        self._feature_memory.append(features)
        return {"extracted": True, "features": features, "feature_count": len(features)}

    def get_dominant_features(self, top_k: int = 3) -> list[dict]:
        if not self._feature_memory:
            return []
        avg_features: dict[str, float] = Counter()
        count = len(self._feature_memory)
        for features in self._feature_memory:
            for k, v in features.items():
                avg_features[k] += v
        ranked = [(k, v / count) for k, v in avg_features.items()]
        ranked.sort(key=lambda x: x[1], reverse=True)
        return [{"feature": k, "avg_value": v} for k, v in ranked[:top_k]]

    def get_stats(self) -> dict:
        return {"extractions": len(self._extractions)}
