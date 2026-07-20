"""InteractionGraph — DIG 因果交互图 (arXiv 2603.00309).

论文核心方法：交互图拓扑 → 失败模式映射。记录交互+因果推理。

Enhancements:
- Build directed interaction graph from agent interaction logs
- Topological failure-pattern detection (cycles, bottlenecks, hubs)
- Causal path analysis (trace failure propagation chains)
- Recommendation generation for identified failure modes
"""

from __future__ import annotations
import logging
import time
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


class InteractionGraph:
    """Dynamic interaction graph for agent collaboration analysis."""

    def __init__(self):
        self._edges: dict[str, dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        self._failures: list[dict] = []
        self._interaction_log: list[dict] = []  # full log with timestamps

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_interaction(
        self, agent_a: str, agent_b: str, success: bool = True,
        payload: dict | None = None,
    ):
        """Record a single agent-to-agent interaction."""
        self._edges[agent_a][agent_b] += 1
        self._interaction_log.append({
            "from": agent_a,
            "to": agent_b,
            "success": success,
            "ts": time.time(),
            "payload": payload or {},
        })
        if not success:
            self._failures.append({
                "from": agent_a,
                "to": agent_b,
                "ts": time.time(),
                "payload": payload or {},
            })

    def build_graph(self, logs: list[dict]) -> dict:
        """Build interaction graph from a list of log entries.

        Each log entry: {"from": str, "to": str, "success": bool, ...}
        Returns adjacency dict: {agent: {neighbour: count}}
        """
        for log in logs:
            self.record_interaction(
                log.get("from", ""),
                log.get("to", ""),
                log.get("success", True),
                log.get("payload"),
            )
        return {k: dict(v) for k, v in self._edges.items()}

    def diagnose_failures(
        self, graph: dict | None = None
    ) -> list[dict]:
        """Identify failure patterns from interaction graph topology.

        Detects:
        - High-fail-rate edges
        - Bottleneck agents (many outgoing failures)
        - Failure cycles
        - Cascade chains

        Returns list of diagnosis dicts with pattern type, severity, recommendation.
        """
        g = graph or {k: dict(v) for k, v in self._edges.items()}
        diagnoses: list[dict] = []

        # --- Pattern 1: High-fail-rate edges ---
        for agent, targets in g.items():
            for target, count in targets.items():
                if count == 0:
                    continue
                fail_count = sum(
                    1
                    for f in self._failures
                    if f["from"] == agent and f["to"] == target
                )
                fail_rate = round(fail_count / count, 4)
                if fail_rate > 0.5 and fail_count >= 2:
                    diagnoses.append({
                        "pattern": "high_fail_rate_edge",
                        "agents": [agent, target],
                        "fail_rate": fail_rate,
                        "fail_count": fail_count,
                        "total": count,
                        "severity": "high" if fail_rate > 0.8 else "medium",
                        "recommendation": (
                            f"Increase redundancy or add retry logic "
                            f"between {agent} → {target}"
                        ),
                    })

        # --- Pattern 2: Bottleneck agents (many outgoing failures) ---
        agent_fail_counts: dict[str, int] = defaultdict(int)
        for f in self._failures:
            agent_fail_counts[f["from"]] += 1
        for agent, fcount in agent_fail_counts.items():
            if fcount >= 3:
                diagnoses.append({
                    "pattern": "bottleneck_agent",
                    "agents": [agent],
                    "fail_count": fcount,
                    "severity": "high" if fcount >= 5 else "medium",
                    "recommendation": (
                        f"Offload tasks from '{agent}' or split into "
                        f"specialised sub-agents to reduce failure bottleneck"
                    ),
                })

        # --- Pattern 3: Failure cycles ---
        cycles = self._detect_failure_cycles()
        for cycle in cycles:
            diagnoses.append({
                "pattern": "failure_cycle",
                "agents": cycle,
                "severity": "high",
                "recommendation": (
                    f"Break the dependency cycle {cycle} by introducing "
                    f"a coordinator agent or async queue"
                ),
            })

        # --- Pattern 4: Cascade chains ---
        cascades = self._detect_cascades()
        for cascade in cascades:
            diagnoses.append({
                "pattern": "failure_cascade",
                "agents": cascade,
                "severity": "high" if len(cascade) > 3 else "medium",
                "recommendation": (
                    f"Insert circuit-breaker at '{cascade[0]}' to prevent "
                    f"cascade propagation through {cascade}"
                ),
            })

        # Deduplicate by (pattern, frozenset(agents))
        seen: set[tuple] = set()
        unique: list[dict] = []
        for d in diagnoses:
            key = (d["pattern"], tuple(sorted(d["agents"])))
            if key not in seen:
                seen.add(key)
                unique.append(d)

        return unique

    def get_stats(self) -> dict:
        return {
            "edges": sum(len(t) for t in self._edges.values()),
            "failures": len(self._failures),
            "interactions": len(self._interaction_log),
        }

    # ------------------------------------------------------------------
    # Internal analysis
    # ------------------------------------------------------------------

    def _detect_failure_cycles(self) -> list[list[str]]:
        """Detect cycles in the failure graph via DFS."""
        # Build adjacency of failure edges only
        fail_adj: dict[str, set[str]] = defaultdict(set)
        for f in self._failures:
            fail_adj[f["from"]].add(f["to"])

        cycles: list[list[str]] = []
        visited: set[str] = set()
        rec_stack: list[str] = []

        def _dfs(node: str, path: list[str]):
            visited.add(node)
            rec_stack.append(node)
            for neighbor in fail_adj.get(node, []):
                if neighbor not in visited:
                    _dfs(neighbor, path + [neighbor])
                elif neighbor in rec_stack:
                    # Found a cycle — extract it
                    idx = rec_stack.index(neighbor)
                    cycle = rec_stack[idx:] + [neighbor]
                    cycles.append(cycle)
            rec_stack.pop()

        for node in list(fail_adj.keys()):
            if node not in visited:
                _dfs(node, [node])

        return cycles

    def _detect_cascades(self) -> list[list[str]]:
        """Detect cascade chains (A→B→C where each edge failed)."""
        fail_adj: dict[str, list[str]] = defaultdict(list)
        for f in self._failures:
            fail_adj[f["from"]].append(f["to"])

        cascades: list[list[str]] = []
        # Find all paths of length >= 2 where each step has a recorded failure
        for start in list(fail_adj.keys()):
            stack = [(start, [start])]
            visited_paths: set[tuple] = set()
            while stack:
                node, path = stack.pop()
                if len(path) >= 3:
                    key = tuple(path)
                    if key not in visited_paths:
                        visited_paths.add(key)
                        cascades.append(path[:])
                for neighbor in fail_adj.get(node, []):
                    if neighbor not in path:
                        stack.append((neighbor, path + [neighbor]))

        # Sort by length descending and deduplicate
        cascades.sort(key=len, reverse=True)
        unique_cascades: list[list[str]] = []
        seen_set: set[frozenset] = set()
        for c in cascades:
            fs = frozenset(c)
            if fs not in seen_set:
                seen_set.add(fs)
                unique_cascades.append(c)

        return unique_cascades[:10]  # limit to top 10
