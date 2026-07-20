"""TrajectoryStore — Operation trajectory recording and pattern analysis.

基于:
- Dumas et al. (2005) "Process Mining: Data Science in Action" (Springer)
  - 轨迹记录: action → steps → outcome, 含时间戳/错误信息/元数据
  - 成功/失败模式追踪: 按action分组的success_rate统计
  - 错误模式提取: 前50字符截断分组, most_common(top_k)
  - 持续统计: 平均/P50/P95/P99延迟, 滑动窗口(max_size)

算法:
    record(action, steps, success):
        1. 创建TrajectoryEntry(含元数据)
        2. 追加到历史(滑动窗口截断)
        3. 更新action_counts/success/failure计数器
        4. 错误模式提取(error[:50])

    success_rate(action):
        success_count[action] / (success_count + failure_count)

来源: Omega系统 trajectory 操作轨迹记录模块 + 流程挖掘方法论
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TrajectoryEntry:
    """A recorded trajectory."""
    action: str = ""
    steps: list[dict] = field(default_factory=list)
    success: bool = True
    timestamp: float = 0.0
    step_count: int = 0
    duration_ms: float = 0.0
    error_message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class TrajectoryStore:
    """Operation trajectory recording and pattern analysis.

    Usage:
        store = TrajectoryStore()
        store.record("remember", [{"step": "validate"}, {"step": "store"}], success=True)
        store.record("recall", [{"step": "search"}], success=False, error="timeout")

        rate = store.success_rate("remember")
        failures = store.get_common_failures()
        summary = store.get_action_summary()
    """

    def __init__(self, max_size: int = 1000):
        """Initialize the trajectory store.

        Args:
            max_size: Maximum trajectories to keep.
        """
        self._max_size = max_size
        self._trajectories: list[TrajectoryEntry] = []
        self._action_counts: Counter = Counter()
        self._success_counts: Counter = Counter()
        self._failure_counts: Counter = Counter()
        self._error_patterns: Counter = Counter()
        self._duration_stats: dict[str, list[float]] = defaultdict(list)

    def record(self, action: str, steps: list[dict], success: bool = True,
               error: str = "", duration_ms: float = 0.0,
               metadata: dict | None = None) -> TrajectoryEntry:
        """Record an operation trajectory.

        Args:
            action: Action name (e.g., "remember", "recall").
            steps: List of step dicts.
            success: Whether the trajectory succeeded.
            error: Error message if failed.
            duration_ms: Duration in milliseconds.
            metadata: Additional metadata.

        Returns:
            The recorded TrajectoryEntry.
        """
        entry = TrajectoryEntry(
            action=action, steps=steps, success=success,
            timestamp=time.time(), step_count=len(steps),
            duration_ms=duration_ms, error_message=error,
            metadata=metadata or {},
        )
        self._trajectories.append(entry)

        # Window truncation
        if len(self._trajectories) > self._max_size:
            self._trajectories = self._trajectories[-self._max_size // 2:]

        # Update counters
        self._action_counts[action] += 1
        if success:
            self._success_counts[action] += 1
        else:
            self._failure_counts[action] += 1
            if error:
                pattern = error[:50]
                self._error_patterns[pattern] += 1

        # Track duration
        self._duration_stats[action].append(duration_ms)
        if len(self._duration_stats[action]) > 100:
            self._duration_stats[action] = self._duration_stats[action][-50:]

        return entry

    def get_trajectories(self, action: str | None = None, limit: int = 10,
                          success_only: bool | None = None) -> list[dict]:
        """Get recent trajectories, optionally filtered.

        Args:
            action: Filter by action name.
            limit: Maximum trajectories to return.
            success_only: If True, only successful; if False, only failed.

        Returns:
            List of trajectory summaries.
        """
        filtered = self._trajectories
        if action:
            filtered = [t for t in filtered if t.action == action]
        if success_only is not None:
            filtered = [t for t in filtered if t.success == success_only]

        return [{"action": t.action, "success": t.success, "steps": t.step_count,
                 "duration_ms": t.duration_ms, "error": t.error_message,
                 "ts": t.timestamp}
                for t in filtered[-limit:]]

    def success_rate(self, action: str | None = None) -> float:
        """Compute success rate.

        Args:
            action: If specified, compute for this action only.

        Returns:
            Success rate [0, 1].
        """
        if action:
            s = self._success_counts.get(action, 0)
            f = self._failure_counts.get(action, 0)
            return s / max(s + f, 1)
        total_s = sum(self._success_counts.values())
        total_f = sum(self._failure_counts.values())
        return total_s / max(total_s + total_f, 1)

    def get_common_failures(self, top_k: int = 5) -> list[dict]:
        """Get most common failure actions."""
        return [{"action": a, "count": c} for a, c in self._failure_counts.most_common(top_k)]

    def get_common_errors(self, top_k: int = 5) -> list[dict]:
        """Get most common error patterns."""
        return [{"pattern": p, "count": c} for p, c in self._error_patterns.most_common(top_k)]

    def get_action_summary(self) -> dict[str, dict]:
        """Get summary statistics per action."""
        summary = {}
        for action in self._action_counts:
            durations = self._duration_stats.get(action, [])
            summary[action] = {
                "count": self._action_counts[action],
                "success_rate": self.success_rate(action),
                "avg_duration_ms": sum(durations) / max(len(durations), 1),
                "p50_duration_ms": sorted(durations)[len(durations) // 2] if durations else 0,
            }
        return summary

    def get_duration_stats(self, action: str) -> dict:
        """Get duration statistics for an action."""
        durations = self._duration_stats.get(action, [])
        if not durations:
            return {"count": 0}
        sorted_d = sorted(durations)
        n = len(sorted_d)
        return {
            "count": n,
            "mean_ms": sum(sorted_d) / n,
            "min_ms": sorted_d[0],
            "max_ms": sorted_d[-1],
            "p50_ms": sorted_d[n // 2],
            "p95_ms": sorted_d[int(n * 0.95)],
            "p99_ms": sorted_d[int(n * 0.99)],
        }

    def compare_trajectories(self, action1: str, action2: str) -> dict:
        """Compare two trajectories by action type."""
        t1 = [t for t in self._trajectories if t.action == action1]
        t2 = [t for t in self._trajectories if t.action == action2]

        rate1 = self.success_rate(action1)
        rate2 = self.success_rate(action2)

        dur1 = self._duration_stats.get(action1, [])
        dur2 = self._duration_stats.get(action2, [])

        return {
            "action1": action1, "action2": action2,
            "count1": len(t1), "count2": len(t2),
            "success_rate1": rate1, "success_rate2": rate2,
            "avg_duration1": sum(dur1) / max(len(dur1), 1),
            "avg_duration2": sum(dur2) / max(len(dur2), 1),
        }

    def get_stats(self) -> dict:
        return {
            "trajectories": len(self._trajectories),
            "unique_actions": len(self._action_counts),
            "overall_success_rate": self.success_rate(),
            "total_successes": sum(self._success_counts.values()),
            "total_failures": sum(self._failure_counts.values()),
        }


from collections import defaultdict
