"""AttributionEvolutionScoring — 归因进化评分系统

借鉴OpenOPC的Work-Item DAG调度和归因进化评分机制：
- 每个节点操作都有明确的"工作项"(Work-Item)概念
- 使用归因分数评估进化质量，而非简单的fitness
- 支持多维度评分（延迟、成功率、资源消耗）
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class WorkItem:
    """工作项 - OpenOPC Work-Item概念"""
    item_id: str
    operation: str
    priority: int = 5
    status: str = "pending"  # pending/running/completed/failed
    start_time: float = 0.0
    end_time: float = 0.0
    attributes: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    error: str = ""

    def duration_ms(self) -> float:
        if self.end_time and self.start_time:
            return (self.end_time - self.start_time) * 1000
        return 0.0


@dataclass
class AttributionScore:
    """归因评分 - OpenOPC Attribution Evolution Scoring"""
    latency_score: float = 0.0      # 延迟评分 [0, 1]
    success_score: float = 0.0       # 成功评分 [0, 1]
    resource_score: float = 0.0      # 资源评分 [0, 1]
    diversity_score: float = 0.0     # 多样性评分 [0, 1]
    attribution_weight: float = 0.25  # 各维度权重

    def total_score(self) -> float:
        """计算总归因分数"""
        return (
            self.latency_score * self.attribution_weight +
            self.success_score * self.attribution_weight +
            self.resource_score * self.attribution_weight +
            self.diversity_score * self.attribution_weight
        )


class AttributionEvolutionScoring:
    """归因进化评分系统

    为进化操作提供多维度归因评分，替代简单的fitness函数。
    """

    def __init__(self, target_latency_ms: float = 100.0):
        self._target_latency = target_latency_ms
        self._work_items: dict[str, WorkItem] = {}
        self._history: list[dict] = []
        self._stats = {
            "total_items": 0,
            "completed_items": 0,
            "failed_items": 0,
            "avg_latency_ms": 0.0,
            "total_latency_ms": 0.0,
        }

    def create_work_item(self, item_id: str, operation: str, priority: int = 5) -> WorkItem:
        """创建工作项"""
        wi = WorkItem(
            item_id=item_id,
            operation=operation,
            priority=priority,
        )
        self._work_items[item_id] = wi
        self._stats["total_items"] += 1
        logger.debug("Created work item: %s for operation %s", item_id, operation)
        return wi

    def start_work_item(self, item_id: str) -> bool:
        """开始工作项"""
        if item_id not in self._work_items:
            return False
        wi = self._work_items[item_id]
        wi.status = "running"
        wi.start_time = time.time()
        return True

    def complete_work_item(self, item_id: str, result: Any = None) -> bool:
        """完成工作项"""
        if item_id not in self._work_items:
            return False
        wi = self._work_items[item_id]
        wi.status = "completed"
        wi.end_time = time.time()
        wi.result = result
        self._stats["completed_items"] += 1
        self._stats["total_latency_ms"] += wi.duration_ms()

        # 记录历史
        history_entry = {
            "item_id": item_id,
            "operation": wi.operation,
            "duration_ms": wi.duration_ms(),
            "priority": wi.priority,
            "timestamp": time.time(),
        }
        self._history.append(history_entry)

        logger.debug("Completed work item: %s in %.1f ms", item_id, wi.duration_ms())
        return True

    def fail_work_item(self, item_id: str, error: str = "") -> bool:
        """标记工作项失败"""
        if item_id not in self._work_items:
            return False
        wi = self._work_items[item_id]
        wi.status = "failed"
        wi.end_time = time.time()
        wi.error = error
        self._stats["failed_items"] += 1
        logger.warning("Failed work item: %s with error: %s", item_id, error)
        return True

    def compute_attribution_score(self, item_id: str) -> AttributionScore:
        """计算归因评分"""
        if item_id not in self._work_items:
            return AttributionScore()

        wi = self._work_items[item_id]
        score = AttributionScore()

        # 延迟评分：越接近目标越好
        latency = wi.duration_ms()
        if latency <= self._target_latency:
            score.latency_score = 1.0
        else:
            ratio = self._target_latency / latency
            score.latency_score = max(0.0, ratio)

        # 成功评分：完成vs失败
        if wi.status == "completed":
            score.success_score = 1.0
        elif wi.status == "failed":
            score.success_score = 0.0
        else:
            score.success_score = 0.5

        # 资源评分：基于优先级（高优先级消耗更多资源但更关键）
        score.resource_score = min(1.0, wi.priority / 10.0)

        # 多样性评分：基于历史中不同操作的数量
        unique_ops = len(set(h["operation"] for h in self._history))
        score.diversity_score = min(1.0, unique_ops / 10.0)

        return score

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        completed = self._stats["completed_items"]
        if completed > 0:
            self._stats["avg_latency_ms"] = self._stats["total_latency_ms"] / completed

        return {
            **self._stats,
            "active_items": sum(1 for wi in self._work_items.values() if wi.status == "running"),
            "pending_items": sum(1 for wi in self._work_items.values() if wi.status == "pending"),
            "recent_history": self._history[-10:],
        }
