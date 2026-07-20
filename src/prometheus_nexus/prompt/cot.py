"""CoTPrompter — Chain-of-thought with step decomposition.

Based on: "Chain-of-Thought Prompting Elicits Reasoning in Large Language Models"
(arXiv:2201.11903, Wei et al. 2022)

Key Concepts from Paper:
    1. "Let's think step by step" prompt significantly improves reasoning
    2. Intermediate reasoning steps enable complex problem solving
    3. CoT improves performance on arithmetic, commonsense, symbolic reasoning

Paper Finding:
    "CoT prompting improves performance on MultiArith by +12%,
     StrategyQA by +10%, and CommonsenseQA by +7%"

Algorithm:
    1. Classify problem type
    2. Decompose into reasoning steps
    3. Generate step-by-step solution
    4. Synthesize final answer
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import re


class CoTPrompter:
    """Chain-of-thought prompting with step decomposition.

    Based on CoT paper (arXiv:2201.11903).

    Usage:
        cot = CoTPrompter()
        prompt = cot.generate("Why is the sky blue?")
        # Returns structured step-by-step reasoning prompt
    """

    # Problem type patterns
    _PATTERNS = {
        "explanation": [r"why", r"how", r"explain", r"describe", r"what is"],
        "comparison": [r"compare", r"contrast", r"difference", r"versus", r"better"],
        "computation": [r"solve", r"calculate", r"compute", r"find", r"number"],
        "debugging": [r"debug", r"fix", r"error", r"bug", r"issue"],
        "design": [r"design", r"build", r"create", r"implement", r"architect"],
        "analysis": [r"analyze", r"evaluate", r"assess", r"review", r"critique"],
        "planning": [r"plan", r"strategy", r"approach", r"method", r"roadmap"],
    }

    # Step templates per problem type
    _TEMPLATES = {
        "explanation": [
            "Identify the key concepts involved",
            "Define the relationships between concepts",
            "Trace the logical chain from cause to effect",
            "Synthesize a clear, concise explanation",
        ],
        "comparison": [
            "Identify the entities or options to compare",
            "List key attributes of each",
            "Find similarities and differences",
            "Evaluate which is better for what context",
            "Provide a nuanced conclusion",
        ],
        "computation": [
            "Understand what is being asked",
            "Identify known values and constraints",
            "Choose the right formula or approach",
            "Execute the computation step by step",
            "Verify the result with a sanity check",
        ],
        "debugging": [
            "Reproduce the error precisely",
            "Identify the root cause from symptoms",
            "Generate potential fixes",
            "Evaluate each fix for side effects",
            "Apply the best fix and verify",
        ],
        "design": [
            "Clarify requirements and constraints",
            "Design the high-level architecture",
            "Identify key components and interfaces",
            "Plan implementation order",
            "Consider edge cases and failure modes",
        ],
        "analysis": [
            "Define the evaluation criteria",
            "Gather relevant evidence",
            "Analyze strengths and weaknesses",
            "Identify patterns and anomalies",
            "Synthesize findings into actionable insights",
        ],
        "planning": [
            "Define the goal and success criteria",
            "Identify required resources and dependencies",
            "Break into sequential milestones",
            "Estimate effort and risks for each",
            "Create a prioritized action plan",
        ],
    }

    def __init__(self):
        self._prompts: list[dict] = []

    def generate(self, task: str) -> str:
        """Generate a chain-of-thought prompt for the given task.

        Args:
            task: The task or question to reason about.

        Returns:
            Structured CoT prompt with reasoning steps.
        """
        problem_type = self._classify(task)
        steps = self._get_steps(problem_type, task)
        sub_questions = self._get_sub_questions(task, problem_type)

        prompt = f"Let's think step by step about: {task}\n\n"
        prompt += f"**Problem type**: {problem_type}\n\n"
        prompt += "**Reasoning steps**:\n"
        for i, step in enumerate(steps, 1):
            prompt += f"{i}. {step}\n"

        if sub_questions:
            prompt += "\n**Sub-questions to consider**:\n"
            for sq in sub_questions:
                prompt += f"- {sq}\n"

        prompt += f"\n**Conclusion**:"
        self._prompts.append({"task": task, "type": problem_type, "steps": steps,
                              "sub_questions": sub_questions, "prompt": prompt})
        return prompt

    def _classify(self, task: str) -> str:
        """Classify the problem type."""
        task_lower = task.lower()
        scores = {}
        for ptype, patterns in self._PATTERNS.items():
            score = sum(1 for p in patterns if re.search(p, task_lower))
            if score > 0:
                scores[ptype] = score
        return max(scores, key=scores.get) if scores else "general"

    def _get_steps(self, problem_type: str, task: str) -> list[str]:
        """Get reasoning steps for the problem type."""
        return self._TEMPLATES.get(problem_type, [
            "Understand the question precisely",
            "Identify relevant knowledge and principles",
            "Apply systematic reasoning",
            "Formulate a clear answer",
        ])

    def _get_sub_questions(self, task: str, problem_type: str) -> list[str]:
        """Generate sub-questions for deeper reasoning."""
        sub_questions = []
        if problem_type == "explanation":
            sub_questions = [
                "What is the direct cause?",
                "What are the underlying mechanisms?",
                "What evidence supports this?",
            ]
        elif problem_type == "comparison":
            sub_questions = [
                "What are the key dimensions of comparison?",
                "What are the trade-offs?",
            ]
        elif problem_type == "debugging":
            sub_questions = [
                "What is the expected behavior?",
                "What is the actual behavior?",
                "What changed recently?",
            ]
        else:
            words = task.split()
            if len(words) > 5:
                sub_questions = [
                    f"What does '{task[:50]}' mean in this context?",
                    f"What are the implications?",
                ]
        return sub_questions

    def get_stats(self) -> dict:
        return {"prompts": len(self._prompts)}
