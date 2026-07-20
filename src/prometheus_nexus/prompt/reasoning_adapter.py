"""ReasoningModelAdapter — Adapts prompts for reasoning models (o1/o3).

Based on: OpenAI Reasoning Models Guide

Key Concepts:
    1. Reasoning models (o1, o3, o4) work better with简洁 instructions
    2. Detailed prompts反而降低推理模型性能
    3. Avoid "think step by step" — model already does internal reasoning
    4. Focus on what to solve, not how to solve it
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import re
from dataclasses import dataclass, field


class ModelType:
    STANDARD = "standard"
    REASONING = "reasoning"  # o1, o3, o4


@dataclass
class AdaptedPrompt:
    original: str = ""
    adapted: str = ""
    model_type: str = ""
    changes: list[str] = field(default_factory=list)


class ReasoningModelAdapter:
    """Adapts prompts for reasoning models.

    Usage:
        adapter = ReasoningModelAdapter()
        adapted = adapter.adapt("Think step by step and explain why...", ModelType.REASONING)
        print(adapted.adapted)  # Simplified version
    """

    WORDY_PATTERNS = [
        "think step by step",
        "let's think about this",
        "reason through",
        "explain your reasoning",
        "show your work",
        "walk through",
    ]

    def __init__(self):
        self._adaptations: list[dict] = []

    def adapt(self, prompt: str, model_type: str = ModelType.STANDARD) -> AdaptedPrompt:
        if model_type == ModelType.STANDARD:
            return AdaptedPrompt(original=prompt, adapted=prompt, model_type=model_type)

        adapted = prompt
        changes = []

        for pattern in self.WORDY_PATTERNS:
            if pattern in adapted.lower():
                adapted = re.sub(re.escape(pattern), "", adapted, flags=re.IGNORECASE)
                changes.append(f"Removed redundant reasoning instruction: '{pattern}'")

        adapted = " ".join(adapted.split())
        if adapted != prompt:
            changes.append("Cleaned whitespace")

        adapted = re.sub(r'\b(step\s+\d+[:.])\s*', '', adapted, flags=re.IGNORECASE)
        if adapted != prompt:
            changes.append("Removed step numbering")

        if not changes:
            changes.append("No changes needed")

        result = AdaptedPrompt(
            original=prompt, adapted=adapted,
            model_type=model_type, changes=changes,
        )
        self._adaptations.append({"model_type": model_type, "changes": len(changes)})
        return result

    def get_stats(self) -> dict:
        return {"total_adaptations": len(self._adaptations)}

