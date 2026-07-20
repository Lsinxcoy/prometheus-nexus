"""StructuredOutput — JSON/XML structured output constraints.

Based on: OpenAI Cookbook + Anthropic Cookbook

Key Concepts:
    1. Force LLM output into specific format (JSON, XML, YAML)
    2. Schema validation of structured output
    3. Retry on format failure
    4. Structured output enables reliable downstream parsing
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import json
import re
from dataclasses import dataclass, field


@dataclass
class SchemaField:
    name: str = ""
    type: str = "string"
    required: bool = True
    description: str = ""


@dataclass
class OutputResult:
    content: str = ""
    parsed: dict | None = None
    valid: bool = False
    errors: list[str] = field(default_factory=list)


class StructuredOutput:
    """Structured output constraints for LLM responses.

    Usage:
        so = StructuredOutput()
        schema = [SchemaField("answer", "string", True), SchemaField("confidence", "number", True)]
        prompt = so.generate_schema_prompt(schema, format="json")
        result = so.validate('{"answer": "Paris", "confidence": 0.95}', schema)
    """

    def __init__(self):
        self._outputs: list[dict] = []

    def generate_schema_prompt(self, fields: list[SchemaField], format: str = "json") -> str:
        if format == "json":
            schema = {f.name: f"<{f.type}>" for f in fields}
            prompt = f"Respond ONLY with valid JSON matching this schema:\n{json.dumps(schema, indent=2)}"
        elif format == "xml":
            tags = "".join(f"<{f.name}>...</{f.name}>" for f in fields)
            prompt = f"Respond ONLY with XML tags:\n{tags}"
        else:
            prompt = f"Respond with structured {format} output with fields: {', '.join(f.name for f in fields)}"
        return prompt

    def validate(self, content: str, fields: list[SchemaField], format: str = "json") -> OutputResult:
        if format == "json":
            return self._validate_json(content, fields)
        elif format == "xml":
            return self._validate_xml(content, fields)
        return OutputResult(content=content, valid=True)

    def _validate_json(self, content: str, fields: list[SchemaField]) -> OutputResult:
        errors = []
        parsed = None
        try:
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
            else:
                parsed = json.loads(content)
        except json.JSONDecodeError as e:
            errors.append(f"JSON parse error: {e}")
            return OutputResult(content=content, valid=False, errors=errors)

        for field_def in fields:
            if field_def.required and field_def.name not in parsed:
                errors.append(f"Missing required field: {field_def.name}")
        return OutputResult(content=content, parsed=parsed, valid=len(errors) == 0, errors=errors)

    def _validate_xml(self, content: str, fields: list[SchemaField]) -> OutputResult:
        errors = []
        parsed = {}
        for field_def in fields:
            pattern = rf'<{field_def.name}>(.*?)</{field_def.name}>'
            match = re.search(pattern, content, re.DOTALL)
            if match:
                parsed[field_def.name] = match.group(1).strip()
            elif field_def.required:
                errors.append(f"Missing required tag: <{field_def.name}>")
        return OutputResult(content=content, parsed=parsed, valid=len(errors) == 0, errors=errors)

    def get_stats(self) -> dict:
        return {"outputs_processed": len(self._outputs)}
