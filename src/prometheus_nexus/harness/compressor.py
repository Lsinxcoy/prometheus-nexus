"""ContextCompressor — Semantic-aware context compression.

Enhanced with token counting and priority-based compression.
Based on:
- "Don't Build Multi-Agents" (Cognition 2025): "Compression is the #1 job"
- Anthropic Multi-Agent Research: "Subagents facilitate compression"
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import re
from dataclasses import dataclass, field


@dataclass
class CompressionResult:
    text: str = ""
    original_tokens: int = 0
    compressed_tokens: int = 0
    ratio: float = 0.0
    sentences_kept: int = 0
    sentences_total: int = 0


class ContextCompressor:
    """Semantic-aware context compression with token counting.

    Based on Cognition's compression principles (2025).

    Usage:
        comp = ContextCompressor(target_ratio=0.5)
        result = comp.compress_with_stats("Long text here...")
        print(f"Compressed {result.original_tokens} → {result.compressed_tokens} tokens")
    """

    IMPORTANT_WORDS = {
        "key", "important", "result", "conclusion", "therefore", "however",
        "critical", "significant", "main", "primary", "essential", "crucial",
    }

    def __init__(self, target_ratio: float = 0.5, max_tokens: int = 4000):
        self._target_ratio = target_ratio
        self._max_tokens = max_tokens
        self._compressions = 0
        self._total_saved = 0
        self._total_tokens_saved = 0

    def compress(self, text: str) -> str:
        result = self.compress_with_stats(text)
        return result.text

    def compress_with_stats(self, text: str) -> CompressionResult:
        self._compressions += 1
        original_tokens = self._estimate_tokens(text)

        if original_tokens <= self._max_tokens:
            return CompressionResult(
                text=text,
                original_tokens=original_tokens,
                compressed_tokens=original_tokens,
                ratio=1.0,
                sentences_kept=0,
                sentences_total=0,
            )

        sentences = re.split(r'(?<=[.!?])\s+', text)
        if len(sentences) <= 3:
            compressed = text[:500] + "..." + text[-200:]
            compressed_tokens = self._estimate_tokens(compressed)
            return CompressionResult(
                text=compressed,
                original_tokens=original_tokens,
                compressed_tokens=compressed_tokens,
                ratio=compressed_tokens / max(original_tokens, 1),
                sentences_kept=len(sentences),
                sentences_total=len(sentences),
            )

        scored = []
        for i, sent in enumerate(sentences):
            score = 0.0
            if i == 0 or i == len(sentences) - 1:
                score += 0.5
            words = sent.split()
            if 5 <= len(words) <= 30:
                score += 0.3
            if any(w.lower() in self.IMPORTANT_WORDS for w in words):
                score += 0.4
            if sent.strip().endswith("?"):
                score += 0.2
            if i < 3:
                score += 0.1
            scored.append((score, i, sent))

        target_count = max(3, int(len(sentences) * self._target_ratio))
        scored.sort(key=lambda x: x[0], reverse=True)
        selected = sorted(scored[:target_count], key=lambda x: x[1])
        compressed = " ".join(s for _, _, s in selected)
        compressed_tokens = self._estimate_tokens(compressed)

        self._total_saved += len(text) - len(compressed)
        self._total_tokens_saved += original_tokens - compressed_tokens

        return CompressionResult(
            text=compressed,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            ratio=compressed_tokens / max(original_tokens, 1),
            sentences_kept=len(selected),
            sentences_total=len(sentences),
        )

    def _estimate_tokens(self, text: str) -> int:
        words = text.split()
        return max(1, int(len(words) * 1.3))

    def get_stats(self) -> dict:
        return {
            "compressions": self._compressions,
            "total_saved_chars": self._total_saved,
            "total_saved_tokens": self._total_tokens_saved,
            "avg_tokens_saved": self._total_tokens_saved / max(self._compressions, 1),
        }
