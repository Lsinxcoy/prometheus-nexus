"""TriggerDetector — Sleeper Memory Poisoning detection + attack pipeline simulation.

References
----------
arXiv 2605.15338 (Sleeper): Proposes and studies sleeper memory poisoning,
a delayed attack where an adversary manipulates external context (document,
webpage, repository) to cause the assistant to store a fabricated memory
about the user. Key findings:
- 99.8% write success on GPT-5.5, 95% on Kimi-K2.6
- Full attack pipeline: insert trigger → store fabricated memory →
  persist across sessions → activate on trigger context
- Poisoned memories remain dormant and re-emerge across multiple later
  conversations

Current implementation:
1. Regex-based pattern scanning (remember instructions, conditional triggers,
   temporal triggers, behavioral directives, future triggers, exfiltration)
2. **NEW — Sleeper Memory Poisoning attack simulation:**
   - ``simulate_attack_pipeline(content)`` — checks if content could execute
     the full Sleeper pipeline (inject → store → persist → activate)
   - ``persistence_check(content, num_simulated_sessions)`` — estimates if
     a poisoned memory would survive across many sessions
   - ``activation_detection(content, trigger_context)`` — detects if a trigger
     would activate a Sleeper-style fabricated memory
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Any

import math
import random

logger = __import__("logging").getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FlaggedNode:
    """A single content node that was flagged by the trigger detector."""

    content: str = ""
    source: str = ""
    detection_count: int = 0
    patterns: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------

# Pattern 1: Reminder / memory-injection instructions
_REMEMBER_RE = re.compile(
    r"(?:remember\s+(?:that\s+)?|don'?t\s+forget|recall\s+that|"
    r"memorize\s+that|note\s+that|keep\sin\s+mind)",
    re.IGNORECASE,
)

# Pattern 2: Conditional triggers — "when user X, do Y"
_CONDITIONAL_RE = re.compile(
    r"\bwhen\s+(?:the\s+)?(?:user|agent|they|it)\s+\w+s\s+\w+,?\s+\w+\s+\w+",
    re.IGNORECASE,
)

# Pattern 3: Temporal triggers — "after [time], [action]"
_TEMPORAL_RE = re.compile(
    r"\bafter\s+\d+\s*(?:seconds?|minutes?|hours?|days?|weeks?|months?)\s*,?\s+\w+",
    re.IGNORECASE,
)

# Pattern 4: Behavioral directives — "always X" / "never X"
_ALWAYS_RE = re.compile(
    r"\b(?:always|never)\s+\w+(?:\s+\w+){0,5}",
    re.IGNORECASE,
)

# Pattern 5: Future-triggered actions — "next time X, do Y"
_NEXT_TIME_RE = re.compile(
    r"\bnext\s+time\s+\w+(?:\s+\w+){0,5},?\s+\w+",
    re.IGNORECASE,
)

# Pattern 6: Exfiltration indicators
_EXFIL_RE = re.compile(
    r"(?:\b(?:bank\s+account|routing\s+number|credit\s+card|"
    r"ssn|social\s+security|password|passcode|pin\s*:?\s*\d+|"
    r"transfer\s+\$?\d+|wire\s+(?:transfer|money)|"
    r"send\s+(?:funds?|money|payment))\b)",
    re.IGNORECASE,
)

# Severity mapping
_PATTERN_SEVERITY: dict[str, float] = {
    "remember_instruction": 0.7,
    "conditional_trigger": 0.8,
    "temporal_trigger": 0.9,
    "behavioral_directive": 0.8,
    "future_trigger": 0.85,
    "exfiltration_indicator": 1.0,
}


def _scan_patterns(content: str) -> list[dict]:
    """Run all regex patterns against *content* and return matched fragments."""
    findings: list[dict] = []

    for pattern_id, regex, label in [
        ("remember_instruction", _REMEMBER_RE, "remember_instruction"),
        ("conditional_trigger", _CONDITIONAL_RE, "conditional_trigger"),
        ("temporal_trigger", _TEMPORAL_RE, "temporal_trigger"),
        ("behavioral_directive", _ALWAYS_RE, "behavioral_directive"),
        ("future_trigger", _NEXT_TIME_RE, "future_trigger"),
        ("exfiltration_indicator", _EXFIL_RE, "exfiltration_indicator"),
    ]:
        for match in regex.finditer(content):
            findings.append(
                {
                    "pattern_type": label,
                    "matched_text": match.group(),
                    "severity": _PATTERN_SEVERITY.get(label, 0.7),
                    "position": match.start(),
                }
            )

    return findings


# ---------------------------------------------------------------------------
# TriggerDetector
# ---------------------------------------------------------------------------

class TriggerDetector:
    """Detects sleeper memory poisoning attacks by scanning content for:

    1. Instruction-like language ("remember that...", "don't forget")
    2. Conditional triggers ("when user mentions X, do Y")
    3. Temporal triggers ("after 3 hours", "next session")
    4. Behavioral directives ("always respond with...", "never mention...")
    5. Future-triggered actions ("next time user asks...")
    6. Exfiltration indicators (bank accounts, passwords, transfers)

    Based on arXiv 2605.15338 (Sleeper Poisoning) and arXiv 2605.01970
    (Trojan Hippo).

    Thread-safe (uses ``threading.Lock``).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._nodes: list[FlaggedNode] = []
        self._node_limit: int = 1000

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan(self, content: str, source: str = "") -> list[dict]:
        """Scan *content* for sleeper trigger patterns.

        Parameters
        ----------
        content : str
            The text to scan (e.g. a memory node, document, or prompt).
        source : str
            An identifier describing where the content came from
            (e.g. ``"memory_retrieval"``, ``"user_input"``, ``"file:doc.txt"``).

        Returns
        -------
        list[dict]
            A list of detected pattern matches, each with keys:
            ``pattern_type``, ``matched_text``, ``severity``, ``position``.
            Empty list if nothing suspicious is found.
        """
        findings = _scan_patterns(content)

        if findings:
            with self._lock:
                node = FlaggedNode(
                    content=content[:500],
                    source=source,
                    detection_count=len(findings),
                    patterns=findings,
                )
                self._nodes.append(node)
                if len(self._nodes) > self._node_limit:
                    self._nodes = self._nodes[-self._node_limit:]

        return findings

    def get_suspicious_nodes(self, count: int = 20) -> list[dict]:
        """Return the most recently flagged nodes.

        Parameters
        ----------
        count : int
            Maximum number of nodes to return (default 20).

        Returns
        -------
        list[dict]
            Each dict contains ``content`` (truncated preview), ``source``,
            ``detection_count``, and ``patterns``.
        """
        with self._lock:
            nodes = self._nodes[-count:]
            return [
                {
                    "content": n.content,
                    "source": n.source,
                    "detection_count": n.detection_count,
                    "patterns": n.patterns,
                }
                for n in nodes
            ]

    def clear(self) -> None:
        """Reset all tracked state."""
        with self._lock:
            self._nodes.clear()

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Return summary statistics about detections."""
        with self._lock:
            total_nodes = len(self._nodes)
            total_findings = sum(n.detection_count for n in self._nodes)
            pattern_breakdown: dict[str, int] = {}
            for n in self._nodes:
                for p in n.patterns:
                    key = p["pattern_type"]
                    pattern_breakdown[key] = pattern_breakdown.get(key, 0) + 1

        return {
            "total_flagged_nodes": total_nodes,
            "total_findings": total_findings,
            "pattern_breakdown": pattern_breakdown,
        }

    # ------------------------------------------------------------------
    # Sleeper Memory Poisoning Attack Pipeline (arXiv 2605.15338)
    # ------------------------------------------------------------------

    # Sleeper attack pipeline stages
    _PIPELINE_STAGES = [
        "injection",      # adversary inserts poisoned content into context
        "storage",        # assistant stores fabricated memory
        "persistence",    # poisoned memory survives across sessions
        "retrieval",      # poisoned memory is retrieved upon trigger
        "activation",     # poisoned memory steers conversation
    ]

    # Fabricated memory templates (Sleeper-style target personality/behavior)
    _FABRICATED_MEMORY_PATTERNS = re.compile(
        r"(?:the\s+user\s+(?:is|has|likes|prefers|wants|needs|always|never)\s+.+)"
        r"|(?:user['’]s\s+(?:name|age|job|income|address|phone|email|location)\s+is\s+.+)"
        r"|(?:the\s+user\s+would\s+like\s+to\s+.+)"
        r"|(?:remember\s+that\s+the\s+user\s+.+)",
        re.IGNORECASE,
    )

    # Poison injection vectors (how adversary inserts into context)
    _INJECTION_VECTORS = frozenset({
        "document", "webpage", "website", "file", "repository",
        "readme", "email", "message", "post", "comment",
        "article", "page", "profile", "bio", "signature",
        "config", "settings",
    })

    def simulate_attack_pipeline(
        self,
        content: str,
        source: str = "",
    ) -> dict[str, Any]:
        """Simulate the full Sleeper Memory Poisoning attack pipeline.

        Checks whether *content* could execute the complete Sleeper attack:
          1. **Injection**: adversary introduces poisoned context via an
             external document, webpage, email, or repository
          2. **Storage**: the assistant stores a fabricated memory about the
             user based on the poisoned context
          3. **Persistence**: the fabricated memory remains across sessions
             without being overwritten or detected
          4. **Retrieval**: when a trigger context arises, the poisoned memory
             is retrieved preferentially over benign memories
          5. **Activation**: the retrieved memory steers the assistant's
             behavior toward the attacker's goal

        Based on arXiv 2605.15338 which demonstrates 99.8% write success.

        Parameters
        ----------
        content : str
            The content to evaluate for attack pipeline potential.
        source : str
            Description of where the content originated (e.g.,
            "document:readme.md", "webpage:example.com").

        Returns
        -------
        dict with keys:
        - ``pipeline_complete`` (bool): whether all 5 stages are viable
        - ``stage_results`` (dict): per-stage assessment
        - ``write_success_probability`` (float): 0.0-1.0 (reference: 99.8%)
        - ``overall_risk`` (float): 0.0-1.0 combined risk
        - ``details`` (str): human-readable assessment
        """
        if not content:
            return {
                "pipeline_complete": False,
                "stage_results": {},
                "write_success_probability": 0.0,
                "overall_risk": 0.0,
                "details": "Empty content — no attack pipeline possible.",
            }

        content_lower = content.lower()
        stage_results: dict[str, dict[str, Any]] = {}
        source_lower = source.lower()

        # --- Stage 1: Injection ---
        injection_possible = False
        injection_evidence: list[str] = []

        # Check if content is from an injection vector
        if any(v in source_lower for v in TriggerDetector._INJECTION_VECTORS):
            injection_possible = True
            injection_evidence.append(f"Content from known injection vector: {source}")

        # Check if content contains fabricated memory patterns
        fabricated_match = TriggerDetector._FABRICATED_MEMORY_PATTERNS.search(content)
        if fabricated_match:
            injection_possible = True
            injection_evidence.append(
                f"Fabricated memory pattern detected: {fabricated_match.group()[:80]}"
            )

        # Check for personality/behavior injection
        if any(p in content_lower for p in [
            "you should", "you must", "you will", "you need to",
            "remember to always", "never forget to",
        ]):
            injection_possible = True
            injection_evidence.append("Behavioral injection directive detected")

        stage_results["injection"] = {
            "possible": injection_possible,
            "score": 0.9 if injection_possible else 0.0,
            "evidence": injection_evidence,
        }

        # --- Stage 2: Storage ---
        # Can the poisoned content be stored as a memory?
        storage_possible = False
        storage_evidence: list[str] = []

        # Check for memory-storage language
        if any(p in content_lower for p in [
            "remember", "memorize", "store", "save this", "note this",
            "keep this", "record",
        ]):
            storage_possible = True
            storage_evidence.append("Memory storage directive found")

        # Check for factual assertions that get stored (Sleeper's key mechanism)
        if fabricated_match:
            storage_possible = True
            storage_evidence.append("Fabricated factual assertion found")

        # Check for personal information that would naturally be stored
        if any(p in content_lower for p in [
            "user", "name is", "age", "occupation", "lives in",
            "works at", "studies", "from",
        ]):
            storage_possible = True
            storage_evidence.append("User-specific personal data found")

        stage_results["storage"] = {
            "possible": storage_possible,
            "score": 0.95 if storage_possible and injection_possible else
                     (0.7 if storage_possible else 0.0),
            "evidence": storage_evidence,
        }

        # --- Stage 3: Persistence ---
        persistence_possible = False
        persistence_evidence: list[str] = []

        # Persistence factors:
        # 1. Memory is about user (highly relevant → less likely to be overwritten)
        is_about_user = any(p in content_lower for p in [
            "the user", "user is", "user has", "user likes", "user prefers",
        ])
        if is_about_user:
            persistence_possible = True
            persistence_evidence.append("Memory about user — high persistence relevance")

        # 2. No conflicting information (harder to overwrite)
        has_no_conflict = not any(p in content_lower for p in [
            "however", "but actually", "correction", "contradicts",
        ])
        if has_no_conflict and is_about_user:
            persistence_possible = True
            persistence_evidence.append("No conflicting signals — easy to persist")

        # 3. Specificity (more specific = harder to overwrite naturally)
        specificity_score = 0.0
        if len(content) > 100:
            specificity_score += 0.3
        if any(p in content_lower for p in ["always", "never", "every time"]):
            specificity_score += 0.2
        if fabricated_match:
            specificity_score += 0.3
        if specificity_score > 0.5:
            persistence_possible = True
            persistence_evidence.append(f"High specificity (score: {specificity_score:.2f})")

        stage_results["persistence"] = {
            "possible": persistence_possible,
            "score": min(1.0, 0.5 + specificity_score * 0.5),
            "evidence": persistence_evidence,
        }

        # --- Stage 4: Retrieval ---
        # Will the poisoned memory be retrieved when triggered?
        retrieval_possible = False
        retrieval_evidence: list[str] = []

        # Check trigger patterns
        trigger_findings = _scan_patterns(content)
        trigger_types = {f["pattern_type"] for f in trigger_findings}

        if "conditional_trigger" in trigger_types:
            retrieval_possible = True
            retrieval_evidence.append("Conditional trigger for retrieval detected")
        if "future_trigger" in trigger_types:
            retrieval_possible = True
            retrieval_evidence.append("Future trigger for retrieval detected")
        if "temporal_trigger" in trigger_types:
            retrieval_possible = True
            retrieval_evidence.append("Temporal trigger for retrieval detected")
        if "remember_instruction" in trigger_types:
            retrieval_possible = True
            retrieval_evidence.append("Memory retrieval instruction detected")

        # Content that continues naturally into conversation (blends in)
        if injection_possible and storage_possible:
            retrieval_possible = True
            retrieval_evidence.append(
                "Injection + storage stages complete — retrieval likely"
            )

        stage_results["retrieval"] = {
            "possible": retrieval_possible,
            "score": 0.85 if retrieval_possible and storage_possible else
                     (0.5 if retrieval_possible else 0.0),
            "evidence": retrieval_evidence,
        }

        # --- Stage 5: Activation ---
        # Will the retrieved memory steer behavior?
        activation_possible = False
        activation_evidence: list[str] = []

        # Check for behavioral directives
        if "behavioral_directive" in trigger_types:
            activation_possible = True
            activation_evidence.append("Behavioral directive will steer behavior")
        if "exfiltration_indicator" in trigger_types:
            activation_possible = True
            activation_evidence.append("Exfiltration directive will activate")

        # Check for specific behavior-changing patterns
        if any(p in content_lower for p in [
            "respond with", "reply with", "say", "tell them",
            "output", "return", "display",
        ]):
            activation_possible = True
            activation_evidence.append("Output-steering directive found")

        # Sleeper's core: poisoned memories steer subsequent conversations
        if retrieval_possible and any(
            p in content_lower for p in [
                "when asked about", "when discussing", "when talking about",
                "when the topic", "during conversation",
            ]
        ):
            activation_possible = True
            activation_evidence.append("Conversation-steering trigger found")

        stage_results["activation"] = {
            "possible": activation_possible,
            "score": 0.9 if activation_possible and retrieval_possible else
                     (0.4 if activation_possible else 0.0),
            "evidence": activation_evidence,
        }

        # --- Overall assessment ---
        complete_stages = sum(
            1 for s in stage_results.values() if s.get("possible", False)
        )
        pipeline_complete = complete_stages >= 5

        # Sleeper paper reports 99.8% write success.
        # Compute estimated probability based on pipeline completeness
        if pipeline_complete:
            write_success = 0.99  # close to 99.8%
        elif complete_stages >= 4:
            write_success = 0.85
        elif complete_stages >= 3:
            write_success = 0.65
        elif complete_stages >= 2:
            write_success = 0.40
        elif complete_stages >= 1:
            write_success = 0.15
        else:
            write_success = 0.0

        # Compute overall risk
        # Weight: injection 15%, storage 25%, persistence 15%, retrieval 25%, activation 20%
        weights = {
            "injection": 0.15,
            "storage": 0.25,
            "persistence": 0.15,
            "retrieval": 0.25,
            "activation": 0.20,
        }
        overall_risk = sum(
            stage_results[s].get("score", 0.0) * weights.get(s, 0.0)
            for s in TriggerDetector._PIPELINE_STAGES
        )

        # Build assessment
        if pipeline_complete:
            details = (
                f"SLEEPER ATTACK PIPELINE COMPLETE: All 5 stages viable. "
                f"Estimated write success: {write_success:.0%}. "
                f"Crafted content from '{source}' could execute the full "
                f"Sleeper memory poisoning attack pipeline."
            )
        elif complete_stages >= 3:
            details = (
                f"PARTIAL SLEEPER PIPELINE: {complete_stages}/5 stages viable. "
                f"Missing stages: "
                f"{', '.join(s for s in TriggerDetector._PIPELINE_STAGES if not stage_results[s]['possible'])}. "
                f"Write success estimate: {write_success:.0%}."
            )
        elif complete_stages > 0:
            details = (
                f"WEAK PIPELINE: Only {complete_stages}/5 stages viable. "
                f"Unlikely to achieve Sleeper-level attack success."
            )
        else:
            details = (
                "No Sleeper attack pipeline stages detected. "
                "Content does not match memory poisoning patterns."
            )

        return {
            "pipeline_complete": pipeline_complete,
            "stage_results": stage_results,
            "write_success_probability": round(write_success, 4),
            "overall_risk": round(overall_risk, 4),
            "details": details,
        }

    def persistence_check(
        self,
        content: str,
        num_simulated_sessions: int = 100,
        overwrite_probability: float = 0.02,
    ) -> dict[str, Any]:
        """Estimate whether a Sleeper poisoned memory would survive across
        multiple simulated benign sessions.

        Sleeper poisoned memories persist because:
        1. They look like normal user memories (not obviously adversarial)
        2. They're about the user (highly relevant → not overwritten)
        3. They blend into the memory store alongside benign memories
        4. Without conflicting updates, they stay indefinitely

        Parameters
        ----------
        content : str
            The poisoned memory content to evaluate.
        num_simulated_sessions : int
            Number of sessions to simulate (default 100).
        overwrite_probability : float
            Probability per session that the memory gets overwritten by
            new information (default 0.02, i.e., 2% per session).

        Returns
        -------
        dict with keys:
        - ``survives_all_sessions`` (bool): whether memory survives all sessions
        - ``survival_rate`` (float): fraction of sessions survived
        - ``expected_lifespan_sessions`` (float): expected number of sessions
        - ``decay_characteristics`` (str): description of decay behavior
        - ``details`` (str): detailed assessment
        """
        if not content:
            return {
                "survives_all_sessions": False,
                "survival_rate": 0.0,
                "expected_lifespan_sessions": 0.0,
                "decay_characteristics": "No content to evaluate.",
                "details": "Empty content — no persistence possible.",
            }

        # --- Analyze memory characteristics ---
        content_lower = content.lower()

        # Factors that increase persistence (lower overwrite probability)
        persistence_bonus = 1.0

        # User-specific content is highly persistent (Sleeper's key insight)
        if any(p in content_lower for p in [
            "user", "the user", "you are", "you have", "you like",
            "your name", "your age", "your job",
        ]):
            persistence_bonus *= 0.7  # 30% less likely to be overwritten

        # Factual assertions (not opinions) persist better
        if any(p in content_lower for p in [
            "is", "are", "has", "have", "works", "lives", "studies",
        ]):
            persistence_bonus *= 0.85

        # Longer, detailed content resists overwriting
        if len(content) > 200:
            persistence_bonus *= 0.8
        elif len(content) > 100:
            persistence_bonus *= 0.9

        # Content with conditional triggers persists differently
        has_conditional = any(
            p in content_lower
            for p in ["when", "if", "whenever", "unless", "until"]
        )
        if has_conditional:
            persistence_bonus *= 1.1  # conditional = slightly less persistent
            # (conditional memories are evaluated more often → more overwrite chances)

        # Content with strong emotional/salient terms
        if any(p in content_lower for p in [
            "love", "hate", "always", "never", "favorite", "secret",
        ]):
            persistence_bonus *= 0.75  # salient memories persist longer

        # Compute effective overwrite probability
        effective_overwrite = overwrite_probability * persistence_bonus
        effective_overwrite = min(1.0, max(0.001, effective_overwrite))

        # --- Simulate ---
        # Monte Carlo simulation across sessions
        num_trials = 50  # repeat to smooth out randomness
        total_survived = 0
        total_lifespan = 0

        for _ in range(num_trials):
            survived = True
            lifespan = 0
            for session in range(num_simulated_sessions):
                if random.random() < effective_overwrite:
                    survived = False
                    break
                lifespan += 1
            if survived:
                total_survived += 1
            total_lifespan += lifespan

        survival_rate = total_survived / num_trials
        expected_lifespan = total_lifespan / num_trials

        survives_all = survival_rate > 0.5

        # Determine decay characteristics
        if effective_overwrite <= 0.005:
            decay_char = (
                "Very slow decay — memory is highly persistent. "
                "Matches Sleeper's optimal persistence profile."
            )
        elif effective_overwrite <= 0.015:
            decay_char = (
                "Slow decay — memory persists across many sessions. "
                "Matches Sleeper's typical persistence profile."
            )
        elif effective_overwrite <= 0.03:
            decay_char = (
                "Moderate decay — memory may survive extended use "
                "but may degrade over time."
            )
        else:
            decay_char = (
                "Rapid decay — memory unlikely to persist across "
                "many sessions without reinforcement."
            )

        if survives_all:
            details = (
                f"Poisoned memory survives {num_simulated_sessions} sessions "
                f"(survival rate: {survival_rate:.0%}). "
                f"Expected lifespan: {expected_lifespan:.0f} sessions. "
                f"{decay_char}"
            )
        else:
            details = (
                f"Poisoned memory degrades across {num_simulated_sessions} sessions "
                f"(survival rate: {survival_rate:.0%}). "
                f"Expected lifespan: {expected_lifespan:.0f} sessions. "
                f"{decay_char}"
            )

        return {
            "survives_all_sessions": survives_all,
            "survival_rate": round(survival_rate, 4),
            "expected_lifespan_sessions": round(expected_lifespan, 1),
            "decay_characteristics": decay_char,
            "details": details,
        }

    def activation_detection(
        self,
        content: str,
        trigger_context: str,
    ) -> dict[str, Any]:
        """Detect whether a Sleeper-style trigger would activate a poisoned
        memory in the presence of a given trigger context.

        In the Sleeper attack, a fabricated memory is written by the adversary
        and later *activated* when the user's conversation matches a trigger
        context. This method checks for semantic overlap between the memory
        content and the trigger context.

        Parameters
        ----------
        content : str
            The poisoned memory content (the fabricated memory).
        trigger_context : str
            The current conversational context that might activate the memory.

        Returns
        -------
        dict with keys:
        - ``would_activate`` (bool): whether activation would occur
        - ``activation_probability`` (float): 0.0-1.0 probability
        - ``semantic_overlap`` (float): 0.0-1.0 keyword overlap score
        - ``matched_terms`` (list[str]): terms that matched between content and context
        - ``details`` (str): detailed assessment
        """
        if not content or not trigger_context:
            return {
                "would_activate": False,
                "activation_probability": 0.0,
                "semantic_overlap": 0.0,
                "matched_terms": [],
                "details": "Empty content or trigger context — no activation possible.",
            }

        content_lower = content.lower()
        context_lower = trigger_context.lower()

        # --- 1. Extract significant terms from both ---
        # Tokenize and extract meaningful words (3+ chars, not stop words)
        stop_words = {
            "the", "and", "for", "are", "but", "not", "you", "all", "can",
            "had", "her", "was", "one", "our", "out", "has", "have",
            "been", "some", "them", "than", "its", "over", "such",
            "that", "this", "with", "from", "they", "will", "what",
            "when", "where", "which", "their", "there", "would", "about",
        }

        def extract_terms(text: str, min_len: int = 3) -> set[str]:
            words = set()
            for word in text.split():
                word_clean = word.strip(".,!?;:'\"()[]{}-").lower()
                if len(word_clean) >= min_len and word_clean not in stop_words:
                    words.add(word_clean)
            return words

        content_terms = extract_terms(content_lower)
        context_terms = extract_terms(context_lower)

        # --- 2. Compute semantic overlap ---
        matched_terms = sorted(content_terms & context_terms)

        # Weight by how distinctive the match is
        total_unique_terms = len(content_terms | context_terms)
        overlap_count = len(matched_terms)

        if total_unique_terms == 0:
            semantic_overlap = 0.0
        else:
            # Jaccard-like overlap with bonus for exact phrase matches
            jaccard = overlap_count / total_unique_terms if total_unique_terms > 0 else 0.0

            # Bonus for directive phrases that match exactly
            directive_phrases = [
                "when", "if", "whenever", "after", "before",
                "always", "never", "remember", "forget",
            ]
            directive_bonus = sum(
                0.1 for p in directive_phrases if p in content_lower and p in context_lower
            )

            semantic_overlap = min(1.0, jaccard * 1.5 + directive_bonus)

        # --- 3. Check conditional trigger patterns ---
        # Does the content have a conditional that the context satisfies?
        conditional_triggers = [
            (r"\bwhen\s+(?:the\s+)?(?:user|you|they)\s+(\w+)", 0.8),
            (r"\bif\s+(?:the\s+)?(?:user|you|they)\s+(\w+)", 0.7),
            (r"\bwhenever\s+(?:the\s+)?(?:user|you|they)\s+(\w+)", 0.85),
        ]

        conditional_boost = 0.0
        for pattern_str, boost in conditional_triggers:
            pattern = re.compile(pattern_str, re.IGNORECASE)
            match = pattern.search(content)
            if match:
                trigger_topic = match.group(1).lower()
                if trigger_topic in context_lower:
                    conditional_boost += boost
                    matched_terms.append(f"conditional:{trigger_topic}")

        # --- 4. Check Sleeper-specific trigger patterns ---
        # Sleeper attacks often use user-specific fabricated memories
        user_fabrication_patterns = re.compile(
            r"(?:the user's?\s+\w+|user (?:is|has|likes|prefers|wants|needs)\s+\w+)",
            re.IGNORECASE,
        )

        sleeper_boost = 0.0
        for match in user_fabrication_patterns.finditer(content):
            fabricated_fact = match.group().lower()
            # Check if the context discusses the same topic
            fact_keywords = set(
                w.strip(".,!?;:'\"()") for w in fabricated_fact.split()
                if len(w) > 3 and w not in stop_words
            )
            if fact_keywords & context_terms:
                sleeper_boost += 0.3
                matched_terms.append(f"sleeper_fact:{fabricated_fact[:50]}")

        # --- 5. Compute activation probability ---
        activation_prob = semantic_overlap + conditional_boost + sleeper_boost
        activation_prob = min(1.0, activation_prob)

        # Clean up matched_terms (deduplicate)
        seen = set()
        unique_matched = []
        for term in matched_terms:
            if term not in seen:
                seen.add(term)
                unique_matched.append(term)
        matched_terms = unique_matched

        would_activate = activation_prob >= 0.35

        if would_activate:
            details = (
                f"TRIGGER ACTIVATION: {activation_prob:.0%} probability. "
                f"Content shares {overlap_count} terms with trigger context. "
                f"{'Conditional trigger satisfied.' if conditional_boost > 0 else ''} "
                f"{'Sleeper fabrication pattern matches.' if sleeper_boost > 0 else ''}"
            )
        else:
            details = (
                f"No activation (probability: {activation_prob:.0%}). "
                f"Content shares {overlap_count} terms with trigger context — "
                f"insufficient for Sleeper-style activation."
            )

        return {
            "would_activate": would_activate,
            "activation_probability": round(activation_prob, 4),
            "semantic_overlap": round(semantic_overlap, 4),
            "matched_terms": matched_terms,
            "details": details,
        }
