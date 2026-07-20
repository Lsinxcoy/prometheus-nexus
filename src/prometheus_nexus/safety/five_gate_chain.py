"""FiveGateMemoryChain — Five-gate memory governance chain.

Based on: MiMo Full Knowledge #20 (五重门控理论)

Five gates in sequence:
    1. Write Gate (SAGE novelty) — accept/reject new memories
    2. Read Gate (MemGate trust) — filter retrieval by trust
    3. Modify Gate (SkillAdaptor delta>=0) — only allow beneficial modifications
    4. Consolidate Gate (Nautilus drift) — detect drift before merging
    5. Execute Gate (AURA-Mem action) — pre-action interception
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import math
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class FiveGateResult:
    gate_name: str = ""
    passed: bool = True
    confidence: float = 1.0
    reason: str = ""


class FiveGateMemoryChain:
    """Five-gate memory governance chain.

    Based on MiMo Knowledge #20 (五重门控理论).
    Implements vMF-inspired novelty filtering for the write gate.
    """

    def __init__(self):
        self._stats = {
            "write_checked": 0, "write_passed": 0,
            "read_checked": 0, "read_passed": 0,
            "modify_checked": 0, "modify_passed": 0,
            "consolidate_checked": 0, "consolidate_passed": 0,
            "execute_checked": 0, "execute_passed": 0,
        }
        self._history: list[dict] = []
        self._seen_content: list[set[str]] = []
        self._concentration = 2.0

    def write_gate(self, content: str, utility: float = 0.5,
                   novelty: float = 0.5) -> FiveGateResult:
        """Gate 1: SAGE vMF novelty filtering.

        Uses von Mises-Fisher inspired concentration scoring:
        - Content with rare words gets higher novelty
        - Repeated content patterns get lower novelty
        """
        self._stats["write_checked"] += 1

        words = set(content.lower().split())
        word_freq = Counter()
        for seen in self._seen_content[-100:]:
            for w in words:
                if w in seen:
                    word_freq[w] += 1

        total_seen = max(len(self._seen_content), 1)
        novelty_score = 0.0
        for w in words:
            freq = word_freq.get(w, 0) / total_seen
            novelty_score += 1.0 - min(1.0, freq)

        if words:
            novelty_score /= len(words)

        novelty_score = novelty_score * 0.7 + novelty * 0.3

        score = utility * 0.5 + novelty_score * 0.5
        passed = score >= 0.3

        self._seen_content.append(words)
        if len(self._seen_content) > 200:
            self._seen_content = self._seen_content[-100:]

        if passed:
            self._stats["write_passed"] += 1

        return FiveGateResult(
            gate_name="write_gate",
            passed=passed,
            confidence=score,
            reason="score=%.3f (util=%.2f, vmf_novelty=%.3f)" % (score, utility, novelty_score),
        )

    def read_gate(self, query: str, trust_score: float = 0.5,
                  source_reliability: float = 0.5) -> FiveGateResult:
        """Gate 2: MemGate trust filtering."""
        self._stats["read_checked"] += 1

        score = trust_score * 0.5 + source_reliability * 0.5
        passed = score >= 0.2

        if passed:
            self._stats["read_passed"] += 1

        return FiveGateResult(
            gate_name="read_gate",
            passed=passed,
            confidence=score,
            reason="trust=%.2f, source=%.2f" % (trust_score, source_reliability),
        )

    def modify_gate(self, content: str, delta: float = 0.0) -> FiveGateResult:
        """Gate 3: SkillAdaptor delta>=0."""
        self._stats["modify_checked"] += 1

        passed = delta >= 0

        if passed:
            self._stats["modify_passed"] += 1

        return FiveGateResult(
            gate_name="modify_gate",
            passed=passed,
            confidence=max(0, delta),
            reason="delta=%.3f (must be >= 0)" % delta,
        )

    def consolidate_gate(self, content: str, drift_score: float = 0.0,
                         age_hours: float = 0.0) -> FiveGateResult:
        """Gate 4: Nautilus drift detection."""
        self._stats["consolidate_checked"] += 1

        age_factor = min(1.0, age_hours / 168)
        drift_threshold = 0.3 + age_factor * 0.2
        passed = drift_score < drift_threshold

        if passed:
            self._stats["consolidate_passed"] += 1

        return FiveGateResult(
            gate_name="consolidate_gate",
            passed=passed,
            confidence=1.0 - drift_score,
            reason="drift=%.3f, threshold=%.3f" % (drift_score, drift_threshold),
        )

    def execute_gate(self, action: str, risk_level: float = 0.5,
                     user_approval: bool = False) -> FiveGateResult:
        """Gate 5: AURA-Mem action gating."""
        self._stats["execute_checked"] += 1

        if risk_level > 0.7 and not user_approval:
            passed = False
            reason = "high risk (%.2f) without approval" % risk_level
        elif risk_level > 0.5 and not user_approval:
            passed = True
            reason = "medium risk (%.2f), logged" % risk_level
        else:
            passed = True
            reason = "low risk or approved"

        if passed:
            self._stats["execute_passed"] += 1

        return FiveGateResult(
            gate_name="execute_gate",
            passed=passed,
            confidence=1.0 - risk_level,
            reason=reason,
        )

    def check_all(self, content: str, utility: float = 0.5, novelty: float = 0.5,
                  trust_score: float = 0.5, delta: float = 0.0,
                  drift_score: float = 0.0, risk_level: float = 0.3) -> list[FiveGateResult]:
        results = []

        r1 = self.write_gate(content, utility, novelty)
        results.append(r1)
        if not r1.passed:
            return results

        r2 = self.read_gate(content, trust_score)
        results.append(r2)
        if not r2.passed:
            return results

        r3 = self.modify_gate(content, delta)
        results.append(r3)
        if not r3.passed:
            return results

        r4 = self.consolidate_gate(content, drift_score)
        results.append(r4)
        if not r4.passed:
            return results

        r5 = self.execute_gate(content, risk_level)
        results.append(r5)

        self._history.append({
            "passed": all(r.passed for r in results),
            "gates_passed": sum(1 for r in results if r.passed),
        })

        return results

    def get_stats(self) -> dict:
        return dict(self._stats)
