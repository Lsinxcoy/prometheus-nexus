"""Tests for mechanisms.failure_stats — 从 life.py 外置的失败日志器官.

验证意图(纯函数, 用 dict 假数据, 无需 Omega):
1. collect_failure_paths: 取含 action 的失败动作名
2. get_failed_trajectory: 取首条失败轨迹; 空→空结构
3. 外置验收: Omega 对应方法委托一致
"""

from __future__ import annotations

import pytest

from prometheus_nexus.mechanisms.failure_stats import (
    collect_failure_paths,
    get_failed_trajectory,
)
from prometheus_nexus.foundation.schema import ZConfig
from prometheus_nexus.life import Omega


def test_collect_failure_paths_filters_empty():
    failures = [
        {"action": "recall", "err": "x"},
        {"action": ""},                 # 无 action → 跳过
        {"note": "no action"},          # 无 action → 跳过
        {"action": "evolve"},
    ]
    out = collect_failure_paths(failures, limit=10)
    assert out == ["recall", "evolve"]


def test_get_failed_trajectory_first():
    failures = [{"trajectory": ["a", "b"], "state": {"x": 1}}, {"trajectory": ["c"]}]
    assert get_failed_trajectory(failures) == {"trajectory": ["a", "b"], "state": {"x": 1}}


def test_get_failed_trajectory_empty():
    assert get_failed_trajectory([]) == {"trajectory": [], "state": {}}


@pytest.fixture(scope="session")
def omega() -> Omega:
    o = Omega(ZConfig(database_path=":memory:"))
    yield o
    o.close()


def test_omega_failure_stats_delegates(omega: Omega):
    # 空 failure_log → 安全默认
    assert omega._collect_failure_paths() == []
    assert omega._get_failed_trajectory() == {"trajectory": [], "state": {}}
