"""Tests for CNS/cerebral_cortex — 生命周期神经系统核心契约(架构优化 P1: 补零单测盲区).

cns_orchestrator.py (603行) / cerebral_cortex.py (656行) 此前零针对性单元测试。
两者 __init__ 仅存 omega 引用(不访问其属性), 用 stub(object()) 即可独立实例化。

覆盖: CNS 阈值调整/状态机/去重间隔; CerebralCortex 知识缺口记录/去重/抑制判定。
"""

from __future__ import annotations

import time

import pytest

from prometheus_nexus.lifecycle.cns_orchestrator import CNSOrchestrator
from prometheus_nexus.lifecycle.cerebral_cortex import CerebralCortex


@pytest.fixture
def cns() -> CNSOrchestrator:
    return CNSOrchestrator(object())


@pytest.fixture
def cortex() -> CerebralCortex:
    return CerebralCortex(object())


# ===================================================================
# CNS
# ===================================================================


def test_cns_initial_state(cns: CNSOrchestrator):
    state = cns.get_state()
    assert state["state"] == "IDLE"
    assert "thresholds" in state


def test_cns_update_threshold(cns: CNSOrchestrator):
    ok = cns.update_threshold("reflect_to_evolve_max_score", 0.3)
    assert ok is True
    assert cns._thresholds["reflect_to_evolve_max_score"] == 0.3


def test_cns_update_threshold_unknown_key(cns: CNSOrchestrator):
    ok = cns.update_threshold("nonexistent_key", 0.5)
    assert ok is False


def test_cns_can_trigger_first_time(cns: CNSOrchestrator):
    # stub omega 无 signal_fusion/cerebral_cortex → 无抑制 → 首次可触发
    assert cns._can_trigger("reflect") is True


def test_cns_can_trigger_respects_min_interval(cns: CNSOrchestrator):
    assert cns._can_trigger("reflect") is True
    # 模拟刚触发过(记录时间), 间隔 30s 未到 → 不可再触发
    cns._last_trigger_time["reflect"] = time.time()
    assert cns._can_trigger("reflect") is False


def test_cns_can_trigger_depth_limit(cns: CNSOrchestrator):
    cns._auto_chain_depth = cns._MAX_AUTO_DEPTH
    assert cns._can_trigger("evolve") is False


# ===================================================================
# CerebralCortex
# ===================================================================


def test_cortex_record_and_count_gap(cortex: CerebralCortex):
    cortex.record_gap("what is X")
    assert cortex.get_gap_count("what is X") == 1
    cortex.record_gap("what is X")
    assert cortex.get_gap_count("what is X") == 2


def test_cortex_is_duplicate_respects_interval(cortex: CerebralCortex):
    assert cortex.is_duplicate("dream", min_interval=30.0) is False
    assert cortex.is_duplicate("dream", min_interval=30.0) is True


def test_cortex_suppress_trigger(cortex: CerebralCortex):
    # 默认未抑制
    assert cortex.should_suppress_trigger("evolve") is False


def test_cortex_get_insights_shape(cortex: CerebralCortex):
    cortex.record_gap("how does Y work")
    insights = cortex.get_insights()
    assert "knowledge_gaps" in insights
    assert "how does Y work" in insights["knowledge_gaps"]
