"""CIPEventBus filter_fn 故障隔离测试 (cycle 16, 事件总线死角深化).

根因 (event_bus.py publish 循环): filter_fn 调用位于 try/except (包裹 handler)
之外。当某订阅者的 filter_fn 抛异常时:
  (1) 异常直接冒泡出 publish() -> 崩溃发布方 (绕过 cycle 6 为 handler 建立的
      死信/日志隔离);
  (2) 异常中断整个 fan-out for 循环 -> 该事件之后**所有其他订阅者被静默跳过**
      (隐藏真实丢失)。
这是"表面有 try/except 故障隔离、filter 路径却裸露"的薄弱点, 与 cycle 6 同一
故障隔离家族的深化。代码库当前所有 subscribe 均不传 filter_fn (grep 确认),
故为潜伏但真实的 API 契约缺陷: 一旦接入带 filter_fn 的订阅者, 其 filter 抛错
即拖垮整条事件总线。

修复: 将 filter_fn 调用包入 try/except, 异常时记 logger.error + 计入 failed +
写入 delivery_log(filter_error) + continue, 与 handler 失败同等隔离, 绝不中断
其余订阅者的派发。

本测试固化 (在 buggy 代码上必失败, 修复后全绿):
  1. filter_fn 抛异常 -> publish 不崩溃 (返回 dict); 抛错订阅者被跳过;
     其余订阅者仍被投递; failed==1 且产生 ERROR 日志; delivery_log 含 filter_error。
  2. filter_fn 返回 False -> 仅该订阅者被跳过, 其余正常投递, failed==0。
  3. filter_fn 返回 True -> 正常投递。
  4. 回归: handler 失败仍记 ERROR + 入死信 + failed 计数 (cycle 6 行为不退化)。
"""
import sys
import os
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from prometheus_nexus.collaboration.event_bus import CIPEventBus


def _find(records, level, needle):
    return [r for r in records if r.levelno == level and needle in r.getMessage()]


def test_filter_fn_exception_is_isolated_and_logged(caplog):
    """filter_fn 抛异常 -> 不崩溃发布方; 抛错订阅者跳过; 其余仍投递; 记 ERROR。

    修复前: filter_fn 异常冒泡出 publish -> 本断言 `report = bus.publish(...)`
    直接抛 RuntimeError, 测试失败 (且循环中断, 后续订阅者被静默跳过)。
    """
    bus = CIPEventBus()
    caplog.set_level(logging.DEBUG)

    bad_received = []
    good_received = []

    def bad_filter(event):
        raise ValueError("filter exploded")

    def bad_handler(event):
        bad_received.append(event)

    def good_handler(event):
        good_received.append(event)

    bus.subscribe("learn_completed", bad_handler, filter_fn=bad_filter, priority=0.9)
    bus.subscribe("learn_completed", good_handler, priority=0.1)

    report = bus.publish({
        "type": "learn_completed",
        "source": "arxiv",
        "new_nodes": 5,
    })

    # 1) publish 不崩溃, 正常返回报告
    assert isinstance(report, dict)
    # 2) 抛错订阅者被隔离跳过, 其余订阅者仍被投递
    assert not bad_received, "filter_fn 抛错的订阅者不应收到事件"
    assert len(good_received) == 1, "filter_fn 异常不得中断其余订阅者派发"
    # 3) failed 计数精确为 1 (该 filter 订阅者)
    assert report["failed"] == 1, "filter_fn 异常应计入 failed"
    assert report["delivered"] == 1
    assert bus.get_stats()["failed"] == 1
    # 4) 必须产生 ERROR 日志 (监控可见, 非静默)
    errs = _find(caplog.records, logging.ERROR, "filter_fn failed")
    assert errs, "filter_fn 异常必须产生 ERROR 日志 (修复前静默拖垮总线)"
    # 5) delivery_log 记录 filter_error 状态
    fe = [d for d in report["delivery_log"] if d.get("status") == "filter_error"]
    assert fe and len(fe) == 1


def test_filter_fn_false_skips_only_that_subscriber(caplog):
    """filter_fn 返回 False -> 仅该订阅者被跳过, 其余正常投递, failed==0。"""
    bus = CIPEventBus()
    caplog.set_level(logging.DEBUG)

    skipped = []
    delivered = []

    def false_filter(event):
        return False

    bus.subscribe("recall_completed", lambda e: skipped.append(e), filter_fn=false_filter)
    bus.subscribe("recall_completed", lambda e: delivered.append(e))

    report = bus.publish({"type": "recall_completed", "query": "q", "hits": 3})

    assert not skipped
    assert len(delivered) == 1
    assert report["delivered"] == 1
    assert report["failed"] == 0
    # 无假阳 ERROR
    assert not _find(caplog.records, logging.ERROR, "filter_fn failed")


def test_filter_fn_true_delivers(caplog):
    """filter_fn 返回 True -> 正常投递。"""
    bus = CIPEventBus()
    received = []

    def true_filter(event):
        return True

    bus.subscribe("remember_completed", lambda e: received.append(e), filter_fn=true_filter)
    report = bus.publish({"type": "remember_completed", "node_id": "n1", "utility": 0.9})

    assert len(received) == 1
    assert report["delivered"] == 1
    assert report["failed"] == 0


def test_handler_failure_visibility_preserved(caplog):
    """回归 cycle 6: handler 失败仍记 ERROR + 入死信 + failed 计数 (不退化)。"""
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

    errs = _find(caplog.records, logging.ERROR, "handler failed")
    assert errs, "handler 失败必须仍产生 ERROR 日志"
    assert report["failed"] == 1
    assert len(bus._dead_letters) == 1
    assert bus.get_stats()["failed"] == 1
