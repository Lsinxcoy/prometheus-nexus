"""ParallelDispatcher — Concurrent subagent workflow dispatch.

Based on: obra/superpowers dispatching-parallel-agents skill
Key insight: Run independent tasks concurrently, then merge results.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field


@dataclass
class SubagentTask:
    task_id: str = ""
    description: str = ""
    status: str = "pending"  # pending, running, complete, failed
    result: dict = field(default_factory=dict)
    start_time: float = 0.0
    end_time: float = 0.0
    duration_ms: float = 0.0
    error: str = ""


@dataclass
class DispatchResult:
    batch_id: str = ""
    tasks: list[SubagentTask] = field(default_factory=list)
    completed: int = 0
    failed: int = 0
    total_duration_ms: float = 0.0
    merged_results: dict = field(default_factory=dict)


class ParallelDispatcher:
    """Concurrent subagent workflow dispatcher with real thread pool.

    Based on Superpowers dispatching-parallel-agents skill:
    1. Identify independent tasks that can run in parallel
    2. Dispatch each to a thread pool worker
    3. Collect results as they complete
    4. Merge and validate
    """

    def __init__(self, max_concurrent: int = 4):
        self._max_concurrent = max_concurrent
        self._dispatches: list[dict] = []
        self._batch_counter = 0
        # 保护共享可变状态(_batch_counter 自增 与 _dispatches 追加)在并发
        # dispatch 下不丢更新/不丢条。ParallelDispatcher 是 Omega 共享单例,
        # 经 uvicorn 线程池可被并发进入, 无锁会导致 batch_id 碰撞、派发日志丢失。
        # 仅锁住极小临界区, 不锁线程池执行区间, 保持并行度。
        self._lock = threading.Lock()

    def dispatch(self, tasks: list[dict], batch_id: str = "",
                 task_handler=None) -> DispatchResult:
        if not batch_id:
            with self._lock:
                self._batch_counter += 1
                batch_id = "batch_%d" % self._batch_counter

        start_time = time.time()
        result = DispatchResult(batch_id=batch_id)

        subagent_tasks = []
        for i, task in enumerate(tasks):
            st = SubagentTask(
                task_id="%s_task_%d" % (batch_id, i),
                description=task.get("description", "task_%d" % i),
                status="running",
                start_time=time.time(),
            )
            subagent_tasks.append(st)

        if task_handler:
            with ThreadPoolExecutor(max_workers=self._max_concurrent) as executor:
                future_to_task = {}
                for st in subagent_tasks:
                    future = executor.submit(task_handler, st.description)
                    future_to_task[future] = st

                for future in as_completed(future_to_task):
                    st = future_to_task[future]
                    st.end_time = time.time()
                    st.duration_ms = (st.end_time - st.start_time) * 1000
                    try:
                        st.result = future.result()
                        st.status = "complete"
                        result.completed += 1
                    except Exception as e:
                        st.status = "failed"
                        st.error = str(e)
                        result.failed += 1
        else:
            for st in subagent_tasks:
                st.end_time = time.time()
                st.duration_ms = (st.end_time - st.start_time) * 1000
                st.result = {"success": True, "task": st.description}
                st.status = "complete"
                result.completed += 1

        result.tasks = subagent_tasks
        result.total_duration_ms = (time.time() - start_time) * 1000
        result.merged_results = self._merge_results(subagent_tasks)

        with self._lock:
            self._dispatches.append({
                "batch_id": batch_id,
                "tasks": len(subagent_tasks),
                "completed": result.completed,
                "failed": result.failed,
            })

        return result

    def _merge_results(self, tasks: list[SubagentTask]) -> dict:
        merged = {
            "total_tasks": len(tasks),
            "successful": sum(1 for t in tasks if t.status == "complete"),
            "failed": sum(1 for t in tasks if t.status == "failed"),
            "results": [t.result for t in tasks if t.status == "complete"],
            "errors": [t.error for t in tasks if t.status == "failed" and t.error],
        }
        return merged

    def get_stats(self) -> dict:
        with self._lock:
            return {"dispatches": len(self._dispatches)}
