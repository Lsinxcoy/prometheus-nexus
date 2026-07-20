"""EverOS — Evolutionary Search with External Memory.

Based on: EvoAgentBench leaderboards + "External Memory for Evolutionary Search"
Implements search-oriented evolution with BFS/DFS/beam search strategies
over the evolution space, using external memory as a searchable graph.

Key Concepts:
    1. BFS: breadth-first exploration of strategy space
    2. DFS: depth-first exploitation with backtracking
    3. Beam Search: maintain top-k candidates at each step
    4. A* Search: heuristic-guided search with fitness estimates

Algorithm (Beam Search example):
    beam = [initial_candidate]
    for step in range(max_steps):
        expanded = []
        for candidate in beam:
            children = generate_neighbors(candidate)
            for child in children:
                score = evaluate(child) + heuristic(child)
                expanded.append((score, child))
        beam = sorted(expanded, key=lambda x: -x[0])[:beam_width]
    return best(beam)
"""
from __future__ import annotations



import logging
import heapq
import math
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
logger = logging.getLogger(__name__)


class SearchStrategy(Enum):
    BFS = "bfs"
    DFS = "dfs"
    BEAM = "beam"
    ASTAR = "a_star"


@dataclass
class SearchNode:
    """A node in the evolution search space."""
    node_id: str = ""
    state: Dict[str, Any] = field(default_factory=dict)
    fitness: float = 0.0
    heuristic: float = 0.0  # For A*
    depth: int = 0
    parent_id: str = ""
    children_ids: List[str] = field(default_factory=list)
    visited: bool = False
    timestamp: float = 0.0


@dataclass
class EverOSResult:
    """Result of EverOS evolution search."""
    method: str = "everos"
    strategy: str = ""
    best_fitness: float = 0.0
    best_state: Dict[str, Any] = field(default_factory=dict)
    nodes_explored: int = 0
    depth_reached: int = 0
    path: List[str] = field(default_factory=list)
    improvement: float = 0.0
    duration_ms: float = 0.0
    details: str = ""


class EverOSEvolution:
    """Evolutionary search with external memory.

    Implements multiple search strategies (BFS, DFS, Beam, A*)
    over the evolution state space. Maintains a searchable graph
    of explored states for replay and analysis.

    Usage:
        everos = EverOSEvolution(beam_width=10, max_depth=5)
        result = everos.evolve(context="optimize", search_strategy="beam")
    """

    def __init__(self, beam_width: int = 10, max_depth: int = 5,
                 branching_factor: int = 5, heuristic_fn: Optional[Callable] = None,
                 evaluate_fn: Optional[Callable] = None):
        self._beam_width = beam_width
        self._max_depth = max_depth
        self._branching = branching_factor
        self._heuristic_fn = heuristic_fn
        self._evaluate_fn = evaluate_fn
        self._nodes: Dict[str, SearchNode] = {}
        self._explored: Set[str] = set()
        self._best_node: Optional[SearchNode] = None
        self._total_explored = 0
        self._history: List[EverOSResult] = []

    def evolve(self, context: str = "", search_strategy: Optional[str] = None,
               initial_state: Optional[Dict[str, Any]] = None,
               max_nodes: int = 1000, **kwargs) -> EverOSResult:
        """Run evolution search with the specified strategy.

        Args:
            context: Task context.
            search_strategy: Search algorithm. None = auto-select.
            initial_state: Starting state dict.
            max_nodes: Max nodes to explore.
            **kwargs: Additional context parameters (ignored).

        Returns:
            EverOSResult with best found state.
        """
        start = time.time()
        strategy = SearchStrategy(search_strategy or self._auto_select(context))

        initial = initial_state or self._default_initial_state(context)
        root = SearchNode(
            node_id="root",
            state=initial,
            fitness=self._evaluate(initial, context),
            depth=0,
            timestamp=time.time(),
        )
        self._nodes["root"] = root
        self._best_node = root

        if strategy == SearchStrategy.BFS:
            result = self._bfs_search(root, context, max_nodes)
        elif strategy == SearchStrategy.DFS:
            result = self._dfs_search(root, context, max_nodes)
        elif strategy == SearchStrategy.BEAM:
            result = self._beam_search(root, context, max_nodes)
        elif strategy == SearchStrategy.ASTAR:
            result = self._astar_search(root, context, max_nodes)
        else:
            result = self._beam_search(root, context, max_nodes)

        result.strategy = strategy.value
        result.duration_ms = (time.time() - start) * 1000
        result.improvement = result.best_fitness - self._evaluate(initial, context)

        self._history.append(result)
        if len(self._history) > 100:
            self._history = self._history[-50:]

        return result

    def _bfs_search(self, root: SearchNode, context: str,
                    max_nodes: int) -> EverOSResult:
        """Breadth-first search: level-by-level exploration."""
        queue = [root]
        explored = {root.node_id}
        nodes_count = 1

        while queue and nodes_count < max_nodes:
            next_queue = []
            for node in queue:
                if node.depth >= self._max_depth:
                    continue
                children = self._generate_children(node, context)
                for child in children:
                    if nodes_count >= max_nodes:
                        break
                    if child.node_id not in explored:
                        explored.add(child.node_id)
                        self._nodes[child.node_id] = child
                        next_queue.append(child)
                        nodes_count += 1
                        self._total_explored += 1
                        if child.fitness > self._best_node.fitness:
                            self._best_node = child
            queue = next_queue

        return self._make_result(nodes_count)

    def _dfs_search(self, root: SearchNode, context: str,
                    max_nodes: int) -> EverOSResult:
        """Depth-first search with iterative deepening."""
        stack = [root]
        explored = {root.node_id}
        nodes_count = 1
        best_depth = 0

        while stack and nodes_count < max_nodes:
            node = stack.pop()
            if node.depth > best_depth:
                best_depth = node.depth

            if node.depth >= self._max_depth:
                continue

            children = self._generate_children(node, context)
            # Sort by fitness (descending) for better DFS order
            children.sort(key=lambda c: -c.fitness)

            for child in children:
                if nodes_count >= max_nodes:
                    break
                if child.node_id not in explored:
                    explored.add(child.node_id)
                    self._nodes[child.node_id] = child
                    stack.append(child)
                    nodes_count += 1
                    self._total_explored += 1
                    if child.fitness > self._best_node.fitness:
                        self._best_node = child

        return self._make_result(nodes_count, best_depth)

    def _beam_search(self, root: SearchNode, context: str,
                     max_nodes: int) -> EverOSResult:
        """Beam search: maintain top-k candidates at each level."""
        beam = [root]
        explored = {root.node_id}
        nodes_count = 1
        best_depth = 0

        for depth in range(self._max_depth):
            if not beam or nodes_count >= max_nodes:
                break

            all_children = []
            for node in beam:
                children = self._generate_children(node, context)
                all_children.extend(children)

            # Filter unexplored and sort by fitness
            candidates = [c for c in all_children if c.node_id not in explored]
            candidates.sort(key=lambda c: -c.fitness)

            # Take top beam_width
            next_beam = candidates[:self._beam_width]
            for child in next_beam:
                explored.add(child.node_id)
                self._nodes[child.node_id] = child
                nodes_count += 1
                self._total_explored += 1
                if child.fitness > self._best_node.fitness:
                    self._best_node = child

            beam = next_beam
            best_depth = depth + 1

        return self._make_result(nodes_count, best_depth)

    def _astar_search(self, root: SearchNode, context: str,
                      max_nodes: int) -> EverOSResult:
        """A* search with fitness-based heuristic.

        f(n) = g(n) + h(n)
        where g(n) = path cost (1 - cumulative fitness)
              h(n) = estimated cost to goal
        """
        # Priority queue: (f_score, counter, node)
        counter = 0
        g_scores = {root.node_id: 0.0}
        came_from = {}
        open_set = []

        root_f = root.fitness + self._heuristic(root, context)
        heapq.heappush(open_set, (-root_f, counter, root))
        closed_set: Set[str] = set()
        nodes_count = 1

        while open_set and nodes_count < max_nodes:
            neg_f, _, current = heapq.heappop(open_set)

            if current.node_id in closed_set:
                continue
            closed_set.add(current.node_id)

            if current.depth >= self._max_depth:
                continue

            children = self._generate_children(current, context)
            for child in children:
                if child.node_id in closed_set:
                    continue

                tentative_g = g_scores[current.node_id] + (1.0 - child.fitness)

                if child.node_id not in g_scores or tentative_g < g_scores[child.node_id]:
                    came_from[child.node_id] = current.node_id
                    g_scores[child.node_id] = tentative_g
                    f_score = tentative_g + self._heuristic(child, context)
                    counter += 1
                    heapq.heappush(open_set, (-f_score, counter, child))

                    self._nodes[child.node_id] = child
                    nodes_count += 1
                    self._total_explored += 1

                    if child.fitness > self._best_node.fitness:
                        self._best_node = child

        return self._make_result(nodes_count)

    def _generate_children(self, parent: SearchNode,
                           context: str) -> List[SearchNode]:
        """Generate child nodes by mutating parent state."""
        children = []
        for i in range(self._branching):
            child_state = dict(parent.state)

            # Mutate each parameter with small perturbation
            for key in child_state:
                if isinstance(child_state[key], (int, float)):
                    if random.random() < 0.3:
                        delta = random.gauss(0, 0.1)
                        child_state[key] = child_state[key] + delta

            child_id = f"n_{self._total_explored}_{i}"
            child = SearchNode(
                node_id=child_id,
                state=child_state,
                fitness=self._evaluate(child_state, context),
                heuristic=self._heuristic_fn(child_state, context) if self._heuristic_fn else 0.0,
                depth=parent.depth + 1,
                parent_id=parent.node_id,
                timestamp=time.time(),
            )
            children.append(child)
            parent.children_ids.append(child_id)

        return children

    def _heuristic(self, node: SearchNode, context: str) -> float:
        """Estimate distance to optimal solution."""
        if self._heuristic_fn:
            return self._heuristic_fn(node.state, context)
        # Default: inverse of fitness (lower heuristic = closer to goal)
        return max(0.0, 1.0 - node.fitness)

    def _evaluate(self, state: Dict[str, Any], context: str) -> float:
        """Evaluate state fitness."""
        if self._evaluate_fn:
            try:
                result = self._evaluate_fn(context, state)
                if isinstance(result, (int, float)):
                    return float(result)
                if isinstance(result, dict):
                    return float(result.get("fitness", result.get("score", 0.0)))
            except Exception as e:
                logger.warning("EverOS fitness evaluation failed: %s", e)
        # Heuristic: weighted sum of numeric state values
        score = 0.0
        for v in state.values():
            if isinstance(v, (int, float)):
                score += max(0, min(1, v))
        return score / max(len(state), 1)

    def _default_initial_state(self, context: str) -> Dict[str, Any]:
        """Default initial state for evolution."""
        return {
            "exploration_rate": random.uniform(0.1, 0.5),
            "learning_rate": random.uniform(0.001, 0.01),
            "temperature": random.uniform(0.5, 1.0),
            "memory_weight": random.uniform(0.3, 0.7),
        }

    def _auto_select(self, context: str) -> SearchStrategy:
        """Auto-select search strategy based on context."""
        ctx = context.lower()
        if any(w in ctx for w in ["debug", "fix", "error"]):
            return SearchStrategy.DFS  # Deep investigation
        if any(w in ctx for w in ["explore", "discover", "search"]):
            return SearchStrategy.BFS  # Broad coverage
        if any(w in ctx for w in ["optimize", "tune", "improve"]):
            return SearchStrategy.ASTAR  # Goal-directed
        return SearchStrategy.BEAM  # Balanced default

    def _make_result(self, nodes_count: int, depth_reached: int = 0) -> EverOSResult:
        """Create result from best node."""
        best = self._best_node or SearchNode()
        path = self._trace_path(best.node_id)
        return EverOSResult(
            method="everos",
            strategy="",
            best_fitness=best.fitness,
            best_state=dict(best.state),
            nodes_explored=nodes_count,
            depth_reached=max(depth_reached, best.depth),
            path=path,
        )

    def _trace_path(self, node_id: str) -> List[str]:
        """Trace path from root to node."""
        path = []
        current = node_id
        visited = set()
        while current and current != "root" and current not in visited:
            visited.add(current)
            node = self._nodes.get(current)
            if node:
                path.append(current)
                current = node.parent_id
            else:
                break
        path.append("root")
        path.reverse()
        return path

    def get_search_graph(self) -> Dict[str, Any]:
        """Get the explored search graph."""
        return {
            "total_nodes": len(self._nodes),
            "total_explored": self._total_explored,
            "best_fitness": self._best_node.fitness if self._best_node else 0.0,
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get EverOS statistics."""
        recent = self._history[-10:] if self._history else []
        avg_fitness = sum(r.best_fitness for r in recent) / max(len(recent), 1)
        avg_explored = sum(r.nodes_explored for r in recent) / max(len(recent), 1)
        return {
            "total_runs": len(self._history),
            "avg_best_fitness": avg_fitness,
            "avg_nodes_explored": avg_explored,
            "graph_nodes": len(self._nodes),
            "total_explored": self._total_explored,
        }


# Backward compatibility alias (for existing life.py imports)
EverOS = EverOSEvolution
