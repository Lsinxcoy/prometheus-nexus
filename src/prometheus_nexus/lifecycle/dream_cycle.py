"""DreamCycle — Memory synthesis with pattern discovery.

基于:
- Tononi (2004) "AGI framework: Sleep and Dream" + 记忆激活合成理论 (Diedrichsen, 2020)
  - 共现分析: PMI加权(含TF-IDF权重), weighted_pmi = pmi × (0.5 + tfidf_weight)
  - 信念合成: 按tag聚合utility, avg>0.4且consistency>0.2 → 合成belief
  - 连接发现: 共享≥2个tag的记忆对 → 记录连接(最多50条)
  - 双接口: run_cycle()→DreamResult, dream()→dict

算法:
    run_cycle():
        1. PMI模式发现: word_pairs共现 + TF-IDF加权 → weighted_pmi>0.5
        2. 信念合成: 按tag聚合utility → 高一致性topic
        3. 连接发现: 共享tag≥2的记忆对

来源: Omega系统 dream_cycle 梦境合成模块 + 激活记忆合成理论
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import time
from collections import Counter
from dataclasses import dataclass, field

from prometheus_nexus.foundation.schema import DreamResult


class DreamCycle:
    """Memory synthesis with pattern discovery.

    Usage:
        dc = DreamCycle()
        dc.register_memory({"id": "e1", "content": "AI research", "utility": 0.8, "tags": ["ai"]})
        dc.register_memory({"id": "e2", "content": "neural networks", "utility": 0.7, "tags": ["ai", "ml"]})

        result = dc.run_cycle()
        print(f"Patterns: {result.patterns_found}, Beliefs: {result.beliefs_synthesized}")
    """

    def __init__(self, store=None):
        self._memories: list[dict] = []
        self._dreams: list[dict] = []
        self._store = store  # P5c: 可选 store 引用, 用于读多类型节点做跨界联想
        self._beliefs: list[dict] = []

    def register_memory(self, memory) -> None:
        """Register a memory for dream processing."""
        if isinstance(memory, dict):
            self._memories.append({
                "id": memory.get("id", str(len(self._memories))),
                "content": memory.get("content", ""),
                "utility": memory.get("utility", 0.5),
                "tags": memory.get("tags", []),
            })
        else:
            self._memories.append({
                "id": getattr(memory, 'id', str(len(self._memories))),
                "content": getattr(memory, 'content', ''),
                "utility": getattr(memory, 'utility', 0.5),
                "tags": getattr(memory, 'tags', []),
            })

    def run_cycle(self, branch: str = "main") -> DreamResult:
        """Run a dream cycle to discover patterns and synthesize beliefs."""
        patterns = self._discover_patterns()
        beliefs = self._synthesize_beliefs()
        connections = self._discover_connections()

        self._dreams.append({
            "ts": time.time(), "patterns": len(patterns),
            "beliefs": len(beliefs), "connections": len(connections),
        })
        self._beliefs.extend(beliefs)

        # Generate textual insights from patterns and beliefs
        insights = []
        for p in patterns[:5]:
            w1, w2 = p["pair"]
            insights.append(f"Pattern: '{w1}' strongly co-occurs with '{w2}' (PMI={p['pmi']:.2f})")
        for b in beliefs[:3]:
            insights.append(f"Belief: topic '{b['topic']}' has confidence {b['confidence']:.2f} ({b['evidence']} evidences)")

        return DreamResult(
            patterns_found=len(patterns),
            beliefs_synthesized=len(beliefs),
            connections_discovered=len(connections),
            insights=insights,
        )

    def dream(self, memories: list | None = None) -> dict:
        """Alternative dream interface returning dict.

        P5c: 若未显式传 memories 且无已注册记忆, 则从 store 取多类型节点
        (CONCEPT/PAPER/PROCEDURE/PROJECT) 做跨界联想, 而非空转。
        """
        mems = memories
        if mems is None:
            if self._memories:
                mems = self._memories
            elif self._store is not None:
                mems = self._store_memories()
        mems = mems or []
        p = self._discover_patterns_from(mems)
        b = self._synthesize_beliefs_from(mems)
        c = self._discover_connections_from(mems)
        return {"patterns_found": len(p), "beliefs_synthesized": len(b),
                "connections_discovered": len(c)}

    def _store_memories(self) -> list[dict]:
        """从 store 取多类型节点转为 dream 可消费的 memory dict。"""
        try:
            from prometheus_nexus.foundation.schema import NodeType
            out = []
            for nt in [NodeType.CONCEPT, NodeType.PAPER, NodeType.PROCEDURE,
                       NodeType.PROJECT, NodeType.PATTERN, NodeType.HYPOTHESIS]:
                for n in self._store.get_nodes_by_type(nt, limit=50):
                    out.append({"id": n.id, "content": n.content,
                                "utility": n.utility, "tags": list(n.tags or [])})
            return out
        except Exception as e:
            logger.debug("DreamCycle._store_memories failed: %s", e)
            return []

    def _discover_patterns(self) -> list[dict]:
        return self._discover_patterns_from(self._memories)

    def _discover_patterns_from(self, memories: list) -> list[dict]:
        patterns = []
        if len(memories) < 3:
            return patterns

        import math
        word_docs: Counter = Counter()
        word_pairs: Counter = Counter()
        word_freq: Counter = Counter()
        total_words = 0

        for mem in memories:
            words = [w.lower() for w in mem.get("content", "").split() if len(w) > 3]
            unique_words = set(words)
            for w in unique_words:
                word_docs[w] += 1
            for w in words:
                word_freq[w] += 1
                total_words += 1
            wl = sorted(unique_words)
            for i in range(len(wl)):
                for j in range(i + 1, min(i + 5, len(wl))):
                    word_pairs[(wl[i], wl[j])] += 1

        total = len(memories)
        for (w1, w2), count in word_pairs.most_common(20):
            if count >= 2:
                p1 = word_docs[w1] / total
                p2 = word_docs[w2] / total
                p_co = count / total

                if p1 * p2 > 0:
                    pmi = math.log2(p_co / (p1 * p2) + 1e-10)

                    # TF-IDF weighting
                    tf1 = word_freq.get(w1, 0) / max(total_words, 1)
                    tf2 = word_freq.get(w2, 0) / max(total_words, 1)
                    idf1 = math.log(max(1, total) / max(1, word_docs.get(w1, 1)))
                    idf2 = math.log(max(1, total) / max(1, word_docs.get(w2, 1)))
                    tfidf_weight = (tf1 * idf1 + tf2 * idf2) / 2

                    # Weighted PMI
                    weighted_pmi = pmi * (0.5 + tfidf_weight)

                    if weighted_pmi > 0.5:
                        patterns.append({
                            "pair": (w1, w2), "pmi": pmi,
                            "weighted_pmi": weighted_pmi,
                            "count": count,
                        })

        return patterns

    def _synthesize_beliefs(self) -> list[dict]:
        return self._synthesize_beliefs_from(self._memories)

    def _synthesize_beliefs_from(self, memories: list) -> list[dict]:
        beliefs = []
        tag_utils: dict[str, list[float]] = {}
        for mem in memories:
            for tag in mem.get("tags", []):
                tag_utils.setdefault(tag, []).append(mem.get("utility", 0.5))
        for tag, utils in tag_utils.items():
            if len(utils) >= 2:  # Relaxed from 3 to 2
                avg = sum(utils) / len(utils)
                consistency = 1.0 - (max(utils) - min(utils))
                if avg > 0.4 and consistency > 0.2:  # Relaxed thresholds
                    beliefs.append({"topic": tag, "confidence": avg * consistency,
                                    "evidence": len(utils)})
        return beliefs[:10]

    def _discover_connections(self) -> list[dict]:
        return self._discover_connections_from(self._memories)

    def _discover_connections_from(self, memories: list) -> list[dict]:
        connections = []
        for i in range(len(memories)):
            for j in range(i + 1, min(i + 20, len(memories))):
                ti = set(memories[i].get("tags", []))
                tj = set(memories[j].get("tags", []))
                common = ti & tj
                if len(common) >= 2:
                    connections.append({
                        "source": memories[i].get("id", ""),
                        "target": memories[j].get("id", ""),
                        "shared": list(common),
                    })
        return connections[:50]

    def get_stats(self) -> dict:
        return {
            "memories": len(self._memories),
            "dreams": len(self._dreams),
            "beliefs": len(self._beliefs),
        }
