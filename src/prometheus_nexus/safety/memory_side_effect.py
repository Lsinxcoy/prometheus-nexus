"""MemorySideEffectDetector — Detects unintended side effects from memory retrieval.

Based on: "Six Months in LLMs" (Simon Willison, 2025)

Key Finding:
    ChatGPT retrieved location info from memory and injected it into
    image generation without user intent. Memory retrieval can cause
    unexpected information leakage across contexts.

Algorithm:
    1. Track what information enters context from memory
    2. Detect when retrieved info is unrelated to current task
    3. Flag potential privacy leakage
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


from dataclasses import dataclass, field


@dataclass
class SideEffect:
    retrieved_content: str = ""
    task_context: str = ""
    relevance_score: float = 0.0
    is_unexpected: bool = False
    severity: str = "low"


class MemorySideEffectDetector:
    """Detects unintended side effects from memory retrieval.

    Usage:
        detector = MemorySideEffectDetector(relevance_threshold=0.2)
        detector.set_current_task("Generate an image of a sunset")
        detector.observe_retrieval("User lives in New York City")
        effects = detector.detect()
    """

    def __init__(self, relevance_threshold: float = 0.3):
        self._threshold = relevance_threshold
        self._current_task = ""
        self._retrievals: list[str] = []
        self._effects: list[SideEffect] = []

    def set_current_task(self, task: str):
        self._current_task = task

    def observe_retrieval(self, content: str):
        self._retrievals.append(content)
        if len(self._retrievals) > 100:
            self._retrievals = self._retrievals[-50:]

        if self._current_task:
            relevance = self._compute_relevance(content, self._current_task)
            is_unexpected = relevance < self._threshold and len(content) > 10
            if is_unexpected:
                severity = "high" if relevance < 0.1 else "medium" if relevance < 0.2 else "low"
                self._effects.append(SideEffect(
                    retrieved_content=content[:100],
                    task_context=self._current_task[:100],
                    relevance_score=relevance,
                    is_unexpected=True,
                    severity=severity,
                ))

    def _compute_relevance(self, content: str, task: str) -> float:
        content_words = set(content.lower().split())
        task_words = set(task.lower().split())
        overlap = content_words & task_words
        if not task_words:
            return 0.5
        return len(overlap) / len(task_words)

    def detect(self) -> list[SideEffect]:
        return [e for e in self._effects if e.is_unexpected]

    def get_stats(self) -> dict:
        return {
            "total_retrievals": len(self._retrievals),
            "side_effects": len(self._effects),
            "high_severity": sum(1 for e in self._effects if e.severity == "high"),
        }
