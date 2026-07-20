"""ContextFailureDetector — Detects 4 context failure modes.

Based on: "How Long Contexts Fail" (Drew Breunig, 2025)
and "Gemini 2.5 Technical Report" (Google DeepMind, 2025)

Four Failure Modes:
    1. Poisoning: Hallucinations enter context and get repeatedly cited
    2. Distraction: Too long context causes model to ignore training knowledge
    3. Confusion: Irrelevant information interferes with output
    4. Clash: Information in context contradicts each other

Algorithm:
    For each failure mode, maintain a detector:
        PoisoningDetector: track hallucination markers + citation frequency
        DistractionDetector: monitor context length vs output quality
        ConfusionDetector: measure signal-to-noise ratio
        ClashDetector: detect semantic contradictions between segments

    Composite score combines all four detectors.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import re
from dataclasses import dataclass, field
from collections import Counter


@dataclass
class FailureReport:
    """Report of detected context failures."""
    has_failure: bool = False
    primary_mode: str = "none"
    severity: float = 0.0
    mode_scores: dict[str, float] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


class PoisoningDetector:
    """Detects hallucination poisoning in context."""

    def __init__(self):
        self._markers: Counter = Counter()
        self._citations: Counter = Counter()

    def observe(self, text: str, is_hallucination: bool = False):
        if is_hallucination:
            key = text[:50].lower()
            self._markers[key] += 1
        words = text.split()
        for w in words:
            if len(w) > 5:
                self._citations[w.lower()] += 1

    def detect(self) -> float:
        if not self._markers:
            return 0.0
        repeated = sum(1 for count in self._markers.values() if count > 2)
        total_markers = len(self._markers)
        return min(1.0, repeated / max(total_markers, 1) * 2)

    def get_repeated_hallucinations(self) -> list[dict]:
        return [{"marker": m, "count": c} for m, c in self._markers.most_common(5) if c > 1]


class DistractionDetector:
    """Detects context length causing distraction."""

    def __init__(self, optimal_tokens: int = 32000):
        self._optimal = optimal_tokens
        self._lengths: list[int] = []
        self._qualities: list[float] = []

    def observe(self, context_length: int, output_quality: float):
        self._lengths.append(context_length)
        self._qualities.append(output_quality)
        if len(self._lengths) > 200:
            self._lengths = self._lengths[-100:]
            self._qualities = self._qualities[-100:]

    def detect(self) -> float:
        if len(self._lengths) < 5:
            return 0.0
        over_optimal = sum(1 for l in self._lengths[-10:] if l > self._optimal)
        ratio = over_optimal / min(len(self._lengths), 10)
        if len(self._qualities) >= 5:
            recent_quality = sum(self._qualities[-5:]) / 5
            older_quality = sum(self._qualities[-10:-5]) / max(len(self._qualities[-10:-5]), 1)
            if recent_quality < older_quality * 0.8:
                ratio = min(1.0, ratio + 0.3)
        return min(1.0, ratio)


class ConfusionDetector:
    """Detects irrelevant information confusing the model."""

    def __init__(self):
        self._topic_words: Counter = Counter()
        self._noise_words: Counter = Counter()

    def observe(self, topic: str, context: str):
        topic_words = set(topic.lower().split())
        context_words = set(context.lower().split())
        overlap = topic_words & context_words
        self._topic_words.update(overlap)
        noise = context_words - topic_words
        self._noise_words.update(noise)

    def detect(self) -> float:
        if not self._topic_words:
            return 0.0
        total = sum(self._topic_words.values()) + sum(self._noise_words.values())
        if total == 0:
            return 0.0
        noise_ratio = sum(self._noise_words.values()) / total
        return min(1.0, noise_ratio * 1.5)


class ContextFailureDetector:
    """Detects 4 context failure modes.

    Based on "How Long Contexts Fail" (Breunig 2025).

    Usage:
        detector = ContextFailureDetector()
        detector.observe_poisoning("The capital is Paris", is_hallucination=False)
        detector.observe_poisoning("The capital is London", is_hallucination=True)
        detector.observe_distraction(50000, 0.6)
        detector.observe_confusion("geography", "The weather is nice today")
        report = detector.detect()
    """

    def __init__(self):
        self._poisoning = PoisoningDetector()
        self._distraction = DistractionDetector()
        self._confusion = ConfusionDetector()
        self._clash_detector = _ClashDetector()
        self._reports: list[FailureReport] = []

    def observe_poisoning(self, text: str, is_hallucination: bool = False):
        self._poisoning.observe(text, is_hallucination)

    def observe_distraction(self, context_length: int, output_quality: float):
        self._distraction.observe(context_length, output_quality)

    def observe_confusion(self, topic: str, context: str):
        self._confusion.observe(topic, context)

    def observe_clash(self, chunks: list[str]):
        self._clash_detector.observe(chunks)

    def detect(self) -> FailureReport:
        scores = {
            "poisoning": self._poisoning.detect(),
            "distraction": self._distraction.detect(),
            "confusion": self._confusion.detect(),
            "clash": self._clash_detector.detect(),
        }

        evidence = []
        recommendations = []
        max_mode = max(scores, key=scores.get) if scores else "none"
        max_score = scores[max_mode] if scores else 0

        if scores["poisoning"] > 0.3:
            repeated = self._poisoning.get_repeated_hallucinations()
            evidence.append(f"Poisoning: {len(repeated)} repeated hallucination markers")
            recommendations.append("Remove repeated hallucinated content from context")
        if scores["distraction"] > 0.3:
            evidence.append(f"Distraction: context exceeding optimal length")
            recommendations.append("Compress context or use context isolation")
        if scores["confusion"] > 0.3:
            evidence.append(f"Confusion: high noise-to-signal ratio")
            recommendations.append("Filter irrelevant content from context")
        if scores["clash"] > 0.3:
            evidence.append(f"Clash: contradicting information detected")
            recommendations.append("Resolve contradictions before proceeding")

        severity = max(scores.values()) if scores else 0
        composite = sum(scores.values()) / max(len(scores), 1)

        report = FailureReport(
            has_failure=composite > 0.2,
            primary_mode=max_mode if max_score > 0.3 else "none",
            severity=composite,
            mode_scores=scores,
            evidence=evidence,
            recommendations=recommendations,
        )

        self._reports.append(report)
        return report

    def get_stats(self) -> dict:
        failures = [r for r in self._reports if r.has_failure]
        return {
            "total_detections": len(self._reports),
            "failures_found": len(failures),
            "primary_modes": dict(Counter(r.primary_mode for r in failures)),
        }


class _ClashDetector:
    def __init__(self):
        self._chunks: list[list[str]] = []

    def observe(self, chunks: list[str]):
        self._chunks.append(chunks)

    def detect(self) -> float:
        if not self._chunks:
            return 0.0
        total_clashes = 0
        total_pairs = 0
        negation_pairs = [("is", "is not"), ("can", "cannot"), ("will", "will not"),
                          ("true", "false"), ("yes", "no")]
        for chunks in self._chunks:
            for i in range(len(chunks)):
                for j in range(i + 1, len(chunks)):
                    total_pairs += 1
                    a, b = chunks[i].lower(), chunks[j].lower()
                    for pos, neg in negation_pairs:
                        if (pos in a and neg in b) or (neg in a and pos in b):
                            shared = set(a.split()) & set(b.split())
                            if len(shared) > 2:
                                total_clashes += 1
                                break
        return min(1.0, total_clashes / max(total_pairs, 1) * 3)
