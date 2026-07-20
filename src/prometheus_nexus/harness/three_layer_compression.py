"""ThreeLayerCompression — Three-layer compression protocol.

Based on: MiMo Self-Evolution System #6.1 (三层压缩协议)

Three layers:
    Layer 1: Summary (≤100 token) → inject into parent context
    Layer 2: Key Insights (3-5 items) → inject into parent context
    Layer 3: Behavior Modifications (1-2 items) → inject into parent context
    Original result → write to file

Triggered when sub-agent result > 500 tokens.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import re
from dataclasses import dataclass, field


@dataclass
class CompressionLayers:
    summary: str = ""
    key_insights: list[str] = field(default_factory=list)
    behavior_modifications: list[str] = field(default_factory=list)
    original_length: int = 0
    compressed_length: int = 0


class ThreeLayerCompression:
    """Three-layer compression protocol.

    Based on MiMo Self-Evolution System.

    Usage:
        tlc = ThreeLayerCompression()
        result = tlc.compress(
            raw_output="Long analysis of AI memory systems with detailed findings...",
            max_summary_tokens=100,
            max_insights=5,
        )
        print(result.summary)
        print(result.key_insights)
    """

    def __init__(self):
        self._stats = {"compressions": 0, "tokens_saved": 0}

    def compress(self, raw_output: str, max_summary_tokens: int = 100,
                 max_insights: int = 5, max_modifications: int = 2) -> CompressionLayers:
        """Compress raw output into three layers.

        Layer 1: Summary — most important sentence
        Layer 2: Key Insights — extracted findings
        Layer 3: Behavior Modifications — actionable changes
        """
        original_length = len(raw_output.split())

        # Layer 1: Extract summary (first meaningful sentence)
        sentences = re.split(r'[.!?]+', raw_output)
        meaningful = [s.strip() for s in sentences if len(s.strip()) > 20]
        summary = meaningful[0] if meaningful else raw_output[:200]
        summary_tokens = len(summary.split())

        # Layer 2: Extract key insights
        insights = []
        for sentence in meaningful[1:max_insights + 1]:
            if any(w in sentence.lower() for w in
                   ["key", "important", "finding", "result", "conclusion",
                    "discovered", "shows", "proves", "significant"]):
                insights.append(sentence.strip())
            elif len(insights) < 2:
                insights.append(sentence.strip())
        insights = insights[:max_insights]

        # Layer 3: Extract behavior modifications
        modifications = []
        for sentence in meaningful:
            if any(w in sentence.lower() for w in
                   ["should", "must", "change", "modify", "replace",
                    "add", "remove", "implement", "behavior"]):
                modifications.append(sentence.strip())
            if len(modifications) >= max_modifications:
                break

        compressed_length = len(summary.split()) + sum(len(i.split()) for i in insights)

        result = CompressionLayers(
            summary=summary[:500],
            key_insights=insights,
            behavior_modifications=modifications,
            original_length=original_length,
            compressed_length=compressed_length,
        )

        self._stats["compressions"] += 1
        self._stats["tokens_saved"] += max(0, original_length - compressed_length)

        return result

    def get_stats(self) -> dict:
        return dict(self._stats)
