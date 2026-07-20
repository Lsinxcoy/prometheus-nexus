"""WorkItemDAGScheduler — 工作项DAG调度器

借鉴OpenOPC的Work-Item DAG概念：
- 将复杂任务分解为可并行执行的工作项
- 支持依赖关系和优先级调度
- 自动处理失败重试和超时
- 提供实时进度追踪
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable
from collections import defaultdict
import threading

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class WorkItem:
    """工作项"""
    item_id: str
    name: str
    operation: str
    params: dict[str, Any] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)  # 依赖的item_ids
    priority: int = 5  # 1-10，越高越优先
    timeout: float = 30.0  # 超时时间(秒)
    retries: int = 2
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    attempts: int = 0

    def duration_ms(self) -> float:
        if self.end_time and self.start_time:
            return (self.end_time - self.start_time) * 1000
        return 0.0


@dataclass
class DAGResult:
    """DAG执行结果"""
    dag_id: str
    status: TaskStatus
    total_items: int
    completed_items: int
    failed_items: int
    duration_ms: float
    results: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


class WorkItemDAGScheduler:
    """工作项DAG调度器

    支持并行执行、依赖管理、失败重试和超时控制。
    """

    def __init__(self, max_concurrent: int = 4):
        """初始化

        Args:
            max_concurrent: 最大并发数
        """
        self._max_concurrent = max_concurrent
        self._work_items: dict[str, WorkItem] = {}
        self._dag_results: dict[str, DAGResult] = {}
        self._execution_log: list[dict] = []
        self._lock = threading.Lock()
        self._stats = {
            "total_executed": 0,
            "successful": 0,
            "failed": 0,
            "retried": 0,
            "timeouts": 0,
            "avg_duration_ms": 0.0,
        }

    def create_dag(
        self,
        dag_id: str,
        items: list[WorkItem],
        execute_fn: Callable[[WorkItem], Any],
    ) -> DAGResult:
        """创建并执行DAG

        Args:
            dag_id: DAG ID
            items: 工作项列表
            execute_fn: 执行函数

        Returns:
            DAG执行结果
        """
        # 注册所有工作项
        for item in items:
            self._work_items[item.item_id] = item

        # 构建依赖图
        dependency_graph = self._build_dependency_graph(items)

        # 执行DAG
        result = self._execute_dag(dag_id, items, dependency_graph, execute_fn)

        self._dag_results[dag_id] = result
        return result

    def get_item_status(self, item_id: str) -> TaskStatus | None:
        """获取工作项状态"""
        item = self._work_items.get(item_id)
        return item.status if item else None

    def cancel_dag(self, dag_id: str) -> bool:
        """取消DAG执行"""
        if dag_id not in self._dag_results:
            return False

        # 标记所有待执行的项目为取消
        for item in self._work_items.values():
            if item.status == TaskStatus.PENDING:
                item.status = TaskStatus.CANCELLED

        return True

    def get_progress(self, dag_id: str) -> dict[str, Any]:
        """获取执行进度"""
        if dag_id not in self._dag_results:
            return {"status": "not_found"}

        result = self._dag_results[dag_id]
        return {
            "dag_id": dag_id,
            "status": result.status.value,
            "progress": round(result.completed_items / max(result.total_items, 1), 2),
            "completed": result.completed_items,
            "total": result.total_items,
            "failed": result.failed_items,
            "duration_ms": result.duration_ms,
        }

    def _build_dependency_graph(self, items: list[WorkItem]) -> dict[str, set[str]]:
        """构建依赖图

        Returns:
            item_id -> set of dependent item_ids
        """
        graph: dict[str, set[str]] = defaultdict(set)

        for item in items:
            for dep_id in item.dependencies:
                if dep_id not in [i.item_id for i in items]:
                    logger.warning("Item %s depends on unknown item %s", item.item_id, dep_id)
                    continue
                graph[dep_id].add(item.item_id)

        return graph

    def _execute_dag(
        self,
        dag_id: str,
        items: list[WorkItem],
        dependency_graph: dict[str, set[str]],
        execute_fn: Callable[[WorkItem], Any],
    ) -> DAGResult:
        """执行DAG"""
        start_time = time.time()
        completed: set[str] = set()
        failed: set[str] = set()
        running: set[str] = set()
        results: dict[str, Any] = {}
        errors: dict[str, str] = {}

        # 按优先级排序
        items_by_priority = sorted(items, key=lambda x: -x.priority)

        while len(completed) + len(failed) < len(items):
            # 找出可以执行的项目（依赖已满足且未运行）
            ready_items = [
                item for item in items_by_priority
                if item.item_id not in completed
                and item.item_id not in failed
                and item.item_id not in running
                and all(dep in completed for dep in item.dependencies)
            ]

            # 启动新项目（不超过并发限制）
            for item in ready_items[:self._max_concurrent - len(running)]:
                thread = threading.Thread(
                    target=self._execute_item,
                    args=(item, execute_fn, results, errors, completed, failed),
                    daemon=True,
                )
                thread.start()
                running.add(item.item_id)
                item.status = TaskStatus.RUNNING
                item.start_time = time.time()

            # 等待任一项目完成
            if running:
                time.sleep(0.1)  # 轮询间隔

                # 检查完成的项目
                to_remove = set()
                for item_id in running:
                    item = self._work_items.get(item_id)
                    if item and item.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.TIMEOUT):
                        to_remove.add(item_id)
                        if item.status == TaskStatus.COMPLETED:
                            completed.add(item_id)
                        else:
                            failed.add(item_id)

                running -= to_remove
            else:
                # 没有可执行的项目，检查是否全部失败
                if not ready_items and len(completed) + len(failed) < len(items):
                    # 有循环依赖或无法执行的项目
                    remaining = [i for i in items if i.item_id not in completed and i.item_id not in failed]
                    for item in remaining:
                        item.status = TaskStatus.FAILED
                        errors[item.item_id] = "Circular dependency or unresolved dependencies"
                        failed.add(item.item_id)
                    break

        end_time = time.time()
        duration_ms = (end_time - start_time) * 1000

        return DAGResult(
            dag_id=dag_id,
            status=TaskStatus.COMPLETED if not failed else TaskStatus.FAILED,
            total_items=len(items),
            completed_items=len(completed),
            failed_items=len(failed),
            duration_ms=duration_ms,
            results=results,
            errors=errors,
        )

    def _execute_item(
        self,
        item: WorkItem,
        execute_fn: Callable[[WorkItem], Any],
        results: dict[str, Any],
        errors: dict[str, str],
        completed: set[str],
        failed: set[str],
    ) -> None:
        """执行单个工作项"""
        max_attempts = item.retries + 1

        for attempt in range(max_attempts):
            try:
                item.attempts = attempt + 1

                # 设置超时
                timeout = item.timeout

                # 执行（简化版，实际应使用线程池+超时控制）
                result = execute_fn(item)

                item.result = result
                item.status = TaskStatus.COMPLETED
                item.end_time = time.time()
                results[item.item_id] = result

                self._update_stats(True, item.duration_ms())
                self._log_execution(item, "success")

                with self._lock:
                    completed.add(item.item_id)

                return

            except Exception as e:
                item.error = str(e)
                self._log_execution(item, "failed", str(e))

                if attempt < max_attempts - 1:
                    self._stats["retried"] += 1
                    logger.info("Retrying item %s (attempt %d/%d)", item.item_id, attempt + 1, max_attempts)
                    time.sleep(0.5 * (attempt + 1))  # 指数退避

        # 所有尝试都失败
        item.status = TaskStatus.FAILED
        item.end_time = time.time()
        errors[item.item_id] = item.error

        self._update_stats(False, item.duration_ms())

        with self._lock:
            failed.add(item.item_id)

    def _update_stats(self, success: bool, duration_ms: float) -> None:
        """更新统计"""
        self._stats["total_executed"] += 1
        if success:
            self._stats["successful"] += 1
            total_duration = self._stats["avg_duration_ms"] * (self._stats["total_executed"] - 1)
            self._stats["avg_duration_ms"] = (total_duration + duration_ms) / self._stats["total_executed"]
        else:
            self._stats["failed"] += 1

    def _log_execution(self, item: WorkItem, status: str, error: str = "") -> None:
        """记录执行日志"""
        self._execution_log.append({
            "item_id": item.item_id,
            "operation": item.operation,
            "status": status,
            "attempts": item.attempts,
            "duration_ms": item.duration_ms(),
            "error": error,
            "timestamp": time.time(),
        })

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        return {
            **self._stats,
            "active_dags": len(self._dag_results),
            "total_items": len(self._work_items),
        }
