"""MementoEvolution — Memory-Driven Method Evolution.

Based on: EvoAgentBench + "Memory-driven Evolutionary Search"
Implements evolution guided by memory retrieval: uses graph_memory
episode associations to find patterns in past successful/unsuccessful
evolution attempts, then applies those patterns to guide future evolution.

Key Concepts:
    1. Store evolution history with episode associations
    2. Retrieve similar past situations from graph memory
    3. Extract patterns from successful past evolutions
    4. Apply learned patterns to current evolution direction

Algorithm:
    evolve(context, current_method, success):
        # Record current state
        record(context, method, success)
        # Retrieve similar past episodes
        similar = graph_memory.retrieve_similar(context, top_k=5)
        # Extract success patterns
        patterns = extract_patterns(similar)
        # Apply pattern to generate next method
        next_method = apply_pattern(current_method, patterns)
        return next_method
"""
from __future__ import annotations



import logging

import math
import random
import time
import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
logger = logging.getLogger(__name__)


@dataclass
class MemoryEvolutionRecord:
    """A record of a memory-guided evolution attempt."""
    record_id: str = ""
    context: str = ""
    method: str = ""
    success: bool = False
    fitness: float = 0.0
    patterns_applied: List[str] = field(default_factory=list)
    retrieved_episodes: List[str] = field(default_factory=list)
    timestamp: float = 0.0


@dataclass
class PatternInfo:
    """An extracted pattern from memory."""
    pattern_id: str = ""
    description: str = ""
    success_rate: float = 0.0
    usage_count: int = 0
    contexts: List[str] = field(default_factory=list)
    methods: List[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class MementoResult:
    """Result of memory-driven evolution."""
    method: str = "memento"
    suggested_method: str = ""
    patterns_used: List[str] = field(default_factory=list)
    similar_episodes: List[str] = field(default_factory=list)
    confidence: float = 0.0
    improvement: float = 0.0
    details: str = ""


class MementoEvolution:
    """Memory-driven evolution using graph memory retrieval.

    Retrieves similar past episodes from graph memory, extracts
    success patterns, and applies them to guide evolution direction.
    True integration with graph_memory instead of isolated dict storage.

    Usage:
        memento = MementoEvolution()
        result = memento.evolve(context="optimize", current_method="gradient", success=True)
        print(f"Suggested method: {result.suggested_method}")
    """

    # Method transformation rules (how patterns affect method selection)
    METHOD_TRANSFORMS = {
        "increase_exploration": [
            lambda m: f"{m}_explorative" if not m.endswith("_explorative") else m,
            lambda m: m.replace("gradient", "random_search"),
            lambda m: m + "+wide_search",
        ],
        "increase_exploitation": [
            lambda m: f"{m}_focused" if not m.endswith("_focused") else m,
            lambda m: m.replace("random", "gradient"),
            lambda m: m + "+refine",
        ],
        "increase_stability": [
            lambda m: f"{m}_stable" if not m.endswith("_stable") else m,
            lambda m: m + "+smoothing",
            lambda m: m.replace("_explorative", ""),
        ],
        "increase_diversity": [
            lambda m: f"{m}_diverse" if not m.endswith("_diverse") else m,
            lambda m: m + "+ensemble",
            lambda m: m + "+niching",
        ],
        "increase_speed": [
            lambda m: f"{m}_fast" if not m.endswith("_fast") else m,
            lambda m: m.replace("_ensemble", ""),
            lambda m: m.replace("+refine", ""),
        ],
    }

    def __init__(self, max_history: int = 1000, pattern_threshold: float = 0.6):
        self._history: List[MemoryEvolutionRecord] = []
        self._patterns: Dict[str, PatternInfo] = {}
        self._method_performance: Dict[str, List[float]] = {}
        self._context_similarity_cache: Dict[str, Dict[str, float]] = {}
        self._max_history = max_history
        self._pattern_threshold = pattern_threshold
        self._graph_memory = None  # Will be set via set_graph_memory()
        self._total_evolutions = 0

    def set_graph_memory(self, graph_memory: Any) -> None:
        """Set the graph memory instance for retrieval.

        Args:
            graph_memory: Instance of GraphMemory for episode retrieval.
        """
        self._graph_memory = graph_memory

    def evolve(self, context: str = "", current_method: str = "default",
               success: bool = True, fitness: float = 0.0,
               graph_memory: Any = None) -> MementoResult:
        """Perform memory-driven evolution step.

        Args:
            context: Current task context.
            current_method: Current method being used.
            success: Whether the previous attempt was successful.
            fitness: Current fitness score.
            graph_memory: Optional graph memory instance.

        Returns:
            MementoResult with suggested method and patterns used.
        """
        self._total_evolutions += 1

        # Use provided graph_memory or instance variable
        gm = graph_memory or self._graph_memory

        # Record current state
        record = MemoryEvolutionRecord(
            record_id=f"mem_{self._total_evolutions}",
            context=context,
            method=current_method,
            success=success,
            fitness=fitness,
            timestamp=time.time(),
        )
        self._history.append(record)

        # Track method performance
        if current_method not in self._method_performance:
            self._method_performance[current_method] = []
        self._method_performance[current_method].append(fitness if success else 0.0)
        if len(self._method_performance[current_method]) > 200:
            self._method_performance[current_method] = self._method_performance[current_method][-100:]

        # Retrieve similar past episodes
        similar = self._retrieve_similar(context, gm, top_k=5)

        # Extract patterns from similar episodes
        patterns = self._extract_patterns(similar, context)

        # Apply patterns to suggest next method
        suggested = self._apply_patterns(current_method, patterns)

        # Update pattern confidence
        for p in patterns:
            if p.pattern_id in self._patterns:
                pat = self._patterns[p.pattern_id]
                if success:
                    pat.success_rate = pat.success_rate * 0.9 + 0.1
                else:
                    pat.success_rate = pat.success_rate * 0.9
                pat.usage_count += 1

        # Keep history bounded
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history // 2:]

        record.patterns_applied = [p.pattern_id for p in patterns]
        record.retrieved_episodes = similar[:3]

        return MementoResult(
            method="memento",
            suggested_method=suggested,
            patterns_used=[p.pattern_id for p in patterns],
            similar_episodes=similar,
            confidence=sum(p.confidence for p in patterns) / max(len(patterns), 1),
            improvement=fitness,
            details=f"patterns={len(patterns)}, similar={len(similar)}",
        )

    def _retrieve_similar(self, context: str, graph_memory: Any = None,
                          top_k: int = 5) -> List[str]:
        """Retrieve similar past episodes from memory.

        Uses graph memory if available, falls back to history similarity.
        """
        # Try graph memory first
        if graph_memory and hasattr(graph_memory, 'search'):
            try:
                results = graph_memory.search(context, limit=top_k * 2)
                if results:
                    # Extract node IDs from search results
                    episode_ids = []
                    for r in results[:top_k]:
                        if isinstance(r, dict):
                            episode_ids.append(r.get("node_id", r.get("id", "")))
                        elif isinstance(r, str):
                            episode_ids.append(r)
                    return [eid for eid in episode_ids if eid]
            except Exception as e:
                logger.warning("Memento graph retrieval failed: %s", e)

        # Fallback: find similar contexts in history
        if not self._history:
            return []

        # Compute similarity scores
        scores = []
        for record in self._history:
            sim = self._context_similarity(context, record.context)
            if sim > 0.3:  # Minimum similarity threshold
                scores.append((sim, record.record_id))

        scores.sort(key=lambda x: -x[0])
        return [eid for _, eid in scores[:top_k]]

    def _context_similarity(self, ctx1: str, ctx2: str) -> float:
        """Compute similarity between two contexts using TF overlap."""
        if not ctx1 or not ctx2:
            return 0.0

        # Check cache
        key = f"{min(ctx1, ctx2)}:{max(ctx1, ctx2)}"
        if key in self._context_similarity_cache:
            return self._context_similarity_cache[key]

        # Tokenize
        tokens1 = set(self._tokenize(ctx1))
        tokens2 = set(self._tokenize(ctx2))

        if not tokens1 or not tokens2:
            return 0.0

        # Jaccard similarity
        intersection = len(tokens1 & tokens2)
        union = len(tokens1 | tokens2)
        sim = intersection / union if union > 0 else 0.0

        # Cache result
        self._context_similarity_cache[key] = sim
        if len(self._context_similarity_cache) > 1000:
            # Clear oldest entries
            items = list(self._context_similarity_cache.items())
            self._context_similarity_cache = dict(items[-500:])

        return sim

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """Simple tokenizer."""
        return [w.lower() for w in text.replace('_', ' ').split() if len(w) > 1]

    def _extract_patterns(self, similar_episodes: List[str],
                          context: str) -> List[PatternInfo]:
        """Extract success patterns from similar episodes."""
        patterns = []

        # Find successful episodes in similar contexts
        successful = [
            r for r in self._history
            if r.record_id in similar_episodes and r.success
        ]

        if not successful:
            # If no similar successes, use general method performance
            return self._get_general_patterns()

        # Analyze method distribution in successful episodes
        method_counts: Dict[str, int] = {}
        for r in successful:
            method_counts[r.method] = method_counts.get(r.method, 0) + 1

        # Generate patterns based on analysis
        # Pattern 1: Most common successful method
        if method_counts:
            best_method = max(method_counts, key=method_counts.get)
            success_rate = method_counts[best_method] / len(successful)
            if success_rate >= self._pattern_threshold:
                pattern = PatternInfo(
                    pattern_id=f"method_{best_method}",
                    description=f"Method '{best_method}' succeeds in {success_rate:.0%} of cases",
                    success_rate=success_rate,
                    usage_count=method_counts[best_method],
                    confidence=success_rate,
                )
                patterns.append(pattern)
                self._patterns[pattern.pattern_id] = pattern

        # Pattern 2: Trend analysis (improving vs declining)
        if len(successful) >= 3:
            recent_fitness = [r.fitness for r in successful[-3:]]
            if len(recent_fitness) >= 2:
                trend = sum(recent_fitness[i+1] - recent_fitness[i] for i in range(len(recent_fitness) - 1))
                if trend > 0.05:
                    patterns.append(PatternInfo(
                        pattern_id="improving_trend",
                        description="Fitness is improving - continue current direction",
                        success_rate=min(1.0, 0.5 + trend),
                        confidence=min(1.0, 0.5 + trend),
                    ))
                elif trend < -0.05:
                    patterns.append(PatternInfo(
                        pattern_id="declining_trend",
                        description="Fitness declining - need to change direction",
                        success_rate=0.7,
                        confidence=abs(trend),
                    ))

        return patterns

    def _get_general_patterns(self) -> List[PatternInfo]:
        """Get general patterns from overall history when no similar episodes."""
        patterns = []

        # Find best performing methods overall
        method_avgs = {}
        for method, rewards in self._method_performance.items():
            if rewards:
                avg = sum(rewards[-20:]) / min(len(rewards), 20)
                method_avgs[method] = avg

        if method_avgs:
            sorted_methods = sorted(method_avgs.items(), key=lambda x: -x[1])
            best_method, best_avg = sorted_methods[0]
            patterns.append(PatternInfo(
                pattern_id=f"best_{best_method}",
                description=f"'{best_method}' has best overall avg fitness: {best_avg:.3f}",
                success_rate=best_avg,
                confidence=min(1.0, best_avg),
            ))

        # Diverse method pattern if we have variety
        if len(method_avgs) > 3:
            patterns.append(PatternInfo(
                pattern_id="try_diverse_methods",
                description="Multiple methods tested - try diversification",
                success_rate=0.6,
                confidence=0.5,
            ))

        return patterns

    def _apply_patterns(self, current_method: str,
                        patterns: List[PatternInfo]) -> str:
        """Apply extracted patterns to suggest next method."""
        suggested = current_method

        for pattern in patterns:
            pid = pattern.pattern_id

            # Map patterns to transformation strategies
            if pid.startswith("method_"):
                # Direct method recommendation
                suggested = pid.replace("method_", "")
            elif pid == "improving_trend":
                # Continue current direction, slight refinement
                if "+refine" not in suggested:
                    suggested = suggested + "+refine"
            elif pid == "declining_trend":
                # Need to change direction
                transform = random.choice(self.METHOD_TRANSFORMS["increase_exploration"])
                suggested = transform(suggested)
            elif pid == "try_diverse_methods":
                transform = random.choice(self.METHOD_TRANSFORMS["increase_diversity"])
                suggested = transform(suggested)
            elif "best_" in pid:
                suggested = pid.replace("best_", "")

        return suggested

    def get_method_rankings(self) -> List[Tuple[str, float]]:
        """Get methods ranked by average fitness."""
        rankings = []
        for method, rewards in self._method_performance.items():
            if rewards:
                avg = sum(rewards[-20:]) / min(len(rewards), 20)
                rankings.append((method, avg))
        rankings.sort(key=lambda x: -x[1])
        return rankings

    def get_pattern_stats(self) -> Dict[str, Any]:
        """Get pattern statistics."""
        return {
            "total_patterns": len(self._patterns),
            "patterns": {
                pid: {
                    "success_rate": p.success_rate,
                    "usage_count": p.usage_count,
                    "confidence": p.confidence,
                }
                for pid, p in self._patterns.items()
            },
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get Memento statistics."""
        recent = self._history[-50:] if self._history else []
        success_rate = sum(1 for r in recent if r.success) / max(len(recent), 1)

        return {
            "total_evolutions": self._total_evolutions,
            "history_size": len(self._history),
            "recent_success_rate": success_rate,
            "num_patterns": len(self._patterns),
            "num_methods_tracked": len(self._method_performance),
            "method_rankings": self.get_method_rankings()[:5],
            "patterns": self.get_pattern_stats(),
        }


# Backward compatibility alias (for existing life.py imports)
Memento = MementoEvolution
