"""SemanticEarlyStopping — Embedding-based loop termination.

Based on: "Semantic Early-Stopping for Iterative LLM Agent Loops"
(arXiv:2606.27009, Shrivastava 2026)

Key insight: cosine distance between consecutive drafts with patience window.
Judge-free variant reduces tokens by 38% at parity quality.
Quality-gated variant is counter-productive (judging cost dominates).
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

from collections import Counter
from dataclasses import dataclass, field
import math


@dataclass
class StopDecision:
    should_stop: bool = False
    reason: str = ""
    cosine_distance: float = 0.0
    patience_remaining: int = 0


class SemanticEarlyStopping:
    """Embedding-based early stopping for iterative loops.

    Uses character-level 3-gram vectors to approximate embedding cosine
    distance without requiring a real embedding model.

    Usage:
        ses = SemanticEarlyStopping(patience=3, threshold=0.01)
        for i in range(max_iterations):
            output = generate_response()
            decision = ses.check(output)
            if decision.should_stop:
                break
    """

    def __init__(self, patience: int = 3, threshold: float = 0.01):
        self._patience = patience
        self._threshold = threshold
        self._history: list[str] = []
        self._history_vectors: list[Counter] = []
        self._unchanged_count = 0
        self._stats = {"checks": 0, "stops": 0}

    def check(self, current_output: str) -> StopDecision:
        self._stats["checks"] += 1

        current_vec = self._text_to_vector(current_output)

        if not self._history:
            self._history.append(current_output)
            self._history_vectors.append(current_vec)
            return StopDecision(reason="first_output")

        prev_vec = self._history_vectors[-1]
        distance = self._cosine_distance(current_vec, prev_vec)

        if distance < self._threshold:
            self._unchanged_count += 1
        else:
            self._unchanged_count = 0

        self._history.append(current_output)
        self._history_vectors.append(current_vec)
        if len(self._history) > 50:
            self._history = self._history[-25:]
            self._history_vectors = self._history_vectors[-25:]

        should_stop = self._unchanged_count >= self._patience
        if should_stop:
            self._stats["stops"] += 1

        return StopDecision(
            should_stop=should_stop,
            reason="unchanged_%d/%d" % (self._unchanged_count, self._patience),
            cosine_distance=distance,
            patience_remaining=max(0, self._patience - self._unchanged_count),
        )

    def _text_to_vector(self, text: str) -> Counter:
        text = text.lower().strip()
        trigrams = Counter()
        for i in range(max(0, len(text) - 2)):
            trigram = text[i:i + 3]
            trigrams[trigram] += 1
        return trigrams

    def _cosine_distance(self, vec_a: Counter, vec_b: Counter) -> float:
        if not vec_a or not vec_b:
            return 1.0

        common_keys = set(vec_a.keys()) & set(vec_b.keys())
        dot_product = sum(vec_a[k] * vec_b[k] for k in common_keys)

        norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
        norm_b = math.sqrt(sum(v * v for v in vec_b.values()))

        if norm_a == 0 or norm_b == 0:
            return 1.0

        cosine_sim = dot_product / (norm_a * norm_b)
        return 1.0 - max(0.0, min(1.0, cosine_sim))

    def reset(self):
        self._history.clear()
        self._history_vectors.clear()
        self._unchanged_count = 0

    def get_stats(self) -> dict:
        return dict(self._stats)
