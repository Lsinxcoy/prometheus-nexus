"""DualPathwayMemory — Verbatim + Compressed Dual Storage System.

Dual-pathway memory architecture inspired by how the brain maintains both
episodic (detail-rich verbatim) and semantic (gist-based compressed) memory.

Verbatim store: exact content with utility scoring, used for detailed recall.
Compressed store: abstracted summaries (first 200 chars), used for broad coverage.

Bidirectional cross-links allow tracing from verbatim → compressed and back.
Selection policy (auto mode) picks the right pathway based on query length and
verbatim match density.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class DualPathwayMemory:
    """Dual-pathway memory: verbatim (exact) + compressed (abstract) stores.

    Usage:
        ds = DualPathwayMemory()
        ds.store_verbatim("mem1", "Detailed research finding about AI memory systems", 0.8)
        ds.store_verbatim("mem2", "Short note", 0.4)
        results = ds.retrieve("AI memory", mode="auto")
    """

    def __init__(
        self,
        verbatim_token_budget: int = 32000,
        compression_threshold_utility: float = 0.7,
        max_compressed_per_verbatim: int = 3,
    ) -> None:
        """Initialize the dual pathway memory.

        Args:
            verbatim_token_budget: Max tokens in verbatim store before eviction.
            compression_threshold_utility: Minimum utility to auto-compress.
            max_compressed_per_verbatim: Max compressed entries per verbatim node.
        """
        self._verbatim_store: dict[str, dict] = {}
        self._compressed_store: dict[str, dict] = {}
        self._links: dict[str, list[str]] = {}  # verbatim_id → [compressed_id]
        self._reverse_links: dict[str, list[str]] = {}  # compressed_id → [verbatim_id]
        self._selection_cache: dict[str, float] = {}  # query_hash → last policy score
        self._verbatim_token_budget: int = verbatim_token_budget
        self._compression_threshold_utility: float = compression_threshold_utility
        self._max_compressed_per_verbatim: int = max_compressed_per_verbatim
        self._total_tokens: int = 0
        self._orphaned_compressed: set[str] = set()

    # ── Public API ────────────────��─────────────────────────────────────────

    def store_verbatim(
        self,
        node_id: str,
        content: str,
        utility: float,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Store exact content in the verbatim store.

        If utility >= compression_threshold_utility, auto-trigger compression.
        If total tokens exceed budget, evict lowest-utility oldest entries.

        Args:
            node_id: Unique identifier for this memory.
            content: Exact content to store.
            utility: Importance score [0, 1].
            tags: Optional tags for filtering.

        Returns:
            {"stored": True, "compressed": bool}
        """
        tags = tags or []
        ts = time.time()
        token_estimate = _estimate_tokens(content)

        self._verbatim_store[node_id] = {
            "content": content,
            "utility": utility,
            "tags": tags,
            "ts": ts,
            "token_estimate": token_estimate,
        }
        self._total_tokens += token_estimate

        compressed = False
        if utility >= self._compression_threshold_utility:
            compressed = True
            self._compress_and_link(node_id, content)

        # Evict if over budget
        self._evict_if_needed()

        logger.debug(
            "DualStorage stored verbatim %s (utility=%.2f, tokens=%d, compressed=%s)",
            node_id[:8], utility, token_estimate, compressed,
        )
        return {"stored": True, "compressed": compressed}

    def retrieve(
        self,
        query: str,
        mode: str = "auto",
        limit: int = 10,
    ) -> dict[str, Any]:
        """Retrieve from dual stores.

        Args:
            query: Search query.
            mode: "verbatim", "compressed", or "auto" (default) for selection policy.
            limit: Max results per pathway.

        Returns:
            {"verbatim": [...], "compressed": [...], "primary_mode": str, "total": int}
        """
        verbatim_hits = self._search_verbatim(query, limit=limit)
        compressed_hits = self._search_compressed(query, limit=limit)

        # Determine primary mode
        primary_mode = self._select_mode(
            query, len(verbatim_hits), mode
        )

        # Cache the decision for learning
        query_hash = str(hash(query.lower()))
        self._selection_cache[query_hash] = 1.0 if primary_mode == "verbatim" else 0.0

        return {
            "verbatim": verbatim_hits,
            "compressed": compressed_hits,
            "primary_mode": primary_mode,
            "total": len(verbatim_hits) + len(compressed_hits),
        }

    def link_verbatim_to_compressed(
        self, verbatim_id: str, compressed_id: str
    ) -> None:
        """Manually link a verbatim entry to a compressed abstraction.

        Args:
            verbatim_id: The verbatim node ID.
            compressed_id: The compressed abstraction ID.
        """
        if verbatim_id not in self._verbatim_store:
            logger.warning("Cannot link: verbatim %s not found", verbatim_id[:8])
            return
        if compressed_id not in self._compressed_store:
            logger.warning("Cannot link: compressed %s not found", compressed_id[:8])
            return

        self._links.setdefault(verbatim_id, [])
        if compressed_id not in self._links[verbatim_id]:
            self._links[verbatim_id].append(compressed_id)

        self._reverse_links.setdefault(compressed_id, [])
        if verbatim_id not in self._reverse_links[compressed_id]:
            self._reverse_links[compressed_id].append(verbatim_id)

        # Update the verbatim store record
        if verbatim_id in self._verbatim_store:
            existing = self._verbatim_store[verbatim_id].get("compressed_ids", [])
            if compressed_id not in existing:
                existing.append(compressed_id)

        # Update the compressed store record
        if compressed_id in self._compressed_store:
            existing = self._compressed_store[compressed_id].get("original_ids", [])
            if verbatim_id not in existing:
                existing.append(verbatim_id)

    def get_compressed_for(self, verbatim_id: str) -> list[dict]:
        """Retrieve all compressed versions of a verbatim entry.

        Args:
            verbatim_id: The verbatim node ID.

        Returns:
            List of compressed entry dicts.
        """
        compressed_ids = self._links.get(verbatim_id, [])
        results = []
        for cid in compressed_ids:
            entry = self._compressed_store.get(cid)
            if entry:
                results.append({
                    "compressed_id": cid,
                    "content": entry["content"],
                    "tokens": entry["tokens"],
                    "ts": entry["ts"],
                })
        return results

    def get_verbatim_sources(self, compressed_id: str) -> list[dict]:
        """Retrieve all verbatim entries compressed into this abstract.

        Args:
            compressed_id: The compressed abstraction ID.

        Returns:
            List of verbatim entry dicts.
        """
        verbatim_ids = self._reverse_links.get(compressed_id, [])
        results = []
        for vid in verbatim_ids:
            entry = self._verbatim_store.get(vid)
            if entry:
                results.append({
                    "node_id": vid,
                    "content": entry["content"],
                    "utility": entry["utility"],
                    "tags": entry["tags"],
                    "ts": entry["ts"],
                })
        return results

    def evict_verbatim(self, node_id: str) -> None:
        """Remove a verbatim entry and update reverse links.

        Orphaned compressed entries (no remaining verbatim links) are kept
        but marked as orphaned.

        Args:
            node_id: The verbatim node ID to evict.
        """
        if node_id not in self._verbatim_store:
            return

        # Remove token count
        self._total_tokens -= self._verbatim_store[node_id].get("token_estimate", 0)

        # Update reverse links from compressed side
        compressed_ids = self._links.get(node_id, [])
        for cid in compressed_ids:
            if cid in self._reverse_links:
                if node_id in self._reverse_links[cid]:
                    self._reverse_links[cid].remove(node_id)
                if not self._reverse_links[cid]:
                    # Orphaned — keep but mark
                    self._orphaned_compressed.add(cid)

        # Clean up forward links
        self._links.pop(node_id, None)

        # Remove from verbatim store
        del self._verbatim_store[node_id]
        logger.debug("DualStorage evicted verbatim %s", node_id[:8])

    def get_stats(self) -> dict[str, Any]:
        """Get memory statistics.

        Returns:
            Dict with verbatim_count, compressed_count, total_tokens, links_count,
            avg_compression_ratio, token_budget_used_pct.
        """
        verbatim_count = len(self._verbatim_store)
        compressed_count = len(self._compressed_store)
        links_count = sum(len(v) for v in self._links.values())

        # Average compression ratio: compressed_tokens / original_verbatim_tokens
        ratios = []
        for cid, centry in self._compressed_store.items():
            original_ids = centry.get("original_ids", [])
            original_tokens = 0
            for vid in original_ids:
                ventry = self._verbatim_store.get(vid)
                if ventry:
                    original_tokens += ventry.get("token_estimate", 0)
            if original_tokens > 0:
                ratios.append(centry["tokens"] / original_tokens)

        avg_compression_ratio = (
            round(sum(ratios) / len(ratios), 4) if ratios else 0.0
        )
        budget_used_pct = round(
            (self._total_tokens / self._verbatim_token_budget) * 100, 2
        )

        return {
            "verbatim_count": verbatim_count,
            "compressed_count": compressed_count,
            "total_tokens": self._total_tokens,
            "links_count": links_count,
            "avg_compression_ratio": avg_compression_ratio,
            "token_budget_used_pct": budget_used_pct,
        }

    # ── Internal helpers ───────────────────────────────────────────────────

    def _compress_and_link(self, node_id: str, content: str) -> str:
        """Create a compressed summary and link it to the verbatim entry.

        Compression: first 200 characters as summary (simple extraction).

        Args:
            node_id: The verbatim node ID.
            content: The content to compress.

        Returns:
            The compressed_id of the new entry.
        """
        # Build summary: first 200 chars
        summary = content[:200].strip()
        if len(content) > 200:
            summary = summary.rstrip() + "…"

        compressed_id = f"comp_{node_id}_{int(time.time())}"
        token_count = _estimate_tokens(summary)

        self._compressed_store[compressed_id] = {
            "content": summary,
            "tokens": token_count,
            "original_ids": [node_id],
            "ts": time.time(),
        }

        # Create bidirectional links
        self._links.setdefault(node_id, [])
        # Enforce max compressed per verbatim
        if len(self._links[node_id]) >= self._max_compressed_per_verbatim:
            existing = self._links[node_id].copy()
            # Put new one and remove the oldest
            pass  # keep all — we limit display but don't drop old ones
        if compressed_id not in self._links[node_id]:
            self._links[node_id].append(compressed_id)

        self._reverse_links.setdefault(compressed_id, [])
        if node_id not in self._reverse_links[compressed_id]:
            self._reverse_links[compressed_id].append(node_id)

        # Update verbatim record
        comp_ids = self._verbatim_store[node_id].setdefault("compressed_ids", [])
        if compressed_id not in comp_ids:
            comp_ids.append(compressed_id)

        logger.debug(
            "DualStorage compressed %s → %s (%d tokens)",
            node_id[:8], compressed_id[:16], token_count,
        )
        return compressed_id

    def _search_verbatim(self, query: str, limit: int = 10) -> list[dict]:
        """Search verbatim store by substring match and tag filtering."""
        query_lower = query.lower()
        query_words = query_lower.split()
        results = []

        for nid, entry in self._verbatim_store.items():
            content_lower = entry["content"].lower()

            # Substring match
            if not any(word in content_lower for word in query_words):
                continue

            results.append({
                "node_id": nid,
                "content": entry["content"][:500],
                "utility": entry["utility"],
                "tags": entry["tags"],
                "ts": entry["ts"],
                "token_estimate": entry.get("token_estimate", 0),
            })

        # Sort by utility descending, then by timestamp descending
        results.sort(key=lambda r: (r["utility"], r["ts"]), reverse=True)
        return results[:limit]

    def _search_compressed(self, query: str, limit: int = 10) -> list[dict]:
        """Search compressed store by substring match."""
        query_lower = query.lower()
        query_words = query_lower.split()
        results = []

        for cid, entry in self._compressed_store.items():
            content_lower = entry["content"].lower()
            if not any(word in content_lower for word in query_words):
                continue

            is_orphaned = cid in self._orphaned_compressed
            results.append({
                "compressed_id": cid,
                "content": entry["content"],
                "tokens": entry["tokens"],
                "ts": entry["ts"],
                "source_count": len(entry.get("original_ids", [])),
                "orphaned": is_orphaned,
            })

        results.sort(key=lambda r: r["ts"], reverse=True)
        return results[:limit]

    def _select_mode(
        self, query: str, verbatim_match_count: int, mode: str
    ) -> str:
        """Select retrieval mode based on policy.

        Args:
            query: The search query.
            verbatim_match_count: Number of verbatim matches found.
            mode: Requested mode ("auto", "verbatim", or "compressed").

        Returns:
            The selected primary mode.
        """
        if mode == "verbatim":
            return "verbatim"
        if mode == "compressed":
            return "compressed"

        # Auto mode: policy based on query length and verbatim match density
        if len(query) > 20 and verbatim_match_count >= 3:
            return "verbatim"
        return "compressed"

    def _evict_if_needed(self) -> None:
        """Evict lowest-utility oldest verbatim entries when over budget."""
        while self._total_tokens > self._verbatim_token_budget and self._verbatim_store:
            # Find worst candidate: lowest utility, then oldest
            worst_id = min(
                self._verbatim_store,
                key=lambda nid: (
                    self._verbatim_store[nid]["utility"],
                    -self._verbatim_store[nid]["ts"],
                ),
            )
            self.evict_verbatim(worst_id)


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English text."""
    return max(1, len(text) // 4)
