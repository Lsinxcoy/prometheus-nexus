"""Tests for mechanisms.retrieval.annotate_trust — 从 life.py 外置的信任感知器官.

验证意图(纯逻辑, 无需实例化 Omega):
1. trust_state 标注: has/not_has/uncertain/unknown 正确写入 hit.metadata
2. 降权: not_has ×0.3, uncertain ×0.7, has 不变
3. 排序截断: 按 score 降序取 limit
4. trust_metadata 统计正确
5. 外置验收: Omega._recall_with_trust 委托 annotate_trust(行为一致)
"""

from __future__ import annotations

from types import SimpleNamespace
from dataclasses import dataclass, field

import pytest

from prometheus_nexus.mechanisms.retrieval import annotate_trust
from prometheus_nexus.foundation.schema import SearchHit, Node, SearchResults, ZConfig, NodeType
from prometheus_nexus.life import Omega


# --- 构造辅助 ---


def _hit(node_id: str, score: float) -> SearchHit:
    return SearchHit(node_id=node_id, score=score, content=f"c-{node_id}")


def _node(trust: str) -> Node:
    return Node(id="x", content="x", trust_state=trust)


class _FakeStore:
    """按 node_id 后缀映射 trust_state 的内存 fake store."""

    def __init__(self, mapping: dict[str, str]):
        self._m = mapping

    def read_node(self, node_id: str) -> Node | None:
        if node_id not in self._m:
            return None
        return _node(self._m[node_id])


def test_annotate_labels_trust_states():
    store = _FakeStore({"a": "has", "b": "not_has", "c": "uncertain", "d": "unknown"})
    hits = [_hit("a", 1.0), _hit("b", 1.0), _hit("c", 1.0), _hit("d", 1.0)]
    out, meta = annotate_trust(hits, store, limit=10)
    labels = {h.node_id: h.metadata["trust_state"] for h in out}
    assert labels == {"a": "has", "b": "not_has", "c": "uncertain", "d": "unknown"}
    assert meta == {"has": 1, "not_has": 1, "uncertain": 1, "unknown": 1}


def test_annotate_downweights():
    store = _FakeStore({"b": "not_has", "c": "uncertain", "a": "has"})
    hits = [_hit("b", 1.0), _hit("c", 1.0), _hit("a", 1.0)]
    out, _ = annotate_trust(hits, store, limit=10)
    by_id = {h.node_id: h for h in out}
    assert by_id["b"].score == 0.3       # not_has × 0.3
    assert by_id["b"].metadata["suppressed"] is True
    assert by_id["c"].score == 0.7       # uncertain × 0.7
    assert by_id["c"].metadata["unverified"] is True
    assert by_id["a"].score == 1.0       # has 不变


def test_annotate_sorts_and_truncates():
    store = _FakeStore({"a": "has", "b": "has", "c": "has", "d": "has", "e": "has"})
    # 乱序分数
    hits = [_hit("a", 0.2), _hit("b", 0.9), _hit("c", 0.5), _hit("d", 0.7), _hit("e", 0.1)]
    out, _ = annotate_trust(hits, store, limit=3)
    scores = [h.score for h in out]
    assert scores == [0.9, 0.7, 0.5]   # 降序截断 3
    assert len(out) == 3


def test_annotate_handles_missing_node_as_unknown():
    store = _FakeStore({})  # 所有 node_id 都 missing
    hits = [_hit("z1", 0.5), _hit("z2", 0.8)]
    out, meta = annotate_trust(hits, store, limit=10)
    assert all(h.metadata["trust_state"] == "unknown" for h in out)
    assert meta["unknown"] == 2


# === 外置验收: Omega._recall_with_trust 委托 annotate_trust ===


@pytest.fixture(scope="session")
def omega() -> Omega:
    o = Omega(ZConfig(database_path=":memory:"))
    yield o
    o.close()


def test_omega_recall_with_trust_runs(omega: Omega):
    # 写入带信任态的节点 → 经 recall_with_trust 应产出带 trust_state 标注的结果
    omega.remember("Quantum entanglement links particles", utility=0.9,
                   node_type=NodeType.FACT)
    res = omega._recall_with_trust("quantum entanglement", limit=5)
    assert isinstance(res, SearchResults)
    # 标注应存在于 metadata
    assert "trust_state_counts" in res.metadata
