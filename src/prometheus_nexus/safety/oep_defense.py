"""OEPDefense — Memory poisoning defense.

Based on: MiMo Full Knowledge #19 (OEP 巩固毒化)

Key concepts:
    - Self-evolving agents can be poisoned through consolidation
    - Attackers inject "correct but non-transferable" experiences
    - GPT-4o ASR > 50% against undefended systems
    - Smarter agents are more vulnerable (capability-vulnerability paradox)
    - Defense: source diversity check + transferability verification
      + separate observation from rule formation
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


from dataclasses import dataclass, field
from collections import Counter


@dataclass
class PoisoningAlert:
    severity: str = "low"  # low, medium, high, critical
    source_check: bool = True
    transferability_check: bool = True
    observation_separation: bool = True
    confidence: float = 0.0
    detail: str = ""


class OEPDefense:
    """Memory poisoning defense system.

    Based on MiMo Knowledge #19 (OEP 巩固毒化).

    Usage:
        defense = OEPDefense()
        alert = defense.check(
            memory_content="AI always works perfectly",
            source="user_input",
            transferable=True,
        )
        if alert.severity == "critical":
            block_consolidation()
    """

    def __init__(self):
        self._source_history: dict[str, list[str]] = {}
        self._alerts: list[PoisoningAlert] = []
        self._stats = {"checked": 0, "blocked": 0}
        self._content_hashes: list[tuple[str, str]] = []

    def check(self, memory_content: str, source: str = "unknown",
              transferable: bool = True, similar_count: int = 0) -> PoisoningAlert:
        """Check for OEP poisoning patterns.

        Defense layers:
        1. Source diversity: single-source memories are suspicious
        2. Transferability: non-transferable local experiences are risky
        3. Observation separation: observation vs rule formation
        4. Semantic repetition: identical/near-identical content injection
        """
        self._stats["checked"] += 1
        severity = "low"
        details = []

        # Layer 1: Source diversity
        self._source_history.setdefault(source, []).append(memory_content[:50])
        source_count = len(self._source_history[source])
        source_check = source_count >= 2
        if not source_check:
            severity = "medium"
            details.append("single_source_risk")

        # Layer 2: Transferability check
        if similar_count > 3 and not transferable:
            severity = "high"
            details.append("non_transferable_pattern")

        # Layer 3: Observation vs rule separation
        has_observation = any(w in memory_content.lower() for w in
                             ["observed", "saw", "noticed", "measured"])
        has_rule = any(w in memory_content.lower() for w in
                      ["always", "never", "must", "should", "rule"])
        observation_separation = not (has_observation and has_rule)
        if not observation_separation:
            severity = "medium"
            details.append("observation_rule_mix")

        # Layer 4: Semantic repetition detection
        content_words = set(memory_content.lower().split())
        for prev_content, prev_source in self._content_hashes[-20:]:
            prev_words = set(prev_content.split())
            if content_words and prev_words:
                overlap = len(content_words & prev_words) / max(len(content_words | prev_words), 1)
                if overlap > 0.8:
                    severity = "high"
                    details.append("near_duplicate_injection")
                    break
        self._content_hashes.append((memory_content[:200], source))
        if len(self._content_hashes) > 100:
            self._content_hashes = self._content_hashes[-50:]

        if severity in ("high", "critical"):
            self._stats["blocked"] += 1

        alert = PoisoningAlert(
            severity=severity,
            source_check=source_check,
            transferability_check=transferable,
            observation_separation=observation_separation,
            confidence=0.8 if severity == "high" else 0.5,
            detail="; ".join(details) if details else "clean",
        )
        self._alerts.append(alert)
        return alert

    def get_stats(self) -> dict:
        return dict(self._stats)
