"""cycle10: ParallelDispatcher 并发数据安全(batch_id 唯一 + 派发日志不丢)。

根因: parallel_dispatcher.py 的 dispatch() 对共享可变状态 self._batch_counter(自增)
与 self._dispatches(append) 无任何锁保护。ParallelDispatcher 是 Omega 上的共享单例
(life.py:478 self.parallel_dispatcher = ParallelDispatcher()), 经 API server 的
uvicorn 线程池(life.py:2985 调用 dispatch)可在并发请求下被同时进入 -> 非原子 += 丢失
更新 -> batch_id 碰撞; _dispatches.append 在并发写入路径下也属无保护共享。
表面单线程测试全绿, 隐藏真实并发弱点。

修复: 引入 threading.Lock, 仅保护两个极小临界区(计数自增 + 派发日志追加)与 get_stats
读, 不锁住线程池执行区间, 保持并行度。

验证策略(声称即验证, 确定性而非靠运气):
CPython GIL 在常规负载下会隐式串行化 `self._batch_counter += 1`, 使无锁丢失更新极难
复现(已实测 128 线程 × 20 轮零碰撞) —— 这正是它被隐藏的原因。为确定性复现, 本测试用
_YieldInt 替换共享计数: 在 `+=` 的"读-改-写"之间强制释放 GIL(time.sleep), 直接命中临界
窗口。无锁时两线程读到同一旧值 -> batch_id 碰撞(断言失败); 加锁后临界区被串行化 -> 唯一。
"""
import os
import sys as _sys
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from prometheus_nexus.loop.parallel_dispatcher import ParallelDispatcher


class _YieldInt:
    """测试用共享计数: 在 += 的读-改-写之间强制释放 GIL, 使无锁自增的丢失更新确定性复现。

    关键: 先捕获旧值 old=self.v, 再 sleep 释放 GIL, 再 self.v = old + other。
    这样并发线程若在其 sleep 期间也进入, 会读到同一个 old -> 双双写回相同结果 -> 碰撞。
    """

    def __init__(self, v: int = 0):
        self.v = v

    def __iadd__(self, other: int) -> "_YieldInt":
        old = self.v
        time.sleep(0.001)  # 强制 GIL 释放, 让并发线程插入读-改-写窗口
        self.v = old + other
        return self

    def __int__(self) -> int:
        return self.v

    def __repr__(self) -> str:
        return f"_YieldInt({self.v})"


def _run_two_concurrent_dispatches(d: ParallelDispatcher):
    """两线程经 barrier 同步后几乎同时进入 dispatch 的计数临界区, 收集各自 batch_id。"""
    results: list[str] = []
    barrier = threading.Barrier(2)
    lock = threading.Lock()

    def worker():
        barrier.wait()
        r = d.dispatch([{"description": "t"}])
        with lock:
            results.append(r.batch_id)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def test_concurrent_lost_update_deterministic():
    """无锁自增丢失更新(确定性复现): 修复前此测试必失败, 修复后必通过。

    _YieldInt 在 += 期间释放 GIL, 直接命中读-改-写窗口。无锁时两线程读到同一旧值 ->
    batch_id 碰撞(>1 线程拿到相同 id); 加锁后临界区串行化 -> 全部唯一。
    """
    d = ParallelDispatcher(max_concurrent=4)
    d._batch_counter = _YieldInt(0)  # 替换共享计数, 注入确定性 GIL 释放点
    ids = _run_two_concurrent_dispatches(d)
    assert len(ids) == 2
    assert len(set(ids)) == 2, f"无锁自增丢失更新导致 batch_id 碰撞: {ids}"
    assert d.get_stats()["dispatches"] == 2


def test_concurrent_stress_under_load():
    """重压并发(许多线程)下: batch_id 全唯一且 get_stats 计数准确(修复后必过, 验证无死锁/无丢失)。"""
    d = ParallelDispatcher(max_concurrent=8)
    n = 64

    def run_round():
        results: list[str] = []
        barrier = threading.Barrier(n)
        lock = threading.Lock()

        def worker():
            barrier.wait()
            r = d.dispatch([{"description": "t"}])
            with lock:
                results.append(r.batch_id)

        threads = [threading.Thread(target=worker) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return results

    total = 0
    for _ in range(5):
        ids = run_round()
        total += n
        assert len(ids) == n
        assert len(set(ids)) == n, f"并发派发 batch_id 碰撞: {sorted(ids)}"
    assert d.get_stats()["dispatches"] == total


def test_sequential_batch_ids_increasing_and_counted():
    """顺序派发基本契约(确定性, 修复前后都应通过): id 唯一且严格递增, 计数准确。"""
    d = ParallelDispatcher()
    prev = -1
    for i in range(20):
        r = d.dispatch([{"description": f"task-{i}"}])
        num = int(r.batch_id.split("_")[-1])
        assert num > prev, f"batch_id 未严格递增: {r.batch_id}"
        prev = num
    assert d.get_stats()["dispatches"] == 20
