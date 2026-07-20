"""SHMRGenerator — Synthetic Belief generation from entity co-occurrence.

基于:
- Church & Hanks (1990) Word Association Norms, Mutual Information, and Lexicography
  - PMI (Pointwise Mutual Information): PMI(a,b) = log2(P(a,b)/(P(a)×P(b)))
  - PMI>0: 正相关, PMI=0: 独立, PMI<0: 负相关
  - 实体共现统计: 频率计数 + 配对计数 → PMI计算
  - 信念合成: PMI≥min_pmi阈值 → 生成Belief实体(含confidence=PMI/5)

算法:
    generate(entities, context):
        1. 更新实体频率(self._entity_freq)
        2. 更新所有配对共现(self._co_occurrence)
        3. 对count≥2的配对: 计算PMI
        4. PMI≥min_pmi → 合成belief存入队列

来源: Omega系统 shmr 合成信念生成模块 + PMI共现分析
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Belief:
    """A synthesized belief from entity co-occurrence."""
    type: str = "co_occurrence"
    entities: list[str] = field(default_factory=list)
    confidence: float = 0.0
    evidence_count: int = 0
    pmi: float = 0.0
    context: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class SHMRGenerator:
    """Synthetic Belief generation from entity co-occurrence.

    Usage:
        gen = SHMRGenerator(min_pmi=1.0)
        gen.generate(entities=["AI", "neural_networks"], context="research")
        gen.generate(entities=["AI", "deep_learning"], context="research")
        gen.generate(entities=["neural_networks", "brain"], context="neuroscience")

        beliefs = gen.get_beliefs(min_confidence=0.3)
        for b in beliefs:
            print(f"{b.entities}: PMI={b.pmi:.2f}, confidence={b.confidence:.2f}")

        # Get statistics
        stats = gen.get_stats()
        print(f"Generated {stats['beliefs']} beliefs from {stats['entities_tracked']} entities")
    """

    def __init__(self, min_pmi: float = 1.0, max_beliefs: int = 100):
        """Initialize the SHMR generator.

        Args:
            min_pmi: Minimum PMI threshold for belief synthesis.
            max_beliefs: Maximum beliefs to store.
        """
        self._min_pmi = min_pmi
        self._max_beliefs = max_beliefs
        self._entity_freq: Counter = Counter()
        self._co_occurrence: Counter = Counter()
        self._total_observations = 0
        self._beliefs: list[Belief] = []

    def generate(self, entities: list | None = None, context: str = "") -> dict:
        """Generate beliefs from entity observations.

        Args:
            entities: List of entity strings.
            context: Context string for the observation.

        Returns:
            Dict with synthesis results.
        """
        entities = entities or []
        if not entities:
            return {"synthesized": False, "new_beliefs": 0, "total_beliefs": len(self._beliefs)}

        self._total_observations += 1
        ent_strs = [str(e) for e in entities]

        # Update frequencies
        for ent in ent_strs:
            self._entity_freq[ent] += 1

        # Update co-occurrence for all pairs
        for i in range(len(ent_strs)):
            for j in range(i + 1, len(ent_strs)):
                pair = tuple(sorted([ent_strs[i], ent_strs[j]]))
                self._co_occurrence[pair] += 1

        # Synthesize beliefs
        new_beliefs = []
        for pair, count in self._co_occurrence.most_common(20):
            if count < 2:
                continue

            e1_freq = self._entity_freq[pair[0]]
            e2_freq = self._entity_freq[pair[1]]

            # Compute PMI
            p_pair = count / max(self._total_observations, 1)
            p_e1 = e1_freq / max(self._total_observations, 1)
            p_e2 = e2_freq / max(self._total_observations, 1)

            if p_e1 * p_e2 > 0:
                pmi = math.log2(p_pair / (p_e1 * p_e2))
            else:
                pmi = 0.0

            if pmi >= self._min_pmi:
                confidence = min(1.0, pmi / 5.0)
                belief = Belief(
                    entities=list(pair),
                    confidence=confidence,
                    evidence_count=count,
                    pmi=pmi,
                    context=context,
                )
                new_beliefs.append(belief)

                if len(self._beliefs) < self._max_beliefs:
                    self._beliefs.append(belief)

        return {
            "synthesized": len(new_beliefs) > 0,
            "new_beliefs": len(new_beliefs),
            "total_beliefs": len(self._beliefs),
        }

    def get_beliefs(self, min_confidence: float = 0.3) -> list[Belief]:
        """Get beliefs above confidence threshold."""
        return [b for b in self._beliefs if b.confidence >= min_confidence]

    def get_entity_stats(self) -> dict[str, int]:
        """Get entity frequency statistics."""
        return dict(self._entity_freq.most_common(20))

    def get_co_occurrence_stats(self) -> dict[str, int]:
        """Get co-occurrence statistics."""
        return dict(self._co_occurrence.most_common(20))

    def get_stats(self) -> dict:
        return {
            "beliefs": len(self._beliefs),
            "entities_tracked": len(self._entity_freq),
            "co_occurrences": len(self._co_occurrence),
            "total_observations": self._total_observations,
        }
