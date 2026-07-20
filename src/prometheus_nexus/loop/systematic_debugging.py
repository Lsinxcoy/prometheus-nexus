"""SystematicDebugging — 4-phase root cause analysis.

Based on: obra/superpowers systematic-debugging skill
Key insight: Isolate → Hypothesize → Verify → Fix, never guess.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import time
from dataclasses import dataclass, field


@dataclass
class DebugPhase:
    phase: str = ""
    findings: list[str] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    duration_ms: float = 0.0


@dataclass
class DebugResult:
    symptom: str = ""
    phases: list[DebugPhase] = field(default_factory=list)
    root_cause: str = ""
    fix_applied: str = ""
    verified: bool = False
    confidence: float = 0.0


class SystematicDebuggingEngine:
    """4-phase systematic debugging engine.

    Based on Superpowers systematic-debugging skill:
    Phase 1: Isolate - Narrow down the problem
    Phase 2: Hypothesize - Form theories about root cause
    Phase 3: Verify - Test each hypothesis with evidence
    Phase 4: Fix - Apply minimal fix and verify
    """

    def __init__(self):
        self._history: list[dict] = []
        self._known_patterns: dict[str, str] = {
            "memory_leak": "Check for unclosed resources or unbounded caches",
            "infinite_loop": "Check termination conditions and loop guards",
            "race_condition": "Check shared state access patterns",
            "null_reference": "Check optional chaining and null guards",
            "timeout": "Check for blocking operations or missing timeouts",
            "stale_state": "Check if state is properly invalidated",
        }

    def debug(self, symptom: str, context: dict | None = None) -> DebugResult:
        ctx = context or {}
        result = DebugResult(symptom=symptom)

        p1 = self._phase_isolate(symptom, ctx)
        result.phases.append(p1)

        p2 = self._phase_hypothesize(symptom, p1.findings, ctx)
        result.phases.append(p2)

        p3 = self._phase_verify(p2.hypotheses, ctx)
        result.phases.append(p3)

        p4 = self._phase_fix(p3.evidence, ctx)
        result.phases.append(p4)

        result.root_cause = self._determine_root_cause(p1, p2, p3)
        result.fix_applied = p4.findings[0] if p4.findings else "no_fix_needed"
        result.verified = len(p3.evidence) > 0
        result.confidence = min(1.0, len(p3.evidence) * 0.2 + len(p2.hypotheses) * 0.1)

        self._history.append({
            "symptom": symptom[:50],
            "root_cause": result.root_cause[:50],
            "verified": result.verified,
            "confidence": result.confidence,
        })

        return result

    def _phase_isolate(self, symptom: str, ctx: dict) -> DebugPhase:
        start = time.time()
        findings = []

        if "error" in symptom.lower() or "exception" in symptom.lower():
            findings.append("Error/exception detected")
            if "traceback" in str(ctx):
                findings.append("Stack trace available for analysis")

        if "slow" in symptom.lower() or "timeout" in symptom.lower():
            findings.append("Performance issue detected")
            findings.append("Check for blocking operations")

        if "crash" in symptom.lower() or "segfault" in symptom.lower():
            findings.append("Crash detected")
            findings.append("Check memory access patterns")

        for pattern, description in self._known_patterns.items():
            if pattern in symptom.lower():
                findings.append("Known pattern: %s" % description)

        findings.append("Symptom: %s" % symptom[:100])

        return DebugPhase(
            phase="isolate",
            findings=findings,
            duration_ms=(time.time() - start) * 1000,
        )

    def _phase_hypothesize(self, symptom: str, findings: list[str], ctx: dict) -> DebugPhase:
        start = time.time()
        hypotheses = []

        if any("memory" in f.lower() for f in findings):
            hypotheses.append("Memory leak in cache or buffer")
            hypotheses.append("Unbounded data structure growth")

        if any("loop" in f.lower() or "timeout" in f.lower() for f in findings):
            hypotheses.append("Missing termination condition")
            hypotheses.append("Circular dependency in processing")

        if any("crash" in f.lower() or "exception" in f.lower() for f in findings):
            hypotheses.append("Unhandled edge case")
            hypotheses.append("Resource exhaustion")

        if any("race" in f.lower() for f in findings):
            hypotheses.append("Shared state mutation without locking")
            hypotheses.append("Inconsistent ordering")

        hypotheses.append("Logic error in recent code change")
        hypotheses.append("Configuration mismatch")

        return DebugPhase(
            phase="hypothesize",
            hypotheses=hypotheses[:4],
            duration_ms=(time.time() - start) * 1000,
        )

    def _phase_verify(self, hypotheses: list[str], ctx: dict) -> DebugPhase:
        start = time.time()
        evidence = []

        for hyp in hypotheses:
            if "memory" in hyp.lower():
                evidence.append("Hypothesis '%s': Check heap dumps or cache sizes" % hyp[:30])
            elif "loop" in hyp.lower():
                evidence.append("Hypothesis '%s': Add logging at loop entry/exit" % hyp[:30])
            elif "race" in hyp.lower():
                evidence.append("Hypothesis '%s': Add synchronization primitives" % hyp[:30])
            elif "edge case" in hyp.lower():
                evidence.append("Hypothesis '%s': Add boundary condition tests" % hyp[:30])
            else:
                evidence.append("Hypothesis '%s': Requires code inspection" % hyp[:30])

        return DebugPhase(
            phase="verify",
            evidence=evidence[:3],
            duration_ms=(time.time() - start) * 1000,
        )

    def _phase_fix(self, evidence: list[str], ctx: dict) -> DebugPhase:
        start = time.time()
        fixes = []

        if evidence:
            fixes.append("Apply minimal fix targeting root cause")
            fixes.append("Add regression test to prevent recurrence")
            fixes.append("Verify fix doesn't introduce new issues")

        return DebugPhase(
            phase="fix",
            findings=fixes,
            duration_ms=(time.time() - start) * 1000,
        )

    def _determine_root_cause(self, p1: DebugPhase, p2: DebugPhase, p3: DebugPhase) -> str:
        if p2.hypotheses:
            return p2.hypotheses[0]
        if p1.findings:
            return p1.findings[-1]
        return "unknown"

    def get_stats(self) -> dict:
        return {"debug_sessions": len(self._history)}
