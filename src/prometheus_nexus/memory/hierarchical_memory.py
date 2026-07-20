"""HORMA hierarchical memory — file-system-like hierarchy (arXiv 2606.11680).

Structure: root / task / episode / action / raw
Thread-safe, path-based organization beats flat semantic retrieval.
Token usage drops to ~22% of baseline; OOD generalization exceeds
unconstrained baselines.

新增:
- get_all_paths(): 返回所有注册的路径前缀
- consolidate_siblings(path): 合并同���目录下的兄弟节点
- 集成了 RL navigator 的协作接口
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)


class HierarchicalMemory:
    """File-system-like hierarchical memory with path-based organization.

    Structure: root → task → episode → action → raw

    Each node is stored at a path (e.g. ``/tasks/exploration/episode_3``).
    Retrieval walks ancestor prefixes from most-specific to least-specific,
    scoring by path-depth overlap + utility.  Thread-safe via a reentrant lock.

    Usage::

        hm = HierarchicalMemory()
        hm.store("node_1", "/tasks/exploration/episode_3", 0.9,
                 content="found a cave")
        hits = hm.retrieve("/tasks/exploration")
        path = hm.get_path("node_1")

        # New operations:
        all_paths = hm.get_all_paths()
        merged = hm.consolidate_siblings("/tasks/exploration")

        stats = hm.get_stats()
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # node_id → {path, utility, content, ts}
        self._nodes: dict[str, dict[str, Any]] = {}
        # path_prefix → set[node_id]
        self._tree: dict[str, set[str]] = {}
        # node_id → access count
        self._access_count: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def store(self, node_id: str, path: str, utility: float = 0.5,
              content: str = "") -> None:
        """Store a node at *path*.

        Args:
            node_id: Unique identifier for the node.
            path: Hierarchical path, e.g. ``"/tasks/exploration/episode_3"``.
            utility: Importance weight in ``[0, 1]`` (affects retrieval rank).
            content: Arbitrary string payload.
        """
        path = self._normalise(path)

        with self._lock:
            self._nodes[node_id] = {
                "path": path,
                "utility": utility,
                "content": content,
                "ts": time.time(),
            }

            # Register under every ancestor prefix so that a query for a parent
            # directory naturally discovers this child.
            parts = path.strip("/").split("/")
            for depth in range(len(parts) + 1):
                prefix = "/" + "/".join(parts[:depth])
                if depth == 0:
                    prefix = "/"
                self._tree.setdefault(prefix, set()).add(node_id)

            logger.debug("HORMA stored %s at %s (utility=%.2f)",
                         node_id, path, utility)

    def retrieve(self, query: str, context: str | None = None,
                 max_results: int = 10,
                 min_utility: float = 0.0) -> list[dict[str, Any]]:
        """Retrieve nodes relevant to *query* (interpreted as a path).

        The method searches from most-specific to broadest ancestor prefixes,
        scoring by shared-path depth (60 %) + utility (40 %).  The optional
        *context* string is currently reserved for future semantic refinement
        (e.g. an LLM-generated summary to disambiguate).

        Args:
            query: Path to query, e.g. ``"/tasks/exploration"``.
            context: Optional semantic hint (reserved).
            max_results: Maximum number of results to return.
            min_utility: Minimum utility threshold.

        Returns:
            List of dicts with keys ``node_id``, ``score``, ``path``, ``content``.
        """
        query_path = self._normalise(query)
        parts = query_path.strip("/").split("/")

        with self._lock:
            candidates: dict[str, float] = {}

            # Walk from deepest prefix up to root.
            for depth in range(len(parts), -1, -1):
                prefix = "/" + "/".join(parts[:depth])
                if depth == 0:
                    prefix = "/"

                for nid in self._tree.get(prefix, set()):
                    if nid in candidates:
                        continue
                    info = self._nodes.get(nid)
                    if info is None or info["utility"] < min_utility:
                        continue

                    node_parts = info["path"].strip("/").split("/")
                    shared = sum(
                        1 for a, b in zip(parts, node_parts) if a == b
                    )
                    depth_score = shared / max(len(node_parts), 1)
                    score = depth_score * 0.6 + info["utility"] * 0.4
                    candidates[nid] = score

            sorted_nodes = sorted(candidates.items(),
                                  key=lambda x: (-x[1], x[0]))
            results: list[dict[str, Any]] = []
            for nid, score in sorted_nodes[:max_results]:
                info = self._nodes[nid]
                results.append({
                    "node_id": nid,
                    "score": round(score, 4),
                    "path": info["path"],
                    "content": info["content"][:200],
                })
                self._access_count[nid] = self._access_count.get(nid, 0) + 1

        return results

    def get_path(self, node_id: str) -> str | None:
        """Return the hierarchical path for *node_id*, or ``None``."""
        with self._lock:
            info = self._nodes.get(node_id)
            return info["path"] if info else None

    # ------------------------------------------------------------------
    # 新增: 路径管理 API
    # ------------------------------------------------------------------

    def get_all_paths(self) -> list[str]:
        """Return all registered path prefixes, sorted.

        Useful for the RL navigator to understand available navigation options.

        Returns:
            Sorted list of path strings (e.g. ``["/", "/tasks", "/tasks/explore", ...]``).
        """
        with self._lock:
            return sorted(self._tree.keys())

    def get_subtree(self, path: str) -> list[dict[str, Any]]:
        """Return all nodes under *path* (inclusive).

        Args:
            path: Query path prefix.

        Returns:
            List of node dicts under this path.
        """
        path = self._normalise(path)
        with self._lock:
            node_ids: set[str] = set()
            for prefix, ids in self._tree.items():
                norm_prefix = prefix.rstrip("/") if prefix != "/" else prefix
                if norm_prefix.startswith(path):
                    node_ids.update(ids)

            results: list[dict[str, Any]] = []
            for nid in node_ids:
                info = self._nodes.get(nid)
                if info:
                    results.append({
                        "node_id": nid,
                        "path": info["path"],
                        "utility": info["utility"],
                        "content": info["content"][:200],
                    })
        return results

    def consolidate_siblings(self, path: str) -> dict[str, Any]:
        """Merge sibling directories at *path* by aggregating content.

        "Siblings" are nodes at exactly one level deeper than *path*.
        Consolidation merges low-utility siblings into a single summary
        node, reducing tree depth and token usage (as discussed in
        HORMA §3.4).

        This implements the HORMA dynamic reorganisation mechanism:
        when too many fine-grained distinctions exist at one level,
        consolidate them into broader categories.

        Args:
            path: Parent path whose children should be consolidated.

        Returns:
            Dict with action summary: merged_groups, nodes_affected.
        """
        path = self._normalise(path)
        path_parts = path.strip("/").split("/")
        target_depth = len(path_parts) + 1  # direct children depth

        with self._lock:
            # Find all nodes that are direct children of *path*.
            # A node is a direct child if its own path is exactly one level
            # deeper than *path*.
            sibling_nodes: list[str] = []
            for nid, info in self._nodes.items():
                node_path = info["path"]
                node_parts = node_path.strip("/").split("/")
                if len(node_parts) == target_depth and node_path.startswith(path + "/"):
                    sibling_nodes.append(nid)

            if len(sibling_nodes) <= 1:
                return {"merged_groups": 0, "nodes_affected": 0,
                        "message": "No siblings to consolidate — need at least 2 sibling nodes"}

            # Compute average utility for this sibling group
            utilities = [
                self._nodes[nid]["utility"]
                for nid in sibling_nodes if nid in self._nodes
            ]
            avg_utility = sum(utilities) / max(len(utilities), 1)

            merged_groups = 0
            nodes_affected = 0
            message = "No siblings to consolidate"

            if avg_utility < 0.5:
                # Low-utility group: merge into a consolidated node
                merged_content = " | ".join(
                    self._nodes[nid]["content"][:80]
                    for nid in sibling_nodes if nid in self._nodes
                )
                # Determine the immediate parent prefix from any one of the siblings
                example_path = self._nodes[sibling_nodes[0]]["path"]
                parent_prefix = "/" + "/".join(example_path.strip("/").split("/")[:-1])
                merged_id = f"consolidated_{int(time.time())}"

                self._nodes[merged_id] = {
                    "path": parent_prefix,
                    "utility": max(avg_utility, 0.5),
                    "content": f"[Consolidated {len(sibling_nodes)} items] {merged_content}",
                    "ts": time.time(),
                }

                # Remove old children
                for nid in sibling_nodes:
                    self._nodes.pop(nid, None)
                    self._access_count.pop(nid, None)

                # Rebuild tree from scratch to reflect all changes
                self._rebuild_tree()

                merged_groups = 1
                nodes_affected = len(sibling_nodes)

            else:
                message = (f"Siblings have avg utility {avg_utility:.2f} >= 0.5 — "
                           "no consolidation needed")

        if merged_groups == 0:
            message = message if 'message' in dir() else "No consolidation needed"

        return {
            "merged_groups": merged_groups,
            "nodes_affected": nodes_affected,
            "message": (f"Consolidated {merged_groups} groups affecting {nodes_affected} nodes"
                        if merged_groups > 0
                        else message),
        }

    def path_similarity(self, path1: str, path2: str) -> float:
        """Compute semantic similarity between two paths.

        Similarity = shared prefix depth / max depth of both paths.

        Returns a float in [0.0, 1.0].
        """
        path1 = self._normalise(path1)
        path2 = self._normalise(path2)

        if path1 == path2:
            return 1.0

        parts1 = path1.strip("/").split("/")
        parts2 = path2.strip("/").split("/")

        shared = sum(1 for a, b in zip(parts1, parts2) if a == b)
        max_depth = max(len(parts1), len(parts2))
        if max_depth == 0:
            return 1.0
        return shared / max_depth

    # ──────────────────────────────────────────────────
    # HORMA §3.4: RC-Token Optimization
    # ──────────────────────────────────────────────────

    def compute_rc_token_saving(self, flat_content: str | None = None) -> dict[str, Any]:
        """Compute RC-token savings from hierarchical vs flat representation.

        HORMA §3.4: Hierarchical paths use dramatically fewer tokens than
        flat text.  The RC (Representation Cost) ratio measures token usage
        of the hierarchical representation relative to an equivalent flat
        representation.

        Args:
            flat_content: Optional flat text baseline.  If None, reconstruct
                          a flat representation from all stored nodes.

        Returns:
            {"hierarchical_tokens": int, "flat_tokens": int,
             "rc_ratio": float, "savings_pct": float,
             "savings_per_node": float}
        """
        with self._lock:
            total_nodes = len(self._nodes)
            if total_nodes == 0:
                return {"hierarchical_tokens": 0, "flat_tokens": 0,
                        "rc_ratio": 1.0, "savings_pct": 0.0, "savings_per_node": 0.0}

            # Hierarchical token cost: sum of all paths + content lengths
            hierarchical_tokens = 0
            for nid, info in self._nodes.items():
                path_cost = len(info["path"].split("/"))
                content_cost = len(info["content"].split())
                hierarchical_tokens += path_cost + content_cost

            # Flat token cost: reconstruct a flat representation
            flat_tokens = 0
            if flat_content:
                flat_tokens = len(flat_content.split())
            else:
                # Simulate flat representation: all content prefixed with
                # a generic tag (no hierarchy benefit)
                for nid, info in self._nodes.items():
                    flat_tokens += len(info["content"].split()) + 2  # +2 for generic tag

            rc_ratio = hierarchical_tokens / max(flat_tokens, 1)
            savings_pct = max(0.0, (1.0 - rc_ratio) * 100.0)

            return {
                "hierarchical_tokens": hierarchical_tokens,
                "flat_tokens": flat_tokens,
                "rc_ratio": round(rc_ratio, 4),
                "savings_pct": round(savings_pct, 2),
                "savings_per_node": round(savings_pct / max(total_nodes, 1), 4),
                "total_nodes": total_nodes,
            }

    def get_stats(self) -> dict[str, Any]:
        """Return summary statistics."""
        with self._lock:
            total_nodes = len(self._nodes)
            total_paths = len(self._tree)
            avg_access = (
                round(sum(self._access_count.values()) / max(total_nodes, 1), 2)
                if total_nodes else 0.0
            )
            path_counts = {
                p: len(nds) for p, nds in self._tree.items() if p != "/"
            }
            top_paths = sorted(path_counts.items(),
                               key=lambda x: -x[1])[:10]

        return {
            "total_nodes": total_nodes,
            "total_paths": total_paths,
            "avg_access": avg_access,
            "top_paths": [{"path": p, "count": c} for p, c in top_paths],
            "nodes_per_path": round(total_nodes / max(total_paths, 1), 1),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rebuild_tree(self) -> None:
        """Rebuild tree index from scratch (after modifications)."""
        self._tree.clear()
        for nid, info in self._nodes.items():
            path = info["path"]
            parts = path.strip("/").split("/")
            for depth in range(len(parts) + 1):
                prefix = "/" + "/".join(parts[:depth])
                if depth == 0:
                    prefix = "/"
                self._tree.setdefault(prefix, set()).add(nid)

    @staticmethod
    def _normalise(path: str) -> str:
        """Ensure *path* starts with ``/`` and has no trailing slash (except root)."""
        path = path.strip().rstrip("/") if path != "/" else path
        if not path.startswith("/"):
            path = "/" + path
        return path
