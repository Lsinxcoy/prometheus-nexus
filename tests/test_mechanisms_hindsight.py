"""Tests for mechanisms.hindsight — 从 life.py 外置的后见蒸馏轨迹拼装器官.

验证意图(纯函数, 用 dict/list 假数据, 无需 Omega):
1. build_hindsight_trajectory: 正确拼装 errors/events/diagnostics/produced/outcome/success
2. 外置验收: Omega._mine_hindsight 用同逻辑拼装(行为一致)
"""

from __future__ import annotations

import pytest

from prometheus_nexus.mechanisms.hindsight import build_hindsight_trajectory
from prometheus_nexus.foundation.schema import ZConfig
from prometheus_nexus.life import Omega


def test_build_trajectory_shape():
    errors = [{"level": "error", "msg": "x"}]
    events = [{"type": "recall"}]
    t = build_hindsight_trajectory(errors, events, "learn", produced=3, outcome="ok", success=True)
    assert t["errors"] == errors
    assert t["events"] == events
    assert t["diagnostics"] == {"pipeline": "learn"}
    assert t["produced"] == 3
    assert t["outcome"] == "ok"
    assert t["success"] is True


def test_build_trajectory_defaults():
    t = build_hindsight_trajectory([], [], "reflect")
    assert t["diagnostics"] == {"pipeline": "reflect"}
    assert t["produced"] == 0
    assert t["outcome"] == ""
    assert t["success"] is True


@pytest.fixture(scope="session")
def omega() -> Omega:
    o = Omega(ZConfig(database_path=":memory:"))
    yield o
    o.close()


def test_omega_mine_hindsight_uses_builder(omega: Omega):
    # 空 issues/events → 委托 build_hindsight_trajectory 拼装后交 miner.mine
    # 验证委托路径通畅(无异常, 返回 int)。具体值取决于 miner 产出, 不假设。
    r = omega._mine_hindsight("learn", produced=1, outcome="test", success=True)
    assert isinstance(r, int)
    assert r >= 0
