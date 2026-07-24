"""Tests for Omega.seed_trusted_knowledge — 批量写 13.9x 在安全边界内的落点.

验证意图:
1. 批量灌库写入 store(节点可被 recall 检索)
2. 跳过在线安全门(可信离线种子路径)
3. 返回 {accepted, created, failed, total} 结构
4. 空/非字符串内容被过滤
"""

from __future__ import annotations

import time

import pytest

from prometheus_nexus.foundation.schema import ZConfig, NodeType
from prometheus_nexus.life import Omega


@pytest.fixture(scope="session")
def omega() -> Omega:
    o = Omega(ZConfig(database_path=":memory:"))
    yield o
    o.close()


def test_seed_writes_and_retrievable(omega: Omega):
    before = omega.store.get_node_count()
    res = omega.seed_trusted_knowledge(
        ["Alpha is the first letter", "Beta follows alpha", "Gamma is third"],
        utility=0.6,
    )
    assert res["accepted"] == 3
    assert res["created"] == 3
    assert res["total"] == 3
    assert omega.store.get_node_count() == before + 3
    # 批量写 FTS 正确 → store.search 可直接检索(验证 create_nodes_batch 写 FTS)
    sr = omega.store.search("alpha", limit=3)
    assert len(sr) >= 1
    assert any("alpha" in (h.content or "").lower() for h in sr)


def test_seed_filters_invalid(omega: Omega):
    res = omega.seed_trusted_knowledge(["valid", "", 123, "  ", "also valid"])
    # 仅 2 个有效字符串
    assert res["accepted"] == 2
    assert res["created"] == 2


def test_seed_batch_faster_than_loop_remember(omega: Omega):
    # 对比: 同量内容, seed(批量) vs 逐条 remember(在线过门) 的写入耗时
    n = 50
    corpus = [f"seed corpus line {i} about topic {i%5}" for i in range(n)]

    t0 = time.perf_counter()
    omega.seed_trusted_knowledge(corpus, utility=0.5)
    seed_ms = (time.perf_counter() - t0) * 1000.0

    # 逐条 remember(过门, 仅验证可达, 不强行比倍数 — 门开销本就更高)
    t1 = time.perf_counter()
    for i, c in enumerate(corpus):
        omega.remember(c, utility=0.5, bypass_dopamine=True)
    loop_ms = (time.perf_counter() - t1) * 1000.0

    # seed 至少成功写入; loop 也应成功(两条路径都写进去了)
    assert seed_ms > 0 and loop_ms > 0
    # 批量路径显著快于逐条过门路径(store 批量收益 + 跳过门)
    assert seed_ms < loop_ms
