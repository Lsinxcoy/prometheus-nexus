"""Tests for Omega 核心管道 smoke(架构优化: 外置器官的回归护栏).

激进路线安全前提: 动 5333 行上帝(life.py)前, 必须先有回归基线。
本文件用真实 Omega(内存 db, 无网络/LLM) 覆盖纯本地链路:
remember → recall → maintain → status → mechanism_telemetry.

不测 LLM 管道(learn/reflect/evolve/dream)的真实输出(需模型),
仅保证本地管道闭环 + 数据一致性 — 这是外置 recall 等器官的安全网。

实例化 Omega 约 6.5s, 用 session 级 fixture 复用。
"""

from __future__ import annotations

import pytest

from prometheus_nexus.foundation.schema import ZConfig, SearchResults, NodeType
from prometheus_nexus.life import Omega


@pytest.fixture(scope="session")
def omega() -> Omega:
    o = Omega(ZConfig(database_path=":memory:"))
    yield o
    o.close()


def test_omega_instantiates(omega: Omega):
    assert omega.store is not None
    assert omega.store.get_node_count() == 0


def test_remember_writes_node(omega: Omega):
    nid = omega.remember("Prometheus is a self-evolving AI system", utility=0.8,
                         node_type=NodeType.FACT)
    assert isinstance(nid, str) and len(nid) > 0
    assert omega.store.get_node_count() >= 1


def test_recall_retrieves_written(omega: Omega):
    omega.remember("Gradient descent optimizes neural network weights", utility=0.9)
    res = omega.recall("gradient descent", limit=5)
    assert isinstance(res, SearchResults)
    # 应能检索到含相关词的节点
    texts = [h.content for h in res.hits]
    joined = " ".join(texts).lower()
    assert "gradient" in joined or len(res.hits) > 0


def test_recall_after_multiple_remembers(omega: Omega):
    for txt in [
        "The causal explainer localizes failure roots",
        "Reasoning alignment checks multi-path consistency",
        "CAMP assembles multi-agent deliberation",
    ]:
        omega.remember(txt, utility=0.7)
    res = omega.recall("causal explainer", limit=3)
    assert isinstance(res, SearchResults)


def test_maintain_returns_stats(omega: Omega):
    r = omega.maintain()
    assert isinstance(r, dict)
    # maintain 应含某种统计键
    assert len(r) > 0


def test_status_consistency(omega: Omega):
    before = omega.store.get_node_count()
    st = omega.status()
    assert st.node_count == before
    assert st.mechanisms == 127


def test_mechanism_telemetry_shape(omega: Omega):
    tel = omega.mechanism_telemetry()
    assert "total_mechanisms" in tel
    assert "mechanisms" in tel
    assert isinstance(tel["mechanisms"], list)
