"""并发安全测试: FailureLogTracker / NodeFeedbackTracker 共享单例锁.

背景: omega.failure_log 是进程级单例 (life.py:356), 同时被主循环
(life.py remember 路径 12+ 处调用 failure_log.log) 与 uvicorn 线程池
(POST /api/v1/remember -> omega.remember -> failure_log.log) 并发写入。
原实现零锁, 非原子 Counter += 与 list append/truncate 在并发下丢更新、
get_action_failure_rates 跨引用不一致。修复: 引入 RLock 串行化。

测试策略: 用 YieldCounter 在 += 的读-改-写之间强制释放 GIL, 配合
threading.Barrier 让两个写线程精确重叠, 使丢更新确定性复现 (修复前必失败)。
"""
import sys
import time
import threading
from collections import Counter

sys.path.insert(0, "src")

from prometheus_nexus.memory.feedback import (
    FailureLogTracker,
    NodeFeedbackTracker,
    FailureRecord,
)


class YieldCounter(Counter):
    """在 __getitem__/__setitem__ 处强制释放 GIL, 放大 read-modify-write 窗口。"""

    def __getitem__(self, k):
        time.sleep(0)  # 释放 GIL, 允许另一线程插入
        return super().__getitem__(k)

    def __setitem__(self, k, v):
        time.sleep(0)
        return super().__setitem__(k, v)


def _install_yield_counters(tracker: FailureLogTracker):
    tracker._action_counts = YieldCounter()
    tracker._error_patterns = YieldCounter()
    tracker._severity_counts = YieldCounter()


def test_failure_log_concurrent_log_no_lost_updates():
    """2 写线程并发 log 同一 action: 修复前 Counter += 丢更新, 修复后精确。"""
    t = FailureLogTracker()
    _install_yield_counters(t)
    N = 200
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        for i in range(N):
            t.log("remember", f"err-{i}")

    a = threading.Thread(target=worker)
    b = threading.Thread(target=worker)
    a.start(); b.start()
    a.join(); b.join()

    # 关键不变量: 每条 log 的 action_counts['remember'] +1, 共 2*N 次。
    assert t._action_counts["remember"] == 2 * N, (
        f"lost-update race: action_counts['remember']="
        f"{t._action_counts['remember']} != {2 * N}"
    )
    stats = t.get_stats()
    assert stats["total_failures"] == 2 * N
    assert stats["unique_actions"] == 1


def test_failure_log_reader_writer_no_iteration_crash():
    """读线程迭代 get_action_failure_rates 同时写线程新增 action key: 修复前
    RuntimeError(dictionary changed size during iteration), 修复后安全。"""
    t = FailureLogTracker()
    _install_yield_counters(t)
    reader_crashed = []
    stop = threading.Event()
    barrier = threading.Barrier(2)

    def reader():
        barrier.wait()
        while not stop.is_set():
            try:
                t.get_action_failure_rates()
                t.get_stats()
            except RuntimeError:
                reader_crashed.append(True)
                break

    def writer():
        barrier.wait()
        for i in range(2000):
            # 每次新 action key -> 改变 _action_counts 字典大小, 制造迭代崩溃
            t.log(f"act-{i % 7}", f"err-{i}")

    r = threading.Thread(target=reader)
    w = threading.Thread(target=writer)
    r.start(); w.start()
    w.join()
    stop.set()
    r.join(timeout=5)

    assert not reader_crashed, (
        f"reader crashed during concurrent iteration (race): {reader_crashed}"
    )


def test_failure_log_single_thread_behavior_intact():
    """锁不应改变单线程语义。"""
    t = FailureLogTracker()
    t.log("remember", "guardrail_blocked", severity="high")
    t.log("remember", "five_gate_blocked", severity="medium")
    t.log("recall", "index_corruption", severity="critical")
    assert t.get_stats()["total_failures"] == 3
    assert t.get_stats()["unique_actions"] == 2
    assert t.get_severity_distribution() == {"high": 1, "medium": 1, "critical": 1}
    assert "remember" in t.get_avoidance_list(top_k=10)
    rates = t.get_action_failure_rates()
    assert rates["remember"]["count"] == 2
    assert rates["remember"]["severities"]["high"] == 1


def test_node_feedback_concurrent_record_no_lost_updates():
    """NodeFeedbackTracker.record 同样并发安全 (与主循环/API 线程同源风险)。"""
    t = NodeFeedbackTracker(max_per_node=500)  # 避免截断干扰并发计数验证
    N = 200
    barrier = threading.Barrier(2)

    def worker(tag):
        barrier.wait()
        for i in range(N):
            t.record(f"node-{tag}", "utility", 0.5 + i * 0.001)

    a = threading.Thread(target=worker, args=("a",))
    b = threading.Thread(target=worker, args=("b",))
    a.start(); b.start()
    a.join(); b.join()

    assert t._type_counts["utility"] == 2 * N
    assert t.get_stats()["total_feedbacks"] == 2 * N
    assert t.get_stats()["nodes_tracked"] == 2


def test_node_feedback_recursive_lock_no_deadlock():
    """get_worst_performers 内部重入 get_average/get_feedback_count (RLock)。"""
    t = NodeFeedbackTracker()
    for i in range(20):
        t.record(f"node-{i}", "utility", 0.1 * i)
    # 若误用 Lock 而非 RLock, 此处会死锁; RLock 正常返回。
    worst = t.get_worst_performers(top_k=5)
    best = t.get_best_performers(top_k=5)
    assert len(worst) == 5 and len(best) == 5
    assert worst[0]["node_id"] == "node-0"
    assert best[0]["node_id"] == "node-19"
