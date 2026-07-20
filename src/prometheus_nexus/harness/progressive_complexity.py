"""ProgressiveComplexity — Progressive complexity architecture.

Based on: "Building Effective AI Agents" (Anthropic, 2024)

Key Principle:
    "Start simple, increase complexity only when needed."
    1. Single LLM call for simple tasks
    2. Chained calls for multi-step tasks
    3. Full agent loop for complex tasks
    4. Nested loops for research-level tasks
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import time
from dataclasses import dataclass, field
from enum import Enum


class ComplexityLevel(Enum):
    SINGLE = "single_call"
    CHAINED = "chained_calls"
    LOOP = "agent_loop"
    NESTED = "nested_loops"


@dataclass
class ComplexityAssessment:
    level: ComplexityLevel = ComplexityLevel.SINGLE
    score: float = 0.0
    factors: dict[str, float] = field(default_factory=dict)
    recommendation: str = ""


class ProgressiveComplexity:
    """Progressive complexity architecture.

    Based on Anthropic's "Building Effective Agents" (2024).

    Usage:
        pc = ProgressiveComplexity()
        assessment = pc.assess(
            task_description="Research and write a report",
            context_tokens=5000,
            requires_tools=True,
            requires_iteration=True,
        )
        print(assessment.level)  # ComplexityLevel.LOOP or NESTED
    """

    def __init__(self):
        self._assessments: list[dict] = []

    def assess(self, task_description: str = "", context_tokens: int = 0,
               requires_tools: bool = False, requires_iteration: bool = False,
               requires_multi_agent: bool = False) -> ComplexityAssessment:
        factors = {}

        word_count = len(task_description.split())
        factors["task_length"] = min(1.0, word_count / 50)

        factors["context_size"] = min(1.0, context_tokens / 50000)

        factors["tool_requirement"] = 0.3 if requires_tools else 0.0

        factors["iteration_requirement"] = 0.4 if requires_iteration else 0.0

        factors["multi_agent"] = 0.3 if requires_multi_agent else 0.0

        score = sum(factors.values()) / len(factors)

        if score < 0.2:
            level = ComplexityLevel.SINGLE
            rec = "Use a single LLM call"
        elif score < 0.4:
            level = ComplexityLevel.CHAINED
            rec = "Chain multiple LLM calls with clear handoffs"
        elif score < 0.7:
            level = ComplexityLevel.LOOP
            rec = "Implement agent loop with tool use and reflection"
        else:
            level = ComplexityLevel.NESTED
            rec = "Use nested loops with sub-agents and orchestration"

        result = ComplexityAssessment(
            level=level, score=score,
            factors=factors, recommendation=rec,
        )

        self._assessments.append({
            "level": level.value,
            "score": score,
        })
        return result

    def get_stats(self) -> dict:
        levels = [a["level"] for a in self._assessments]
        from collections import Counter
        return {"assessments": len(self._assessments), "level_distribution": dict(Counter(levels))}
