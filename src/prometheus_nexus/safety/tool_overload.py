"""ToolOverloadDetector — Detects tool overload degrading performance.

Based on: "Tool Overload: Small Model Performance with Many Tools"
(arXiv:2411.15399, 2024)

Key Finding:
    Llama 3.1 8b fails at 46 tools, succeeds at 19 tools.
    All models degrade as tool count increases.
    Berkeley FC Leaderboard confirms: performance drops with more tools.

Algorithm:
    1. Track registered tools count
    2. Monitor tool selection accuracy over time
    3. Detect accuracy drop correlating with tool count
    4. Recommend tool pruning when overload detected
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import time
from dataclasses import dataclass, field
from collections import Counter


@dataclass
class ToolRecord:
    name: str = ""
    registered_at: float = 0.0
    selection_count: int = 0
    success_count: int = 0

    @property
    def success_rate(self) -> float:
        return self.success_count / max(self.selection_count, 1)


@dataclass
class OverloadReport:
    is_overloaded: bool = False
    tool_count: int = 0
    threshold: int = 20
    accuracy_trend: float = 0.0
    recommended_prune_count: int = 0
    tools_to_prune: list[str] = field(default_factory=list)


class ToolOverloadDetector:
    """Detects tool overload degrading performance.

    Based on Tool Overload paper (arXiv:2411.15399).

    Usage:
        detector = ToolOverloadDetector(soft_threshold=15, hard_threshold=30)
        detector.register_tool("search")
        detector.register_tool("calculator")
        detector.record_selection("search", success=True)
        report = detector.detect()
    """

    def __init__(self, soft_threshold: int = 15, hard_threshold: int = 30):
        self._soft = soft_threshold
        self._hard = hard_threshold
        self._tools: dict[str, ToolRecord] = {}
        self._accuracy_history: list[float] = []
        self._reports: list[dict] = []

    def register_tool(self, name: str):
        self._tools[name] = ToolRecord(name=name, registered_at=time.time())

    def unregister_tool(self, name: str):
        self._tools.pop(name, None)

    def record_selection(self, tool_name: str, success: bool):
        if tool_name not in self._tools:
            self._tools[tool_name] = ToolRecord(name=tool_name, registered_at=time.time())
        record = self._tools[tool_name]
        record.selection_count += 1
        if success:
            record.success_count += 1

        total_selections = sum(t.selection_count for t in self._tools.values())
        total_successes = sum(t.success_count for t in self._tools.values())
        accuracy = total_successes / max(total_selections, 1)
        self._accuracy_history.append(accuracy)
        if len(self._accuracy_history) > 200:
            self._accuracy_history = self._accuracy_history[-100:]

    def detect(self) -> OverloadReport:
        tool_count = len(self._tools)
        is_overloaded = tool_count >= self._hard

        accuracy_trend = 0.0
        if len(self._accuracy_history) >= 10:
            recent = sum(self._accuracy_history[-5:]) / 5
            older = sum(self._accuracy_history[-10:-5]) / max(len(self._accuracy_history[-10:-5]), 1)
            accuracy_trend = recent - older
            if accuracy_trend < -0.1 and tool_count >= self._soft:
                is_overloaded = True

        prune_count = max(0, tool_count - self._soft) if is_overloaded else 0

        least_used = sorted(self._tools.values(), key=lambda t: t.selection_count)
        tools_to_prune = [t.name for t in least_used[:prune_count]]

        report = OverloadReport(
            is_overloaded=is_overloaded,
            tool_count=tool_count,
            threshold=self._soft,
            accuracy_trend=accuracy_trend,
            recommended_prune_count=prune_count,
            tools_to_prune=tools_to_prune,
        )

        self._reports.append({"overloaded": is_overloaded, "tool_count": tool_count})
        return report

    def get_stats(self) -> dict:
        return {
            "tool_count": len(self._tools),
            "total_selections": sum(t.selection_count for t in self._tools.values()),
            "overall_accuracy": sum(t.success_count for t in self._tools.values()) / max(sum(t.selection_count for t in self._tools.values()), 1),
        }
