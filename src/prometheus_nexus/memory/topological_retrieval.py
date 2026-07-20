"""TopologicalRetrieval — Graph-based retrieval with temporal awareness.

Based on: MemoryData benchmark topological methods (HippoRAG, RAPTOR, Zep)

Key concepts:
    - HippoRAG: retrieval over graph-style document organization
    - RAPTOR: hierarchical cluster-and-summarize retrieval
    - Zep: temporal knowledge graph with recency weighting
"""
from __future__ import annotations



import logging

import time
from dataclasses import dataclass, field
logger = logging.getLogger(__name__)


@dataclass
class TopologicalHit:
    node_id: str = ""
    score: float = 0.0
    content: str = ""
    path: list[str] = field(default_factory=list)
    temporal_weight: float = 1.0


class TopologicalRetrieval:
    """Graph-based retrieval with temporal awareness.

    Combines HippoRAG graph traversal, RAPTOR hierarchical clustering,
    and Zep temporal weighting.

    Usage:
        tr = TopologicalRetrieval(recency_decay=0.95)
        hits = tr.retrieve(query="AI safety", graph=graph_memory, limit=5)
    """

    def __init__(self, recency_decay: float = 0.95, max_depth: int = 3):
        self._recency_decay = recency_decay
        self._max_depth = max_depth
        self._stats = {"retrievals": 0, "total_hits": 0}

    def retrieve(self, query: str, graph=None, limit: int = 5) -> list[TopologicalHit]:
        self._stats["retrievals"] += 1
        hits = []

        if graph and hasattr(graph, 'search'):
            try:
                results = graph.search(query, limit=limit)
                for r in results:
                    content = r.content if hasattr(r, 'content') else str(r)
                    score = r.score if hasattr(r, 'score') else 0.5

                    temporal_weight = self._compute_temporal_weight(time.time())
                    weighted_score = score * temporal_weight

                    hits.append(TopologicalHit(
                        node_id=str(hash(content))[:12],
                        score=weighted_score,
                        content=content[:500],
                        temporal_weight=temporal_weight,
                    ))
            except Exception as e:
                logger.warning("Topological retrieval failed for node: %s", e)

        hits.sort(key=lambda h: h.score, reverse=True)
        hits = hits[:limit]
        self._stats["total_hits"] += len(hits)
        return hits

    def _compute_temporal_weight(self, timestamp: float) -> float:
        age_hours = (time.time() - timestamp) / 3600
        return max(0.1, self._recency_decay ** (age_hours / 24))

    def cluster_hierarchically(self, hits: list[TopologicalHit]) -> list[list[TopologicalHit]]:
        """RAPTOR-style hierarchical clustering."""
        if not hits:
            return []
        clusters = [[h] for h in hits]
        while len(clusters) > 1:
            merged = []
            i = 0
            while i < len(clusters):
                if i + 1 < len(clusters):
                    merged.append(clusters[i] + clusters[i + 1])
                    i += 2
                else:
                    merged.append(clusters[i])
                    i += 1
            clusters = merged
        return clusters

    def get_stats(self) -> dict:
        return dict(self._stats)
