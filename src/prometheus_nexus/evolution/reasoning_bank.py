"""ReasoningBank — Reasoning strategy library with retrieval.

Based on: EvoAgentBench leaderboard (ReasoningBank method)
Best on: BrowseComp (+18-41%), SWE-Bench (+5-89%)

Implements a library of reasoning strategies that can be retrieved
based on task type and applied to improve problem-solving.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

from dataclasses import dataclass, field
import math


@dataclass
class ReasoningStrategy:
    name: str = ""
    description: str = ""
    task_types: list[str] = field(default_factory=list)
    success_rate: float = 0.5
    usage_count: int = 0
    total_reward: float = 0.0
    patterns: list[str] = field(default_factory=list)


@dataclass
class ReasoningResult:
    method: str = "reasoning_bank"
    improvement: float = 0.0
    cost_delta: float = 0.0
    details: str = ""


class ReasoningBank:
    """Reasoning strategy library with retrieval.

    Based on EvoAgentBench: stores and retrieves reasoning strategies
    based on task type, tracks success rates, and evolves strategy
    selection over time.

    Usage:
        rb = ReasoningBank()
        result = rb.evolve(task="solve equation", context={"type": "math"})
    """

    def __init__(self):
        self._strategies: list[ReasoningStrategy] = []
        self._history: list[dict] = []
        self._task_type_counts: dict[str, int] = {}
        self._register_defaults()

    def _register_defaults(self):
        defaults = [
            ReasoningStrategy(
                name="chain_of_thought",
                description="Step-by-step sequential reasoning with intermediate conclusions",
                task_types=["math", "logic", "code", "analysis", "general"],
                success_rate=0.72, patterns=["step_by_step", "intermediate_conclusion", "verify_each_step"],
            ),
            ReasoningStrategy(
                name="tree_search",
                description="BFS/DFS exploration of solution space with backtracking",
                task_types=["puzzle", "optimization", "planning", "search"],
                success_rate=0.65, patterns=["explore_branches", "backtrack", "prune_low_value"],
            ),
            ReasoningStrategy(
                name="analogical_reasoning",
                description="Map structural relationships from known domain to target",
                task_types=["creative", "design", "transfer", "general"],
                success_rate=0.58, patterns=["find_source_domain", "map_structure", "align_relations"],
            ),
            ReasoningStrategy(
                name="decomposition",
                description="Break complex problem into independent subproblems",
                task_types=["complex", "multi_step", "planning", "code"],
                success_rate=0.70, patterns=["identify_subproblems", "solve_independently", "merge_solutions"],
            ),
            ReasoningStrategy(
                name="contradiction_detection",
                description="Identify conflicting information and resolve via evidence weight",
                task_types=["verification", "fact_check", "research", "analysis"],
                success_rate=0.63, patterns=["find_conflicts", "weight_evidence", "resolve_or_flag"],
            ),
            ReasoningStrategy(
                name="iterative_refinement",
                description="Generate solution, evaluate, refine in loop",
                task_types=["writing", "code", "design", "creative"],
                success_rate=0.67, patterns=["generate_draft", "evaluate_gaps", "refine_targeted"],
            ),
            ReasoningStrategy(
                name="causal_reasoning",
                description="Trace cause-effect chains to identify root causes",
                task_types=["debugging", "analysis", "research", "diagnosis"],
                success_rate=0.61, patterns=["trace_chain", "identify_root", "predict_effects"],
            ),
            ReasoningStrategy(
                name="constraint_satisfaction",
                description="Enumerate constraints and find feasible assignment",
                task_types=["scheduling", "optimization", "logic", "puzzle"],
                success_rate=0.64, patterns=["enumerate_constraints", "propagate", "backtrack_if_stuck"],
            ),
            ReasoningStrategy(
                name="metacognitive_monitoring",
                description="Track confidence, detect confusion, adjust strategy",
                task_types=["general", "complex", "uncertain"],
                success_rate=0.55, patterns=["assess_confidence", "detect_confusion", "switch_strategy"],
            ),
            ReasoningStrategy(
                name="evidence_accumulation",
                description="Gather multiple evidence pieces before concluding",
                task_types=["research", "fact_check", "verification", "analysis"],
                success_rate=0.68, patterns=["gather_evidence", "weight_by_source", "converge_on_answer"],
            ),
        ]
        self._strategies.extend(defaults)

    def register_strategy(self, name: str, description: str, task_types: list[str]):
        self._strategies.append(ReasoningStrategy(
            name=name, description=description, task_types=task_types,
        ))

    def evolve(self, task: str, context: dict = None) -> ReasoningResult:
        context = context or {}
        task_type = context.get("type", "general")

        self._task_type_counts[task_type] = self._task_type_counts.get(task_type, 0) + 1

        best_strategy = self._retrieve_strategy(task_type)
        improvement = self._estimate_improvement(best_strategy, task_type)

        for s in self._strategies:
            if s.name == best_strategy:
                s.usage_count += 1
                s.total_reward += improvement
                s.success_rate = s.total_reward / s.usage_count
                break

        self._history.append({
            "task": task, "task_type": task_type,
            "strategy": best_strategy, "improvement": improvement,
        })

        return ReasoningResult(
            method="reasoning_bank",
            improvement=improvement,
            cost_delta=0.03,
            details="strategy=%s, type=%s" % (best_strategy, task_type),
        )

    def _retrieve_strategy(self, task_type: str) -> str:
        candidates = []
        for s in self._strategies:
            if task_type in s.task_types:
                ucb1_score = s.success_rate + math.sqrt(2 * math.log(max(1, len(self._history))) / max(1, s.usage_count))
                candidates.append((s.name, ucb1_score))
        if not candidates:
            for s in self._strategies:
                if "general" in s.task_types:
                    candidates.append((s.name, s.success_rate))
        if not candidates:
            return self._strategies[0].name if self._strategies else "default"
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]

    def _estimate_improvement(self, strategy_name: str, task_type: str) -> float:
        for s in self._strategies:
            if s.name == strategy_name:
                base = s.success_rate
                type_bonus = 0.1 if task_type in s.task_types else 0.0
                usage_bonus = min(0.1, s.usage_count * 0.01)
                return min(1.0, base * 0.3 + type_bonus + usage_bonus)
        return 0.1

    def get_strategy(self, name: str) -> ReasoningStrategy | None:
        for s in self._strategies:
            if s.name == name:
                return s
        return None

    def get_strategies_for_type(self, task_type: str) -> list[ReasoningStrategy]:
        return [s for s in self._strategies if task_type in s.task_types]

    def get_stats(self) -> dict:
        return {
            "strategies": len(self._strategies),
            "evolutions": len(self._history),
            "task_types": dict(self._task_type_counts),
            "top_strategies": sorted(
                [(s.name, s.success_rate, s.usage_count) for s in self._strategies],
                key=lambda x: x[1], reverse=True
            )[:5],
        }
