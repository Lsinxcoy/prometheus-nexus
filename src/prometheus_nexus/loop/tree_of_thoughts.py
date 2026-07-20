"""TreeOfThoughts — Tree-structured reasoning with BFS/DFS search.

Based on: "Tree of Thoughts: Deliberate Problem Solving with LLMs"
(arXiv:2305.10601, Yao et al. 2023 | NeurIPS 2023)

Key Concepts from Paper:
    1. Decompose input into intermediate "thought" steps
    2. Explore multiple thoughts per step (branching factor)
    3. Self-evaluate each thought for promise
    4. Search algorithms: BFS (breadth-first) or DFS (depth-first)
    5. Prune unpromising branches early

Paper Finding:
    "Game of 24 success rate: CoT 4%, CoT-SC 9%, ToT-BFS 74%"
    "Mini Crosswords: ToT-BFS 60% vs CoT 16%"

Algorithm:
    BFS:
        for each depth level:
            generate candidate thoughts for each frontier node
            evaluate each thought's promise
            keep top-k candidates (prune rest)
        return best complete thought path

    DFS:
        recursively explore deepest thought first
        backtrack if thought evaluates poorly
        return first complete path found

Complexity:
    BFS: O(b^d * e) where b=branching, d=depth, e=evaluation cost
    DFS: O(b^d * e) worst case, but prunes early
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import time
from dataclasses import dataclass, field
from enum import Enum


class SearchStrategy(Enum):
    BFS = "bfs"
    DFS = "dfs"


@dataclass
class ThoughtNode:
    """A single thought in the tree."""
    content: str = ""
    depth: int = 0
    score: float = 0.0
    parent: ThoughtNode | None = None
    children: list[ThoughtNode] = field(default_factory=list)
    is_terminal: bool = False
    timestamp: float = 0.0

    def path(self) -> list[str]:
        """Get the full thought path from root to this node."""
        node = self
        path = []
        while node:
            path.append(node.content)
            node = node.parent
        return list(reversed(path))

    def __repr__(self) -> str:
        return f"ThoughtNode(d={self.depth}, score={self.score:.3f}, content={self.content[:50]}...)"


@dataclass
class SearchResult:
    """Result of tree search."""
    best_path: list[str] = field(default_factory=list)
    best_score: float = 0.0
    nodes_explored: int = 0
    depth_reached: int = 0
    strategy: str = ""
    duration_ms: float = 0.0
    all_terminal_scores: list[float] = field(default_factory=list)


class TreeOfThoughts:
    """Tree-structured reasoning with BFS/DFS search.

    Based on ToT paper (arXiv:2305.10601).

    Usage:
        tot = TreeOfThoughts(branching_factor=3, max_depth=4)
        result = tot.search(
            initial_thought="Solve: 24 from [4, 7, 8, 8]",
            thought_generator=my_generator,
            thought_evaluator=my_evaluator,
            strategy=SearchStrategy.BFS,
        )
        print(f"Best: {result.best_path}, score: {result.best_score}")

    Parameters:
        branching_factor: Number of thoughts to generate per step (b in paper)
        max_depth: Maximum search depth (d in paper)
        top_k: Number of candidates to keep at each BFS level
        score_threshold: Minimum score to continue DFS exploration
    """

    def __init__(self, branching_factor: int = 3, max_depth: int = 4,
                 top_k: int = 2, score_threshold: float = 0.3):
        self._branching = branching_factor
        self._max_depth = max_depth
        self._top_k = top_k
        self._score_threshold = score_threshold
        self._searches: list[dict] = []

    def search(self, initial_thought: str, thought_generator=None,
               thought_evaluator=None, strategy: SearchStrategy = SearchStrategy.BFS,
               goal_test=None) -> SearchResult:
        start = time.time()

        if thought_generator is None:
            thought_generator = self._default_generator
        if thought_evaluator is None:
            thought_evaluator = self._default_evaluator
        if goal_test is None:
            goal_test = self._default_goal_test

        root = ThoughtNode(content=initial_thought, depth=0, score=1.0, timestamp=time.time())

        if strategy == SearchStrategy.BFS:
            result = self._bfs(root, thought_generator, thought_evaluator, goal_test)
        else:
            result = self._dfs(root, thought_generator, thought_evaluator, goal_test)

        result.strategy = strategy.value
        result.duration_ms = (time.time() - start) * 1000

        self._searches.append({
            "strategy": strategy.value,
            "nodes_explored": result.nodes_explored,
            "best_score": result.best_score,
            "depth": result.depth_reached,
            "duration_ms": result.duration_ms,
        })

        return result

    def _bfs(self, root: ThoughtNode, generator, evaluator, goal_test) -> SearchResult:
        frontier = [root]
        best_terminal = None
        nodes_explored = 0
        max_depth_reached = 0

        for depth in range(self._max_depth):
            if not frontier:
                break

            candidates = []
            for node in frontier:
                thoughts = generator(node.content, depth)
                for thought_content in thoughts:
                    child = ThoughtNode(
                        content=thought_content,
                        depth=depth + 1,
                        parent=node,
                        timestamp=time.time(),
                    )
                    child.score = evaluator(child.content, child.path())
                    node.children.append(child)
                    nodes_explored += 1

                    if goal_test(child.content, child.path()):
                        child.is_terminal = True
                        if best_terminal is None or child.score > best_terminal.score:
                            best_terminal = child
                    elif depth + 1 < self._max_depth:
                        candidates.append(child)

            max_depth_reached = depth + 1

            candidates.sort(key=lambda n: n.score, reverse=True)
            frontier = candidates[:self._top_k]

        if best_terminal:
            return SearchResult(
                best_path=best_terminal.path(),
                best_score=best_terminal.score,
                nodes_explored=nodes_explored,
                depth_reached=max_depth_reached,
            )

        all_leaves = []
        for node in frontier:
            all_leaves.extend(self._get_leaves(node))
        if all_leaves:
            best = max(all_leaves, key=lambda n: n.score)
            return SearchResult(
                best_path=best.path(),
                best_score=best.score,
                nodes_explored=nodes_explored,
                depth_reached=max_depth_reached,
            )

        return SearchResult(nodes_explored=nodes_explored, depth_reached=max_depth_reached)

    def _dfs(self, node: ThoughtNode, generator, evaluator, goal_test) -> SearchResult:
        nodes_explored = 0
        max_depth_reached = node.depth

        if goal_test(node.content, node.path()):
            node.is_terminal = True
            return SearchResult(
                best_path=node.path(),
                best_score=node.score,
                nodes_explored=1,
                depth_reached=node.depth,
            )

        if node.depth >= self._max_depth:
            return SearchResult(
                best_path=node.path(),
                best_score=node.score,
                nodes_explored=1,
                depth_reached=node.depth,
            )

        thoughts = generator(node.content, node.depth)
        best_result = None

        for thought_content in thoughts:
            child = ThoughtNode(
                content=thought_content,
                depth=node.depth + 1,
                parent=node,
                timestamp=time.time(),
            )
            child.score = evaluator(child.content, child.path())
            node.children.append(child)
            nodes_explored += 1

            if child.score < self._score_threshold:
                continue

            child_result = self._dfs(child, generator, evaluator, goal_test)
            child_result.nodes_explored += nodes_explored
            nodes_explored = 0

            if child_result.best_score > 0:
                if best_result is None or child_result.best_score > best_result.best_score:
                    best_result = child_result

            if best_result and best_result.best_score >= 0.9:
                break

        if best_result:
            return best_result

        return SearchResult(
            best_path=node.path(),
            best_score=node.score,
            nodes_explored=nodes_explored,
            depth_reached=max_depth_reached,
        )

    def _get_leaves(self, node: ThoughtNode) -> list[ThoughtNode]:
        if not node.children:
            return [node]
        leaves = []
        for child in node.children:
            leaves.extend(self._get_leaves(child))
        return leaves

    def _default_generator(self, current_thought: str, depth: int) -> list[str]:
        keywords = current_thought.split()
        thoughts = []
        for i in range(self._branching):
            thought = f"Step {depth + 1}: Consider approach {chr(65 + i)} based on '{' '.join(keywords[:3])}'"
            thoughts.append(thought)
        return thoughts

    def _default_evaluator(self, thought: str, path: list[str]) -> float:
        depth_bonus = len(path) * 0.1
        length_score = min(1.0, len(thought) / 100)
        return min(1.0, length_score * 0.5 + depth_bonus)

    def _default_goal_test(self, thought: str, path: list[str]) -> bool:
        return len(path) >= self._max_depth

    def get_stats(self) -> dict:
        scores = [s["best_score"] for s in self._searches]
        return {
            "total_searches": len(self._searches),
            "avg_score": sum(scores) / max(len(scores), 1),
            "avg_nodes": sum(s["nodes_explored"] for s in self._searches) / max(len(self._searches), 1),
        }
