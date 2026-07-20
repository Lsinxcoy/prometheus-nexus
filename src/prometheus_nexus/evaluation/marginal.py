"""MarginalAdvantageAccumulator — Evidence accumulation for agent self-evolution.

Based on: "Marginal Advantage Accumulation for Memory-Driven Agent Self-Evolution"
(arXiv:2606.20475, Yang et al. 2026)

Key Concepts from Paper:
    1. Alignability: Operations must be comparable across batches
    2. Comparability: Differential signals make operations comparable
    3. EMA (Exponential Moving Average) evidence accumulation per operation
    4. Semantic identity merging for cross-batch traceability
    5. Post-processing architecture (reduces token consumption by ~75%)
    6. Distinguish stably effective operations from accidental hits

Paper Finding:
    "MAA achieves the best results in 14 out of 16 settings across 4 benchmarks,
     consistently outperforming existing batch-level distillation baselines."

Algorithm:
    For each operation o in batch b:
        1. Compute differential signal: δ(o, b) = score(o, b) - baseline(b)
        2. Accumulate via EMA: EMA(o) = α × δ(o, b) + (1-α) × EMA(o)
        3. Merge by semantic identity (operation signature)
    Final advantage = weighted sum of EMA values

Complexity:
    accumulate(): O(N) per batch
    get_advantages(): O(N log N) for ranking
    merge_operations(): O(N) for semantic merge
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import hashlib
import math
from dataclasses import dataclass, field
from typing import Any

import time


@dataclass
class OperationRecord:
    """A recorded operation with its advantage evidence."""
    operation_id: str = ""
    operation_type: str = ""
    content: str = ""
    semantic_hash: str = ""
    ema_advantage: float = 0.0
    count: int = 0
    total_differential: float = 0.0
    batch_history: list[dict] = field(default_factory=list)


@dataclass
class BatchRecord:
    """A batch of evaluations with baseline."""
    batch_id: int = 0
    baseline_score: float = 0.0
    operations: list[dict] = field(default_factory=list)
    timestamp: float = 0.0
    total_tokens: int = 0


class MarginalAdvantageAccumulator:
    """Marginal Advantage Accumulation for memory-driven self-evolution.

    Based on MAA paper (arXiv:2606.20475).

    Usage:
        maa = MarginalAdvantageAccumulator(alpha=0.3)

        # Process batches
        maa.accumulate_batch(
            batch_id=1,
            baseline_score=0.5,
            operations=[
                {"id": "op1", "type": "memory_write", "content": "AI research", "score": 0.8},
                {"id": "op2", "type": "memory_delete", "content": "old data", "score": 0.3},
            ]
        )

        # Get accumulated advantages
        advantages = maa.get_advantages()
        stable = maa.get_stable_operations(threshold=0.1)
    """

    def __init__(self, alpha: float = 0.3, semantic_window: int = 50):
        """Initialize MAA accumulator.

        Args:
            alpha: EMA decay rate (0 = only history, 1 = only current).
            semantic_window: Window for semantic identity matching.
        """
        self._alpha = alpha
        self._semantic_window = semantic_window
        self._operations: dict[str, OperationRecord] = {}
        self._batches: list[BatchRecord] = []
        self._batch_count = 0
        self._total_differentials = 0
        self._records: list[dict] = []

    def accumulate_batch(self, batch_id: int | None = None,
                         baseline_score: float = 0.0,
                         operations: list[dict] | None = None) -> dict:
        """Accumulate evidence from a batch of operations.

        Args:
            batch_id: Batch identifier (auto-increments if None).
            baseline_score: Baseline score for differential computation.
            operations: List of operation dicts with id, type, content, score.

        Returns:
            Dict with batch accumulation results.
        """
        if batch_id is None:
            self._batch_count += 1
            batch_id = self._batch_count
        else:
            self._batch_count = max(self._batch_count, batch_id)

        operations = operations or []

        # Compute differential for each operation
        differentials = []
        for op in operations:
            op_id = op.get("id", f"op_{len(differentials)}")
            op_score = op.get("score", 0.0)
            differential = op_score - baseline_score
            differentials.append(differential)
            self._total_differentials += abs(differential)

            # Get or create operation record
            semantic_hash = self._compute_semantic_hash(op)
            if op_id not in self._operations:
                self._operations[op_id] = OperationRecord(
                    operation_id=op_id,
                    operation_type=op.get("type", ""),
                    content=op.get("content", ""),
                    semantic_hash=semantic_hash,
                )

            rec = self._operations[op_id]

            # EMA accumulation
            if rec.count == 0:
                rec.ema_advantage = differential
            else:
                rec.ema_advantage = self._alpha * differential + (1 - self._alpha) * rec.ema_advantage

            rec.count += 1
            rec.total_differential += differential
            rec.batch_history.append({
                "batch_id": batch_id,
                "differential": differential,
                "score": op_score,
                "baseline": baseline_score,
            })

            # Keep history bounded
            if len(rec.batch_history) > self._semantic_window:
                rec.batch_history = rec.batch_history[-self._semantic_window // 2:]

        # Record batch
        batch = BatchRecord(
            batch_id=batch_id, baseline_score=baseline_score,
            operations=operations, timestamp=time.time(),
        )
        self._batches.append(batch)

        # Semantic merge
        merged = self._merge_by_semantic()

        return {
            "batch_id": batch_id,
            "operations_processed": len(operations),
            "avg_differential": sum(differentials) / max(len(differentials), 1),
            "merged_groups": len(merged),
        }

    def _compute_semantic_hash(self, op: dict) -> str:
        """Compute semantic hash for operation identity."""
        content = op.get("content", "")
        op_type = op.get("type", "")
        key = f"{op_type}:{content[:100]}"
        return hashlib.md5(key.encode()).hexdigest()[:16]

    def _merge_by_semantic(self) -> dict[str, list[str]]:
        """Merge operations by semantic identity."""
        semantic_groups: dict[str, list[str]] = {}
        for op_id, rec in self._operations.items():
            if rec.semantic_hash not in semantic_groups:
                semantic_groups[rec.semantic_hash] = []
            semantic_groups[rec.semantic_hash].append(op_id)
        return semantic_groups

    def get_advantages(self, top_k: int | None = None) -> list[dict]:
        """Get operations ranked by accumulated advantage.

        Args:
            top_k: If specified, return only top k operations.

        Returns:
            List of operation advantages sorted by EMA value.
        """
        advantages = []
        for op_id, rec in self._operations.items():
            advantages.append({
                "operation_id": op_id,
                "operation_type": rec.operation_type,
                "ema_advantage": rec.ema_advantage,
                "count": rec.count,
                "total_differential": rec.total_differential,
                "avg_differential": rec.total_differential / max(rec.count, 1),
                "semantic_hash": rec.semantic_hash,
            })

        advantages.sort(key=lambda x: x["ema_advantage"], reverse=True)

        if top_k:
            advantages = advantages[:top_k]

        return advantages

    def get_stable_operations(self, threshold: float = 0.1,
                               min_batches: int = 3) -> list[dict]:
        """Get operations with stable positive advantage.

        From paper: "distinguish stably effective operations from accidental hits."

        Args:
            threshold: Minimum EMA advantage to be considered stable.
            min_batches: Minimum batch appearances for stability.

        Returns:
            List of stable operations.
        """
        stable = []
        for op_id, rec in self._operations.items():
            if rec.count >= min_batches and rec.ema_advantage > threshold:
                # Check consistency (low variance in batch history)
                if len(rec.batch_history) >= 2:
                    diffs = [b["differential"] for b in rec.batch_history]
                    mean_diff = sum(diffs) / len(diffs)
                    variance = sum((d - mean_diff) ** 2 for d in diffs) / len(diffs)
                    consistency = 1.0 / (1.0 + variance)

                    if consistency > 0.5:
                        stable.append({
                            "operation_id": op_id,
                            "operation_type": rec.operation_type,
                            "ema_advantage": rec.ema_advantage,
                            "count": rec.count,
                            "consistency": consistency,
                        })

        stable.sort(key=lambda x: x["ema_advantage"], reverse=True)
        return stable

    def get_operation_history(self, operation_id: str) -> list[dict]:
        """Get batch history for a specific operation."""
        rec = self._operations.get(operation_id)
        if not rec:
            return []
        return rec.batch_history

    def get_batch_comparison(self, batch1_id: int, batch2_id: int) -> dict:
        """Compare two batches for evolution analysis."""
        b1 = next((b for b in self._batches if b.batch_id == batch1_id), None)
        b2 = next((b for b in self._batches if b.batch_id == batch2_id), None)

        if not b1 or not b2:
            return {"error": "batch_not_found"}

        # Compare operation scores
        b1_scores = {op.get("id", ""): op.get("score", 0) for op in b1.operations}
        b2_scores = {op.get("id", ""): op.get("score", 0) for op in b2.operations}

        improvements = 0
        declines = 0
        for op_id in set(b1_scores.keys()) | set(b2_scores.keys()):
            s1 = b1_scores.get(op_id, 0)
            s2 = b2_scores.get(op_id, 0)
            if s2 > s1:
                improvements += 1
            elif s2 < s1:
                declines += 1

        return {
            "batch1_id": batch1_id,
            "batch2_id": batch2_id,
            "baseline_change": b2.baseline_score - b1.baseline_score,
            "improvements": improvements,
            "declines": declines,
            "net_improvement": improvements - declines,
        }

    def record(self, gain: float = 0.0, dimension: str = "", description: str = "") -> None:
        """Record a marginal advantage (backward-compatible method).

        Args:
            gain: Marginal gain value.
            dimension: Dimension of the gain.
            description: Description of the gain.
        """
        self._records.append({"gain": gain, "dimension": dimension, "description": description})

    def get_stats(self) -> dict:
        """Get MAA statistics."""
        ema_values = [r.ema_advantage for r in self._operations.values()]
        gains = [r.get("gain", 0) for r in self._records]
        return {
            "total_operations": len(self._operations),
            "total_batches": len(self._batches),
            "total_differentials": self._total_differentials,
            "avg_ema": sum(ema_values) / max(len(ema_values), 1),
            "max_ema": max(ema_values) if ema_values else 0,
            "min_ema": min(ema_values) if ema_values else 0,
            "records": len(self._records),
            "total_gain": sum(gains),
        }
