"""XMLTagPrompting — XML tag-based prompt organization.

Based on: Anthropic Prompt Engineering Guide

Key Concepts:
    1. XML tags organize prompt into clear sections
    2. Claude specifically trained to respect XML tags
    3. Tags create hierarchical structure in prompts
    4. Easier for models to parse than plain text
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


from dataclasses import dataclass, field


@dataclass
class PromptSection:
    tag: str = ""
    content: str = ""
    attributes: dict[str, str] = field(default_factory=dict)


class XMLTagPrompting:
    """XML tag-based prompt organization.

    Based on Anthropic's prompt engineering best practices.

    Usage:
        prompting = XMLTagPrompting()
        prompt = prompting.build([
            PromptSection("system", "You are a helpful assistant."),
            PromptSection("context", "User is asking about AI safety."),
            PromptSection("task", "Answer the user's question concisely."),
            PromptSection("constraints", "Max 200 words. Cite sources."),
        ])
    """

    def __init__(self):
        self._prompts: list[dict] = []

    def build(self, sections: list[PromptSection]) -> str:
        parts = []
        for section in sections:
            attrs = ""
            if section.attributes:
                attrs = " " + " ".join(f'{k}="{v}"' for k, v in section.attributes.items())
            parts.append(f"<{section.tag}{attrs}>\n{section.content}\n</{section.tag}>")
        prompt = "\n\n".join(parts)
        self._prompts.append({"sections": len(sections), "length": len(prompt)})
        return prompt

    def extract_section(self, prompt: str, tag: str) -> str | None:
        import re
        pattern = rf"<{tag}[^>]*>(.*?)</{tag}>"
        match = re.search(pattern, prompt, re.DOTALL)
        return match.group(1).strip() if match else None

    def extract_all_sections(self, prompt: str) -> dict[str, str]:
        import re
        sections = {}
        for match in re.finditer(r'<(\w+)[^>]*>(.*?)</\1>', prompt, re.DOTALL):
            sections[match.group(1)] = match.group(2).strip()
        return sections

    def get_stats(self) -> dict:
        return {"prompts_built": len(self._prompts)}
