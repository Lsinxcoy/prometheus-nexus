"""DAGScheduler — DAG task scheduler with topological sort, enhanced.

增强功能:
  - 动态优先级调整（基于运行时表现）
  - checkpoint/restart 支持（断点续跑）
  - 并行度自动调节（基于系统负载和任务完成速率）

Usage:
    scheduler = DAGScheduler(max_concurrent=4)
    scheduler.add_task("deploy", dependencies=["build", "test"])
    scheduler.add_task("build")
    scheduler.add_task("test")
    order = scheduler.topological_sort()
    # 执行
    result = scheduler.execute_all(my_fn)
    # 保存 checkpoint
    scheduler.save_checkpoint("ckpt.json")
    # 恢复
    scheduler.load_checkpoint("ckpt.json")
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import json
import math
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


# ============================================================
# 数据模型
# ============================================================

class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = auto()
    READY = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    SKIPPED = auto()


@dataclass
class DAGTask:
    """DAG中的单个任务"""
    id: str
    name: str
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    dependencies: Set[str] = field(default_factory=set)
    dependents: Set[str] = field(default_factory=set)
    priority: int = 0                        # 静态优先级
    dynamic_priority: float = 0.0            # 动态优先级（运行时调整）
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    retry_count: int = 0
    max_retries: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration(self) -> Optional[float]:
        """任务执行耗时（秒）"""
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return None

    @property
    def effective_priority(self) -> float:
        """综合优先级 = 静态优先级 + 动态优先级"""
        return self.priority + self.dynamic_priority


# ============================================================
# 调度器主体
# ============================================================

class DAGScheduler:
    """DAG 任务调度器（增强版）

    支持:
    - 拓扑排序与优先级调度
    - 动态优先级调整（基于依赖完成度与执行时间）
    - checkpoint / restart（断点续跑）
    - 并行度自动调节
    - 关键路径分析
    """

    def __init__(
        self,
        max_concurrent: int = 4,
        auto_parallelism: bool = True,
        min_concurrent: int = 1,
        max_concurrent_cap: int = 16,
        priority_adjust_interval: float = 5.0,
    ):
        """
        Args:
            max_concurrent: 初始最大并发任务数
            auto_parallelism: 是否启用并行度自动调节
            min_concurrent: 最小并发数下限
            max_concurrent_cap: 最大并发数上限
            priority_adjust_interval: 动态优先级调整间隔（秒）
        """
        self._tasks: Dict[str, DAGTask] = {}
        self._max_concurrent = max_concurrent
        self._auto_parallelism = auto_parallelism
        self._min_concurrent = min_concurrent
        self._max_concurrent_cap = max_concurrent_cap
        self._priority_adjust_interval = priority_adjust_interval

        self._execution_log: List[Dict[str, Any]] = []
        self._running: Set[str] = set()

        # 并行度自动调节相关
        self._completion_times: List[float] = []   # 最近完成时间戳
        self._last_adjust_time: float = 0.0
        self._parallelism_trend: float = 0.0       # >0 增加, <0 减少

        # checkpoint 相关
        self._last_priority_adjust: float = time.time()

    # ---------------------------------------------------------------
    # 任务管理
    # ---------------------------------------------------------------

    def add_task(
        self,
        task_id: str,
        data: dict | None = None,
        dependencies: list[str] | None = None,
        priority: int = 0,
        max_retries: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DAGTask:
        """添加任务

        Args:
            task_id: 任务唯一标识
            data: 任务数据（兼容旧版 dict 接口）
            dependencies: 依赖的任务ID列表
            priority: 静态优先级（越高越先执行）
            max_retries: 最大重试次数
            metadata: 附加元数据

        Returns:
            创建的 DAGTask 对象
        """
        deps = set(dependencies or [])

        # 兼容旧版：data 字典可包含优先级
        if data and isinstance(data, dict):
            if "priority" in data and priority == 0:
                priority = data["priority"]
            if metadata is None:
                metadata = dict(data)

        task = DAGTask(
            id=task_id,
            name=task_id,
            priority=priority,
            max_retries=max_retries,
            dependencies=deps,
            metadata=metadata or (data or {}),
        )
        self._tasks[task_id] = task

        # 更新依赖图的反向引用
        for dep in deps:
            if dep in self._tasks:
                self._tasks[dep].dependents.add(task_id)

        return task

    def remove_task(self, task_id: str) -> None:
        """移除任务并清理依赖关系"""
        if task_id not in self._tasks:
            return
        task = self._tasks[task_id]
        for dep_id in task.dependencies:
            if dep_id in self._tasks:
                self._tasks[dep_id].dependents.discard(task_id)
        for dep_id in task.dependents:
            if dep_id in self._tasks:
                self._tasks[dep_id].dependencies.discard(task_id)
        self._running.discard(task_id)
        del self._tasks[task_id]

    # ---------------------------------------------------------------
    # 拓扑排序
    # ---------------------------------------------------------------

    def topological_sort(self) -> list[str]:
        """Kahn 算法拓扑排序

        返回:
            拓扑排序后的任务ID列表
        Raises:
            ValueError: 检测到环时
        """
        in_degree: Dict[str, int] = {tid: 0 for tid in self._tasks}
        for tid, task in self._tasks.items():
            for dep in task.dependencies:
                if dep in self._tasks:
                    in_degree[tid] += 1

        # 使用优先队列实现（按优先级降序）
        queue: deque[str] = deque()
        for tid, deg in in_degree.items():
            if deg == 0:
                queue.append(tid)

        result: list[str] = []
        while queue:
            # 按有效优先级排序同层节点
            batch = sorted(queue, key=lambda t: -self._tasks[t].effective_priority)
            queue.clear()
            for tid in batch:
                result.append(tid)
                for dep_id in self._tasks[tid].dependents:
                    if dep_id in in_degree:
                        in_degree[dep_id] -= 1
                        if in_degree[dep_id] == 0:
                            queue.append(dep_id)

        if len(result) != len(self._tasks):
            raise ValueError("Cycle detected in DAG")
        return result

    # ---------------------------------------------------------------
    # 动态优先级调整
    # ---------------------------------------------------------------

    def adjust_dynamic_priorities(self) -> Dict[str, float]:
        """动态调整任务优先级

        调整策略:
          1. 就绪任务的依赖完成度越高，优先级越高
          2. 长时间等待的任务获得优先级补偿（防饥饿）
          3. 已完成依赖的平均耗时短，优先级提升

        Returns:
            各任务新的动态优先级字典
        """
        now = time.time()
        if now - self._last_priority_adjust < self._priority_adjust_interval:
            return {tid: t.dynamic_priority for tid, t in self._tasks.items()}

        self._last_priority_adjust = now

        order = self.topological_sort()
        depth: Dict[str, int] = {}
        for tid in order:
            task = self._tasks[tid]
            if not task.dependencies:
                depth[tid] = 0
            else:
                depth[tid] = max(
                    (depth.get(d, 0) for d in task.dependencies if d in depth),
                    default=0
                ) + 1

        changes: Dict[str, float] = {}
        for tid, task in self._tasks.items():
            if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED):
                continue

            dp = 0.0

            # 1. 基于拓扑深度：深度越大优先级越高（下游任务优先）
            dp += depth.get(tid, 0) * 0.1

            # 2. 依赖完成度：已完成依赖比例越高优先级越高
            total_deps = len(task.dependencies)
            if total_deps > 0:
                completed_deps = sum(
                    1 for d in task.dependencies
                    if d in self._tasks and self._tasks[d].status == TaskStatus.COMPLETED
                )
                dp += (completed_deps / total_deps) * 0.5

            # 3. 防饥饿：如果任务已就绪但等待时间过长，补偿优先级
            if task.status == TaskStatus.READY:
                # 通过执行日志估算等待时间
                wait_start = self._get_task_ready_time(tid)
                if wait_start:
                    wait_seconds = now - wait_start
                    dp += min(wait_seconds / 60.0, 2.0)  # 最多补偿 2.0

            task.dynamic_priority = dp
            changes[tid] = dp

        return changes

    def _get_task_ready_time(self, task_id: str) -> Optional[float]:
        """从执行日志中查找任务就绪时间"""
        for entry in reversed(self._execution_log):
            if entry.get("task_id") == task_id and entry.get("action") == "ready":
                return entry.get("time", time.time())
        return None

    # ---------------------------------------------------------------
    # 并行度自动调节
    # ---------------------------------------------------------------

    def adjust_parallelism(self) -> int:
        """根据任务完成速率自动调整并行度

        策略:
          - 完成速率快（>1任务/秒）→ 增加并行度
          - 完成速率慢（<0.2任务/秒）→ 降低并行度
          - 在 [min_concurrent, max_concurrent_cap] 范围内调整

        Returns:
            新的并行度
        """
        if not self._auto_parallelism:
            return self._max_concurrent

        now = time.time()
        # 仅最近30秒内的完���记录
        recent = [t for t in self._completion_times if now - t < 30]
        self._completion_times = recent

        if len(recent) < 2:
            return self._max_concurrent

        # 计算完成速率（任务/秒）
        time_span = recent[-1] - recent[0]
        if time_span <= 0:
            return self._max_concurrent

        completion_rate = len(recent) / time_span

        old_parallelism = self._max_concurrent

        if completion_rate > 1.0:
            # 完成很快，增加并行度
            self._max_concurrent = min(
                self._max_concurrent_cap,
                old_parallelism + 1,
            )
        elif completion_rate < 0.2:
            # 完成很慢，降低并行度（避免资源争抢）
            self._max_concurrent = max(
                self._min_concurrent,
                old_parallelism - 1,
            )
        # 否则保持不变

        self._parallelism_trend = self._max_concurrent - old_parallelism
        self._last_adjust_time = time.time()

        return self._max_concurrent

    @property
    def current_parallelism(self) -> int:
        """当前并行度"""
        return self._max_concurrent

    # ---------------------------------------------------------------
    # 任务执行
    # ---------------------------------------------------------------

    def get_ready_tasks(self) -> List[DAGTask]:
        """获取当前就绪任务（按有效优先级排序）

        就绪条件: PENDING 状态且所有依赖已完成。

        Returns:
            就绪任务列表（最多 max_concurrent 个）
        """
        ready: List[DAGTask] = []
        for task_id, task in self._tasks.items():
            if task.status != TaskStatus.PENDING:
                continue

            deps_met = all(
                self._tasks.get(dep_id, DAGTask("", "")).status == TaskStatus.COMPLETED
                for dep_id in task.dependencies
                if dep_id in self._tasks
            )

            if deps_met:
                task.status = TaskStatus.READY
                self._execution_log.append({
                    "task_id": task_id,
                    "action": "ready",
                    "time": time.time(),
                })
                ready.append(task)

        # 按有效优先级降序排列
        ready.sort(key=lambda t: -t.effective_priority)
        return ready[: self._max_concurrent]

    def get_ready_batch(self) -> List[str]:
        """获取就绪任务ID列表"""
        return [t.id for t in self.get_ready_tasks()]

    def execute_task(
        self,
        task_id: str,
        fn: Callable[[DAGTask], Any],
    ) -> Any:
        """执行单个任务，支持重试

        Args:
            task_id: 任务ID
            fn: 执行函数 (task) -> result

        Returns:
            任务执行结果
        Raises:
            ValueError: 任务不存在
        """
        if task_id not in self._tasks:
            raise ValueError(f"Task {task_id} not found")

        task = self._tasks[task_id]

        # 缓存命中
        if task.status == TaskStatus.COMPLETED:
            return task.result

        task.status = TaskStatus.RUNNING
        task.start_time = time.time()
        self._running.add(task_id)

        self._execution_log.append({
            "task_id": task_id,
            "action": "start",
            "time": task.start_time,
            "attempt": task.retry_count + 1,
        })

        last_error = None
        while True:
            try:
                result = fn(task)
                task.result = result
                task.status = TaskStatus.COMPLETED
                self._running.discard(task_id)
                task.end_time = time.time()

                self._execution_log.append({
                    "task_id": task_id,
                    "action": "complete",
                    "time": task.end_time,
                    "duration": task.duration,
                })

                # 记录完成时间（用于并行度调整）
                self._completion_times.append(task.end_time)

                return result

            except Exception as e:
                last_error = str(e)
                task.error = last_error

                # 判断是否可重试
                if task.retry_count < task.max_retries:
                    task.retry_count += 1
                    self._execution_log.append({
                        "task_id": task_id,
                        "action": "retry",
                        "time": time.time(),
                        "attempt": task.retry_count + 1,
                        "error": last_error,
                    })
                    continue
                else:
                    task.status = TaskStatus.FAILED
                    self._running.discard(task_id)
                    task.end_time = time.time()

                    self._execution_log.append({
                        "task_id": task_id,
                        "action": "failed",
                        "time": task.end_time,
                        "duration": task.duration,
                        "error": last_error,
                    })
                    return None

    def execute_all(
        self,
        fn: Callable[[DAGTask], Any],
        on_complete: Optional[Callable[[DAGTask], None]] = None,
    ) -> Dict[str, Any]:
        """执行DAG中所有任务（按拓扑顺序）

        Args:
            fn: 执行函数
            on_complete: 任务完成回调

        Returns:
            执行结果统计
        """
        # 执行前调整优先级
        self.adjust_dynamic_priorities()

        order = self.topological_sort()
        results: Dict[str, Any] = {}

        for task_id in order:
            task = self._tasks[task_id]

            # 跳过已完成的任务（checkpoint 恢复场景）
            if task.status == TaskStatus.COMPLETED:
                results[task_id] = task.result
                continue

            # 检查依赖
            deps_ok = all(
                self._tasks.get(dep_id, DAGTask("", "")).status == TaskStatus.COMPLETED
                for dep_id in task.dependencies
                if dep_id in self._tasks
            )

            if not deps_ok:
                task.status = TaskStatus.SKIPPED
                task.error = "Dependency failed"
                results[task_id] = None
                continue

            # 定期调整优先级
            self.adjust_dynamic_priorities()
            # 定期调整并行度
            self.adjust_parallelism()

            result = self.execute_task(task_id, fn)
            results[task_id] = result

            if on_complete and task.status == TaskStatus.COMPLETED:
                on_complete(task)

        completed = sum(1 for t in self._tasks.values() if t.status == TaskStatus.COMPLETED)
        failed = sum(1 for t in self._tasks.values() if t.status == TaskStatus.FAILED)
        skipped = sum(1 for t in self._tasks.values() if t.status == TaskStatus.SKIPPED)

        return {
            "results": results,
            "completed": completed,
            "failed": failed,
            "skipped": skipped,
            "total": len(self._tasks),
            "execution_order": order,
        }

    # ---------------------------------------------------------------
    # checkpoint / restart
    # ---------------------------------------------------------------

    def save_checkpoint(self, path: str) -> Dict[str, Any]:
        """保存当前调度状态到文件

        包含所有任务的状态、结果、执行日志等，用于断点续跑。

        Args:
            path: 保存路径

        Returns:
            保存的数据字典
        """
        checkpoint = {
            "version": 1,
            "timestamp": time.time(),
            "max_concurrent": self._max_concurrent,
            "auto_parallelism": self._auto_parallelism,
            "tasks": {},
            "execution_log": self._execution_log[-1000:],  # 保留最近1000条
        }

        for tid, task in self._tasks.items():
            checkpoint["tasks"][tid] = {
                "id": task.id,
                "name": task.name,
                "status": task.status.name,
                "result": task.result,
                "error": task.error,
                "dependencies": list(task.dependencies),
                "dependents": list(task.dependents),
                "priority": task.priority,
                "dynamic_priority": task.dynamic_priority,
                "retry_count": task.retry_count,
                "max_retries": task.max_retries,
                "start_time": task.start_time,
                "end_time": task.end_time,
                "metadata": task.metadata,
            }

        # 原子写: 先写临时文件再 os.replace, 避免进程在写 checkpoint 中途崩溃
        # (断电/异常) 时留下半截 JSON, 导致下次 load_checkpoint 解析失败、
        # 整个断点续跑(崩溃恢复)失效。replace 是原子的, 旧 checkpoint 始终完整。
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, ensure_ascii=False, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)

        return checkpoint

    def load_checkpoint(self, path: str) -> int:
        """从 checkpoint 文件恢复调度状态

        Args:
            path: checkpoint 文件路径

        Returns:
            恢复的任务数
        """
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            # 文件级损坏(磁盘比特翻转/被截断): 抛出清晰错误而非裸 JSONDecodeError,
            # 便于上层定位 checkpoint 文件而非静默吞掉。
            raise ValueError(f"checkpoint 文件 '{path}' 损坏或不可读: {e}") from e

        self._max_concurrent = data.get("max_concurrent", self._max_concurrent)
        self._auto_parallelism = data.get("auto_parallelism", self._auto_parallelism)
        self._execution_log = data.get("execution_log", [])

        valid_statuses = set(TaskStatus.__members__)
        restored = 0
        skipped = 0
        for tid, tdata in data.get("tasks", {}).items():
            # 逐任务容错: 单条任务记录损坏(未知状态/缺字段)不得中止整个断点续跑。
            # 此前 TaskStatus[tdata["status"]] 遇非法值直接抛 KeyError,
            # 导致全部进度丢失; 现降级为 PENDING(恢复后会被重试)并告警。
            if not isinstance(tdata, dict) or "id" not in tdata or "name" not in tdata:
                logger.warning("load_checkpoint: 跳过损坏的任务记录 %r", tid)
                skipped += 1
                continue
            raw_status = tdata.get("status")
            if raw_status not in valid_statuses:
                logger.warning(
                    "load_checkpoint: 任务 %r 状态 %r 非法, 降级为 PENDING", tid, raw_status
                )
                status = TaskStatus.PENDING
            else:
                status = TaskStatus[raw_status]
            task = DAGTask(
                id=tdata["id"],
                name=tdata["name"],
                status=status,
                result=tdata.get("result"),
                error=tdata.get("error"),
                dependencies=set(tdata.get("dependencies", [])),
                dependents=set(tdata.get("dependents", [])),
                priority=tdata.get("priority", 0),
                dynamic_priority=tdata.get("dynamic_priority", 0.0),
                start_time=tdata.get("start_time"),
                end_time=tdata.get("end_time"),
                retry_count=tdata.get("retry_count", 0),
                max_retries=tdata.get("max_retries", 0),
                metadata=tdata.get("metadata", {}),
            )
            self._tasks[tid] = task
            restored += 1

        if skipped:
            logger.warning("load_checkpoint: 恢复 %d 条, 跳过 %d 条损坏记录", restored, skipped)
        return restored

    def reset_failed_tasks(self) -> int:
        """将所有失败和跳过的任务重置为 PENDING

        用于 checkpoint 恢复后的重试。

        Returns:
            重置的任务数
        """
        count = 0
        for task in self._tasks.values():
            if task.status in (TaskStatus.FAILED, TaskStatus.SKIPPED):
                task.status = TaskStatus.PENDING
                task.error = None
                task.result = None
                task.start_time = None
                task.end_time = None
                count += 1
        return count

    # ---------------------------------------------------------------
    # 查询与统计
    # ---------------------------------------------------------------

    def schedule(self) -> list[dict]:
        """获取调度计划（兼容旧版接口）

        Returns:
            按拓扑序排列的任务计划
        """
        order = self.topological_sort()
        return [
            {
                "id": t,
                "data": self._tasks[t].metadata,
                "deps": list(self._tasks[t].dependencies),
            }
            for t in order
        ]

    def task_status(self) -> Dict[str, str]:
        """获取所有任务状态"""
        return {tid: task.status.name for tid, task in self._tasks.items()}

    def execution_log(self) -> List[Dict[str, Any]]:
        """获取执行日志"""
        return list(self._execution_log)

    def summary(self) -> Dict[str, Any]:
        """调度器摘要"""
        statuses = defaultdict(int)
        for task in self._tasks.values():
            statuses[task.status.name] += 1
        return {
            "total_tasks": len(self._tasks),
            "statuses": dict(statuses),
            "running": list(self._running),
            "current_parallelism": self._max_concurrent,
            "parallelism_trend": self._parallelism_trend,
        }

    def critical_path(self) -> list[str]:
        """计算关键路径

        从根节点到终点的最长路径（任务数最多）。

        Returns:
            关键路径上的任务ID列表
        """
        order = self.topological_sort()
        if not order:
            return []

        dist: Dict[str, int] = {t: 0 for t in self._tasks}
        parent: Dict[str, Optional[str]] = {t: None for t in self._tasks}

        for task_id in order:
            task = self._tasks[task_id]
            for dep_id in task.dependencies:
                if dep_id in self._tasks and dist[dep_id] + 1 > dist[task_id]:
                    dist[task_id] = dist[dep_id] + 1
                    parent[task_id] = dep_id

        # 找到终点
        end = max(dist, key=lambda t: dist[t])
        path: list[str] = []
        current: Optional[str] = end
        while current is not None:
            path.append(current)
            current = parent[current]

        return list(reversed(path))

    def get_stats(self) -> dict:
        """统计信息（兼容旧版接口）"""
        return {
            "tasks": len(self._tasks),
            "total_dependencies": sum(
                len(t.dependencies) for t in self._tasks.values()
            ),
            "running": len(self._running),
            "current_parallelism": self._max_concurrent,
        }

    def validate_dag(self) -> Tuple[bool, List[str]]:
        """验证DAG无环

        Returns:
            (是否有效, 错误列表)
        """
        errors: List[str] = []
        visited: Set[str] = set()
        rec_stack: Set[str] = set()

        def dfs(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            for dep_id in self._tasks.get(node, DAGTask("", "")).dependents:
                if dep_id in self._tasks:
                    if dep_id not in visited:
                        if dfs(dep_id):
                            return True
                    elif dep_id in rec_stack:
                        errors.append(f"Cycle detected involving {node} -> {dep_id}")
                        return True
            rec_stack.discard(node)
            return False

        for task_id in self._tasks:
            if task_id not in visited:
                dfs(task_id)

        return len(errors) == 0, errors
