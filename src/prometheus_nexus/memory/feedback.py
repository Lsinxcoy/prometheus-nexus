"""NodeFeedbackTracker + FailureLogTracker — Feedback and failure tracking.

NodeFeedbackTracker:
    - Records feedback per node (utility, success, etc.)
    - Computes average feedback per node
    - Ranks worst performers for improvement
    - Detects feedback trends over time

FailureLogTracker:
    - Records failures with action and error message
    - Deduplicates for avoidance list
    - Tracks failure patterns and frequency
    - Provides actionable failure summaries

Algorithm:
    NodeFeedbackTracker:
        record(node_id, feedback_type, value):
            1. Create FeedbackRecord
            2. Append to node's feedback list
            3. Update type counts
        get_worst_performers(top_k):
            1. Compute average per node
            2. Sort ascending
            3. Return bottom K

    FailureLogTracker:
        log(action, error, context):
            1. Create FailureRecord
            2. Append to failure list
            3. Update action and pattern counts
        get_avoidance_list(top_k):
            1. Sort by failure count
            2. Return top K actions to avoid

Complexity:
    record(): O(1) amortized
    get_worst_performers(): O(N log N) where N = nodes
    log(): O(1) amortized
    get_avoidance_list(): O(A log A) where A = unique actions
"""
from __future__ import annotations
import logging
import threading
import time

logger = logging.getLogger(__name__)


from collections import Counter
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FeedbackRecord:
    """A feedback record for a node."""
    node_id: str = ""
    feedback_type: str = ""
    value: float = 0.0
    timestamp: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class FailureRecord:
    """A failure record."""
    action: str = ""
    error: str = ""
    timestamp: float = 0.0
    context: dict[str, Any] = field(default_factory=dict)
    severity: str = "medium"


class NodeFeedbackTracker:
    """Track feedback per node with ranking.

    Usage:
        tracker = NodeFeedbackTracker()
        tracker.record("node1", "utility", 0.8)
        tracker.record("node1", "utility", 0.3)
        tracker.record("node2", "utility", 0.9)

        worst = tracker.get_worst_performers(top_k=5)
        avg = tracker.get_average("node1")
    """

    def __init__(self, max_per_node: int = 100):
        """Initialize the feedback tracker.

        Args:
            max_per_node: Maximum feedback records per node.
        """
        self._max_per_node = max_per_node
        self._feedbacks: dict[str, list[FeedbackRecord]] = {}
        self._type_counts: Counter = Counter()
        self._total_recorded = 0
        # RLock: get_worst_performers/get_best_performers re-enter via
        # get_average/get_feedback_count, so a reentrant lock avoids deadlock
        # while still serialising concurrent record()/read access from the
        # main loop and the uvicorn API thread pool.
        self._lock = threading.RLock()

    def record(self, node_id: str, feedback_type: str, value: float,
               metadata: dict | None = None) -> None:
        """Record feedback for a node.

        Args:
            node_id: Node identifier.
            feedback_type: Type of feedback (e.g., "utility", "relevance").
            value: Feedback value.
            metadata: Additional metadata.
        """
        record = FeedbackRecord(
            node_id=node_id, feedback_type=feedback_type,
            value=value, timestamp=time.time(),
            metadata=metadata or {},
        )
        with self._lock:
            if node_id not in self._feedbacks:
                self._feedbacks[node_id] = []
            self._feedbacks[node_id].append(record)

            # Truncate if too many
            if len(self._feedbacks[node_id]) > self._max_per_node:
                self._feedbacks[node_id] = self._feedbacks[node_id][-self._max_per_node // 2:]

            self._type_counts[feedback_type] += 1
            self._total_recorded += 1

    def get_average(self, node_id: str) -> float:
        """Get average feedback value for a node."""
        with self._lock:
            records = self._feedbacks.get(node_id, [])
            if not records:
                return 0.0
            return sum(r.value for r in records) / len(records)

    def get_feedback_count(self, node_id: str) -> int:
        """Get total feedback count for a node."""
        with self._lock:
            return len(self._feedbacks.get(node_id, []))

    def get_worst_performers(self, top_k: int = 5) -> list[dict]:
        """Get nodes with lowest average feedback."""
        with self._lock:
            scored = [(nid, self.get_average(nid), self.get_feedback_count(nid))
                      for nid in self._feedbacks]
            scored.sort(key=lambda x: x[1])
            return [{"node_id": nid, "avg_score": sc, "feedback_count": cnt}
                    for nid, sc, cnt in scored[:top_k]]

    def get_best_performers(self, top_k: int = 5) -> list[dict]:
        """Get nodes with highest average feedback."""
        with self._lock:
            scored = [(nid, self.get_average(nid), self.get_feedback_count(nid))
                      for nid in self._feedbacks]
            scored.sort(key=lambda x: x[1], reverse=True)
            return [{"node_id": nid, "avg_score": sc, "feedback_count": cnt}
                    for nid, sc, cnt in scored[:top_k]]

    def get_feedback_trend(self, node_id: str, window: int = 10) -> list[float]:
        """Get feedback trend for a node."""
        with self._lock:
            records = self._feedbacks.get(node_id, [])
            return [r.value for r in records[-window:]]

    def get_type_stats(self) -> dict[str, int]:
        """Get feedback type distribution."""
        with self._lock:
            return dict(self._type_counts)

    def get_stats(self) -> dict:
        with self._lock:
            total = sum(len(v) for v in self._feedbacks.values())
            return {
                "nodes_tracked": len(self._feedbacks),
                "total_feedbacks": total,
                "unique_types": len(self._type_counts),
            }


class FailureLogTracker:
    """Track failures with pattern detection.

    Usage:
        tracker = FailureLogTracker()
        tracker.log("remember", "timeout error", context={"node_id": "n1"})
        tracker.log("recall", "index corruption")

        avoidance = tracker.get_avoidance_list()
        errors = tracker.get_common_errors()
    """

    def __init__(self, max_size: int = 1000):
        """Initialize the failure log tracker.

        Args:
            max_size: Maximum failure records to keep.
        """
        self._max_size = max_size
        self._failures: list[FailureRecord] = []
        self._action_counts: Counter = Counter()
        self._error_patterns: Counter = Counter()
        self._severity_counts: Counter = Counter()
        # RLock guards the shared mutable counters/list below. This tracker is a
        # process-wide singleton (omega.failure_log) written concurrently by the
        # main loop AND by the uvicorn API thread pool (POST /api/v1/remember ->
        # omega.remember -> failure_log.log). Without it, the non-atomic
        # Counter += and list append/truncate race (lost updates, inconsistent
        # get_action_failure_rates cross-reference).
        self._lock = threading.RLock()

    def log(self, action: str, error: str, context: dict | None = None,
            severity: str = "medium") -> None:
        """Record a failure.

        Args:
            action: Action that failed.
            error: Error message.
            context: Failure context.
            severity: Failure severity (low/medium/high/critical).
        """
        record = FailureRecord(
            action=action, error=error,
            timestamp=time.time(), context=context or {},
            severity=severity,
        )
        with self._lock:
            self._failures.append(record)

            # Truncate if too many
            if len(self._failures) > self._max_size:
                self._failures = self._failures[-self._max_size // 2:]

            # Update counters
            self._action_counts[action] += 1
            pattern = error[:50]
            self._error_patterns[pattern] += 1
            self._severity_counts[severity] += 1

    def get_avoidance_list(self, top_k: int = 10) -> list[str]:
        """Get actions to avoid (most frequent failures)."""
        with self._lock:
            return [a for a, _ in self._action_counts.most_common(top_k)]

    def get_common_errors(self, top_k: int = 5) -> list[dict]:
        """Get most common error patterns."""
        with self._lock:
            return [{"pattern": p, "count": c} for p, c in self._error_patterns.most_common(top_k)]

    def get_action_failure_rates(self) -> dict[str, dict]:
        """Get failure statistics per action."""
        with self._lock:
            result = {}
            for action, count in self._action_counts.items():
                action_failures = [f for f in self._failures if f.action == action]
                severities = Counter(f.severity for f in action_failures)
                result[action] = {
                    "count": count,
                    "severities": dict(severities),
                    "latest_error": action_failures[-1].error if action_failures else "",
                }
            return result

    def get_severity_distribution(self) -> dict[str, int]:
        """Get failure severity distribution."""
        with self._lock:
            return dict(self._severity_counts)

    def get_recent_failures(self, n: int = 10) -> list[dict]:
        """Get recent failures."""
        with self._lock:
            return [{"action": f.action, "error": f.error, "severity": f.severity,
                     "ts": f.timestamp}
                    for f in self._failures[-n:]]

    def get_stats(self) -> dict:
        with self._lock:
            return {
                "total_failures": len(self._failures),
                "unique_actions": len(self._action_counts),
                "unique_errors": len(self._error_patterns),
                "severity_distribution": dict(self._severity_counts),
            }
