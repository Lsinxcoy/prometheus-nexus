"""主循环 pipeline smoke — 高风险重构(真拆 life.py)的安全网.

验证意图: 主循环各 pipeline(learn/reflect/evolve/dream_cycle/maintain)调用
不抛未捕获异常, 返回合理结构。这是"真拆 life.py"前的系统护栏 —
拆之前必须保证现有主循环行为可观察、不崩。

轻路径(recall 空库)全本地; 重路径(learn/reflect/evolve)可能触 LLM,
默认降级模式不真调外部 API, 仅验证调用契约(返回 dict/对象, 不崩)。
"""

from __future__ import annotations

import pytest

from prometheus_nexus.foundation.schema import ZConfig
from prometheus_nexus.life import Omega


@pytest.fixture(scope="session")
def omega() -> Omega:
    o = Omega(ZConfig(database_path=":memory:"))
    yield o
    o.close()


def test_recall_empty(omega: Omega):
    r = omega.recall("anything", limit=5)
    assert hasattr(r, "hits")
    assert isinstance(r.hits, list)


def test_learn_runs(omega: Omega):
    # 最小参数; 降级模式不真调 LLM
    res = omega.learn(source="web", query="test", max_results=2)
    assert isinstance(res, dict)


def test_reflect_runs(omega: Omega):
    res = omega.reflect(context="")
    assert isinstance(res, dict)


def test_evolve_runs(omega: Omega):
    res = omega.evolve(context="", branch="main", confidence=0.5)
    # 返回 EvolutionOutcome 或 dict
    assert res is not None


def test_dream_cycle_runs(omega: Omega):
    res = omega.dream_cycle(branch="main")
    assert res is not None


def test_maintain_runs(omega: Omega):
    res = omega.maintain()
    assert isinstance(res, dict)
