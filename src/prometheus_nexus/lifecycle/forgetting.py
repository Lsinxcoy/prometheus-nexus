"""WeibullForgetting — Weibull distribution-based forgetting curve with FSFM.

Based on:
- FSFM: A Biologically-Inspired Framework for Selective Forgetting of
  Agent Memory (arXiv 2604.20300)
- Three FSFM dimensions: (1) Efficiency — intelligent memory pruning,
  (2) Quality — dynamic update of outdated preferences, (3) Security —
  active sanitization of sensitive content.
- Weibull CDF: R(t) = exp(-(t/λ)^k)
  - shape(k): controls forgetting curve shape (1=exponential, >1=steeper)
  - scale(λ): controls when forgetting accelerates
  - LRU eviction: evicts nodes with lowest retention when over max_tracked

FSFM Security dimension (safety_trigger_forget):
    Immediately sets retention=0 for specified node_ids, logs the
    operation with a reason string, and returns statistics. Supports
    classification of sensitive content detection (malicious input,
    PII leakage, privacy-violating data).

FSFM Quality dimension (adaptive_reinforce):
    Boosts retention for frequently accessed nodes with diminishing
    returns. Each access increases retention but the boost magnitude
    decays as the node approaches R=1.0. Also records access count and
    boosts the base retention calculation (the Weibull curve is scaled
    by the reinforcement factor).

FSFM Efficiency dimension (prune / prune_below_threshold):
    Permanently removes nodes below a retention threshold to free
    memory. This is the "intelligent memory pruning" mechanism.
"""

from __future__ import annotations
import logging
import math
import time

logger = logging.getLogger(__name__)


class WeibullForgetting:
    """Weibull distribution-based forgetting curve with FSFM three dimensions.

    Usage:
        wf = WeibullForgetting(shape=1.5, scale=100.0)

        # Compute retention for different ages
        r_0 = wf.compute_retention(age=0.0)    # R=1.0
        r_50 = wf.compute_retention(age=50.0)   # R≈0.78
        r_100 = wf.compute_retention(age=100.0)  # R≈0.50
        r_200 = wf.compute_retention(age=200.0)  # R≈0.14

        # FSFM Security: forcibly forget nodes
        wf.safety_trigger_forget(["node1", "node2"], reason="PII detected")

        # FSFM Quality: reinforce frequently accessed nodes
        wf.adaptive_reinforce("node3")

        # FSFM Efficiency: prune expired nodes
        pruned = wf.prune_below_threshold(threshold=0.05)
    """

    def __init__(
        self,
        shape: float = 1.5,
        scale: float = 100.0,
        max_tracked: int = 5000,
        reinforce_base: float = 0.15,
        reinforce_decay: float = 0.7,
        max_reinforce_count: int = 20,
    ) -> None:
        """Initialize the forgetting curve.

        Args:
            shape: Weibull shape parameter (k). Higher = sharper forgetting.
            scale: Weibull scale parameter (λ). Higher = slower forgetting.
            max_tracked: Maximum nodes to track before LRU eviction.
            reinforce_base: Base boost amount for adaptive_reinforce.
            reinforce_decay: Multiplicative decay per reinforcement (diminishing returns).
            max_reinforce_count: Max reinforcements before boost becomes negligible.
        """
        if shape <= 0:
            raise ValueError(f"shape must be > 0, got {shape}")
        if scale <= 0:
            raise ValueError(f"scale must be > 0, got {scale}")
        if max_tracked <= 0:
            raise ValueError(f"max_tracked must be > 0, got {max_tracked}")

        self._shape = shape
        self._scale = scale
        self._max_tracked = max_tracked
        self._reinforce_base = reinforce_base
        self._reinforce_decay = reinforce_decay
        self._max_reinforce_count = max_reinforce_count

        # Core retention storage
        self._retentions: dict[str, float] = {}
        self._access_times: dict[str, float] = {}

        # FSFM Quality dimension: reinforcement tracking
        self._access_counts: dict[str, int] = {}
        self._reinforcement_factors: dict[str, float] = {}

        # FSFM Security dimension: forget log
        self._safety_forget_log: list[dict] = []
        self._forgotten_nodes: set[str] = set()  # Track nodes forgotten via safety trigger

    # ── Core Weibull ──

    def compute_retention(self, age: float) -> float:
        """Compute retention probability for a given age.

        Args:
            age: Age of memory (in same units as scale).

        Returns:
            Retention probability [0, 1].
        """
        if age < 0:
            return 1.0
        return math.exp(-((age / self._scale) ** self._shape))

    def compute_retention_compat(self, node_id: str, age: float = 1.0) -> float:
        """Compute and cache retention for a node.

        Args:
            node_id: Node identifier.
            age: Age of the node.

        Returns:
            Retention probability [0, 1].
        """
        base_r = self.compute_retention(age)

        # Apply reinforcement factor (FSFM Quality)
        rf = self._reinforcement_factors.get(node_id, 1.0)
        # Reinforcement pushes retention higher: R' = min(1.0, R * rf)
        r = min(1.0, base_r * rf)

        self._retentions[node_id] = r
        self._access_times[node_id] = time.time()

        # LRU eviction if over limit
        if len(self._retentions) > self._max_tracked:
            sorted_keys = sorted(self._retentions, key=lambda k: self._retentions[k])
            evict_count = len(self._retentions) // 4
            for k in sorted_keys[:evict_count]:
                self._evict_node(k)

        return r

    def get_retention(self, node_id: str) -> float:
        """Get cached retention for a node."""
        return self._retentions.get(node_id, 1.0)

    def get_expired_nodes(self, threshold: float = 0.1) -> list[str]:
        """Get nodes with retention below threshold."""
        return [nid for nid, r in self._retentions.items() if r < threshold]

    def get_most_forgotten(self, top_k: int = 10) -> list[dict]:
        """Get nodes closest to being forgotten."""
        sorted_nodes = sorted(self._retentions.items(), key=lambda x: x[1])
        return [{"node_id": nid, "retention": r} for nid, r in sorted_nodes[:top_k]]

    def get_most_retained(self, top_k: int = 10) -> list[dict]:
        """Get nodes with highest retention."""
        sorted_nodes = sorted(
            self._retentions.items(), key=lambda x: x[1], reverse=True
        )
        return [{"node_id": nid, "retention": r} for nid, r in sorted_nodes[:top_k]]

    def get_retention_distribution(self, bins: int = 10) -> dict[int, int]:
        """Get retention distribution in bins."""
        distribution = {i: 0 for i in range(bins)}
        for r in self._retentions.values():
            bin_idx = min(int(r * bins), bins - 1)
            distribution[bin_idx] += 1
        return distribution

    def predict_forget_time(self, node_id: str, threshold: float = 0.1) -> float | None:
        """Predict when a node will be forgotten below threshold.

        Solves: threshold = exp(-(t/λ)^k) for t
        Returns: t = λ × (-ln(threshold))^(1/k)
        """
        # Check if node was explicitly forgotten
        if node_id in self._forgotten_nodes:
            return 0.0
        r = self._retentions.get(node_id, 1.0)
        if r <= threshold:
            return 0.0
        # Apply reinforcement factor to the prediction
        rf = self._reinforcement_factors.get(node_id, 1.0)
        # Adjust threshold: reinforced nodes take longer to forget
        adjusted_threshold = threshold / max(rf, 0.1)
        adjusted_threshold = min(adjusted_threshold, 0.99)
        t = self._scale * (-math.log(adjusted_threshold)) ** (1.0 / self._shape)
        return t

    # ── FSFM Security Dimension (arXiv 2604.20300, Section B-4) ──

    def safety_trigger_forget(
        self,
        node_ids: list[str],
        reason: str = "security",
        classification: str | None = None,
    ) -> dict:
        """安全触发遗忘：立即将指定节点遗忘（retention 设为 0）。

        FSFM Security dimension (Section B-4 "Safety-Triggered Forgetting"):
        Detects malicious/sensitive content and immediately forgets it.

        Args:
            node_ids: List of node identifiers to forget.
            reason: Human-readable reason for the forced forget.
            classification: Optional security classification (e.g., "malicious",
                          "PII", "privacy_violation", "toxic_content").

        Returns:
            Dict with keys: forgotten (count), total_requested (count),
                           reason, classification, log (list of entries).
        """
        if not node_ids:
            return {
                "forgotten": 0,
                "total_requested": 0,
                "reason": reason,
                "classification": classification,
                "log": [],
            }

        forgotten: list[str] = []
        already_forgotten: list[str] = []

        for nid in node_ids:
            # Always track as forgotten, even if not in retentions
            self._forgotten_nodes.add(nid)  # Track as forgotten
            if nid in self._retentions:
                self._retentions[nid] = 0.0
                self._access_times.pop(nid, None)
                self._reinforcement_factors.pop(nid, None)
                self._access_counts.pop(nid, None)  # Fix: also clear access counts
                forgotten.append(nid)
            else:
                already_forgotten.append(nid)

        # Log the safety forget action
        timestamp = time.time()
        log_entry = {
            "timestamp": timestamp,
            "node_ids": node_ids,
            "forgotten": forgotten,
            "already_forgotten": already_forgotten,
            "reason": reason,
            "classification": classification,
        }
        self._safety_forget_log.append(log_entry)

        logger.warning(
            "FSFM safety-triggered forget: %d nodes (%s, classification=%s)",
            len(forgotten),
            reason,
            classification or "unspecified",
        )

        return {
            "forgotten": len(forgotten),
            "total_requested": len(node_ids),
            "reason": reason,
            "classification": classification,
            "log_entry": log_entry,
        }

    def get_safety_forget_log(
        self, limit: int = 50, classification: str | None = None
    ) -> list[dict]:
        """Get the safety forget log, optionally filtered by classification.

        Args:
            limit: Max log entries to return.
            classification: Optional filter by classification string.

        Returns:
            List of log entries, newest first.
        """
        log = self._safety_forget_log
        if classification:
            log = [e for e in log if e.get("classification") == classification]
        return sorted(log, key=lambda x: x["timestamp"], reverse=True)[:limit]

    def get_safety_candidates(self, threshold: float = 0.8) -> list[dict]:
        """获取低 retention 节点作为安全遗忘候选。

        Args:
            threshold: Maximum retention value to be considered a candidate.

        Returns:
            Sorted list of candidate dicts (node_id, retention), up to 100.
        """
        candidates = []
        for nid, r in self._retentions.items():
            if r < threshold:
                candidates.append({"node_id": nid, "retention": r})
        candidates.sort(key=lambda x: x["retention"])
        return candidates[:100]

    # ── FSFM Quality Dimension (arXiv 2604.20300, Section B-3) ──

    def adaptive_reinforce(self, node_id: str, boost: float | None = None) -> float:
        """自适应增强：对频繁访问的记忆增加 retention。

        FSFM Quality dimension (Section B-3 "Adaptive Reinforcement"):
        Frequently accessed memories receive reinforcement, while rarely
        accessed ones decay faster. Implements diminishing returns — each
        successive boost is smaller.

        Args:
            node_id: Node identifier to reinforce.
            boost: Override boost amount. If None, uses automatic diminishing
                   returns based on access count.

        Returns:
            New retention value after reinforcement.
        """
        # Update access count
        current_count = self._access_counts.get(node_id, 0) + 1
        self._access_counts[node_id] = current_count

        # Compute boost with diminishing returns
        if boost is not None:
            actual_boost = boost
        else:
            # Diminishing returns: each access gives less boost
            exp_idx = min(current_count - 1, self._max_reinforce_count)
            actual_boost = self._reinforce_base * (self._reinforce_decay ** exp_idx)

        # Update reinforcement factor (multiplicative)
        current_rf = self._reinforcement_factors.get(node_id, 1.0)
        # Reinforcement boost translates to a multiplier bump
        new_rf = current_rf + actual_boost
        # Cap at a reasonable max
        new_rf = min(new_rf, 3.0)
        self._reinforcement_factors[node_id] = new_rf

        # Update retention directly
        current_r = self._retentions.get(node_id, 0.0)
        new_ret = min(1.0, current_r + actual_boost * 0.5)
        self._retentions[node_id] = new_ret

        logger.debug(
            "FSFM adaptive reinforce: node=%s, count=%d, rf=%.3f, retention=%.3f",
            node_id,
            current_count,
            new_rf,
            new_ret,
        )

        return new_ret

    def get_reinforcement_factor(self, node_id: str) -> float:
        """Get the reinforcement factor for a node."""
        return self._reinforcement_factors.get(node_id, 1.0)

    def get_access_count(self, node_id: str) -> int:
        """Get the access count for a node."""
        return self._access_counts.get(node_id, 0)

    # ── FSFM Efficiency Dimension (Section B-2) ──

    def prune_below_threshold(self, threshold: float = 0.05) -> dict:
        """FSFM Efficiency: permanently remove nodes below retention threshold.

        Intelligent memory pruning — removes low-value memories to free
        resources.

        Args:
            threshold: Retention threshold below which nodes are pruned.

        Returns:
            Dict with keys: pruned (count), total_before (count),
                           freed_node_ids (list).
        """
        total_before = len(self._retentions)
        to_prune = [nid for nid, r in self._retentions.items() if r < threshold]

        if not to_prune:
            return {
                "pruned": 0,
                "total_before": total_before,
                "total_after": total_before,
                "freed_node_ids": [],
            }

        for nid in to_prune:
            self._evict_node(nid)

        logger.info(
            "FSFM efficiency prune: removed %d nodes (threshold=%.3f)",
            len(to_prune),
            threshold,
        )

        return {
            "pruned": len(to_prune),
            "total_before": total_before,
            "total_after": len(self._retentions),
            "freed_node_ids": to_prune,
        }

    def prune_by_count(self, count: int) -> dict:
        """FSFM Efficiency: prune the N lowest-retention nodes.

        Args:
            count: Number of lowest-retention nodes to prune.

        Returns:
            Dict with keys: pruned, total_before, total_after.
        """
        if count <= 0:
            return {"pruned": 0, "total_before": len(self._retentions), "total_after": len(self._retentions)}

        total_before = len(self._retentions)
        sorted_nodes = sorted(self._retentions.items(), key=lambda x: x[1])
        to_prune = [nid for nid, _ in sorted_nodes[:count]]

        for nid in to_prune:
            self._evict_node(nid)

        return {
            "pruned": len(to_prune),
            "total_before": total_before,
            "total_after": len(self._retentions),
        }

    # ── Stats ──

    def get_stats(self) -> dict:
        """Get comprehensive statistics including FSFM dimensions."""
        vals = list(self._retentions.values())
        return {
            "tracked_nodes": len(self._retentions),
            "avg_retention": sum(vals) / max(len(vals), 1),
            "min_retention": min(vals) if vals else 0,
            "max_retention": max(vals) if vals else 1,
            "shape": self._shape,
            "scale": self._scale,
            "fsfm": {
                "safety_forget_count": len(self._safety_forget_log),
                "reinforced_nodes": len(self._reinforcement_factors),
                "total_access_events": sum(self._access_counts.values()),
            },
        }

    # ── Internal ──

    def _evict_node(self, node_id: str) -> None:
        """Remove a node from all tracking structures."""
        self._retentions.pop(node_id, None)
        self._access_times.pop(node_id, None)
        self._access_counts.pop(node_id, None)
        self._reinforcement_factors.pop(node_id, None)
