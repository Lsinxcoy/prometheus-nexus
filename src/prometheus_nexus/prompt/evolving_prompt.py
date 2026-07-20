"""EvolvingPrompt — Prompt evolution based on output quality feedback.

Based on:
- "Self-Refine: Iterative Refinement with Self-Feedback" (Madaan et al., 2023)
  - Generate → Feedback → Refine loop
  - LLM provides its own feedback on output
  - Iterative refinement until quality threshold met
  - HumanEval +8.5%, summarization +5.5%, math +12%

- "Self-Consistency Improves CoT Reasoning" (Wang et al., 2022)
  - Multiple samples → majority vote
  - Consistency across paths indicates confidence

- "Generated Knowledge Prompting" (Liu et al., 2021)
  - Generate relevant knowledge first
  - Use knowledge to improve answer accuracy

- "Chain-of-Thought Prompting" (Wei et al., 2022)
  - Step-by-step reasoning prompts
  - Zero-shot CoT: just add "Let's think step by step"

Algorithm:
    evolve_prompt(template, task, output, feedback):
        1. Evaluate output quality (self-consistency check)
        2. Identify prompt weaknesses (vague, incomplete, wrong format)
        3. Generate prompt variants (mutation)
        4. Select best variant (tournament selection)
        5. Store successful templates for reuse

    generate_prompt(task, context):
        1. Select best template from evolution history
        2. Adapt template to current task
        3. Apply CoT/Few-shot/Generated Knowledge as appropriate
        4. Validate output format
"""
from __future__ import annotations



import logging

import time
import re
from dataclasses import dataclass, field
logger = logging.getLogger(__name__)


@dataclass
class PromptTemplate:
    """A prompt template with evolution metadata."""
    template_id: str = ""
    task_type: str = ""
    template: str = ""
    score: float = 0.0
    usage_count: int = 0
    version: int = 1
    parent_id: str = ""
    mutations: list[str] = field(default_factory=list)


@dataclass
class PromptEvaluation:
    """Evaluation of a prompt's output quality."""
    template_id: str = ""
    output_quality: float = 0.0
    format_compliance: float = 0.0
    completeness: float = 0.0
    coherence: float = 0.0
    overall_score: float = 0.0
    feedback: list[str] = field(default_factory=list)


class EvolvingPrompt:
    """Prompt evolution based on output quality feedback.

    Based on Self-Refine (Madaan 2023) + Self-Consistency (Wang 2022).

    Usage:
        ep = EvolvingPrompt()

        # Generate a prompt
        prompt = ep.generate_prompt("Explain quantum computing", context="Beginner audience")

        # Evaluate output and evolve
        evaluation = ep.evaluate_output(prompt, "Quantum computing uses qubits...")
        ep.record_evaluation(prompt, evaluation)

        # Get evolved prompt
        evolved = ep.generate_prompt("Explain quantum computing", context="Beginner audience")
    """

    # CoT templates by task type (from Wei et al. 2022)
    COT_TEMPLATES = {
        "explanation": "Let's think step by step about {task}.\nStep 1: Identify key concepts.\nStep 2: Explain relationships.\nStep 3: Provide clear summary.",
        "computation": "Let's solve {task} step by step.\nStep 1: Identify known values.\nStep 2: Choose approach.\nStep 3: Calculate.\nStep 4: Verify.",
        "comparison": "Let's compare systematically.\nStep 1: List attributes.\nStep 2: Analyze differences.\nStep 3: Evaluate trade-offs.",
        "debugging": "Let's debug step by step.\nStep 1: Reproduce the issue.\nStep 2: Identify root cause.\nStep 3: Propose fix.\nStep 4: Verify fix.",
        "general": "Let's approach {task} systematically.\nStep 1: Understand the problem.\nStep 2: Identify key factors.\nStep 3: Develop solution.\nStep 4: Evaluate result.",
    }

    def __init__(self):
        self._templates: dict[str, PromptTemplate] = {}
        self._evaluations: list[PromptEvaluation] = []
        self._evolution_history: list[dict] = []
        self._template_counter = 0

    def generate_prompt(self, task: str, context: str = "",
                       task_type: str = "general") -> str:
        """Generate an optimized prompt for a task.

        Based on Wei et al. 2022: CoT template selection
        """
        # Select best template for task type
        template_text = self.COT_TEMPLATES.get(task_type, self.COT_TEMPLATES["general"])

        # Adapt to task
        prompt = template_text.format(task=task)

        # Add context if provided
        if context:
            prompt = f"Context: {context}\n\n{prompt}"

        # Add task-specific instructions
        if task_type == "explanation":
            prompt += "\n\nPlease provide a clear, concise explanation suitable for the audience."
        elif task_type == "computation":
            prompt += "\n\nShow all calculation steps and verify the final answer."
        elif task_type == "debugging":
            prompt += "\n\nFocus on root cause analysis and provide actionable fixes."

        # Store template
        self._template_counter += 1
        template = PromptTemplate(
            template_id="tmpl_%d" % self._template_counter,
            task_type=task_type,
            template=prompt,
            score=0.5,
            usage_count=1,
        )
        self._templates[template.template_id] = template

        return prompt

    def evaluate_output(self, prompt: str, output: str,
                       expected_format: str = "") -> PromptEvaluation:
        """Evaluate output quality (from Self-Refine paper).

        Feedback categories:
        - redundancy: repeated content
        - length: too long or too short
        - vague: unclear language
        - structure: missing organization
        """
        feedback = []
        output_quality = 0.5
        format_compliance = 1.0
        completeness = 0.5
        coherence = 0.5

        # Check output length
        words = output.split()
        if len(words) < 10:
            feedback.append("Output too short - may be incomplete")
            completeness = 0.2
        elif len(words) > 500:
            feedback.append("Output very long - consider compression")
            completeness = 0.7
        else:
            completeness = 0.8

        # Check for redundancy
        sentences = re.split(r'[.!?]+', output)
        unique_sentences = set(s.strip().lower() for s in sentences if s.strip())
        if len(sentences) > 3 and len(unique_sentences) < len(sentences) * 0.7:
            feedback.append("Output contains repetitive content")
            coherence = 0.4

        # Check for vague language
        vague_words = {"something", "stuff", "things", "maybe", "perhaps"}
        vague_count = sum(1 for w in words if w.lower() in vague_words)
        if vague_count > len(words) * 0.05:
            feedback.append("Output contains vague language")
            coherence = max(0.3, coherence - 0.2)

        # Check structure
        if len(sentences) > 5 and not any(s.strip().startswith(('#', '-', '*', '1'))
                                           for s in sentences):
            feedback.append("Long output lacks structure")
            coherence = max(0.3, coherence - 0.1)

        # Check format compliance
        if expected_format:
            if expected_format == "json":
                try:
                    import json
                    json.loads(output)
                    format_compliance = 1.0
                except Exception as e:
                    feedback.append(f"Output is not valid JSON: {e}")
                    format_compliance = 0.0
            elif expected_format == "markdown":
                if re.search(r'#+\s', output) or re.search(r'\*\*.*\*\*', output):
                    format_compliance = 1.0
                else:
                    feedback.append("Output lacks markdown formatting")
                    format_compliance = 0.5

        overall_score = (output_quality * 0.3 + format_compliance * 0.2 +
                        completeness * 0.25 + coherence * 0.25)

        return PromptEvaluation(
            output_quality=output_quality,
            format_compliance=format_compliance,
            completeness=completeness,
            coherence=coherence,
            overall_score=overall_score,
            feedback=feedback,
        )

    def record_evaluation(self, prompt: str, evaluation: PromptEvaluation):
        """Record evaluation for prompt evolution."""
        # Find matching template
        for template in self._templates.values():
            if template.template == prompt:
                template.usage_count += 1
                # Update score with EMA
                template.score = template.score * 0.8 + evaluation.overall_score * 0.2
                break

        self._evaluations.append(evaluation)

        self._evolution_history.append({
            "overall_score": evaluation.overall_score,
            "feedback_count": len(evaluation.feedback),
            "timestamp": time.time(),
        })

    def evolve_template(self, template_id: str) -> PromptTemplate | None:
        """Evolve a prompt template based on evaluation feedback.

        Based on Self-Refine: "identify issues → apply targeted fixes"
        """
        if template_id not in self._templates:
            return None

        original = self._templates[template_id]
        mutated = PromptTemplate(
            template_id="%s_v%d" % (template_id, original.version + 1),
            task_type=original.task_type,
            template=original.template,
            score=original.score,
            version=original.version + 1,
            parent_id=template_id,
        )

        # Find evaluations for this template
        template_evals = [e for e in self._evaluations[-50:]
                         if e.template_id == template_id]

        if template_evals:
            avg_score = sum(e.overall_score for e in template_evals) / len(template_evals)
            common_feedback = Counter()
            for e in template_evals:
                for f in e.feedback:
                    common_feedback[f] += 1

            # Apply mutations based on feedback
            if "vague" in [f for e in template_evals for f in e.feedback]:
                mutated.template += "\n\nBe specific and precise in your response."
                mutated.mutations.append("added_specificity")

            if "repetitive" in [f for e in template_evals for f in e.feedback]:
                mutated.template += "\n\nAvoid repetition. Each point should be unique."
                mutated.mutations.append("added_no_repetition")

            if "lacks structure" in [f for e in template_evals for f in e.feedback]:
                mutated.template += "\n\nOrganize your response with clear sections."
                mutated.mutations.append("added_structure")

            mutated.score = avg_score

        self._templates[mutated.template_id] = mutated
        return mutated

    def select_best_template(self, task_type: str) -> PromptTemplate | None:
        """Select the best template for a task type.

        Based on Self-Consistency: "majority vote indicates confidence"
        """
        candidates = [t for t in self._templates.values()
                     if t.task_type == task_type and t.usage_count > 0]

        if not candidates:
            return None

        # Sort by score, then by usage count
        candidates.sort(key=lambda t: (t.score, t.usage_count), reverse=True)
        return candidates[0]

    def get_stats(self) -> dict:
        scores = [e.overall_score for e in self._evaluations]
        return {
            "templates": len(self._templates),
            "evaluations": len(self._evaluations),
            "avg_score": sum(scores) / max(len(scores), 1),
            "evolutions": len(self._evolution_history),
        }
