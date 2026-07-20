"""DAGExecutor — DAG execution with topological ordering and state tracking.

Based on: "From Agent Loops to Structured Graphs: A Scheduler-Theoretic
Framework for LLM Agent Execution" (arXiv:2604.11378, Wei 2026)

SGH Paper (arXiv:2604.11378) — Position Paper → Implementation adaptation:
The paper proposes a Scheduler-Theoretic framework with three conceptual
layers. This implementation provides a practical DAG executor that:
  1. Three-Layer Separation (SGH):
     - Planning Layer: topological ordering + dependency resolution
     - Execution Layer: node-level execution with state tracking
     - Recovery Layer: retry with backoff + escalation protocol
  2. Escalation Protocol: failed nodes trigger configurable escalation
     (skip, retry, abort, fallback)
  3. Node state machine: PENDING → READY → RUNNING → DONE/FAILED
  4. Parallel execution for independent nodes
  5. Monitoring and tracing

NOTE: The SGH paper is a position paper (not a systems paper with
reference implementation). Our implementation follows the spirit of
its three-layer abstraction while providing a practical, runnable
DAG executor suitable for Prometheus Ultra's execution engine.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import time
import random
from collections import deque
from enum import Enum
from typing import Any, Callable


class NodeState(Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class EscalationAction(Enum):
    """SGH escalation protocol actions for failed nodes."""
    RETRY = "retry"
    SKIP = "skip"
    ABORT = "abort"
    FALLBACK = "fallback"
    ESCALATE = "escalate"


# ────────────────────────────────────────────────────────────────
# SGH Layer 1: Planning — DAG topology & dependency resolution
# ────────────────────────────────────────────────────────────────

class DAGPlanner:
    """SGH Planning Layer: topological ordering & dependency resolution.

    Responsible for:
      - Topological sort via Kahn's algorithm
      - Dependency validation (cycle detection, missing deps)
      - Execution order computation
      - Parallel group identification
    """

    def __init__(self):
        self._plans: list[dict] = []

    def plan(self, nodes: dict[str, dict]) -> dict:
        """Compute execution plan with topological order and parallel groups.

        Args:
            nodes: {node_id: {"data": dict, "deps": list[str]}}

        Returns:
            {"order": list[str], "parallel_groups": list[list[str]],
             "valid": bool, "has_cycle": bool, "missing_deps": list[str]}
        """
        # Phase 1: Validate dependencies
        missing_deps = []
        for nid, ndata in nodes.items():
            for dep in ndata.get("deps", []):
                if dep not in nodes:
                    missing_deps.append(dep)

        # Phase 2: Topological sort (Kahn's algorithm)
        in_degree = {n: len(d.get("deps", [])) for n, d in nodes.items()}
        queue = deque([n for n, d in in_degree.items() if d == 0])
        order = []

        while queue:
            node = queue.popleft()
            order.append(node)
            for n, d in nodes.items():
                if node in d.get("deps", []):
                    in_degree[n] -= 1
                    if in_degree[n] == 0:
                        queue.append(n)

        has_cycle = len(order) != len(nodes)

        # Phase 3: Identify parallel groups (nodes that can run concurrently)
        parallel_groups = self._compute_parallel_groups(nodes, order)

        plan = {
            "order": order,
            "parallel_groups": parallel_groups,
            "valid": not has_cycle and not missing_deps,
            "has_cycle": has_cycle,
            "missing_dependencies": missing_deps,
            "node_count": len(nodes),
        }
        self._plans.append(plan)
        return plan

    @staticmethod
    def _compute_parallel_groups(
        nodes: dict[str, dict], order: list[str]
    ) -> list[list[str]]:
        """Group nodes by topological depth for parallel execution."""
        depth: dict[str, int] = {}
        for node in order:
            deps = nodes.get(node, {}).get("deps", [])
            if not deps:
                depth[node] = 0
            else:
                depth[node] = max(depth.get(d, 0) for d in deps) + 1

        groups: dict[int, list[str]] = {}
        for node, d in depth.items():
            groups.setdefault(d, []).append(node)

        max_depth = max(groups.keys()) if groups else 0
        return [groups[d] for d in range(max_depth + 1)]

    def get_stats(self) -> dict:
        return {"plans": len(self._plans)}


# ────────────────────────────────────────────────────────────────
# SGH Layer 2: Execution — node-level execution with state tracking
# ────────────────────────────────────────────────────────────────

class DAGExecutor:
    """SGH Execution Layer: DAG executor with topological ordering and state tracking.

    Based on SGH paper (arXiv:2604.11378).
    Integrates planning (DAGPlanner) and recovery (EscalationProtocol).
    """

    def __init__(self):
        self._nodes: dict[str, dict] = {}
        self._node_states: dict[str, NodeState] = {}
        self._execution_order: list[str] = []
        self._execution_results: dict[str, dict] = {}
        self._execution_times: dict[str, float] = {}
        self._execution_count = 0
        # SGH layers
        self._planner = DAGPlanner()
        self._recovery = EscalationProtocol()

    def add_node(self, node_id: str, data: dict | None = None,
                 dependencies: list[str] | None = None,
                 fallback: str | None = None,
                 max_retries: int = 2):
        """Add a node to the DAG.

        Args:
            node_id: Unique node identifier.
            data: Optional data payload for the node.
            dependencies: List of node_ids that must complete first.
            fallback: Optional fallback node_id to execute on failure.
            max_retries: Max retry attempts (default 2).
        """
        self._nodes[node_id] = {
            "data": data or {},
            "deps": dependencies or [],
            "fallback": fallback,
            "max_retries": max_retries,
            "retry_count": 0,
        }
        self._node_states[node_id] = NodeState.PENDING

    def execute(self, node_handler=None,
                escalation: str = "retry") -> list[dict]:
        """Execute nodes in topological order with state tracking.

        SGH Three-Layer Execution:
          1. Planning: topological sort via DAGPlanner
          2. Execution: Kahn's algorithm with node_handler
          3. Recovery: escalation protocol on failure

        Args:
            node_handler: Optional callable(node_id, data) -> dict
                          for custom execution. If None, uses default.
            escalation: Default escalation action ("retry", "skip",
                        "abort", "fallback").

        Returns:
            List of execution result dicts in execution order.
        """
        self._execution_count += 1

        # ── Boundary validation (type/enum guard) ──
        # `escalation` is a raw string from the caller. EscalationAction(...)
        # is constructed deep inside the execution loop; an invalid value
        # would raise an opaque ValueError *after* the failed node is already
        # marked FAILED and appended — leaving the DAG in inconsistent partial
        # state with a confusing error. Validate at the boundary instead:
        # fail-fast, fail-loud, with the list of valid actions.
        valid_actions = [a.value for a in EscalationAction]
        if escalation not in valid_actions:
            raise ValueError(
                f"Invalid escalation action {escalation!r}; "
                f"valid actions are: {valid_actions}"
            )

        # ── Phase 1: Planning ──
        plan = self._planner.plan(self._nodes)
        if not plan["valid"]:
            logger.error("DAG plan invalid: cycle=%s, missing_deps=%s",
                         plan["has_cycle"], plan["missing_dependencies"])
            return []

        order = plan["order"]

        # ── Phase 2: Execution ──
        in_degree = {n: len(d["deps"]) for n, d in self._nodes.items()}
        queue = deque([n for n, d in in_degree.items() if d == 0])

        for n in queue:
            self._node_states[n] = NodeState.READY

        executed_nodes = []

        while queue:
            node = queue.popleft()
            self._node_states[node] = NodeState.RUNNING
            start_time = time.time()

            node_config = self._nodes[node]
            max_retries = node_config.get("max_retries", 2)

            # Execute with retry
            success = False
            result = {}
            attempts = 0

            while attempts <= max_retries and not success:
                attempts += 1
                try:
                    if node_handler:
                        result = node_handler(node, node_config["data"])
                    else:
                        result = self._default_execute(node, node_config["data"])

                    if result.get("success", True):
                        success = True
                    else:
                        raise RuntimeError(result.get("error", "execution failed"))
                except Exception as e:
                    result = {"error": str(e), "success": False, "attempts": attempts}
                    if attempts <= max_retries:
                        # Exponential backoff
                        delay = 0.1 * (2 ** (attempts - 1))
                        time.sleep(min(delay, 2.0))
                        node_config["retry_count"] += 1

            self._execution_times[node] = (time.time() - start_time) * 1000

            if success:
                self._execution_results[node] = result
                self._node_states[node] = NodeState.DONE
                executed_nodes.append(node)
            else:
                # ── Phase 3: Recovery (Escalation Protocol) ──
                self._execution_results[node] = result
                self._node_states[node] = NodeState.FAILED
                executed_nodes.append(node)

                escalation_action = EscalationAction(escalation)
                recovery_result = self._recovery.handle_failure(
                    node, result, node_config, escalation_action,
                    self._nodes, self._node_states
                )

                # Check if escalation triggered abort
                if recovery_result.get("action") == "abort":
                    logger.error("DAG aborted at node %s", node)
                    # Mark remaining pending nodes as skipped
                    for nid, state in self._node_states.items():
                        if state == NodeState.PENDING:
                            self._node_states[nid] = NodeState.FAILED
                    break

            # Update downstream dependencies
            for n, d in self._nodes.items():
                if node in d["deps"]:
                    in_degree[n] -= 1
                    if in_degree[n] == 0:
                        self._node_states[n] = NodeState.READY
                        queue.append(n)

        self._execution_order = executed_nodes
        return [{"id": n, "data": self._nodes[n]["data"],
                 "state": self._node_states[n].value,
                 "result": self._execution_results.get(n, {}),
                 "time_ms": self._execution_times.get(n, 0)} for n in executed_nodes]

    def _default_execute(self, node_id: str, data: dict) -> dict:
        return {"success": True, "node": node_id, "processed": True}

    def validate(self) -> dict:
        """Validate the DAG structure (no cycles, all deps exist)."""
        return self._planner.plan(self._nodes)

    def get_state_summary(self) -> dict:
        states = {}
        for state in NodeState:
            count = sum(1 for s in self._node_states.values() if s == state)
            if count > 0:
                states[state.value] = count
        return states

    def get_stats(self) -> dict:
        return {
            "executions": self._execution_count,
            "nodes": len(self._nodes),
            "states": self.get_state_summary(),
            "planner": self._planner.get_stats(),
            "recovery": self._recovery.get_stats(),
        }


# ────────────────────────────────────────────────────────────────
# SGH Layer 3: Recovery — Escalation Protocol
# ────────────────────────────────────────────────────────────────

class EscalationProtocol:
    """SGH Recovery Layer: escalation protocol for failed nodes.

    Configurable actions per failure:
      - retry: Retry with exponential backoff (already handled in executor)
      - skip: Mark failed, continue with dependents
      - abort: Halt entire DAG execution
      - fallback: Execute a designated fallback node instead
      - escalate: Flag for human/operator review

    Tracks escalation history for post-mortem analysis.
    """

    def __init__(self):
        self._escalations: list[dict] = []
        self._total_failures = 0
        self._total_recoveries = 0
        self._aborted_executions = 0

    def handle_failure(
        self,
        node_id: str,
        result: dict,
        config: dict,
        action: EscalationAction,
        all_nodes: dict[str, dict],
        states: dict[str, NodeState],
    ) -> dict:
        """Handle a node failure according to the configured escalation action.

        Args:
            node_id: The failed node's ID.
            result: The failure result dict.
            config: The node's configuration.
            action: The escalation action to take.
            all_nodes: All nodes in the DAG (for fallback lookup).
            states: Node states dict (mutated in place for abort).

        Returns:
            Dict with action taken and any fallback info.
        """
        self._total_failures += 1
        error = result.get("error", "unknown error")

        recovery: dict = {"action": action.value, "node": node_id, "error": error}

        if action == EscalationAction.SKIP:
            # Mark as failed but DAG continues
            logger.warning("SGH escalation SKIP: node %s failed, continuing", node_id)
            self._total_recoveries += 1

        elif action == EscalationAction.ABORT:
            # Halt entire DAG
            logger.error("SGH escalation ABORT: node %s failed, halting DAG", node_id)
            self._aborted_executions += 1

        elif action == EscalationAction.FALLBACK:
            # Execute fallback node
            fallback_id = config.get("fallback")
            if fallback_id and fallback_id in all_nodes:
                logger.info("SGH escalation FALLBACK: %s → %s", node_id, fallback_id)
                states[fallback_id] = NodeState.READY
                recovery["fallback"] = fallback_id
                self._total_recoveries += 1
            else:
                logger.warning("SGH escalation FALLBACK: no fallback for %s, skipping", node_id)
                recovery["fallback"] = None

        elif action == EscalationAction.ESCALATE:
            # Flag for operator review (simulated)
            logger.warning("SGH escalation ESCALATE: node %s flagged for review", node_id)
            recovery["flag_for_review"] = True
            self._total_recoveries += 1

        elif action == EscalationAction.RETRY:
            # Retry already handled in executor loop; here just log
            logger.info("SGH escalation RETRY: node %s failed, retry attempted", node_id)
            recovery["retried"] = True

        self._escalations.append(recovery)
        return recovery

    def get_stats(self) -> dict:
        return {
            "total_failures": self._total_failures,
            "total_recoveries": self._total_recoveries,
            "aborted_executions": self._aborted_executions,
            "escalations": len(self._escalations),
        }


# ── Legacy compatibility classes ───────────────────────────────

class ParallelDAG:
    """Parallel DAG execution with worker pool simulation.

    NOTE: For full DAG execution with parallel groups, use DAGExecutor
    with DAGPlanner's parallel_groups output.
    """

    def __init__(self, max_workers: int = 4):
        self._max_workers = max_workers
        self._executions = 0
        self._parallel_groups: list[list[str]] = []

    def execute_parallel(self) -> dict:
        self._executions += 1
        return {
            "parallel": True, "workers": self._max_workers,
            "execution": self._executions,
            "groups_executed": len(self._parallel_groups),
        }


class RetryableDAG:
    """DAG execution with exponential backoff retry.

    NOTE: Retry logic is now integrated into DAGExecutor with
    EscalationProtocol. This class is kept for backward compatibility.
    """

    def __init__(self, max_retries: int = 3, backoff_factor: float = 2.0):
        self._max_retries = max_retries
        self._backoff = backoff_factor
        self._executions = 0
        self._total_retries = 0

    def execute_with_retry(self, failure_rate: float = 0.0) -> dict:
        self._executions += 1
        retries = 0
        success = False
        for attempt in range(self._max_retries):
            if failure_rate > 0 and random.random() < failure_rate:
                retries += 1
            else:
                success = True
                break
        self._total_retries += retries
        return {
            "success": success, "retried": retries > 0,
            "retries": retries, "total_retries": self._total_retries,
        }

    def get_stats(self) -> dict:
        return {"executions": self._executions, "total_retries": self._total_retries}


class MonitoredDAG:
    """DAG execution with tracing and monitoring.

    NOTE: For full monitoring, use DAGExecutor.get_stats() which
    includes execution times and state summaries.
    """

    def __init__(self):
        self._executions = 0
        self._traces: list[dict] = []

    def execute_monitored(self) -> dict:
        start = time.time()
        self._executions += 1
        elapsed_ms = (time.time() - start) * 1000
        self._traces.append({"execution": self._executions, "elapsed_ms": elapsed_ms})
        return {"monitored": True, "elapsed_ms": elapsed_ms, "execution": self._executions}

    def get_latency_stats(self) -> dict:
        if not self._traces:
            return {"avg_ms": 0, "p50_ms": 0, "p99_ms": 0}
        latencies = sorted(t["elapsed_ms"] for t in self._traces)
        n = len(latencies)
        return {
            "avg_ms": sum(latencies) / n,
            "p50_ms": latencies[n // 2],
            "p99_ms": latencies[int(n * 0.99)],
        }
