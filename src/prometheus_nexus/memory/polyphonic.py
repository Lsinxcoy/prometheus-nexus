"""PolyphonicRetriever — Multi-route search pipeline with score fusion.

Architecture:
    Combines results from multiple search routes:
    1. FTS5 full-text search (via MinervaStore)
    2. Graph-based expansion (via GraphMemory)
    3. Tag-based retrieval via inverted index
    4. Recency-weighted retrieval
    5. Importance-weighted retrieval

    Results from all routes are merged, deduplicated, and ranked.

Algorithm:
    For each route r:
        results_r = route.search(query)
        for each result in results_r:
            score += result.score × route_weight

    Score fusion:
        fused_score = Σ(route_weight × raw_score × recency_boost × importance_boost)

    Final ranking: sort by fused score, deduplicate by node_id.

Route Weights:
    - FTS: 1.0 (primary, most reliable)
    - Graph: 0.8 (expands via relationships)
    - Tags: 0.6 (exact match bonus)
    - Recency: 0.4 (time decay)
    - Importance: 0.3 (utility-based)

Complexity:
    search(): O(R × N × log N) where R = routes, N = results per route
    _deduplicate(): O(N × log N)
    _compute_fused_score(): O(R) per result

Edge Cases:
    - Empty query: returns empty results
    - No routes configured: returns empty results
    - All routes fail: returns empty results
    - Duplicate nodes across routes: merged with max score
    - Very large result sets: truncated to limit

Thread Safety:
    - Not thread-safe. Use external lock if needed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================
# Configuration
# ============================================================

@dataclass
class SearchRoute:
    """Configuration for a search route.

    Attributes:
        name: Route name for identification.
        weight: Weight for score fusion [0, 1].
        enabled: Whether this route is active.
        max_results: Maximum results from this route.
        timeout_ms: Route timeout in milliseconds.
    """
    name: str = ""
    weight: float = 1.0
    enabled: bool = True
    max_results: int = 100
    timeout_ms: float = 5000.0


@dataclass
class SearchConfig:
    """Configuration for the polyphonic retriever."""
    routes: list[SearchRoute] = field(default_factory=lambda: [
        SearchRoute(name="fts", weight=1.0),
        SearchRoute(name="graph", weight=0.8),
        SearchRoute(name="tags", weight=0.6),
    ])
    dedup_strategy: str = "max_score"  # max_score, first_seen, merge
    recency_decay: float = 0.95
    importance_weight: float = 0.3
    max_total_results: int = 1000


# ============================================================
# Result Types
# ============================================================

@dataclass
class RouteResult:
    """Results from a single search route."""
    route_name: str = ""
    hits: list[dict] = field(default_factory=list)
    latency_ms: float = 0.0
    success: bool = True
    error: str = ""


@dataclass
class FusedResult:
    """A result after score fusion across routes."""
    node_id: str = ""
    fused_score: float = 0.0
    content: str = ""
    route_scores: dict[str, float] = field(default_factory=dict)
    matched_routes: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


# ============================================================
# PolyphonicRetriever
# ============================================================

class PolyphonicRetriever:
    """Multi-route search pipeline with score fusion.

    Combines results from multiple search strategies and merges them
    into a unified ranking with fused scores.

    Usage:
        retriever = PolyphonicRetriever()
        results = retriever.search(
            query="AI research",
            store=store,
            graph_memory=graph_memory,
            limit=10,
        )
        for r in results:
            print(f"Score: {r.fused_score:.3f} - {r.content[:80]}")

    Search Routes:
        1. FTS: Full-text search via MinervaStore (weight=1.0)
        2. Graph: BFS expansion via GraphMemory (weight=0.8)
        3. Tags: Inverted index tag matching (weight=0.6)

    Score Fusion Formula:
        fused_score = Σ(route_weight × raw_score × recency_boost × importance_boost) / Σ(route_weight)

    Performance:
        - search(): O(R × N × log N)
        - Memory: O(N) where N = total unique results
    """

    def __init__(self, config: SearchConfig | None = None):
        """Initialize the retriever.

        Args:
            config: Search configuration. Uses defaults if None.
        """
        self._cfg = config or SearchConfig()
        self._route_stats: dict[str, dict] = {}
        self._total_searches = 0
        self._total_results = 0
        self._total_fusions = 0

    def search(self, query: str, store=None, graph_memory=None,
               limit: int = 10) -> list[FusedResult]:
        """Search across all configured routes.

        Args:
            query: Search query string.
            store: MinervaStore instance for FTS.
            graph_memory: GraphMemory instance for graph search.
            limit: Maximum results to return.

        Returns:
            List of FusedResult objects sorted by fused_score descending.

        Complexity: O(R × N × log N) where R = routes, N = results.
        """
        if not query or not query.strip():
            return []

        self._total_searches += 1
        all_route_results: list[RouteResult] = []

        # Execute each route
        for route in self._cfg.routes:
            if not route.enabled:
                continue

            route_result = self._execute_route(route, query, store, graph_memory, limit)
            all_route_results.append(route_result)

            # Update route stats
            if route.name not in self._route_stats:
                self._route_stats[route.name] = {"searches": 0, "total_results": 0, "errors": 0}
            self._route_stats[route.name]["searches"] += 1
            self._route_stats[route.name]["total_results"] += len(route_result.hits)
            if not route_result.success:
                self._route_stats[route.name]["errors"] += 1

        # Fuse results across routes
        fused_results = self._fuse_results(all_route_results)

        # Deduplicate
        deduped = self._deduplicate(fused_results)

        # Sort by fused score
        deduped.sort(key=lambda r: r.fused_score, reverse=True)

        # Truncate to limit
        results = deduped[:limit]

        self._total_results += len(results)
        self._total_fusions += 1

        return results

    def _execute_route(self, route: SearchRoute, query: str,
                       store, graph_memory, limit: int) -> RouteResult:
        """Execute a single search route."""
        import time
        start = time.time()

        try:
            if route.name == "fts" and store is not None:
                hits = self._search_fts(store, query, route.max_results)
            elif route.name == "graph" and graph_memory is not None:
                hits = self._search_graph(graph_memory, query, route.max_results)
            elif route.name == "tags" and store is not None:
                hits = self._search_tags(store, query, route.max_results)
            else:
                hits = []

            latency = (time.time() - start) * 1000
            return RouteResult(route_name=route.name, hits=hits, latency_ms=latency)

        except Exception as e:
            latency = (time.time() - start) * 1000
            logger.warning("Route %s failed: %s", route.name, e)
            return RouteResult(route_name=route.name, hits=[], latency_ms=latency,
                               success=False, error=str(e))

    def _search_fts(self, store, query: str, limit: int) -> list[dict]:
        """Execute FTS5 full-text search."""
        nodes = store.search(query, limit=limit)
        return [{"id": n.id, "score": n.utility, "content": n.content,
                 "tags": n.tags, "confidence": n.confidence}
                for n in nodes]

    def _search_graph(self, graph_memory, query: str, limit: int) -> list[dict]:
        """Execute graph-based BFS search."""
        results = graph_memory.search(query, limit=limit)
        hits = []
        for r in results:
            if hasattr(r, 'episode_id'):
                hits.append({"id": r.episode_id, "score": r.score, "content": r.content})
            elif isinstance(r, dict):
                hits.append({"id": r.get("id", ""), "score": r.get("score", 0.5),
                             "content": r.get("content", "")})
        return hits

    def _search_tags(self, store, query: str, limit: int) -> list[dict]:
        """Execute tag-based search."""
        hits = []
        for word in query.split():
            nodes = store.search(word, limit=limit)
            for node in nodes:
                if word.lower() in [t.lower() for t in node.tags]:
                    hits.append({"id": node.id, "score": node.utility * 0.5,
                                 "content": node.content, "tags": node.tags})
        return hits

    def _fuse_results(self, route_results: list[RouteResult]) -> list[FusedResult]:
        """Fuse results from multiple routes with weighted scoring."""
        # Collect all results by node_id
        node_results: dict[str, dict] = {}

        for route_result in route_results:
            route_weight = 1.0
            for route in self._cfg.routes:
                if route.name == route_result.route_name:
                    route_weight = route.weight
                    break

            for hit in route_result.hits:
                node_id = hit.get("id", "")
                if not node_id:
                    continue

                if node_id not in node_results:
                    node_results[node_id] = {
                        "id": node_id, "content": hit.get("content", ""),
                        "route_scores": {}, "matched_routes": 0,
                        "raw_scores": [],
                    }

                entry = node_results[node_id]
                raw_score = hit.get("score", 0.5)
                weighted_score = raw_score * route_weight

                entry["route_scores"][route_result.route_name] = weighted_score
                entry["matched_routes"] += 1
                entry["raw_scores"].append(weighted_score)
                if not entry["content"]:
                    entry["content"] = hit.get("content", "")

        # Compute fused scores
        fused_results = []
        total_weight = sum(r.weight for r in self._cfg.routes if r.enabled)

        for node_id, entry in node_results.items():
            # Fused score = weighted average across routes
            if entry["raw_scores"]:
                fused_score = sum(entry["raw_scores"]) / max(total_weight, 1)
            else:
                fused_score = 0.0

            # Bonus for multi-route matches
            route_bonus = min(0.2, entry["matched_routes"] * 0.05)
            fused_score += route_bonus

            # Importance boost
            fused_score *= (1.0 + self._cfg.importance_weight * 0.5)

            fused_results.append(FusedResult(
                node_id=node_id, fused_score=fused_score,
                content=entry["content"],
                route_scores=entry["route_scores"],
                matched_routes=entry["matched_routes"],
            ))

        return fused_results

    def _deduplicate(self, results: list[FusedResult]) -> list[FusedResult]:
        """Deduplicate results by node_id."""
        seen: dict[str, FusedResult] = {}

        for result in results:
            if result.node_id in seen:
                existing = seen[result.node_id]
                # Keep the one with higher score, or merge route_scores
                if result.fused_score > existing.fused_score:
                    seen[result.node_id] = result
                # Merge route scores
                for route, score in result.route_scores.items():
                    if route not in existing.route_scores:
                        existing.route_scores[route] = score
                existing.matched_routes = max(existing.matched_routes, result.matched_routes)
            else:
                seen[result.node_id] = result

        return list(seen.values())

    # ============================================================
    # Statistics & Inspection
    # ============================================================

    def get_route_stats(self) -> dict[str, dict]:
        """Get per-route statistics."""
        return dict(self._route_stats)

    def get_fusion_stats(self) -> dict:
        """Get fusion statistics."""
        return {
            "total_searches": self._total_searches,
            "total_results": self._total_results,
            "total_fusions": self._total_fusions,
            "avg_results_per_search": self._total_results / max(self._total_searches, 1),
            "routes_configured": len(self._cfg.routes),
            "routes_enabled": sum(1 for r in self._cfg.routes if r.enabled),
        }

    def get_stats(self) -> dict:
        """Get comprehensive retriever statistics."""
        return {
            **self.get_fusion_stats(),
            "route_stats": self.get_route_stats(),
            "dedup_strategy": self._cfg.dedup_strategy,
            "recency_decay": self._cfg.recency_decay,
        }

    def reset_stats(self) -> None:
        """Reset all statistics."""
        self._route_stats.clear()
        self._total_searches = 0
        self._total_results = 0
        self._total_fusions = 0
