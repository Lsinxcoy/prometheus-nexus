"""ContextWindowManager — Manages context window size limits.

Based on: "Long Context RAG Performance of LLMs" (Databricks, 2025)

Key Finding:
    Llama 3.1 405b accuracy drops after 32k tokens.
    Million-token windows have much lower practical usability than theoretical.
    Longer context ≠ better performance.

Algorithm:
    1. Track total token usage across context components
    2. Enforce per-component token budgets
    3. Trigger compression when budget exceeded
    4. Priority-based eviction: keep high-value content

Extensions:
    - PriorityEvictionEngine: utility × recency × relevance scoring
    - get_budget_report(): per-component token usage breakdown
    - compress_if_needed(): auto-trigger when >80% budget used
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import math
import time
from dataclasses import dataclass, field


@dataclass
class ContextBudget:
    total_tokens: int = 128000
    system_prompt_tokens: int = 4000
    history_tokens: int = 32000
    retrieval_tokens: int = 16000
    tool_results_tokens: int = 8000
    reserved_tokens: int = 2000

    @property
    def available_tokens(self) -> int:
        return (self.total_tokens - self.system_prompt_tokens -
                self.reserved_tokens)


@dataclass
class ComponentUsage:
    name: str = ""
    tokens_used: int = 0
    tokens_budget: int = 0
    priority: int = 0  # Higher = more important
    # For PriorityEvictionEngine
    utility: float = 0.5
    recency: float = 1.0
    relevance: float = 0.5
    access_count: int = 0


@dataclass
class WindowReport:
    total_used: int = 0
    total_budget: int = 0
    utilization: float = 0.0
    components: list[ComponentUsage] = field(default_factory=list)
    needs_compression: bool = False
    overflow_components: list[str] = field(default_factory=list)


@dataclass
class BudgetBreakdown:
    """Detailed per-component breakdown for budget reports."""
    component: str = ""
    budget: int = 0
    used: int = 0
    percentage: float = 0.0
    status: str = "ok"  # "ok", "warning", "overflow"
    priority: int = 0
    evictable: int = 0  # tokens that could be evicted


@dataclass
class CompressionAction:
    """Single compression action suggestion."""
    component: str = ""
    tokens_to_free: int = 0
    strategy: str = ""  # "evict", "compress", "summarize"
    new_tokens: int = 0
    priority_delta: int = 0  # how much priority was sacrificed


# ============================================================
# Priority Eviction Engine
# ============================================================

class PriorityEvictionEngine:
    """Sophisticated priority scoring for eviction decisions.

    Score = utility_weight × utility + recency_weight × recency
            + relevance_weight × relevance

    Each weight is configurable. Lower-scored components are evicted first.
    """

    def __init__(self, utility_weight: float = 0.4,
                 recency_weight: float = 0.35,
                 relevance_weight: float = 0.25):
        self.utility_weight = utility_weight
        self.recency_weight = recency_weight
        self.relevance_weight = relevance_weight

    def score(self, usage: ComponentUsage) -> float:
        """Compute priority score for a component usage.

        Args:
            usage: ComponentUsage with utility, recency, relevance fields.

        Returns:
            Float score (higher = more valuable to keep).
        """
        return (
            self.utility_weight * usage.utility +
            self.recency_weight * usage.recency +
            self.relevance_weight * usage.relevance
        )

    def rank_eviction_order(self, usages: list[ComponentUsage]) -> list[ComponentUsage]:
        """Sort components by eviction desirability (lowest score first).

        Args:
            usages: List of component usages to evaluate.

        Returns:
            List sorted ascending by priority score (least valuable first).
        """
        scored = [(self.score(u), u) for u in usages]
        scored.sort(key=lambda x: x[0])
        return [u for _, u in scored]

    def suggest_evictions(self, usages: list[ComponentUsage],
                          target_tokens: int) -> list[dict]:
        """Determine which components to evict to meet a token target.

        Args:
            usages: Current component usages.
            target_tokens: Number of tokens to free up.

        Returns:
            List of eviction suggestions sorted by eviction order.
        """
        ordered = self.rank_eviction_order(usages)
        suggestions = []
        freed = 0

        for usage in ordered:
            if freed >= target_tokens:
                break
            # Don't evict below a minimum threshold (10% of budget)
            min_keep = int(usage.tokens_budget * 0.1)
            evictable = max(0, usage.tokens_used - min_keep)
            if evictable <= 0:
                continue

            to_free = min(evictable, target_tokens - freed)
            new_tokens = usage.tokens_used - to_free
            suggestions.append({
                "component": usage.name,
                "tokens_to_free": to_free,
                "tokens_remaining": new_tokens,
                "strategy": "evict",
                "priority_score": round(self.score(usage), 4),
            })
            freed += to_free

        return suggestions


# ============================================================
# Context Window Manager
# ============================================================

class ContextWindowManager:
    """Manages context window size limits.

    Based on Databricks findings (2025).

    Usage:
        mgr = ContextWindowManager(ContextBudget(total_tokens=128000))
        mgr.register_component("system", 2500, priority=10)
        mgr.register_component("history", 15000, priority=5)
        mgr.register_component("retrieval", 8000, priority=7)
        report = mgr.check()
        if report.needs_compression:
            print(f"Overflow: {report.overflow_components}")
    """

    # Compression threshold: auto-trigger when utilization > 80%
    COMPRESSION_THRESHOLD = 0.80

    def __init__(self, budget: ContextBudget | None = None):
        self._budget = budget or ContextBudget()
        self._components: dict[str, ComponentUsage] = {}
        self._reports: list[dict] = []
        self._eviction_engine = PriorityEvictionEngine()
        self._auto_compress_count = 0

    def register_component(self, name: str, tokens_used: int, priority: int = 5,
                           utility: float = 0.5, recency: float = 1.0,
                           relevance: float = 0.5):
        budget_map = {
            "system": self._budget.system_prompt_tokens,
            "history": self._budget.history_tokens,
            "retrieval": self._budget.retrieval_tokens,
            "tool_results": self._budget.tool_results_tokens,
        }
        budget = budget_map.get(name, self._budget.available_tokens // 4)
        self._components[name] = ComponentUsage(
            name=name, tokens_used=tokens_used,
            tokens_budget=budget, priority=priority,
            utility=utility, recency=recency,
            relevance=relevance, access_count=0,
        )

    def update_usage(self, name: str, tokens_used: int):
        if name in self._components:
            self._components[name].tokens_used = tokens_used
            self._components[name].access_count += 1
            # Decay recency on each update (fresh access resets)
            self._components[name].recency = min(
                1.0, self._components[name].recency + 0.1
            )

    def get_budget_report(self) -> list[BudgetBreakdown]:
        """Get detailed per-component token usage breakdown.

        Returns:
            List of BudgetBreakdown with budget, usage, percentage, status.
        """
        breakdowns = []
        total_budget = self._budget.total_tokens - self._budget.reserved_tokens

        for name, comp in self._components.items():
            pct = comp.tokens_used / max(comp.tokens_budget, 1)
            if comp.tokens_used > comp.tokens_budget:
                status = "overflow"
            elif pct > 0.85:
                status = "warning"
            else:
                status = "ok"

            min_keep = int(comp.tokens_budget * 0.1)
            evictable = max(0, comp.tokens_used - min_keep)

            breakdowns.append(BudgetBreakdown(
                component=name,
                budget=comp.tokens_budget,
                used=comp.tokens_used,
                percentage=round(pct * 100, 1),
                status=status,
                priority=comp.priority,
                evictable=evictable,
            ))

        # Sort by status severity: overflow first, then warning, then ok
        status_order = {"overflow": 0, "warning": 1, "ok": 2}
        breakdowns.sort(key=lambda b: (status_order.get(b.status, 99), -b.percentage))

        return breakdowns

    def compress_if_needed(self) -> list[CompressionAction]:
        """Auto-trigger compression when utilization >80% of budget.

        This is the main compression entry point. It:
        1. Checks current utilization against COMPRESSION_THRESHOLD
        2. If over threshold, uses the PriorityEvictionEngine to score
           components and suggest evictions/compression
        3. Returns list of CompressionAction suggestions

        Returns:
            List of CompressionAction suggestions. Empty list if no
            compression needed.
        """
        report = self.check()
        if not report.needs_compression and report.utilization < self.COMPRESSION_THRESHOLD:
            return []

        self._auto_compress_count += 1

        actions: list[CompressionAction] = []

        # Step 1: handle overflow components first
        overflow_components = [
            self._components[name] for name in report.overflow_components
        ]
        for comp in overflow_components:
            excess = comp.tokens_used - comp.tokens_budget
            # Try to bring back to budget
            reduction_target = excess + int(comp.tokens_budget * 0.05)
            actual_reduction = min(reduction_target, comp.tokens_used)
            new_tokens = comp.tokens_used - actual_reduction

            strategy = "evict" if comp.priority < 5 else "compress"
            actions.append(CompressionAction(
                component=comp.name,
                tokens_to_free=actual_reduction,
                strategy=strategy,
                new_tokens=new_tokens,
                priority_delta=comp.priority,
            ))

        # Step 2: global pressure — target 70% utilization
        total_budget = self._budget.total_tokens - self._budget.reserved_tokens
        target_used = int(total_budget * 0.70)
        current_used = report.total_used
        needed_freed = max(0, current_used - target_used)

        if needed_freed > 0:
            eviction_suggestions = self._eviction_engine.suggest_evictions(
                list(self._components.values()), needed_freed
            )
            for es in eviction_suggestions:
                # Avoid duplicate entries already handled above
                already_handled = any(
                    a.component == es["component"] for a in actions
                )
                if already_handled:
                    continue
                actions.append(CompressionAction(
                    component=es["component"],
                    tokens_to_free=es["tokens_to_free"],
                    strategy=es["strategy"],
                    new_tokens=es["tokens_remaining"],
                    priority_delta=self._components[es["component"]].priority,
                ))

        # Step 3: sort actions by priority ascending (lowest priority first)
        actions.sort(key=lambda a: a.priority_delta)

        return actions

    def check(self) -> WindowReport:
        total_used = sum(c.tokens_used for c in self._components.values())
        total_budget = self._budget.total_tokens - self._budget.reserved_tokens
        utilization = total_used / max(total_budget, 1)

        overflow = []
        for name, comp in self._components.items():
            if comp.tokens_used > comp.tokens_budget:
                overflow.append(name)

        needs_compression = utilization > 0.85 or len(overflow) > 0

        report = WindowReport(
            total_used=total_used,
            total_budget=total_budget,
            utilization=utilization,
            components=list(self._components.values()),
            needs_compression=needs_compression,
            overflow_components=overflow,
        )

        self._reports.append({
            "utilization": utilization,
            "overflow": len(overflow),
        })
        return report

    def suggest_compression(self) -> list[dict]:
        suggestions = []
        sorted_comps = sorted(self._components.values(), key=lambda c: c.priority)
        for comp in sorted_comps:
            if comp.tokens_used > comp.tokens_budget:
                excess = comp.tokens_used - comp.tokens_budget
                suggestions.append({
                    "component": comp.name,
                    "excess_tokens": excess,
                    "action": "compress" if comp.priority < 5 else "evict_low_priority",
                })
        return suggestions

    def get_stats(self) -> dict:
        return {
            "components": len(self._components),
            "total_used": sum(c.tokens_used for c in self._components.values()),
            "budget": self._budget.total_tokens,
            "auto_compress_count": self._auto_compress_count,
            "eviction_engine_weights": {
                "utility": self._eviction_engine.utility_weight,
                "recency": self._eviction_engine.recency_weight,
                "relevance": self._eviction_engine.relevance_weight,
            },
        }
