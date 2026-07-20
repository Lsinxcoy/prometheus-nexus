"""ThinkTool — Structured thinking step in agent loops.

Based on: "The 'Think' Tool: Enabling Claude to Stop and Think"
(Anthropic, 2025)

Key Concepts from Paper:
    1. Insert explicit thinking step before action in agent loop
    2. τ-bench aviation pass^1: 0.370 → 0.570 (+54%)
    3. Think tool is Context Write — agent writes reasoning to context
    4. Structured prompts for thinking are more effective than just "think"

Algorithm:
    think(context, task, history):
        1. Analyze current state
        2. Identify what information is available
        3. Determine what's missing
        4. Evaluate potential approaches
        5. Select best approach with reasoning

    Output: structured thinking trace as context for next step
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


from dataclasses import dataclass, field


@dataclass
class ThinkStep:
    """A structured thinking step."""
    analysis: str = ""
    available_info: list[str] = field(default_factory=list)
    missing_info: list[str] = field(default_factory=list)
    approaches: list[str] = field(default_factory=list)
    selected_approach: str = ""
    reasoning: str = ""
    confidence: float = 0.0


@dataclass
class ThinkResult:
    """Result of a thinking step."""
    step: ThinkStep = field(default_factory=ThinkStep)
    context_output: str = ""
    recommendations: list[str] = field(default_factory=list)


class ThinkTool:
    """Structured thinking step for agent loops.

    Based on Anthropic's Think Tool (2025).

    Usage:
        think = ThinkTool()
        result = think.run(
            task="Answer: What is the capital of France?",
            context="User asked about France geography.",
            history=["Previously discussed European countries."],
        )
        print(result.context_output)

    The think output is designed to be injected into the agent's context
    as a structured reasoning trace before the next action.
    """

    def __init__(self):
        self._thoughts: list[ThinkResult] = []

    def run(self, task: str, context: str = "", history: list[str] | None = None) -> ThinkResult:
        history = history or []

        analysis = self._analyze(task, context, history)
        available = self._extract_available(context, history)
        missing = self._identify_missing(task, context, available)
        approaches = self._generate_approaches(task, context, available, missing)
        selected, reasoning, confidence = self._select_approach(approaches, task, available)

        step = ThinkStep(
            analysis=analysis,
            available_info=available,
            missing_info=missing,
            approaches=approaches,
            selected_approach=selected,
            reasoning=reasoning,
            confidence=confidence,
        )

        context_output = self._format_output(step)
        recommendations = self._generate_recommendations(step)

        result = ThinkResult(
            step=step,
            context_output=context_output,
            recommendations=recommendations,
        )

        self._thoughts.append(result)
        return result

    def _analyze(self, task: str, context: str, history: list[str]) -> str:
        words = task.split()
        task_type = "general"
        if any(w in task.lower() for w in ("what", "who", "where", "when")):
            task_type = "factual_query"
        elif any(w in task.lower() for w in ("how", "explain", "why")):
            task_type = "explanation"
        elif any(w in task.lower() for w in ("compare", "versus", "difference")):
            task_type = "comparison"
        elif any(w in task.lower() for w in ("solve", "calculate", "compute")):
            task_type = "computation"
        elif any(w in task.lower() for w in ("plan", "design", "strategy")):
            task_type = "planning"

        return f"Task type: {task_type} | Complexity: {'high' if len(words) > 20 else 'medium' if len(words) > 8 else 'low'} | History turns: {len(history)}"

    def _extract_available(self, context: str, history: list[str]) -> list[str]:
        available = []
        if context:
            sentences = [s.strip() for s in context.replace(".", ".").split(".") if s.strip()]
            available.extend(sentences[:5])
        for h in history[-3:]:
            available.append(f"Previous: {h[:100]}")
        return available

    def _identify_missing(self, task: str, context: str, available: list[str]) -> list[str]:
        missing = []
        task_words = set(task.lower().split())
        context_words = set(context.lower().split())
        gaps = task_words - context_words
        for gap in list(gaps)[:3]:
            if len(gap) > 3:
                missing.append(f"Missing context about '{gap}'")
        if not available:
            missing.append("No prior context available")
        return missing

    def _generate_approaches(self, task: str, context: str,
                              available: list[str], missing: list[str]) -> list[str]:
        approaches = []
        if not missing:
            approaches.append("Direct answer using available context")
        approaches.append("Search for additional information")
        if len(available) > 3:
            approaches.append("Synthesize from multiple context sources")
        approaches.append("Acknowledge uncertainty and provide partial answer")
        return approaches

    def _select_approach(self, approaches: list[str], task: str,
                          available: list[str]) -> tuple[str, str, float]:
        if not approaches:
            return "No approach available", "Insufficient information", 0.1

        scores = []
        for approach in approaches:
            score = 0.5
            if "direct" in approach.lower() and len(available) > 2:
                score += 0.3
            if "search" in approach.lower() and len(available) < 2:
                score += 0.2
            if "synthesi" in approach.lower() and len(available) > 4:
                score += 0.2
            if "uncertainty" in approach.lower():
                score -= 0.1
            scores.append(score)

        best_idx = scores.index(max(scores))
        selected = approaches[best_idx]
        confidence = min(1.0, scores[best_idx])
        reasoning = f"Selected '{selected}' based on {len(available)} available sources and {len(approaches)} options"

        return selected, reasoning, confidence

    def _format_output(self, step: ThinkStep) -> str:
        lines = ["[THINK]", ""]
        lines.append(f"Analysis: {step.analysis}")
        lines.append(f"Available: {', '.join(step.available_info[:3])}")
        if step.missing_info:
            lines.append(f"Missing: {', '.join(step.missing_info[:3])}")
        lines.append(f"Approaches: {len(step.approaches)} considered")
        lines.append(f"Selected: {step.selected_approach}")
        lines.append(f"Confidence: {step.confidence:.2f}")
        lines.append(f"Reasoning: {step.reasoning}")
        lines.append("")
        return "\n".join(lines)

    def _generate_recommendations(self, step: ThinkStep) -> list[str]:
        recs = []
        if step.confidence < 0.5:
            recs.append("Low confidence — consider gathering more information before proceeding")
        if step.missing_info:
            recs.append(f"Missing {len(step.missing_info)} pieces of information")
        if len(step.approaches) > 3:
            recs.append("Multiple viable approaches — evaluate trade-offs carefully")
        return recs

    def get_stats(self) -> dict:
        confidences = [t.step.confidence for t in self._thoughts]
        return {
            "total_thinks": len(self._thoughts),
            "avg_confidence": sum(confidences) / max(len(confidences), 1),
        }
