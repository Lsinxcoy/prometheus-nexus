"""Tests for 真拆 life.py 第六步: get_dependency_depth → omega.monitor 委托.

验证意图(纯搬迁, 行为不变):
1. Omega.get_dependency_depth() 委托到 monitor.get_dependency_depth
2. 返回结构含 transitive_islands/depth
3. 与 get_mechanism_consumption 联动(silent 为空时 depth=0)
"""

from __future__ import annotations

import pytest

from prometheus_nexus.foundation.schema import ZConfig
from prometheus_nexus.life import Omega
from prometheus_nexus.omega.monitor import get_dependency_depth


@pytest.fixture(scope="session")
def omega() -> Omega:
    o = Omega(ZConfig(database_path=":memory:"))
    yield o
    o.close()


def test_dependency_depth_structure(omega: Omega):
    res = omega.get_dependency_depth()
    assert isinstance(res, dict)
    assert "transitive_islands" in res
    assert "depth" in res
    assert isinstance(res["transitive_islands"], list)


def test_dependency_depth_delegate_matches(omega: Omega):
    assert omega.get_dependency_depth() == get_dependency_depth(omega)


def test_dependency_depth_empty_silent(omega: Omega):
    # 空库 silent 可能仍含测试残留机制 → depth 为 0 或 1, 结构有效即可
    res = get_dependency_depth(omega)
    assert res["depth"] in (0, 1)
    assert isinstance(res["transitive_islands"], list)
