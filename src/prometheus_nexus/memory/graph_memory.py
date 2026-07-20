"""GraphMemory — Episode-based graph memory with BFS traversal and tag indexing.

Architecture:
    Episodes are stored in a dictionary keyed by episode_id.
    Edges are stored in an adjacency list for efficient graph traversal.
    A tag倒排索引 (inverted index) enables fast tag-based retrieval.

Algorithm:
    Search combines:
    1. Direct content/tag matching (keyword search)
    2. BFS expansion from matched nodes (graph traversal)
    3. Tag-based retrieval via inverted index

    Score = content_match × 1.0 + tag_match × 0.5 + bfs_boost × weight × 0.5

Complexity:
    add_episode(): O(1)
    add_edge(): O(1)
    search(): O(V + E) where V = episodes, E = edges (BFS)
    get_episode(): O(1) by ID
    get_neighbors(): O(degree)

Edge Cases:
    - Empty graph: returns empty results
    - Circular edges: BFS has visited set to prevent cycles
    - Very large graphs: BFS depth-limited to prevent runaway
    - Duplicate edges: allowed (multiple relationship types)

Thread Safety:
    - Not thread-safe. Use external lock if needed.
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from prometheus_nexus.memory.hebbian import HebbianMemory

logger = logging.getLogger(__name__)


# ============================================================
# Data Types
# ============================================================

@dataclass
class EpisodeEvent:
    """An episode in the graph memory.

    Attributes:
        episode_id: Unique identifier.
        content: Text content of the episode.
        tags: Set of tags for categorization.
        importance: Importance score [0, 1].
        metadata: Additional metadata.
    """
    episode_id: str = ""
    content: str = ""
    tags: set = field(default_factory=set)
    importance: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Edge:
    """An edge connecting two episodes.

    Attributes:
        source: Source episode ID.
        target: Target episode ID.
        relation: Relationship type.
        weight: Edge weight [0, 1].
    """
    source: str = ""
    target: str = ""
    relation: str = ""
    weight: float = 1.0


@dataclass
class SearchResult:
    """A search result from graph memory.

    Attributes:
        episode_id: Matched episode ID.
        score: Relevance score.
        content: Episode content.
        path: BFS path from query origin (if applicable).
    """
    episode_id: str = ""
    score: float = 0.0
    content: str = ""
    path: list[str] = field(default_factory=list)


# ============================================================
# GraphMemory
# ============================================================

class GraphMemory:
    """Episode-based graph memory with BFS traversal.

    Stores episodes as nodes and relationships as edges, enabling
    graph-based retrieval that goes beyond simple keyword matching.

    Usage:
        gm = GraphMemory()
        ep = EpisodeEvent(episode_id="e1", content="AI research", tags={"ai", "ml"})
        gm.add_episode(ep)
        gm.add_edge("e1", "e2", "related", 0.8)

        results = gm.search("AI", limit=5)
        for r in results:
            print(f"{r.episode_id}: {r.score:.2f}")

    Search Algorithm:
        1. Direct match: content/tag substring matching
        2. BFS expansion: traverse edges from matched nodes
        3. Score combining: match_score × importance + bfs_boost × edge_weight
    """

    def __init__(self, max_bfs_depth: int = 3, max_results_per_query: int = 100,
                 hebbian: HebbianMemory | None = None):
        """Initialize graph memory.

        Args:
            max_bfs_depth: Maximum BFS traversal depth.
            max_results_per_query: Maximum results per search query.
            hebbian: Optional HebbianMemory instance for edge-weight learning.
        """
        self._episodes: dict[str, EpisodeEvent] = {}
        self._adjacency: dict[str, list[Edge]] = {}
        self._tag_index: dict[str, set[str]] = {}
        self._max_bfs_depth = max_bfs_depth
        self._max_results = max_results_per_query
        self._edge_count = 0
        self._hebbian = hebbian

    def add_episode(self, episode: EpisodeEvent) -> None:
        """Add an episode to the graph.

        Args:
            episode: The episode to add.

        Complexity: O(T) where T = number of tags.
        """
        if not episode.episode_id:
            raise ValueError("Episode ID required")

        self._episodes[episode.episode_id] = episode

        # Update tag index
        for tag in episode.tags:
            if tag not in self._tag_index:
                self._tag_index[tag] = set()
            self._tag_index[tag].add(episode.episode_id)

        logger.debug("Added episode %s with %d tags", episode.episode_id, len(episode.tags))

    def add_edge(self, source: str, target: str, relation: str = "related",
                 weight: float = 1.0) -> bool:
        """Add an edge between two episodes.

        Args:
            source: Source episode ID.
            target: Target episode ID.
            relation: Relationship type.
            weight: Edge weight [0, 1].

        Returns:
            True if edge was added, False if episodes don't exist.

        Complexity: O(1).
        """
        if source not in self._episodes:
            # Auto-create placeholder for cross-references to DB nodes
            self._episodes[source] = EpisodeEvent(episode_id=source)
        if target not in self._episodes:
            self._episodes[target] = EpisodeEvent(episode_id=target)

        edge = Edge(source=source, target=target, relation=relation, weight=weight)

        if source not in self._adjacency:
            self._adjacency[source] = []
        self._adjacency[source].append(edge)

        # Undirected: add reverse edge
        if target not in self._adjacency:
            self._adjacency[target] = []
        self._adjacency[target].append(Edge(source=target, target=source, relation=relation, weight=weight))

        self._edge_count += 1

        # Hebbian update: edges that fire together wire together
        if self._hebbian is not None:
            self._hebbian.update_edge(source, target, delta_weight=0.05, relation=relation)

        return True

    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """Search for episodes matching the query.

        Uses tag index for O(K) candidate selection instead of O(N) full scan.
        """
        if not query or not query.strip():
            return []

        query_lower = query.lower()
        query_words = set(query_lower.split())

        # Phase 1: Collect candidates via tag index (O(K) instead of O(N))
        candidate_ids: set[str] = set()
        for word in query_words:
            if word in self._tag_index:
                candidate_ids.update(self._tag_index[word])

        # Also add most recent episodes for recency bonus
        all_ids = list(self._episodes.keys())
        candidate_ids.update(all_ids[-10:])

        # Phase 2: Score only candidates
        direct_matches: dict[str, float] = {}
        for eid in candidate_ids:
            if eid in self._episodes:
                ep = self._episodes[eid]
                score = self._compute_direct_score(query_lower, query_words, ep)
                if score > 0:
                    direct_matches[eid] = score

        if not direct_matches:
            return []

        # Phase 3: BFS expansion from top matches
        results: dict[str, SearchResult] = {}
        visited: set[str] = set()

        start_nodes = sorted(direct_matches.keys(),
                             key=lambda x: direct_matches[x], reverse=True)[:3]

        for start in start_nodes:
            if start in visited:
                continue
            self._bfs_expand(start, query_lower, query_words, results, visited, limit)

        # Merge direct matches into results
        for eid, score in direct_matches.items():
            if eid not in results:
                results[eid] = SearchResult(
                    episode_id=eid,
                    score=score,
                    content=self._episodes[eid].content,
                )
            else:
                results[eid].score = max(results[eid].score, score)

        sorted_results = sorted(results.values(), key=lambda r: r.score, reverse=True)
        final = sorted_results[:limit]

        # Hebbian learning: strengthen edges between co-retrieved nodes
        if self._hebbian is not None and len(final) >= 2:
            retrieved_ids = [r.episode_id for r in final]
            for i in range(len(retrieved_ids)):
                for j in range(i + 1, min(i + 5, len(retrieved_ids))):
                    self._hebbian.update_edge(
                        retrieved_ids[i], retrieved_ids[j],
                        delta_weight=0.02, relation="co_retrieved",
                    )

        return final

    def _compute_direct_score(self, query_lower: str, query_words: set[str],
                               episode: EpisodeEvent) -> float:
        """Compute direct match score with temporal weighting."""
        import time
        score = 0.0
        content_lower = episode.content.lower()

        # Exact substring match
        if query_lower in content_lower:
            score += 1.0

        # Word overlap
        content_words = set(content_lower.split())
        overlap = query_words & content_words
        if query_words:
            score += len(overlap) / len(query_words) * 0.5

        # Tag match
        for tag in episode.tags:
            if query_lower in tag.lower():
                score += 0.3
            for word in query_words:
                if word in tag.lower():
                    score += 0.2

        # Importance bonus
        score *= (0.5 + episode.importance * 0.5)

        # Temporal weighting: more recent = higher score
        if hasattr(episode, 'metadata') and episode.metadata.get('timestamp'):
            age_hours = (time.time() - episode.metadata['timestamp']) / 3600
            recency_boost = 1.0 + max(0, 0.3 - age_hours * 0.01)
            score *= recency_boost

        return min(score, 2.0)

    def _bfs_expand(self, start: str, query_lower: str, query_words: set[str],
                     results: dict[str, SearchResult], visited: set[str],
                     limit: int) -> None:
        """BFS expansion from a starting node."""
        queue: deque[tuple[str, float, list[str]]] = deque()
        queue.append((start, 1.0, [start]))
        visited.add(start)

        while queue and len(results) < self._max_results:
            node_id, path_score, path = queue.popleft()

            if node_id in self._episodes:
                ep = self._episodes[node_id]
                direct_score = self._compute_direct_score(query_lower, query_words, ep)
                boosted_score = direct_score * path_score

                if boosted_score > 0.01:
                    if node_id not in results or results[node_id].score < boosted_score:
                        results[node_id] = SearchResult(
                            episode_id=node_id,
                            score=boosted_score,
                            content=ep.content,
                            path=list(path),
                        )

            # Traverse edges
            if len(path) <= self._max_bfs_depth:
                for edge in self._adjacency.get(node_id, []):
                    if edge.target not in visited:
                        visited.add(edge.target)
                        new_score = path_score * edge.weight * 0.5
                        if new_score > 0.01:
                            queue.append((edge.target, new_score, path + [edge.target]))

    def get_episode(self, episode_id: str) -> EpisodeEvent | None:
        """Get an episode by ID.

        Args:
            episode_id: The episode identifier.

        Returns:
            EpisodeEvent if found, None otherwise.

        Complexity: O(1).
        """
        return self._episodes.get(episode_id)

    def get_neighbors(self, episode_id: str) -> list[str]:
        """Get all neighbors of an episode.

        Args:
            episode_id: The episode identifier.

        Returns:
            List of neighbor episode IDs.

        Complexity: O(degree).
        """
        return [edge.target for edge in self._adjacency.get(episode_id, [])]

    def get_edges(self, episode_id: str) -> list[Edge]:
        """Get all edges from an episode.

        Args:
            episode_id: The episode identifier.

        Returns:
            List of Edge objects.

        Complexity: O(degree).
        """
        return list(self._adjacency.get(episode_id, []))

    def remove_episode(self, episode_id: str) -> bool:
        """Remove an episode and all its edges.

        Args:
            episode_id: The episode to remove.

        Returns:
            True if removed, False if not found.

        Complexity: O(E) where E = edges connected to episode.
        """
        if episode_id not in self._episodes:
            return False

        # Remove episode
        ep = self._episodes.pop(episode_id)

        # Remove from tag index
        for tag in ep.tags:
            if tag in self._tag_index:
                self._tag_index[tag].discard(episode_id)
                if not self._tag_index[tag]:
                    del self._tag_index[tag]

        # Remove edges
        edges_to_remove = []
        for source, edges in self._adjacency.items():
            for edge in edges:
                if edge.source == episode_id or edge.target == episode_id:
                    edges_to_remove.append((source, edge))

        for source, edge in edges_to_remove:
            if source in self._adjacency:
                self._adjacency[source] = [e for e in self._adjacency[source] if e != edge]

        return True

    def get_episodes_by_tag(self, tag: str) -> list[EpisodeEvent]:
        """Get all episodes with a specific tag.

        Args:
            tag: The tag to search for.

        Returns:
            List of matching episodes.

        Complexity: O(N) where N = episodes with tag.
        """
        episode_ids = self._tag_index.get(tag, set())
        return [self._episodes[eid] for eid in episode_ids if eid in self._episodes]

    # ============================================================
    # Statistics
    # ============================================================

    def get_stats(self) -> dict:
        """Get graph memory statistics.

        Returns:
            Dictionary with episode count, edge count, average degree, etc.
        """
        avg_degree = 0.0
        if self._episodes:
            total_degree = sum(len(edges) for edges in self._adjacency.values())
            avg_degree = total_degree / len(self._episodes)

        return {
            "episodes": len(self._episodes),
            "edges": self._edge_count,
            "avg_degree": avg_degree,
            "tags": len(self._tag_index),
            "max_bfs_depth": self._max_bfs_depth,
        }
