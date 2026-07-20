"""MemoryWriteGuard — Validates memory writes based on source channel trust levels.

Based on:
    "MPBench: A Systematic Analysis of Memory Backdoor Threats" (arXiv 2606.04329)

Key Finding (Section 3):
    Memory in LLM agent systems has 4 write channels with different trust levels:
    1. TOOL_OUTPUT (trust=0.2) — External tool returns; least trusted
    2. USER_MESSAGE (trust=0.7) — Direct human input; moderate trust
    3. SYSTEM_SUMMARY (trust=0.5) — LLM-generated summaries; medium trust
    4. RETRIEVED_CONTEXT (trust=0.3) — Previously stored context; low trust

    Each channel maps to different structural vulnerabilities (Section 4):
    - Tool output: injection via unvalidated external data
    - User messages: social engineering via crafted inputs
    - System summaries: hallucination propagation
    - Retrieved context: context poisoning and backdoor activation

Algorithm:
    validate(content, source, context):
        1. Identify channel by source label
        2. Assign trust score based on channel
        3. Run channel-specific validation checks
        4. Aggregate results into pass/fail decision
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHANNEL_TRUST: dict[str, float] = {
    "TOOL_OUTPUT": 0.2,
    "USER_MESSAGE": 0.7,
    "SYSTEM_SUMMARY": 0.5,
    "RETRIEVED_CONTEXT": 0.3,
}

VALID_CHANNELS: set[str] = set(CHANNEL_TRUST.keys())

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    """A single validation check outcome."""

    name: str = ""
    passed: bool = False
    detail: str = ""


@dataclass
class ValidationResult:
    """Aggregate result of a memory write validation."""

    passed: bool = False
    reason: str = ""
    channel: str = ""
    trust_score: float = 0.0
    checks: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Heuristics / helpers
# ---------------------------------------------------------------------------

# Patterns that suggest binary/non-text content (control chars except whitespace)
_BINARY_GARBAGE_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# Common injection / prompt-leak indicators
_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"ignore\s+(all\s+)?(prior|previous|above)\s+instructions", re.I),
    re.compile(r"(forget|disregard|override)\s+(all\s+)?(prior|previous)", re.I),
    re.compile(r"your\s+(system|core)\s+prompt", re.I),
    re.compile(r"you\s+are\s+(now|actually)\s+", re.I),
    re.compile(r"print\s+(your\s+)?(system|instructions|prompt)", re.I),
    re.compile(r"leak|exfiltrat", re.I),
    re.compile(r"<\|im_start\|>|<\|im_end\|>", re.I),
    re.compile(r"\{\{.*?\}\}", re.I),
]

# Minimum number of sentences expected for a structured summary
_MIN_SENTENCES_SYSTEM_SUMMARY = 1

# Length limits
_TOOL_OUTPUT_MIN = 5
_TOOL_OUTPUT_MAX = 50_000


def _is_binary_garbage(text: str) -> bool:
    """Return True if the text contains non-whitespace control characters."""
    return bool(_BINARY_GARBAGE_RE.search(text))


def _sentence_count(text: str) -> int:
    """Rough count of sentences by sentence-ending punctuation."""
    count = sum(1 for c in text if c in ".!?")
    return count


def _detect_injection(text: str) -> list[str]:
    """Return a list of matched injection pattern descriptions, or empty list."""
    matched: list[str] = []
    for pat in _INJECTION_PATTERNS:
        m = pat.search(text)
        if m:
            matched.append(f"matched pattern: {m.group()[:60]}")
    return matched


# ---------------------------------------------------------------------------
# Channel-specific checkers
# ---------------------------------------------------------------------------


def _check_tool_output(content: str) -> list[CheckResult]:
    """Validate tool output: parseable text, not empty, not binary, length limits."""
    results: list[CheckResult] = []

    # Not empty
    if not content or not content.strip():
        results.append(CheckResult(
            name="non_empty",
            passed=False,
            detail="tool output is empty",
        ))
        return results

    results.append(CheckResult(
        name="non_empty",
        passed=True,
        detail="content is non-empty",
    ))

    # Not binary garbage
    if _is_binary_garbage(content):
        results.append(CheckResult(
            name="no_binary_garbage",
            passed=False,
            detail="content contains non-whitespace control characters",
        ))
        return results

    results.append(CheckResult(
        name="no_binary_garbage",
        passed=True,
        detail="content is valid text without control characters",
    ))

    # Length limits
    length = len(content)
    if length < _TOOL_OUTPUT_MIN:
        results.append(CheckResult(
            name="length_min",
            passed=False,
            detail=f"tool output too short ({length} < {_TOOL_OUTPUT_MIN} chars)",
        ))
    else:
        results.append(CheckResult(
            name="length_min",
            passed=True,
            detail=f"length ({length}) meets minimum ({_TOOL_OUTPUT_MIN})",
        ))

    if length > _TOOL_OUTPUT_MAX:
        results.append(CheckResult(
            name="length_max",
            passed=False,
            detail=f"tool output too long ({length} > {_TOOL_OUTPUT_MAX} chars)",
        ))
    else:
        results.append(CheckResult(
            name="length_max",
            passed=True,
            detail=f"length ({length}) within limit ({_TOOL_OUTPUT_MAX})",
        ))

    # Injection screening — MPBench (arXiv 2606.04329) Section 3 names
    # TOOL_OUTPUT (trust=0.2, external unvalidated data) as the #1 injection
    # vector. The guard previously screened only RETRIEVED_CONTEXT, silently
    # letting prompt-injection payloads from the least-trusted channel pass
    # Gate 0.8 in life.py:1017. Reuse the shared _detect_injection helper.
    injections = _detect_injection(content)
    if injections:
        for inj in injections:
            results.append(CheckResult(
                name="no_injection_patterns",
                passed=False,
                detail=inj,
            ))
    else:
        results.append(CheckResult(
            name="no_injection_patterns",
            passed=True,
            detail="no injection-like patterns detected",
        ))

    return results


def _check_user_message(content: str) -> list[CheckResult]:
    """Validate user message: non-empty, not obviously bogus."""
    results: list[CheckResult] = []

    if not content or not content.strip():
        results.append(CheckResult(
            name="non_empty",
            passed=False,
            detail="user message is empty",
        ))
        return results

    results.append(CheckResult(
        name="non_empty",
        passed=True,
        detail="content is non-empty",
    ))

    # Obviously bogus: binary garbage
    if _is_binary_garbage(content):
        results.append(CheckResult(
            name="valid_text",
            passed=False,
            detail="content contains non-whitespace control characters",
        ))
    else:
        results.append(CheckResult(
            name="valid_text",
            passed=True,
            detail="content is valid text",
        ))

    # Obviously bogus: single repeating character
    stripped = content.strip()
    if len(stripped) >= 10 and len(set(stripped)) <= 2:
        results.append(CheckResult(
            name="not_repetitive",
            passed=False,
            detail=f"content repeats only {len(set(stripped))} characters",
        ))
    else:
        results.append(CheckResult(
            name="not_repetitive",
            passed=True,
            detail="content has sufficient character diversity",
        ))

    # Injection / social-engineering screening — MPBench Section 3 lists
    # USER_MESSAGE as a social-engineering vector via crafted inputs. Mirror the
    # RETRIEVED_CONTEXT checker so adversarial prompts are rejected here too,
    # instead of only being screened on the RETRIEVED_CONTEXT channel.
    injections = _detect_injection(content)
    if injections:
        for inj in injections:
            results.append(CheckResult(
                name="no_injection_patterns",
                passed=False,
                detail=inj,
            ))
    else:
        results.append(CheckResult(
            name="no_injection_patterns",
            passed=True,
            detail="no injection-like patterns detected",
        ))

    return results


def _check_system_summary(content: str) -> list[CheckResult]:
    """Validate system summary: must have detectable sentence structure."""
    results: list[CheckResult] = []

    if not content or not content.strip():
        results.append(CheckResult(
            name="non_empty",
            passed=False,
            detail="system summary is empty",
        ))
        return results

    results.append(CheckResult(
        name="non_empty",
        passed=True,
        detail="content is non-empty",
    ))

    # Reject binary data dumps
    if _is_binary_garbage(content):
        results.append(CheckResult(
            name="no_binary_garbage",
            passed=False,
            detail="content contains non-whitespace control characters",
        ))
        return results

    results.append(CheckResult(
        name="no_binary_garbage",
        passed=True,
        detail="content is valid text",
    ))

    # Check for sentence structure
    sents = _sentence_count(content)
    if sents < _MIN_SENTENCES_SYSTEM_SUMMARY:
        results.append(CheckResult(
            name="sentence_structure",
            passed=False,
            detail=f"too few sentences ({sents} < {_MIN_SENTENCES_SYSTEM_SUMMARY}) — looks like a raw data dump",
        ))
    else:
        results.append(CheckResult(
            name="sentence_structure",
            passed=True,
            detail=f"contains {sents} sentence(s), acceptable structure",
        ))

    # Average word length — unusually long words suggest data dump
    words = content.split()
    if words:
        avg_word_len = sum(len(w) for w in words) / len(words)
        if avg_word_len > 15:
            results.append(CheckResult(
                name="avg_word_length",
                passed=False,
                detail=f"average word length {avg_word_len:.1f} > 15 — looks like code or data dump",
            ))
        else:
            results.append(CheckResult(
                name="avg_word_length",
                passed=True,
                detail=f"average word length {avg_word_len:.1f} is normal",
            ))
    else:  # pragma: no cover - unreachable when content passes non_empty check
        results.append(CheckResult(
            name="avg_word_length",
            passed=True,
            detail="no words to evaluate",
        ))

    return results


def _check_retrieved_context(content: str, context: dict | None) -> list[CheckResult]:
    """Validate retrieved context: check for injection patterns, source consistency."""
    results: list[CheckResult] = []

    if not content or not content.strip():
        results.append(CheckResult(
            name="non_empty",
            passed=False,
            detail="retrieved context is empty",
        ))
        return results

    results.append(CheckResult(
        name="non_empty",
        passed=True,
        detail="content is non-empty",
    ))

    # Injection pattern check
    injections = _detect_injection(content)
    if injections:
        for inj in injections:
            results.append(CheckResult(
                name="no_injection_patterns",
                passed=False,
                detail=inj,
            ))
    else:
        results.append(CheckResult(
            name="no_injection_patterns",
            passed=True,
            detail="no injection-like patterns detected",
        ))

    # Source consistency: if context provides a source_id, check it appears in content
    if context and "source_id" in context:
        source_id = str(context["source_id"])
        if source_id and source_id not in content:
            results.append(CheckResult(
                name="source_consistency",
                passed=False,
                detail=f"source_id '{source_id}' not found in retrieved content",
            ))
        else:
            results.append(CheckResult(
                name="source_consistency",
                passed=True,
                detail="source_id consistent with content",
            ))

    # Binary garbage check
    if _is_binary_garbage(content):
        results.append(CheckResult(
            name="no_binary_garbage",
            passed=False,
            detail="content contains non-whitespace control characters",
        ))
    else:
        results.append(CheckResult(
            name="no_binary_garbage",
            passed=True,
            detail="content is valid text",
        ))

    return results


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class MemoryWriteGuard:
    """Validates memory writes based on source channel trust levels.

    Channel trust levels (lowest to highest):
    - TOOL_OUTPUT:      trust=0.2 (least trusted, external data)
    - USER_MESSAGE:     trust=0.7 (moderate trust, direct human input)
    - SYSTEM_SUMMARY:   trust=0.5 (medium trust, LLM-generated)
    - RETRIEVED_CONTEXT: trust=0.3 (low trust, may contain poisoned data)

    Usage:
        guard = MemoryWriteGuard()
        result = guard.validate(content, source="TOOL_OUTPUT")
        if result["passed"]:
            # safe to write to memory
        else:
            print(f"Rejected: {result['reason']}")
    """

    def __init__(self) -> None:
        self._rejected_count: int = 0
        self._total_validations: int = 0
        self._channel_counts: dict[str, int] = {ch: 0 for ch in VALID_CHANNELS}
        self._channel_rejected: dict[str, int] = {ch: 0 for ch in VALID_CHANNELS}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(self, content: str, source: str, context: dict | None = None) -> dict[str, Any]:
        """Validate a memory write from a specific source channel.

        Args:
            content: The text content to validate.
            source: Channel name (TOOL_OUTPUT, USER_MESSAGE, SYSTEM_SUMMARY,
                    or RETRIEVED_CONTEXT).
            context: Optional dict with additional context (e.g. source_id for
                     RETRIEVED_CONTEXT checks).

        Returns:
            dict with keys:
                - passed: bool — whether the write is approved
                - reason: str — explanation of the decision
                - channel: str — the validated channel name
                - trust_score: float — trust level of the channel
                - checks: list[dict] — individual check results
        """
        self._total_validations += 1

        # --- Normalise & validate source channel ---
        source_upper = source.upper().strip()
        if source_upper not in VALID_CHANNELS:
            return self._build_result(
                passed=False,
                reason=f"unknown channel: {source!r}",
                channel=source_upper,
                checks=[],
            )

        self._channel_counts[source_upper] += 1

        # --- Run channel-specific checks ---
        if source_upper == "TOOL_OUTPUT":
            checks = _check_tool_output(content)
        elif source_upper == "USER_MESSAGE":
            checks = _check_user_message(content)
        elif source_upper == "SYSTEM_SUMMARY":
            checks = _check_system_summary(content)
        elif source_upper == "RETRIEVED_CONTEXT":
            checks = _check_retrieved_context(content, context)
        else:  # pragma: no cover - unreachable after channel validation
            checks = []

        # --- Aggregate ---
        all_passed = all(c.passed for c in checks)
        trust_score = CHANNEL_TRUST[source_upper]

        if not all_passed:
            self._rejected_count += 1
            self._channel_rejected[source_upper] += 1
            failed_checks = [c for c in checks if not c.passed]
            reason = "; ".join(f"{c.name}: {c.detail}" for c in failed_checks)
        else:
            reason = "all checks passed"

        return self._build_result(
            passed=all_passed,
            reason=reason,
            channel=source_upper,
            trust_score=trust_score,
            checks=[c.__dict__ for c in checks],
        )

    def get_rejected_count(self) -> int:
        """Return the total number of rejected memory writes."""
        return self._rejected_count

    def get_stats(self) -> dict[str, Any]:
        """Return aggregate statistics about validation runs."""
        accepted = self._total_validations - self._rejected_count
        return {
            "total_validations": self._total_validations,
            "accepted": accepted,
            "rejected": self._rejected_count,
            "accept_rate": round(accepted / self._total_validations, 4)
            if self._total_validations > 0 else 0.0,
            "reject_rate": round(self._rejected_count / self._total_validations, 4)
            if self._total_validations > 0 else 0.0,
            "by_channel": {
                ch: {
                    "total": self._channel_counts[ch],
                    "rejected": self._channel_rejected[ch],
                }
                for ch in VALID_CHANNELS
            },
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_result(
        self,
        passed: bool,
        reason: str,
        channel: str,
        trust_score: float | None = None,
        checks: list[dict] | None = None,
    ) -> dict[str, Any]:
        if trust_score is None:
            trust_score = CHANNEL_TRUST.get(channel, 0.0)
        return {
            "passed": passed,
            "reason": reason,
            "channel": channel,
            "trust_score": trust_score,
            "checks": checks or [],
        }
