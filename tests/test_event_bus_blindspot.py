"""CIPEventBus 事件总线死角修复回归测试 (cycle 6).

根因: event_bus.py 的 publish() 在订阅者处理器抛异常时, 仅把失败静默记入
_dead_letters 且从不写日志 (logger 定义了却从未使用); 死信队列溢出时还静默
丢弃旧的死信。结果: capability_consumed / *_completed 等关键生命周期事件
的订阅者一旦失败, 系统"表面正常" (publish 不抛错、返回报告) 却无人知晓 ——
典型的事件总线监控死角。

修复: 处理失败时记 logger.error; 死信溢出丢弃时记 logger.warning 并保留
最近的 dead_letter_limit 条 (原实现只保留一半且零日志)。

本测试固化:
  1. 订阅者失败 -> 必须产生 ERROR 日志 + 计入 failed + 入死信队列
  2. 单个订阅者失败不阻断其他订阅者 (隔离性)
  3. 正常投递不产生 handler-failed 的 ERROR 日志 (无假阳)
  4. 死信溢出 -> 必须产生 WARNING 日志且队列长度收敛到 dead_letter_limit
"""
import sys
import os
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from prometheus_nexus.collaboration.event_bus import CIPEventBus


def _find(records, level, needle):
    return [
        r for r in records
        if r.levelno == level and needle in r.getMessage()
    ]


def test_handler_failure_is_logged_error_and_recorded(caplog):
    """订阅者抛异常 -> ERROR 日志 + failed=1 + 入死信队列 (不再静默)。"""
    bus = CIPEventBus()
    caplog.set_level(logging.DEBUG)

    def boom(event):
        raise RuntimeError("subscriber exploded")

    bus.subscribe("evolve_completed", boom)

    report = bus.publish({
        "type": "evolve_completed",
        "fitness_before": 0.1,
        "fitness_after": 0.2,
        "result": "SUCCESS",
        "strategy": "gepa",
    })

    # 不再静默: 必须有 ERROR 日志
    errs = _find(caplog.records, logging.ERROR, "handler failed")
    assert errs, "订阅者失败必须产生 ERROR 日志 (修复前此处为静默死角)"
    assert "evolve_completed" in errs[0].getMessage()

    # 计数与死信落地 (原本只有这俩, 但无日志 -> 监控盲区)
    assert report["failed"] == 1
    assert report["delivered"] == 0
    assert len(bus._dead_letters) == 1
    assert bus.get_stats()["failed"] == 1


def test_failed_handler_does_not_block_other_subscribers(caplog):
    """单个订阅者失败不能阻断其余订阅者, 且失败被记录日志。"""
    bus = CIPEventBus()
    caplog.set_level(logging.DEBUG)

    received = []

    def boom(event):
        raise ValueError("nope")

    def ok(event):
        received.append(event)

    bus.subscribe("learn_completed", boom, priority=0.9)
    bus.subscribe("learn_completed", ok, priority=0.1)

    report = bus.publish({
        "type": "learn_completed",
        "source": "arxiv",
        "new_nodes": 5,
    })

    # 隔离性: 第二个订阅者仍被投递
    assert len(received) == 1, "失败订阅者不应阻断其他订阅者"
    assert report["delivered"] == 1
    assert report["failed"] == 1

    errs = _find(caplog.records, logging.ERROR, "handler failed")
    assert errs and len(errs) == 1, "恰好一次 ERROR (对应唯一失败订阅者)"


def test_successful_delivery_no_false_error_log(caplog):
    """正常投递不应产生 handler-failed 的 ERROR 日志 (无假阳)。"""
    bus = CIPEventBus()
    caplog.set_level(logging.DEBUG)

    received = []
    bus.subscribe("remember_completed", lambda e: received.append(e))
    bus.publish({"type": "remember_completed", "node_id": "n1", "utility": 0.9})

    assert len(received) == 1
    errs = _find(caplog.records, logging.ERROR, "handler failed")
    assert not errs, "正常投递不应产生 handler-failed ERROR 日志"


def test_dead_letter_overflow_logs_warning_and_keeps_limit(caplog):
    """死信溢出 -> 必须 WARNING 日志, 且队列长度收敛到 dead_letter_limit
    (原实现只保留一半且零日志, 等于无声丢失一半死信)。"""
    bus = CIPEventBus(dead_letter_limit=3)
    caplog.set_level(logging.DEBUG)

    def boom(event):
        raise RuntimeError("x")

    bus.subscribe("recall_completed", boom)

    # 连续触发 6 次失败, 超出 dead_letter_limit=3
    for _ in range(6):
        bus.publish({"type": "recall_completed", "hits": 0})

    warns = _find(caplog.records, logging.WARNING, "dead-letter queue exceeded")
    assert warns, "死信溢出必须产生 WARNING 日志 (修复前静默丢弃)"
    assert "dropped" in warns[0].getMessage()

    # 队列长度必须收敛到上限, 而非原实现的一半
    assert len(bus._dead_letters) == bus._dead_letter_limit, (
        "死信队列应保留最近的 dead_letter_limit 条"
    )
    assert bus.get_stats()["dead_letters"] == bus._dead_letter_limit
