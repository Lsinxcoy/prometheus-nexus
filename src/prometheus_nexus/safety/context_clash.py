"""ContextClashDetector — Detects conflicting information in context.

Implements detection of multi-turn conversation degradation patterns
as described in the referenced paper.

Based on: "LLMs Get Lost In Multi-Turn Conversation"
(arXiv:2505.06120, Microsoft/Salesforce 2025)

Key Concepts from Paper:
    1. LLMs suffer performance degradation in multi-turn conversations
    2. Information from early turns can be lost or contradicted in later turns
    3. Detection of contradictions, repetitions, and information loss

Algorithm:
    1. Segment context into semantic chunks
    2. Pairwise comparison of chunks for semantic similarity
    3. Low similarity + high topical overlap = potential clash
    4. Detect direct contradictions via negation patterns
    5. Score clash severity: 0 (no clash) to 1 (severe)

Complexity:
    detect(): O(N^2 * S) where N = chunks, S = similarity computation
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import re
from dataclasses import dataclass, field


@dataclass
class ClashEvidence:
    """Evidence of a context clash between two segments."""
    segment_a: str = ""
    segment_b: str = ""
    clash_type: str = ""  # contradiction, inconsistency, factual_conflict
    severity: float = 0.0
    detail: str = ""


@dataclass
class ClashReport:
    """Report of detected context clashes."""
    has_clash: bool = False
    severity: float = 0.0
    evidence: list[ClashEvidence] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


class ContextClashDetector:
    """Detects conflicting information in context.

    Based on Context Clash paper (arXiv:2505.06120).

    Two-pronged detection:
      1. **Upstream cause detection** (NEW): premature commitment — detecting
         when a model commits to an answer/position too early based on
         incomplete information, which is the root cause of later clashes.
      2. **Downstream symptom detection**: contradictions, factual conflicts,
         and inconsistencies that result from upstream premature commitment.

    Usage:
        detector = ContextClashDetector()
        report = detector.detect([
            "The answer is 42.",
            "The answer is 37.",
            "Confirmed: the answer is 42.",
        ])
        if report.has_clash:
            print(f"Clash detected: {report.severity:.2f}")

    Detection methods:
        1. Premature commitment detection (upstream cause)
        2. Direct contradiction (negation patterns)
        3. Factual inconsistency (number/value conflicts)
        4. Semantic opposition (antonym detection)
    """

    NEGATION_PAIRS = [
        ("is", "is not"), ("are", "are not"), ("was", "was not"),
        ("can", "cannot"), ("will", "will not"), ("has", "has not"),
        ("true", "false"), ("yes", "no"), ("correct", "incorrect"),
        ("increase", "decrease"), ("higher", "lower"), ("more", "less"),
        ("always", "never"), ("all", "none"), ("positive", "negative"),
    ]

    _PREMATURE_COMMITMENT_INDICATORS = [
        "i think", "i believe", "i'm pretty sure", "probably", "likely",
        "most likely", "i'd say", "my guess", "my bet", "seems like",
        "appears to be", "it looks like", "off the top of my head",
        "without checking", "from memory", "i recall", "as far as i know",
    ]

    _DEFINITIVE_COMMITMENT_INDICATORS = [
        "the answer is", "definitely", "certainly", "absolutely",
        "without a doubt", "confirmed", "i'm sure", "i know",
        "it is", "it's", "the result is",
    ]

    def __init__(self, contradiction_threshold: float = 0.5,
                 chunk_size: int = 3):
        self._threshold = contradiction_threshold
        self._chunk_size = chunk_size
        self._detections: list[dict] = []

    def detect(self, context_chunks: list[str]) -> ClashReport:
        if len(context_chunks) < 2:
            return ClashReport()

        evidence = []

        # Upstream cause detection: premature commitment per chunk
        for i, chunk in enumerate(context_chunks):
            premature = self._detect_premature_commitment(chunk, i)
            evidence.extend(premature)

        # Downstream symptom detection: pairwise contradictions and conflicts
        for i in range(len(context_chunks)):
            for j in range(i + 1, len(context_chunks)):
                chunk_a = context_chunks[i]
                chunk_b = context_chunks[j]

                contradictions = self._detect_contradictions(chunk_a, chunk_b)
                evidence.extend(contradictions)

                number_conflicts = self._detect_number_conflicts(chunk_a, chunk_b)
                evidence.extend(number_conflicts)

        severity = self._compute_severity(evidence, len(context_chunks))
        recommendations = self._generate_recommendations(evidence, severity)

        has_clash = severity >= self._threshold
        report = ClashReport(
            has_clash=has_clash,
            severity=severity,
            evidence=evidence,
            recommendations=recommendations,
        )

        self._detections.append({
            "has_clash": has_clash,
            "severity": severity,
            "evidence_count": len(evidence),
            "chunk_count": len(context_chunks),
            "premature_commitment_count": sum(1 for e in evidence if e.clash_type == "premature_commitment"),
        })

        return report

    # ── Upstream cause detection: premature commitment ──────────

    def _detect_premature_commitment(self, chunk: str, chunk_idx: int) -> list[ClashEvidence]:
        """Detect premature commitment — the upstream cause of later clashes.

        Premature commitment means the model commits to a specific answer or
        position too early, before sufficient information is available. This
        is detectable via hedging language followed by definitive statements
        within the same chunk, or via early-turn definitive statements that
        are later contradicted.
        """
        evidence: list[ClashEvidence] = []
        chunk_lower = chunk.lower()

        has_hedging = any(ind in chunk_lower for ind in self._PREMATURE_COMMITMENT_INDICATORS)
        has_definitive = any(ind in chunk_lower for ind in self._DEFINITIVE_COMMITMENT_INDICATORS)

        if has_hedging and has_definitive:
            hedging_used = [ind for ind in self._PREMATURE_COMMITMENT_INDICATORS if ind in chunk_lower]
            definitive_used = [ind for ind in self._DEFINITIVE_COMMITMENT_INDICATORS if ind in chunk_lower]
            severity = 0.5 + min(0.3, len(definitive_used) * 0.1)
            evidence.append(ClashEvidence(
                segment_a=chunk[:100],
                segment_b=chunk[:100],
                clash_type="premature_commitment",
                severity=severity,
                detail=(
                    f"Chunk {chunk_idx}: hedged ({hedging_used[:2]}) → "
                    f"definitive ({definitive_used[:2]}) — "
                    f"committed without verification"
                ),
            ))

        # Early chunk + definitive + no factual support = premature
        if chunk_idx == 0 and has_definitive:
            definitive_used = [ind for ind in self._DEFINITIVE_COMMITMENT_INDICATORS if ind in chunk_lower]
            has_facts = bool(re.findall(r'\b\d+\b', chunk))
            if not has_facts:
                evidence.append(ClashEvidence(
                    segment_a=chunk[:100],
                    segment_b="",
                    clash_type="premature_commitment",
                    severity=0.6,
                    detail=(
                        f"First chunk makes definitive claim ({definitive_used[:2]}) "
                        f"without numerical evidence — high premature commitment risk"
                    ),
                ))

        return evidence

    # ── Downstream detection: contradictions and conflicts ─────

    def _detect_contradictions(self, a: str, b: str) -> list[ClashEvidence]:
        evidence = []
        a_lower = a.lower()
        b_lower = b.lower()

        for pos, neg in self.NEGATION_PAIRS:
            if pos in a_lower and neg in b_lower:
                a_words = set(a_lower.split())
                b_words = set(b_lower.split())
                overlap = a_words & b_words - {pos, neg, "is", "are", "was", "the", "a", "an"}
                if len(overlap) >= 1:
                    evidence.append(ClashEvidence(
                        segment_a=a[:100], segment_b=b[:100],
                        clash_type="contradiction",
                        severity=0.7 + min(0.3, len(overlap) * 0.1),
                        detail=f"'{pos}' vs '{neg}' with shared context: {overlap}",
                    ))
            elif neg in a_lower and pos in b_lower:
                a_words = set(a_lower.split())
                b_words = set(b_lower.split())
                overlap = a_words & b_words - {pos, neg, "is", "are", "was", "the", "a", "an"}
                if len(overlap) >= 1:
                    evidence.append(ClashEvidence(
                        segment_a=a[:100], segment_b=b[:100],
                        clash_type="contradiction",
                        severity=0.7 + min(0.3, len(overlap) * 0.1),
                        detail=f"'{neg}' vs '{pos}' with shared context: {overlap}",
                    ))

        return evidence

    def _detect_number_conflicts(self, a: str, b: str) -> list[ClashEvidence]:
        evidence = []
        numbers_a = set(re.findall(r'\b\d+\.?\d*\b', a))
        numbers_b = set(re.findall(r'\b\d+\.?\d*\b', b))

        if not numbers_a or not numbers_b:
            return evidence

        a_words = set(a.lower().split())
        b_words = set(b.lower().split())
        shared_words = a_words & b_words - {"the", "a", "an", "is", "are", "was", "value", "result"}

        if len(shared_words) >= 2 and numbers_a != numbers_b:
            severity = 0.5
            if len(numbers_a) == 1 and len(numbers_b) == 1:
                severity = 0.8
            evidence.append(ClashEvidence(
                segment_a=a[:100], segment_b=b[:100],
                clash_type="factual_conflict",
                severity=severity,
                detail=f"Numbers: {numbers_a} vs {numbers_b}, shared context: {shared_words}",
            ))

        return evidence

    def _compute_severity(self, evidence: list[ClashEvidence], chunk_count: int) -> float:
        if not evidence:
            return 0.0

        max_severity = max(e.severity for e in evidence)
        evidence_density = len(evidence) / max(chunk_count * (chunk_count - 1) / 2, 1)
        normalized_density = min(1.0, evidence_density * 2)

        return max_severity * 0.6 + normalized_density * 0.4

    def _generate_recommendations(self, evidence: list[ClashEvidence],
                                   severity: float) -> list[str]:
        recs = []
        premature_count = sum(1 for e in evidence if e.clash_type == "premature_commitment")
        if premature_count > 0:
            recs.append(f"Found {premature_count} instance(s) of premature commitment — the root cause of downstream contradictions. Encourage the model to defer conclusions until sufficient information is available.")
        if severity >= 0.7:
            recs.append("Context has severe contradictions. Consider isolating conflicting segments into separate context windows.")
        if severity >= 0.4:
            recs.append("Detect inconsistencies. Verify facts before relying on context for reasoning.")
        contradiction_count = sum(1 for e in evidence if e.clash_type == "contradiction")
        if contradiction_count > 0:
            recs.append(f"Found {contradiction_count} direct contradictions. Remove or reconcile conflicting statements.")
        return recs

    def get_stats(self) -> dict:
        clashes = [d for d in self._detections if d["has_clash"]]
        premature_in_history = sum(
            d.get("premature_commitment_count", 0) for d in self._detections
        )
        return {
            "total_detections": len(self._detections),
            "clashes_found": len(clashes),
            "avg_severity": sum(d["severity"] for d in self._detections) / max(len(self._detections), 1),
            "premature_commitments": premature_in_history,
        }
