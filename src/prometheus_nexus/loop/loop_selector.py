"""LoopSelector — Automatic loop strategy selection based on task characteristics.

Based on:
- "CoALA: Cognitive Architectures for Language Agents" (Yao et al., 2023 | TMLR)
  - Modular cognitive architecture with structured action space
  - Decision process selects actions based on memory and goals
- Multi-Loop Architecture (from report):
  - Outer loop: task decomposition (low frequency)
  - Middle loop: subtask execution (medium frequency)
  - Inner loop: single-step reasoning (high frequency)
- "A Survey on LLM-based Autonomous Agents" (Wang et al., 2023)
  - Unified framework: profile + memory + planning + action
  - Agent loop is the core decision cycle

Algorithm:
    select_loop(task, context):
        1. Classify task complexity (simple/medium/complex/research)
        2. Check available loop strategies
        3. Select optimal strategy based on:
           - Task type matching
           - Historical success rate
           - Resource budget
           - Convergence guarantee
        4. Configure loop parameters (max_steps, branching, etc.)

Complexity:
    select(): O(S) where S = number of strategies
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import time
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum


class TaskComplexity(Enum):
    SIMPLE = "simple"       # 1-5 steps, single strategy
    MEDIUM = "medium"       # 5-15 steps, may need reflection
    COMPLEX = "complex"     # 15-50 steps, needs search/exploration
    RESEARCH = "research"   # 50+ steps, needs multi-agent collaboration


class LoopStrategy(Enum):
    REACT = "react"              # ToolLoop: action-observation cycle
    REFLEXION = "reflexion"      # Learn from failures
    TREE_OF_THOUGHTS = "tot"     # Tree search with backtracking
    DEBATE = "debate"            # Multi-perspective argumentation
    MULTI_AGENT = "multi_agent"  # Parallel agent execution
    CHAIN_OF_THOUGHT = "cot"     # Step-by-step reasoning


@dataclass
class LoopConfig:
    """Configuration for a loop execution."""
    strategy: LoopStrategy = LoopStrategy.REACT
    max_steps: int = 10
    branching_factor: int = 3
    reflection_threshold: float = 0.7
    convergence_threshold: float = 0.01
    timeout_seconds: float = 60.0
    metadata: dict = field(default_factory=dict)


@dataclass
class LoopResult:
    """Result of loop execution."""
    strategy: str = ""
    steps_taken: int = 0
    final_score: float = 0.0
    converged: bool = False
    history: list[dict] = field(default_factory=list)
    duration_ms: float = 0.0


# Strategy-task compatibility matrix (from CoALA + report)
STRATEGY_COMPATIBILITY = {
    TaskComplexity.SIMPLE: {
        LoopStrategy.REACT: 0.9,
        LoopStrategy.CHAIN_OF_THOUGHT: 0.8,
        LoopStrategy.REFLEXION: 0.3,
        LoopStrategy.TREE_OF_THOUGHTS: 0.2,
        LoopStrategy.DEBATE: 0.1,
        LoopStrategy.MULTI_AGENT: 0.1,
    },
    TaskComplexity.MEDIUM: {
        LoopStrategy.REACT: 0.7,
        LoopStrategy.CHAIN_OF_THOUGHT: 0.8,
        LoopStrategy.REFLEXION: 0.7,
        LoopStrategy.TREE_OF_THOUGHTS: 0.5,
        LoopStrategy.DEBATE: 0.4,
        LoopStrategy.MULTI_AGENT: 0.3,
    },
    TaskComplexity.COMPLEX: {
        LoopStrategy.REACT: 0.4,
        LoopStrategy.CHAIN_OF_THOUGHT: 0.6,
        LoopStrategy.REFLEXION: 0.7,
        LoopStrategy.TREE_OF_THOUGHTS: 0.9,
        LoopStrategy.DEBATE: 0.7,
        LoopStrategy.MULTI_AGENT: 0.6,
    },
    TaskComplexity.RESEARCH: {
        LoopStrategy.REACT: 0.2,
        LoopStrategy.CHAIN_OF_THOUGHT: 0.4,
        LoopStrategy.REFLEXION: 0.6,
        LoopStrategy.TREE_OF_THOUGHTS: 0.7,
        LoopStrategy.DEBATE: 0.8,
        LoopStrategy.MULTI_AGENT: 0.9,
    },
}

# Step budget by complexity (from report)
STEP_BUDGETS = {
    TaskComplexity.SIMPLE: (3, 10),
    TaskComplexity.MEDIUM: (5, 15),
    TaskComplexity.COMPLEX: (15, 50),
    TaskComplexity.RESEARCH: (50, 200),
}


class LoopSelector:
    """Automatic loop strategy selection.

    Based on CoALA cognitive architecture and multi-loop design.

    Usage:
        selector = LoopSelector()
        config = selector.select("Write a Python function to sort a list")
        print(config.strategy, config.max_steps)
    """

    def __init__(self):
        self._history: list[dict] = []
        self._strategy_scores: dict[str, list[float]] = {s.value: [] for s in LoopStrategy}

    def classify_task(self, task: str, context: str = "") -> TaskComplexity:
        """Classify task complexity based on keywords and structure."""
        text = (task + " " + context).lower()
        words = text.split()
        word_count = len(words)

        # Simple indicators
        simple_keywords = {"hello", "hi", "thanks", "yes", "no", "ok"}
        if any(w in simple_keywords for w in words) and word_count < 5:
            return TaskComplexity.SIMPLE

        # Research indicators
        research_keywords = {"research", "analyze", "compare", "survey", "investigate",
                            "hypothesis", "experiment", "evaluate", "benchmark"}
        if sum(1 for w in words if w in research_keywords) >= 2:
            return TaskComplexity.RESEARCH

        # Complex indicators
        complex_keywords = {"design", "architecture", "optimize", "debug", "refactor",
                           "multi-step", "chain", "reasoning", "proof"}
        if sum(1 for w in words if w in complex_keywords) >= 2:
            return TaskComplexity.COMPLEX

        # Medium: default for most tasks
        if word_count > 15 or "?" in text:
            return TaskComplexity.MEDIUM

        return TaskComplexity.SIMPLE

    def select(self, task: str, context: str = "",
               available_strategies: list[LoopStrategy] | None = None) -> LoopConfig:
        """Select optimal loop strategy for a task.

        Based on CoALA: "decision process selects actions based on memory and goals"
        """
        complexity = self.classify_task(task, context)
        compat = STRATEGY_COMPATIBILITY[complexity]

        if available_strategies is None:
            available_strategies = list(LoopStrategy)

        # Score each strategy
        best_strategy = LoopStrategy.REACT
        best_score = -1

        for strategy in available_strategies:
            if strategy not in compat:
                continue

            base_score = compat[strategy]

            # Adjust based on historical performance
            history = self._strategy_scores.get(strategy.value, [])
            if history:
                historical_avg = sum(history[-10:]) / len(history[-10:])
                base_score = base_score * 0.7 + historical_avg * 0.3

            if base_score > best_score:
                best_score = base_score
                best_strategy = strategy

        # Configure step budget
        min_steps, max_steps = STEP_BUDGETS[complexity]

        # Adjust based on strategy
        if best_strategy == LoopStrategy.REACT:
            max_steps = min(max_steps, 10)
        elif best_strategy == LoopStrategy.TREE_OF_THOUGHTS:
            max_steps = min(max_steps, 30)
        elif best_strategy == LoopStrategy.MULTI_AGENT:
            max_steps = min(max_steps, 20)

        config = LoopConfig(
            strategy=best_strategy,
            max_steps=max_steps,
            branching_factor=3 if best_strategy == LoopStrategy.TREE_OF_THOUGHTS else 1,
            reflection_threshold=0.7 if best_strategy == LoopStrategy.REFLEXION else 0.5,
            metadata={"complexity": complexity.value, "score": best_score},
        )

        self._history.append({
            "task": task[:50],
            "complexity": complexity.value,
            "strategy": best_strategy.value,
            "score": best_score,
            "timestamp": time.time(),
        })

        return config

    def record_outcome(self, strategy: LoopStrategy, score: float):
        """Record loop outcome for future selection."""
        self._strategy_scores[strategy.value].append(score)
        if len(self._strategy_scores[strategy.value]) > 100:
            self._strategy_scores[strategy.value] = self._strategy_scores[strategy.value][-50:]

    def get_stats(self) -> dict:
        return {
            "total_selections": len(self._history),
            "strategy_distribution": dict(Counter(h["strategy"] for h in self._history)),
            "avg_scores": {s: sum(scores) / max(len(scores), 1)
                          for s, scores in self._strategy_scores.items() if scores},
        }
