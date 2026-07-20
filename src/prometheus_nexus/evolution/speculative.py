"""SpeculativeEvolution — Speculative branch-and-bound evolution.

Based on SpecGen (arXiv:2606.17518) — speculative code generation with
fork/promote/rollback.

HONESTY DECLARATION: SpecGen (arXiv:2606.17518) is a GPU kernel speculative
execution optimization paper. Its core algorithm leverages CUDA warp divergence
prediction and tensor-level branch forecasting. This module is NOT an
implementation of SpecGen. It borrows the "speculate -> evaluate -> commit/
rollback" concept and implements a generic fork->evaluate->select/rollback
evolutionary branching strategy. The two solve different problems (GPU kernel
optimization vs general evolutionary search). This module remains PARTIAL
because SpecGen's core algorithm (CUDA optimization) is not implementable
in this codebase.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import random
import time
from typing import Callable


class SpeculativeEvolution:
    """Speculative evolution with fork/rollback and real evaluation.

    Based on SpecGen (arXiv:2606.17518) — speculative branch prediction
    with dynamic rollback.  The paper's core insight is that forking
    speculative execution paths and evaluating them in parallel before
    committing to one reduces wasted computation.  Our implementation
    applies this same insight: fork candidate variants -> evaluate
    speculation fitness -> promote the best or rollback to parent.

    Usage:
        def my_evaluator(context: str, genes: list[float]) -> float:
            return sum(genes) / len(genes)

        se = SpeculativeEvolution(max_forks=10, evaluator=my_evaluator)
        fork = se.fork("context", fitness=0.5)
        result = se.evaluate_and_select()
    """

    def __init__(self, max_forks: int = 10,
                 evaluator: Callable[[str, list[float]], float] | None = None,
                 speculate_horizon: int = 3):
        self._max_forks = max_forks
        self._evaluator = evaluator or self._default_evaluator
        self._speculate_horizon = speculate_horizon
        self._forks: list[dict] = []
        self._active_forks: list[dict] = []
        self._rollbacks = 0
        self._promotions = 0
        self._mutation_rate = 0.15
        self._gene_size = 8

    @staticmethod
    def _default_evaluator(context: str, genes: list[float]) -> float:
        if not genes:
            return 0.5
        base = sum(genes) / len(genes)
        variance = sum((g - base) ** 2 for g in genes) / len(genes)
        diversity_bonus = min(0.1, variance * 0.5)
        return max(0.0, min(1.0, base + diversity_bonus))

    def fork(self, context: str = "", fitness: float = 0.5) -> dict:
        if self._active_forks:
            parent = max(self._active_forks, key=lambda f: f.get("actual_fitness", f["speculative_fitness"]))
            parent_genes = parent["variant_genes"]
            genes = [
                max(0.0, min(1.0, g + random.gauss(0, self._mutation_rate)))
                for g in parent_genes
            ]
        else:
            genes = [max(0.0, min(1.0, fitness + random.gauss(0, 0.2))) for _ in range(self._gene_size)]

        spec_fitness = self._evaluator(context, genes)

        fork = {
            "context": context,
            "parent_fitness": fitness,
            "variant_genes": genes,
            "speculative_fitness": spec_fitness,
            "actual_fitness": spec_fitness,
            "created_at": time.time(),
            "status": "active",
        }

        if len(self._active_forks) < self._max_forks:
            self._active_forks.append(fork)
        else:
            weakest = min(self._active_forks, key=lambda f: f.get("actual_fitness", 0))
            if spec_fitness > weakest.get("actual_fitness", 0):
                self._active_forks.remove(weakest)
                weakest["status"] = "rolled_back"
                self._rollbacks += 1
                self._active_forks.append(fork)

        self._forks.append(fork)
        return fork

    def evaluate_and_select(self) -> dict | None:
        if not self._active_forks:
            return None
        for fork in self._active_forks:
            fork["actual_fitness"] = self._evaluator(fork["context"], fork["variant_genes"])
        best = max(self._active_forks, key=lambda f: f.get("actual_fitness", 0))
        if best.get("actual_fitness", 0) > best.get("parent_fitness"):
            best["status"] = "promoted"
            best["consumed_at"] = __import__("time").time()  # 方案Y: fork 被 promote=激活, 记时间戳供 B1 消费率
            self._promotions += 1
            return best
        else:
            best["status"] = "rolled_back"
            self._rollbacks += 1
            self._active_forks.remove(best)
            return None

    def get_best(self) -> dict | None:
        if not self._active_forks:
            return None
        return max(self._active_forks, key=lambda f: f.get("actual_fitness", 0))

    def get_stats(self) -> dict:
        return {
            "total_forks": len(self._forks),
            "active": len(self._active_forks),
            "promotions": self._promotions,
            "rollbacks": self._rollbacks,
            "success_rate": self._promotions / max(self._promotions + self._rollbacks, 1),
        }
