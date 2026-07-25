"""Tests for 真拆 life.py 第七步: _compute_fitness → omega.maturity 委托.

验证意图(纯搬迁, 行为不变):
1. Omega._compute_fitness() 委托到 maturity.compute_fitness
2. 返回 0-1 分, 且写 self._last_fitness_detail(三维分解)
3. 与已外置的 _compute_health / get_mechanism_consumption 联动
"""

from __future__ import annotations

import pytest

from prometheus_nexus.foundation.schema import ZConfig
from prometheus_nexus.life import Omega
from prometheus_nexus.omega.maturity import compute_fitness


@pytest.fixture(scope="session")
def omega() -> Omega:
    o = Omega(ZConfig(database_path=":memory:"))
    yield o
    o.close()


def test_fitness_in_range(omega: Omega):
    score = omega._compute_fitness()
    assert 0.0 <= score <= 1.0


def test_fitness_writes_detail(omega: Omega):
    omega._compute_fitness()
    detail = omega._last_fitness_detail
    assert isinstance(detail, dict)
    assert "total" in detail
    assert "memory" in detail
    # 所有维度键齐
    for k in ("diversity", "evolution", "health", "harness", "utility",
              "energy", "multitype", "consumption", "rumination"):
        assert k in detail


def test_fitness_delegate_matches(omega: Omega):
    assert omega._compute_fitness() == compute_fitness(omega)
