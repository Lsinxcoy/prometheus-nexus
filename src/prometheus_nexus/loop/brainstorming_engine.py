"""BrainstormingEngine — Socratic design refinement for evolution.

Based on: obra/superpowers brainstorming skill
Key insight: Ask "what are you really trying to do?" before jumping to implementation.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import re
from dataclasses import dataclass, field


@dataclass
class DesignQuestion:
    question: str = ""
    purpose: str = ""
    category: str = ""  # goal, constraint, alternative, risk


@dataclass
class DesignSection:
    title: str = ""
    content: str = ""
    validated: bool = False


@dataclass
class BrainstormingResult:
    topic: str = ""
    clarifying_questions: list[DesignQuestion] = field(default_factory=list)
    design_sections: list[DesignSection] = field(default_factory=list)
    alternatives_explored: list[str] = field(default_factory=list)
    risks_identified: list[str] = field(default_factory=list)
    final_design: str = ""
    ready_for_planning: bool = False


class BrainstormingEngine:
    """Socratic design refinement engine.

    Based on Superpowers brainstorming skill:
    1. Ask clarifying questions about the real goal
    2. Explore alternatives
    3. Present design in digestible sections
    4. Validate each section before proceeding
    """

    GOAL_QUESTIONS = [
        "What is the core problem you're trying to solve?",
        "What does success look like?",
        "What are the constraints?",
        "Who benefits from this?",
    ]

    ALTERNATIVE_QUESTIONS = [
        "What other approaches have you considered?",
        "What would happen if we did nothing?",
        "Is there a simpler way?",
        "What are the trade-offs?",
    ]

    RISK_QUESTIONS = [
        "What could go wrong?",
        "What are the dependencies?",
        "What's the rollback plan?",
        "What metrics will we track?",
    ]

    def __init__(self):
        self._history: list[dict] = []
        self._designs: list[BrainstormingResult] = []

    def brainstorm(self, topic: str, context: str = "",
                   max_questions: int = 4) -> BrainstormingResult:
        result = BrainstormingResult(topic=topic)

        goal_qs = self._generate_goal_questions(topic, context)
        result.clarifying_questions.extend(goal_qs[:max_questions])

        alt_qs = self._generate_alternative_questions(topic, context)
        result.clarifying_questions.extend(alt_qs[:2])

        risk_qs = self._generate_risk_questions(topic, context)
        result.clarifying_questions.extend(risk_qs[:2])

        result.alternatives_explored = self._explore_alternatives(topic, context)
        result.risks_identified = self._identify_risks(topic, context)

        result.design_sections = self._generate_design_sections(topic, context)
        result.final_design = self._synthesize_design(topic, result)
        result.ready_for_planning = len(result.design_sections) >= 2

        self._history.append({
            "topic": topic, "questions": len(result.clarifying_questions),
            "sections": len(result.design_sections),
        })
        self._designs.append(result)

        return result

    def _generate_goal_questions(self, topic: str, context: str) -> list[DesignQuestion]:
        questions = []
        topic_words = set(topic.lower().split())

        if any(w in topic_words for w in ["improve", "optimize", "enhance"]):
            questions.append(DesignQuestion(
                question="What specific metric will define 'improved'?",
                purpose="Establish measurable success criteria",
                category="goal",
            ))

        if any(w in topic_words for w in ["add", "create", "build"]):
            questions.append(DesignQuestion(
                question="What existing functionality does this replace or complement?",
                purpose="Understand integration scope",
                category="goal",
            ))

        if any(w in topic_words for w in ["fix", "repair", "debug"]):
            questions.append(DesignQuestion(
                question="What is the root cause, not just the symptom?",
                purpose="Prevent surface-level fixes",
                category="goal",
            ))

        for q in self.GOAL_QUESTIONS:
            if len(questions) >= 3:
                break
            questions.append(DesignQuestion(
                question=q, purpose="Clarify core objective", category="goal",
            ))

        return questions

    def _generate_alternative_questions(self, topic: str, context: str) -> list[DesignQuestion]:
        questions = []
        for q in self.ALTERNATIVE_QUESTIONS[:2]:
            questions.append(DesignQuestion(
                question=q, purpose="Explore alternatives", category="alternative",
            ))
        return questions

    def _generate_risk_questions(self, topic: str, context: str) -> list[DesignQuestion]:
        questions = []
        for q in self.RISK_QUESTIONS[:2]:
            questions.append(DesignQuestion(
                question=q, purpose="Identify risks", category="risk",
            ))
        return questions

    def _explore_alternatives(self, topic: str, context: str) -> list[str]:
        alternatives = []
        topic_lower = topic.lower()

        if "improve" in topic_lower or "optimize" in topic_lower:
            alternatives.append("Measure current baseline before improving")
            alternatives.append("Consider if the improvement is within budget")

        if "add" in topic_lower or "create" in topic_lower:
            alternatives.append("Check if existing mechanism can be extended")
            alternatives.append("Consider minimal viable implementation first")

        if "fix" in topic_lower:
            alternatives.append("Write a test that reproduces the issue first")
            alternatives.append("Check if the fix introduces new regressions")

        alternatives.append("Simplify the problem before solving it")
        alternatives.append("Consider if this is a one-time fix or recurring need")

        return alternatives[:4]

    def _identify_risks(self, topic: str, context: str) -> list[str]:
        risks = []
        topic_lower = topic.lower()

        if any(w in topic_lower for w in ["memory", "cache", "store"]):
            risks.append("Memory leak or unbounded growth")
            risks.append("Data corruption on crash")

        if any(w in topic_lower for w in ["evolve", "mutate", "change"]):
            risks.append("Regression in existing functionality")
            risks.append("Performance degradation")

        if any(w in topic_lower for w in ["parallel", "concurrent", "async"]):
            risks.append("Race condition or deadlock")
            risks.append("Inconsistent state")

        risks.append("Complexity increase without proportional benefit")
        risks.append("Dependency on external services")

        return risks[:4]

    def _generate_design_sections(self, topic: str, context: str) -> list[DesignSection]:
        sections = []
        sections.append(DesignSection(
            title="Problem Statement",
            content="Addressing: %s. Context: %s" % (topic, context[:200] if context else "general improvement"),
        ))
        sections.append(DesignSection(
            title="Proposed Solution",
            content="Implement changes to %s with focus on correctness and minimal complexity." % topic,
        ))
        sections.append(DesignSection(
            title="Verification Plan",
            content="Test with existing test suite + add targeted tests for new behavior.",
        ))
        return sections

    def _synthesize_design(self, topic: str, result: BrainstormingResult) -> str:
        parts = ["Design for '%s':" % topic]
        parts.append("- Problem: %s" % topic)
        parts.append("- Questions answered: %d" % len(result.clarifying_questions))
        parts.append("- Alternatives: %d" % len(result.alternatives_explored))
        parts.append("- Risks: %d" % len(result.risks_identified))
        parts.append("- Sections: %d" % len(result.design_sections))
        return "\n".join(parts)

    def get_stats(self) -> dict:
        return {"brainstorms": len(self._history), "designs": len(self._designs)}
