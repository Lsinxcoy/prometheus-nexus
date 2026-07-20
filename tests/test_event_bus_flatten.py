"""CIPEventBus 防腐回归测试。

背景 (A1 教训): 部分 publish 误将业务字段嵌套进二级
{"type": "x_completed", "data": {"field": v}} —— 总线会把整个
event 包进 enriched_event["data"], 导致 Telemetry/订阅者从
event.data.field 读取时落到 event.data.data.field (静默 None)。
本测试固化: 总线必须在入口自动扁平化二级 data, 使
两种写法 (字段在顶层 / 嵌套 data) 都能被订阅者正确解析。
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from prometheus_nexus.collaboration.event_bus import CIPEventBus


def test_flatten_nested_data_normalizes_to_top_level():
    """嵌套 data 写法 → 总线自动提升字段到顶层, 订阅者拿到顶层字段。"""
    bus = CIPEventBus()
    received = []
    bus.subscribe("rumination_completed", lambda e: received.append(e))

    # 错误嵌套写法 (今天 Task1 初版踩的坑)
    bus.publish({
        "type": "rumination_completed",
        "data": {
            "total_scanned": 80,
            "relearned": 80,
            "utility_raised": 76,
        },
    })

    assert len(received) == 1
    ev = received[0]
    # 总线包层后, 顶层字段应在 event["data"] 里直接可读
    assert ev["data"].get("total_scanned") == 80
    assert ev["data"].get("relearned") == 80
    assert ev["data"].get("utility_raised") == 76


def test_top_level_fields_untouched():
    """正确写法 (字段已在顶层) 不应被扁平化破坏。"""
    bus = CIPEventBus()
    received = []
    bus.subscribe("learn_completed", lambda e: received.append(e))

    bus.publish({
        "type": "learn_completed",
        "source": "arxiv",
        "query": "test",
        "new_nodes": 12,
    })

    assert len(received) == 1
    ev = received[0]
    assert ev["data"].get("source") == "arxiv"
    assert ev["data"].get("query") == "test"
    assert ev["data"].get("new_nodes") == 12


def test_bus_ignores_extra_top_keys_no_flatten():
    """当 event 含其他业务键 (如 node_id) 时, 不应误扁平化。"""
    bus = CIPEventBus()
    received = []
    bus.subscribe("remember_completed", lambda e: received.append(e))

    bus.publish({
        "type": "remember_completed",
        "node_id": "n_123",
        "utility": 0.9,
    })

    assert len(received) == 1
    ev = received[0]
    assert ev["data"].get("node_id") == "n_123"
    assert ev["data"].get("utility") == 0.9
    # 不应把 node_id 当成二级 data 去展开
    assert "data" not in ev["data"]
