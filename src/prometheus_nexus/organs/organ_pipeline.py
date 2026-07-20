"""FiveOrganPipeline — 5-organ cognitive pipeline with real data processing.

Based on: Biological cognitive architecture metaphor.
Each organ performs real transformations on the data flowing through.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import time
import re


class FiveOrganPipeline:
    def __init__(self):
        self._executions: list[dict] = []
        self._organ_states: dict[str, dict] = {
            name: {"status": "idle", "processed": 0, "avg_latency_ms": 0.0}
            for name in ["perception", "processing", "memory", "decision", "action"]
        }
        self._data_log: list[dict] = []

    def execute(self, data: dict | None = None) -> dict:
        data = data or {"action": "maintain"}
        start = time.time()
        organs_processed = []
        current_data = dict(data)

        for organ_name in ["perception", "processing", "memory", "decision", "action"]:
            organ_start = time.time()
            self._organ_states[organ_name]["status"] = "processing"

            if organ_name == "perception":
                current_data = self._perception_organ(current_data)
            elif organ_name == "processing":
                current_data = self._processing_organ(current_data)
            elif organ_name == "memory":
                current_data = self._memory_organ(current_data)
            elif organ_name == "decision":
                current_data = self._decision_organ(current_data)
            elif organ_name == "action":
                current_data = self._action_organ(current_data)

            organ_elapsed = (time.time() - organ_start) * 1000
            self._organ_states[organ_name]["processed"] += 1
            prev_avg = self._organ_states[organ_name]["avg_latency_ms"]
            count = self._organ_states[organ_name]["processed"]
            self._organ_states[organ_name]["avg_latency_ms"] = prev_avg * (count - 1) / count + organ_elapsed / count
            self._organ_states[organ_name]["status"] = "idle"
            organs_processed.append(organ_name)

        elapsed = (time.time() - start) * 1000
        result = {
            "executed": True,
            "organs_processed": organs_processed,
            "elapsed_ms": elapsed,
            "output": current_data,
        }
        self._executions.append(result)
        self._data_log.append({"input": data, "output": current_data, "elapsed_ms": elapsed})
        return result

    def _perception_organ(self, data: dict) -> dict:
        content = str(data.get("content", data.get("action", "")))
        words = content.split()
        unique_words = set(w.lower() for w in words)
        data["perception"] = {
            "word_count": len(words),
            "unique_words": len(unique_words),
            "has_numbers": bool(re.search(r'\d', content)),
            "has_code": bool(re.search(r'[{}\[\]();]', content)),
            "complexity_hint": "high" if len(words) > 50 else "medium" if len(words) > 10 else "low",
        }
        return data

    def _processing_organ(self, data: dict) -> dict:
        perception = data.get("perception", {})
        keywords = []
        content = str(data.get("content", data.get("action", "")))
        for word in content.split():
            if len(word) > 4 and word[0].isupper():
                keywords.append(word)
        data["processing"] = {
            "keywords_extracted": keywords[:10],
            "estimated_importance": min(1.0, len(keywords) * 0.1 + 0.3),
            "requires_memory": perception.get("complexity_hint") == "high",
        }
        return data

    def _memory_organ(self, data: dict) -> dict:
        processing = data.get("processing", {})
        data["memory"] = {
            "should_store": processing.get("estimated_importance", 0) > 0.4,
            "relevant_keywords": processing.get("keywords_extracted", []),
            "storage_priority": "high" if processing.get("estimated_importance", 0) > 0.7 else "normal",
        }
        return data

    def _decision_organ(self, data: dict) -> dict:
        memory_info = data.get("memory", {})
        processing = data.get("processing", {})
        importance = processing.get("estimated_importance", 0.5)
        data["decision"] = {
            "action_type": data.get("action", "unknown"),
            "confidence": importance,
            "should_proceed": importance > 0.3,
            "risk_level": "low" if importance < 0.5 else "medium" if importance < 0.8 else "high",
        }
        return data

    def _action_organ(self, data: dict) -> dict:
        decision = data.get("decision", {})
        data["action_result"] = {
            "executed": decision.get("should_proceed", True),
            "action_type": decision.get("action_type", "unknown"),
            "confidence": decision.get("confidence", 0.5),
            "status": "completed",
        }
        return data

    def get_stats(self) -> dict:
        return {
            "executions": len(self._executions),
            "organ_states": {k: {"processed": v["processed"], "avg_latency_ms": round(v["avg_latency_ms"], 2)}
                            for k, v in self._organ_states.items()},
        }
