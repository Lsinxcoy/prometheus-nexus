"""ContextPoisoningDetector — Detects hallucination contamination in context.

Based on: "Gemini 2.5 Technical Report" (Google DeepMind, 2025)

Key Finding:
    In Pokémon gameplay, hallucinated location data entered the context
    and was repeatedly cited by the agent, leading to pursuit of
    impossible goals. >100k tokens caused degradation to replaying
    historical behavior.

Algorithm:
    1. Track content chunks entering context
    2. Mark chunks with hallucination probability scores
    3. Detect repeated citation of low-confidence content
    4. Compute poisoning severity: frequency × recency × confidence_inverse
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


from dataclasses import dataclass, field
from collections import Counter


@dataclass
class ContentChunk:
    content: str = ""
    confidence: float = 1.0
    citation_count: int = 0
    is_marked: bool = False


@dataclass
class PoisoningReport:
    is_poisoned: bool = False
    severity: float = 0.0
    poisoned_chunks: list[dict] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


class ContextPoisoningDetector:
    """Detects hallucination contamination in context.

    Based on Gemini 2.5 Report's context poisoning observation.

    Usage:
        detector = ContextPoisoningDetector(confidence_threshold=0.3)
        detector.add_chunk("Paris is the capital of France", confidence=0.95)
        detector.add_chunk("Atlantis is in the Atlantic", confidence=0.1)
        detector.mark_as_cited("Atlantis is in the Atlantic")
        report = detector.detect()
    """

    def __init__(self, confidence_threshold: float = 0.3,
                 citation_threshold: int = 2):
        self._threshold = confidence_threshold
        self._citation_threshold = citation_threshold
        self._chunks: list[ContentChunk] = []
        self._citation_history: list[str] = []
        self._reports: list[dict] = []

    def add_chunk(self, content: str, confidence: float = 1.0):
        chunk = ContentChunk(
            content=content[:200],
            confidence=confidence,
            is_marked=confidence < self._threshold,
        )
        self._chunks.append(chunk)
        if len(self._chunks) > 500:
            self._chunks = self._chunks[-300:]

    def mark_as_cited(self, content: str):
        self._citation_history.append(content[:50])
        for chunk in self._chunks:
            if content[:50] in chunk.content[:50]:
                chunk.citation_count += 1

    def detect(self) -> PoisoningReport:
        poisoned = []
        for chunk in self._chunks:
            if chunk.confidence < self._threshold and chunk.citation_count >= self._citation_threshold:
                severity = (1.0 - chunk.confidence) * min(1.0, chunk.citation_count / 5)
                poisoned.append({
                    "content": chunk.content,
                    "confidence": chunk.confidence,
                    "citations": chunk.citation_count,
                    "severity": severity,
                })

        total_severity = sum(p["severity"] for p in poisoned)
        max_severity = max((p["severity"] for p in poisoned), default=0)
        overall = max_severity * 0.6 + min(1.0, total_severity / max(len(poisoned), 1)) * 0.4

        recommendations = []
        if poisoned:
            recommendations.append(f"Found {len(poisoned)} poisoned chunks — remove or quarantine them")
            if overall > 0.7:
                recommendations.append("Severe poisoning detected — consider context reset")
            for p in poisoned[:3]:
                recommendations.append(f"Low-confidence content cited {p['citations']}x: '{p['content'][:60]}'")

        report = PoisoningReport(
            is_poisoned=overall > 0.3,
            severity=overall,
            poisoned_chunks=poisoned,
            recommendations=recommendations,
        )

        self._reports.append({"poisoned": len(poisoned), "severity": overall})
        return report

    def get_stats(self) -> dict:
        low_conf = sum(1 for c in self._chunks if c.confidence < self._threshold)
        return {
            "total_chunks": len(self._chunks),
            "low_confidence_chunks": low_conf,
            "total_reports": len(self._reports),
        }
