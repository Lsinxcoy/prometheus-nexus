"""Tests for harness 模块 — 关键纯逻辑契约(架构优化 P1: 补零单测盲区).

harness/active_compressor.py (1126行) / tool_tax_gate.py (853行) /
tiered_router.py (821行) 此前零针对性单元测试。本测试覆盖其核心纯逻辑:
- SawToothDetector: 锯齿模式识别
- SlimeMoldExplorer: 信息密度估算
- TaskClassifier: 任务分层级
- SemanticNoiseEstimator: 语义噪声评分
- GainEstimator: 噪声下有效增益衰减 (G-STEP)

均为轻量类, 独立运行, 不依赖 omega/store。
"""

from __future__ import annotations

import pytest

from prometheus_nexus.harness.active_compressor import (
    SawToothDetector,
    SlimeMoldExplorer,
)
from prometheus_nexus.harness.tiered_router import TaskClassifier
from prometheus_nexus.harness.tool_tax_gate import (
    SemanticNoiseEstimator,
    GainEstimator,
)


# ===================================================================
# SawToothDetector
# ===================================================================


def test_sawtooth_insufficient_data():
    d = SawToothDetector(window_size=10)
    d.record(100)
    d.record(120)
    res = d.detect_saw_tooth()
    assert res["pattern_type"] == "unknown"
    assert res["pattern_detected"] is False


def test_sawtooth_detects_pattern():
    d = SawToothDetector(window_size=20)
    # 上升-压缩-上升 锯齿: 100,200,300, (compress) 100, 250, 400
    for t in [100, 200, 300, 100, 250, 400]:
        d.record(t)
    d.record_compress(300, 100)
    res = d.detect_saw_tooth()
    assert res["pattern_detected"] is True
    assert res["pattern_type"] == "saw_tooth"
    assert res["peak_tokens"] >= 400


def test_sawtooth_monotonic_up():
    d = SawToothDetector(window_size=20)
    for t in [100, 150, 200, 250, 300]:
        d.record(t)
    res = d.detect_saw_tooth()
    # 持续上升 → 识别为 monotonic_up (需压缩信号), 属已识别模式
    assert res["pattern_detected"] is True
    assert res["pattern_type"] == "monotonic_up"


# ===================================================================
# SlimeMoldExplorer
# ===================================================================


def test_information_density_empty():
    e = SlimeMoldExplorer()
    assert e.estimate_information_density("") == 0.0
    assert e.estimate_information_density("ab") == 0.0  # <5 chars


def test_information_density_high_for_technical():
    e = SlimeMoldExplorer()
    text = "The API endpoint calls the database function to compute the model parameter and validate the response token"
    density = e.estimate_information_density(text)
    assert 0.0 <= density <= 1.0
    assert density > 0.0


# ===================================================================
# TaskClassifier
# ===================================================================


def test_classify_returns_tier():
    c = TaskClassifier()
    res = c.classify("Write a function to sort a list")
    assert "tier" in res
    assert "tier_index" in res
    assert "confidence" in res
    assert 0.0 <= res["confidence"] <= 1.0


def test_classify_batch_consistent():
    c = TaskClassifier()
    tasks = ["run a query", "design a multi-stage pipeline with review"]
    results = c.classify_batch(tasks)
    assert len(results) == 2
    for r in results:
        assert "tier" in r


# ===================================================================
# SemanticNoiseEstimator
# ===================================================================


def test_noise_estimate_shape():
    est = SemanticNoiseEstimator()
    res = est.estimate("The system configuration requires careful parameter tuning")
    assert "noise_score" in res
    assert 0.0 <= res["noise_score"] <= 1.0


# ===================================================================
# GainEstimator (G-STEP 噪声衰减)
# ===================================================================


def test_gain_without_noise_full_base():
    g = GainEstimator()
    res = g.estimate("complex data analysis task", tool_info={"gain": 0.7})
    assert res["base_gain"] == 0.7
    # 无噪声 → 有效增益 == 基础增益
    assert res["effective_gain"] == res["base_gain"]
    assert res["noise_penalty"] == 0.0


def test_gain_with_noise_reduces_effective():
    g = GainEstimator()
    base = g.estimate("complex data analysis task", tool_info={"gain": 0.7})
    noisy = g.estimate(
        "complex data analysis task", tool_info={"gain": 0.7},
        noise_result={"noise_score": 0.9},
    )
    # 噪声下有效增益应低于基础增益
    assert noisy["effective_gain"] < base["base_gain"]
    assert noisy["noise_penalty"] > 0.0
