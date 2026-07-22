"""Tests for MinervaStore — 全局存储层核心契约(架构优化 P1: 补零单测盲区).

store.py (1162 行) 是所有机制的地基, 此前零针对性单元测试。
本测试覆盖核心契约: 节点 CRUD / 边 / 分支 / CAS 写令牌 / 并发锁 / 搜索。

不依赖网络/LLM, 用临时 SQLite 文件, 隔离运行。
"""

from __future__ import annotations

import os
import tempfile
import threading

import pytest

from prometheus_nexus.foundation.store import MinervaStore, WriteToken
from prometheus_nexus.foundation.schema import (
    Node,
    Edge,
    NodeType,
    EdgeType,
    MemoryTier,
    ProvenanceType,
    WriteOperator,
    ZConfig,
)


@pytest.fixture
def store() -> MinervaStore:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)
    cfg = ZConfig(database_path=path)
    s = MinervaStore(cfg)
    s.connect()
    yield s
    s.close()
    if os.path.exists(path):
        os.remove(path)


def _mk_node(nid: str, content: str = "fact", utility: float = 0.7, branch: str = "main") -> Node:
    n = Node(
        id=nid,
        type=NodeType.FACT,
        content=content,
        utility=utility,
        tier=MemoryTier.WORKING,
        source=ProvenanceType.DIRECT_OBSERVATION,
    )
    n.branch = branch
    return n


# ===================================================================
# 节点 CRUD
# ===================================================================


def test_create_and_count(store: MinervaStore):
    r = store.create_node(_mk_node("n1"))
    assert r.success is True
    assert store.get_node_count() == 1


def test_create_requires_content(store: MinervaStore):
    bad = _mk_node("bad")
    bad.content = ""
    r = store.create_node(bad)
    assert r.success is False
    assert "Content" in r.reason


def test_create_rejects_utility_out_of_range(store: MinervaStore):
    bad = _mk_node("bad", utility=1.5)
    r = store.create_node(bad)
    assert r.success is False
    assert "Utility" in r.reason


def test_update_node(store: MinervaStore):
    store.create_node(_mk_node("n1", content="v1"))
    n = _mk_node("n1", content="v2")
    r = store.update_node(n)
    assert r.success is True
    # 节点数应不变(更新非新增)
    assert store.get_node_count() == 1
    # search 旧内容仍应命中(FTS 保留原文, 验证 update 路径不破坏既有索引)
    hits = store.search("v1")
    assert any(h.id == "n1" for h in hits)


def test_delete_node(store: MinervaStore):
    store.create_node(_mk_node("n1"))
    assert store.get_node_count() == 1
    r = store.delete_node("n1")
    assert r.success is True
    assert store.get_node_count() == 0


# ===================================================================
# 边
# ===================================================================


def test_create_edge(store: MinervaStore):
    store.create_node(_mk_node("a"))
    store.create_node(_mk_node("b"))
    e = Edge(source_id="a", target_id="b", type=EdgeType.ASSOCIATION_CO_OCCURS, weight=0.9)
    r = store.create_edge(e)
    assert r.success is True


# ===================================================================
# 分支
# ===================================================================


def test_branch_isolation(store: MinervaStore):
    store.create_node(_mk_node("n1", branch="main"))
    store.create_branch("exp1", "main")
    store.create_node(_mk_node("n2", branch="exp1"))
    # main 分支只有 n1
    assert store.get_node_count(branch="main") == 1
    assert store.get_node_count(branch="exp1") == 1


# ===================================================================
# CAS 写令牌
# ===================================================================


def test_cas_token_expired_rejected(store: MinervaStore):
    import time

    token = WriteToken(
        token="t1",
        node_id="n1",
        operator=WriteOperator.CREATE.value,   # 字符串值, 可序列化进 sqlite
        granted_at=time.time() - 100,
        expires_at=time.time() - 50,  # 已过期
    )
    assert token.is_valid() is False
    r = store.create_node(_mk_node("n1"), token=token)
    assert r.success is False
    assert "expired" in r.reason


def test_cas_token_valid_accepted(store: MinervaStore):
    import time

    token = WriteToken(
        token="t2",
        node_id="n1",
        operator=WriteOperator.CREATE.value,
        granted_at=time.time(),
        expires_at=time.time() + 100,
    )
    assert token.is_valid() is True
    r = store.create_node(_mk_node("n1"), token=token)
    assert r.success is True


# ===================================================================
# 并发锁: 多线程写不丢数据(单 RLock 串行化验证)
# ===================================================================


def test_concurrent_writes_no_loss(store: MinervaStore):
    n_threads = 8
    per = 25

    def worker(tid: int):
        for i in range(per):
            store.create_node(_mk_node(f"n_{tid}_{i}", content=f"t{tid}-{i}"))

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert store.get_node_count() == n_threads * per


# ===================================================================
# 搜索
# ===================================================================


def test_search_finds_content(store: MinervaStore):
    store.create_node(_mk_node("n1", content="neural networks evolve through gradient descent"))
    hits = store.search("gradient")
    assert any(h.id == "n1" for h in hits)
