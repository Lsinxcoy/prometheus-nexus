"""CoALAArchitecture — Cognitive architecture with working/long-term memory.

Based on: "CoALA: Cognitive Architectures for Language Agents"
(arXiv:2309.02427, Sumers et al. 2023)

Key Concepts from Paper:
    1. Modular cognitive architecture: memory + action space + decision
    2. Working memory: limited capacity, active context
    3. Long-term memory: persistent storage, retrieval
    4. Action space: structured set of available actions
    5. Decision process: select actions based on memory and goals

Paper Finding:
    "CoALA provides a unifying framework for understanding and
     building language agents, enabling systematic comparison
     of different agent designs."

Algorithm:
    - Working memory: fixed-size buffer with attention-based eviction
    - Long-term memory: overflow from working memory
    - Consolidation: periodic transfer from WM to LTM
    - Retrieval: query LTM based on current context
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CognitiveItem:
    """An item in cognitive memory."""
    content: str = ""
    importance: float = 0.5
    attention: float = 0.5
    timestamp: float = 0.0
    source: str = ""
    metadata: dict = field(default_factory=dict)


class CoALAArchitecture:
    """Cognitive architecture for language agents.

    Based on CoALA paper (arXiv:2309.02427).

    Usage:
        coala = CoALAArchitecture(working_memory_size=7)

        # Add to working memory
        coala.add_to_working_memory({"content": "User asked about AI", "importance": 0.8})

        # Observe environment
        coala.observe({"attention_score": 0.9})

        # Retrieve from long-term memory
        relevant = coala.retrieve_from_ltm("AI research", top_k=3)
    """

    def __init__(self, working_memory_size: int = 7):
        """Initialize CoALA architecture.

        Args:
            working_memory_size: Maximum items in working memory (Miller's 7±2).
        """
        self._wm_size = working_memory_size
        self._working_memory: list[CognitiveItem] = []
        self._long_term_memory: list[CognitiveItem] = []
        self._attention_weights: dict[str, float] = {}
        self._consolidations = 0
        self._total_retrieved = 0

    def add_to_working_memory(self, item: dict | CognitiveItem) -> None:
        """Add an item to working memory.

        If working memory is full, the lowest-attention item is
        consolidated to long-term memory.

        Args:
            item: Dict or CognitiveItem to add.
        """
        if isinstance(item, dict):
            cognitive_item = CognitiveItem(
                content=item.get("content", ""),
                importance=item.get("importance", 0.5),
                attention=item.get("utility", item.get("attention", 0.5)),
                timestamp=time.time(),
                source=item.get("source", "direct"),
                metadata=item,
            )
        else:
            cognitive_item = item
            cognitive_item.timestamp = time.time()

        self._working_memory.append(cognitive_item)

        # Consolidate if over capacity
        if len(self._working_memory) > self._wm_size:
            self._working_memory.sort(key=lambda x: getattr(x, 'attention', x.get('attention', 0.5) if isinstance(x, dict) else 0.5))
            evicted = self._working_memory.pop(0)
            self._long_term_memory.append(evicted)
            self._consolidations += 1

    def observe(self, data: dict | None = None) -> None:
        """Observe environment and update attention weights.

        From CoALA: "The agent's decision process depends on
        what it attends to in working memory"
        """
        if not data:
            return
        for key, value in data.items():
            if isinstance(value, (int, float)):
                old = self._attention_weights.get(key, 0.5)
                self._attention_weights[key] = old * 0.8 + value * 0.2

    def retrieve_from_ltm(self, query: str, top_k: int = 3) -> list[dict]:
        """Retrieve relevant items from long-term memory.

        Uses TF-IDF-inspired scoring:
        - Term frequency in query × inverse document frequency
        - Positional bonus for exact phrase matches
        - Recency decay for older items
        """
        import math
        query_lower = query.lower()
        query_words = query_lower.split()

        # Compute IDF-like weights for query words
        doc_count = len(self._long_term_memory)
        word_doc_freq: dict[str, int] = {}
        for item in self._long_term_memory:
            # 兼容 dict / MemoryItem
            if isinstance(item, dict):
                content_words = set(item.get("content", "").lower().split())
            else:
                content_words = set(item.content.lower().split())
            for w in query_words:
                if w in content_words:
                    word_doc_freq[w] = word_doc_freq.get(w, 0) + 1

        idf_weights = {}
        for w in query_words:
            df = word_doc_freq.get(w, 0)
            idf_weights[w] = math.log(max(1, doc_count) / max(1, df)) + 1.0

        scored = []
        current_time = time.time()
        for item in self._long_term_memory:
            # 兼容 dict / MemoryItem
            if isinstance(item, dict):
                content_lower = item.get("content", "").lower()
                content_words = set(content_lower.split())
                importance = item.get("importance", 0.5)
                timestamp = item.get("timestamp", current_time)
            else:
                content_lower = item.content.lower()
                content_words = set(content_lower.split())
                importance = item.importance
                timestamp = item.timestamp

            # TF-IDF score
            score = 0.0
            for w in query_words:
                if w in content_words:
                    tf = content_lower.count(w) / max(len(content_words), 1)
                    score += tf * idf_weights.get(w, 1.0)

            # Exact phrase bonus
            if query_lower in content_lower:
                score += 2.0

            # Partial phrase match
            for i in range(len(query_words) - 1):
                bigram = query_words[i] + " " + query_words[i + 1]
                if bigram in content_lower:
                    score += 0.5

            # Recency decay (exponential)
            age_hours = (current_time - timestamp) / 3600
            recency = math.exp(-age_hours / 168)  # 1-week half-life
            score *= (0.7 + 0.3 * recency)

            # Importance boost
            score *= (0.5 + importance * 0.5)

            if score > 0.01:
                scored.append((score, item))

        scored.sort(key=lambda x: x[0], reverse=True)
        self._total_retrieved += min(top_k, len(scored))

        result = []
        for score, item in scored[:top_k]:
            if isinstance(item, dict):
                result.append({"content": item.get("content", ""), "score": score, "importance": item.get("importance", 0.5)})
            else:
                result.append({"content": item.content, "score": score, "importance": item.importance})
        return result

    def get_working_memory_contents(self) -> list[dict]:
        """Get current working memory contents."""
        result = []
        for item in self._working_memory:
            if isinstance(item, dict):
                result.append({
                    "content": item.get("content", ""),
                    "attention": item.get("attention", item.get("utility", 0.5)),
                    "importance": item.get("importance", 0.5),
                })
            else:
                result.append({
                    "content": item.content,
                    "attention": item.attention,
                    "importance": item.importance,
                })
        return result

    def get_ltm_size(self) -> int:
        """Get long-term memory size."""
        return len(self._long_term_memory)

    def get_stats(self) -> dict:
        return {
            "working_memory": len(self._working_memory),
            "working_memory_capacity": self._wm_size,
            "long_term_memory": len(self._long_term_memory),
            "consolidations": self._consolidations,
            "total_retrieved": self._total_retrieved,
            "attention_weights": len(self._attention_weights),
        }
