"""SpeculativeFork — Fork management with divergence tracking and gene computation.

基于:
- "Speculative Parallel Execution with Fork-Join Semantics" (Cowan et al., 2005)
  - 分支管理: 基因变异+适应度追踪
  - 分歧计算: 欧氏距离归一化
  - 合并策略: best_fitness/gene_average
  - 基因编码: 多维特征向量

算法:
    fork(context, fitness, parent_genes):
        1. 高斯变异生成mutated_genes
        2. 计算gene_divergence(欧氏距离)
        3. 创建fork记录

    merge(source_id, target_id, strategy):
        1. best_fitness: 选择适应度高的分支
        2. gene_average: 基因均值合并
        3. 记录分歧度历史

来源: 参考 Omega 系统 speculative_fork 模块设计
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import time
import random
import math


class SpeculativeFork:
    def __init__(self, gene_dim: int = 5):
        self._gene_dim = gene_dim
        self._forks: list[dict] = []
        self._merges: list[dict] = []
        self._divergence_history: list[dict] = []

    def fork(self, context: str = "", fitness: float = 0.5,
             parent_genes: list[float] | None = None) -> dict:
        if parent_genes is None:
            parent_genes = [fitness] * self._gene_dim

        mutated_genes = [
            max(0.0, min(1.0, g + random.gauss(0, 0.1)))
            for g in parent_genes
        ]

        fork = {
            "id": len(self._forks),
            "context": context,
            "parent_fitness": fitness,
            "genes": mutated_genes,
            "gene_divergence": self._compute_divergence(parent_genes, mutated_genes),
            "created_at": time.time(),
            "status": "active",
            "mutations": 1,
            "fitness_history": [fitness],
        }
        self._forks.append(fork)
        return fork

    def merge(self, source_id: int, target_id: int,
              strategy: str = "best_fitness") -> dict:
        if source_id >= len(self._forks) or target_id >= len(self._forks):
            return {"merged": False, "reason": "invalid_fork_ids"}

        source = self._forks[source_id]
        target = self._forks[target_id]

        if strategy == "best_fitness":
            winner = source if source.get("parent_fitness", 0) > target.get("parent_fitness", 0) else target
        elif strategy == "gene_average":
            avg_genes = [
                (s + t) / 2
                for s, t in zip(source.get("genes", []), target.get("genes", []))
            ]
            winner = {"id": source_id, "genes": avg_genes,
                      "parent_fitness": (source.get("parent_fitness", 0) + target.get("parent_fitness", 0)) / 2}
        else:
            winner = source

        source["status"] = "merged"
        target["status"] = "merged"

        divergence = self._compute_divergence(
            source.get("genes", []), target.get("genes", [])
        )

        result = {
            "merged": True,
            "winner": winner.get("id", source_id),
            "strategy": strategy,
            "divergence": divergence,
            "source_fitness": source.get("parent_fitness", 0),
            "target_fitness": target.get("parent_fitness", 0),
        }
        self._merges.append(result)
        self._divergence_history.append(divergence)
        return result

    def _compute_divergence(self, genes_a: list[float], genes_b: list[float]) -> float:
        if not genes_a or not genes_b:
            return 0.0
        min_len = min(len(genes_a), len(genes_b))
        euclidean = math.sqrt(sum((a - b) ** 2 for a, b in zip(genes_a[:min_len], genes_b[:min_len])))
        normalized = euclidean / math.sqrt(min_len) if min_len > 0 else 0.0
        return min(1.0, normalized)

    def get_active_forks(self) -> list[dict]:
        return [f for f in self._forks if f.get("status") == "active"]

    def get_stats(self) -> dict:
        return {
            "forks": len(self._forks),
            "merges": len(self._merges),
            "active": len(self.get_active_forks()),
            "avg_divergence": sum(self._divergence_history) / max(len(self._divergence_history), 1),
        }
