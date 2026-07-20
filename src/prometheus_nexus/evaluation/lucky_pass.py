"""LuckyPassDetector — Agent "Lucky Pass" detection per paper 2605.12925.

Paper finding:
  "10.7% through trajectory is Lucky Pass. Only 20.2% is Ideal.
   pass rate is the wrong evaluation metric."

A "lucky pass" occurs when an agent reaches the correct final output but
through a fragile path that would not survive input variations or task
rephrasing. This detector identifies such trajectories heuristically.

Detection heuristics:
  1. Single-path success (no backtracking) — only 1 path tried, successful
  2. No explanation of WHY the approach works
  3. Missing key intermediate steps (jump from A → result with no B)

Algorithm:
    is_lucky_pass(trajectory):
        1. Extract path count, explanation tokens, intermediate steps
        2. Evaluate each heuristic independently
        3. Combine: lucky = any 2 of 3 heuristics fire (or all 3)

Usage:
    detector = LuckyPassDetector()
    result = detector.analyze(trajectory_log)
    if detector.is_lucky_pass(trajectory_log):
        print("Fragile trajectory detected!")

Complexity:
    analyze(): O(S) where S = number of steps in the trajectory
    is_lucky_pass(): O(S)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class LuckyPassAnalysis:
    """Result of a lucky-pass analysis on a single trajectory."""
    lucky_probability: float = 0.0
    ideal_path_probability: float = 0.0
    missing_steps: list[str] = field(default_factory=list)
    failure_recovery_count: int = 0
    is_lucky_pass: bool = False
    heuristic_signals: dict[str, bool] = field(default_factory=dict)
    path_count: int = 0
    total_steps: int = 0
    explanation_token_estimate: int = 0


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------

class LuckyPassDetector:
    """Detector for "lucky pass" trajectories in agent evolution.

    A lucky pass is a trajectory where the agent reaches the correct final
    output through a fragile path — no backtracking, no explanation, missing
    intermediate reasoning steps.

    Usage:
        detector = LuckyPassDetector()
        analysis = detector.analyze(trajectory_log)
        if detector.is_lucky_pass(trajectory_log):
            ...  # flag for re-evaluation
    """

    # Minimum tokens in a "why" explanation to be considered non-lucky
    _MIN_EXPLANATION_TOKENS: int = 10

    def __init__(self) -> None:
        self._analyses: list[LuckyPassAnalysis] = []
        self._lucky_count: int = 0
        self._ideal_count: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_lucky_pass(self, trajectory_log: dict[str, Any]) -> bool:
        """Returns True if the trajectory is a lucky pass.

        A trajectory is considered a lucky pass when at least **2 of 3**
        heuristics fire:

        1. **Single-path** — only 1 path was tried and it succeeded
           (no backtracking / no branch exploration).
        2. **No explanation** — success achieved without explaining WHY
           the chosen approach works.
        3. **Missing steps** — key intermediate reasoning / action steps
           are absent (jump from A → result skipping B).

        Args:
            trajectory_log: Dict representation of the trajectory.
                Expected keys (all optional):
                - "paths": list[dict] — each path tried
                - "steps": list[dict] — individual reasoning/action steps
                - "explanation": str — agent's explanation of its approach
                - "actions": list[str] — sequence of actions taken
                - "success": bool — whether output is correct
                - "reasoning": str — chain-of-thought text

        Returns:
            True if lucky pass, False otherwise.
        """
        analysis = self.analyze(trajectory_log)
        return analysis.is_lucky_pass

    def analyze(self, trajectory_log: dict[str, Any]) -> LuckyPassAnalysis:
        """Analyse a trajectory for lucky-pass characteristics.

        Args:
            trajectory_log: Dict representation of the trajectory.

        Returns:
            LuckyPassAnalysis with detailed breakdown.
        """
        # --- Extract features ---
        paths: list[dict[str, Any]] = trajectory_log.get("paths", [])
        steps: list[dict[str, Any]] = trajectory_log.get("steps", [])
        actions: list[str] = trajectory_log.get("actions", [])
        explanation_raw: str = trajectory_log.get("explanation", "")
        reasoning_raw: str = trajectory_log.get("reasoning", "")
        trajectory_success: bool = trajectory_log.get("success", False)

        path_count = len(paths)
        total_steps = len(steps) or len(actions)

        # --- Heuristic 1: Single-path (no backtracking) ---
        # Exactly 1 path tried and successful (no branch exploration)
        heuristic_single_path = path_count == 1 and trajectory_success

        # --- Heuristic 2: No explanation of WHY ---
        # Combine explanation + reasoning text, estimate token count
        combined_explanation = f"{explanation_raw} {reasoning_raw}".strip()
        explanation_tokens = self._estimate_tokens(combined_explanation)
        heuristic_no_why = explanation_tokens < self._MIN_EXPLANATION_TOKENS

        # --- Heuristic 3: Missing key intermediate steps ---
        # Detect A→result jumps by looking for:
        # - Few steps relative to what's expected (less than ~3 steps is suspect)
        # - No intermediate "analysis", "check", "verify", "refine" steps
        # - Direct final output without any tentative / exploratory actions
        missing: list[str] = []
        heuristic_missing_steps = False

        if total_steps < 3:
            heuristic_missing_steps = True
            missing.append("too_few_steps")

        # Check for intermediate reasoning markers in action/step descriptions
        intermediate_markers = [
            "analysis", "check", "verify", "refine", "evaluate",
            "compare", "debug", "test", "review", "inspect",
            "intermediate", "draft", "attempt", "candidate",
        ]
        step_texts = self._extract_step_texts(steps, actions)
        found_markers = sum(
            1 for m in intermediate_markers
            if any(m in st.lower() for st in step_texts)
        )
        if found_markers < 1:
            heuristic_missing_steps = True
            missing.append("no_intermediate_markers")

        # Check for the word "because" or explicit causal reasoning
        if not self._has_causal_reasoning(step_texts, combined_explanation):
            heuristic_missing_steps = True
            missing.append("no_causal_reasoning")

        # Strengthen heuristic_missing_steps: require at least 2 sub-indicators to fire
        # (too_few_steps, no_intermediate_markers, no_causal_reasoning)
        missing_sub_count = len(missing)
        if missing_sub_count < 2:
            heuristic_missing_steps = False
            missing = []

        # --- Failure recovery count ---
        failure_count = self._count_failure_recoveries(steps, actions)

        # --- Combine heuristics (lucky = any 2 of 3, AND trajectory must have succeeded) ---
        signals: dict[str, bool] = {
            "single_path": heuristic_single_path,
            "no_explanation": heuristic_no_why,
            "missing_steps": heuristic_missing_steps,
        }
        fired_count = sum(1 for v in signals.values() if v)
        # A "lucky pass" only makes sense if the trajectory actually succeeded
        is_lucky = (fired_count >= 2) and trajectory_success

        # Ideal path = succeeded with zero heuristic signals (all 3 false)
        is_ideal = trajectory_success and fired_count == 0

        # --- Compute probabilities (normalised heuristic counts) ---
        # Empty/invalid trajectories (no paths, no steps) should have zero probability
        if path_count == 0 and total_steps == 0:
            lucky_prob = 0.0
            is_lucky = False
        else:
            lucky_prob = fired_count / 3.0
        ideal_prob = 1.0 - lucky_prob if trajectory_success else 0.0

        analysis = LuckyPassAnalysis(
            lucky_probability=round(lucky_prob, 4),
            ideal_path_probability=round(ideal_prob, 4),
            missing_steps=missing,
            failure_recovery_count=failure_count,
            is_lucky_pass=is_lucky,
            heuristic_signals=signals,
            path_count=path_count,
            total_steps=total_steps,
            explanation_token_estimate=explanation_tokens,
        )

        self._analyses.append(analysis)
        if is_lucky:
            self._lucky_count += 1
        if is_ideal:
            self._ideal_count += 1

        return analysis

    def get_stats(self) -> dict[str, Any]:
        """Return aggregate statistics across all analysed trajectories.

        Returns:
            Dict with total_analyses, lucky_count, ideal_count,
            avg_lucky_probability, avg_ideal_probability.
        """
        total = len(self._analyses)
        if total == 0:
            return {
                "total_analyses": 0,
                "lucky_count": 0,
                "ideal_count": 0,
                "avg_lucky_probability": 0.0,
                "avg_ideal_probability": 0.0,
            }

        avg_lucky = sum(a.lucky_probability for a in self._analyses) / total
        avg_ideal = sum(a.ideal_path_probability for a in self._analyses) / total

        return {
            "total_analyses": total,
            "lucky_count": self._lucky_count,
            "ideal_count": self._ideal_count,
            "avg_lucky_probability": round(avg_lucky, 4),
            "avg_ideal_probability": round(avg_ideal, 4),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token-count estimate (~4 chars per token)."""
        return len(text.split())

    @staticmethod
    def _extract_step_texts(
        steps: list[dict[str, Any]],
        actions: list[str],
    ) -> list[str]:
        """Extract human-readable step/action text for marker matching."""
        texts: list[str] = []

        for s in steps:
            if isinstance(s, dict):
                for key in ("content", "description", "action", "thought", "output"):
                    val = s.get(key)
                    if isinstance(val, str):
                        texts.append(val)
            elif isinstance(s, str):
                texts.append(s)

        for a in actions:
            if isinstance(a, str):
                texts.append(a)

        return texts

    @staticmethod
    def _has_causal_reasoning(
        step_texts: list[str],
        combined_explanation: str,
    ) -> bool:
        """Check for causal / explanatory language."""
        causal_markers = ["because", "since", "therefore", "hence",
                          "reason", "why", "implies", "due to"]
        combined = " ".join(step_texts) + " " + combined_explanation
        return any(m in combined.lower() for m in causal_markers)

    @staticmethod
    def _count_failure_recoveries(
        steps: list[dict[str, Any]],
        actions: list[str],
    ) -> int:
        """Count how many times the agent failed then continued (recovery)."""
        count = 0
        error_markers = re.compile(
            r"(error|fail|exception|timeout|crash|invalid|wrong)", re.IGNORECASE
        )

        text_blocks = []
        for s in steps:
            if isinstance(s, dict):
                text_blocks.append(str(s))
            elif isinstance(s, str):
                text_blocks.append(s)
        text_blocks.extend(actions)

        for tb in text_blocks:
            if error_markers.search(tb):
                count += 1

        return count
