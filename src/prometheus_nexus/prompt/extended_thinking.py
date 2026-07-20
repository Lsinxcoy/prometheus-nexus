"""ExtendedThinking — Recursive decomposition with semantic reasoning.

Based on: "Claude Extended Thinking" (Anthropic, 2025)

Key Concepts:
    1. Model performs internal reasoning before responding
    2. Structured thinking traces improve complex problem solving
    3. Depth-controlled recursion prevents infinite loops
    4. Each thought is evaluated for relevance and quality

Enhanced with:
- Semantic scoring of thoughts
- Pruning of low-relevance branches
- Confidence estimation
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import re
from dataclasses import dataclass, field


@dataclass
class ThoughtNode:
    content: str = ""
    depth: int = 0
    score: float = 0.0
    confidence: float = 0.0
    sub_thoughts: list[ThoughtNode] = field(default_factory=list)
    conclusion: str = ""


class ExtendedThinking:
    """Extended thinking with semantic reasoning.

    Based on Anthropic's Extended Thinking (2025).

    Usage:
        et = ExtendedThinking(max_depth=4, prune_threshold=0.2)
        result = et.think({"context": "How does photosynthesis work?"})
        print(f"Thought tree depth: {result['depth']}")
    """

    def __init__(self, max_depth: int = 5, prune_threshold: float = 0.2):
        self._max_depth = max_depth
        self._prune_threshold = prune_threshold
        self._thoughts: list[dict] = []
        self._total_thoughts = 0
        self._pruned = 0

    def think(self, context: dict | None = None, depth: int = 0) -> dict:
        ctx = context or {}
        thought = {"depth": depth, "context_keys": list(ctx.keys()), "sub_thoughts": []}

        if depth >= self._max_depth:
            thought["conclusion"] = "max_depth_reached"
            thought["confidence"] = 0.3
            self._thoughts.append(thought)
            return thought

        if "context" in ctx:
            text = ctx["context"]
            score = self._score_thought(text, depth)
            thought["score"] = score

            if score < self._prune_threshold and depth > 0:
                self._pruned += 1
                thought["conclusion"] = "pruned_low_relevance"
                thought["confidence"] = 0.1
                self._thoughts.append(thought)
                return thought

            sub_contexts = self._decompose(text)
            for sub_ctx in sub_contexts[:3]:
                self._total_thoughts += 1
                sub_thought = self.think({"context": sub_ctx, **ctx}, depth + 1)
                thought["sub_thoughts"].append(sub_thought)

            avg_child_score = (
                sum(st.get("score", 0) for st in thought["sub_thoughts"]) /
                max(len(thought["sub_thoughts"]), 1)
            )
            thought["confidence"] = min(1.0, avg_child_score * 0.6 + score * 0.4)
            thought["conclusion"] = f"depth_{depth}_analyzed_{len(thought['sub_thoughts'])}_branches"
        else:
            thought["conclusion"] = "no_context"
            thought["confidence"] = 0.0

        self._thoughts.append(thought)
        return thought

    def _score_thought(self, text: str, depth: int) -> float:
        words = text.split()
        length_score = min(1.0, len(words) / 20)

        question_words = {"how", "why", "what", "when", "where", "which"}
        has_question = any(w.lower() in question_words for w in words)
        question_bonus = 0.2 if has_question else 0.0

        causal_words = {"because", "therefore", "however", "consequently", "thus"}
        has_causal = any(w.lower() in causal_words for w in words)
        causal_bonus = 0.15 if has_causal else 0.0

        depth_penalty = depth * 0.05

        score = length_score * 0.4 + question_bonus + causal_bonus - depth_penalty
        return max(0.0, min(1.0, score))

    def _decompose(self, text: str) -> list[str]:
        sentences = re.split(r'[.!?]+', text)
        sentences = [s.strip() for s in sentences if s.strip()]

        if len(sentences) <= 1:
            words = text.split()
            if len(words) <= 5:
                return [text]
            chunk_size = max(3, len(words) // 3)
            return [" ".join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size)]

        return sentences

    def get_thought_tree(self) -> list[dict]:
        return self._thoughts

    def get_stats(self) -> dict:
        max_depth = max((t.get("depth", 0) for t in self._thoughts), default=0)
        avg_confidence = (
            sum(t.get("confidence", 0) for t in self._thoughts) /
            max(len(self._thoughts), 1)
        )
        return {
            "total_thoughts": self._total_thoughts,
            "max_depth": max_depth,
            "avg_confidence": avg_confidence,
            "pruned": self._pruned,
        }
