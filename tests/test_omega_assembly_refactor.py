"""Tests for 真拆 life.py 第一步: _nexus_register_all → omega.assembly 委托.

验证意图(纯搬迁, 行为不变):
1. Omega 实例化后机制仍注册进 self.nexus(register_all_mechanisms 生效)
2. 7 管道(learn/reflect/...)被 mark_invoked 包裹(调用后 nexus 记账)
3. omega.assembly.register_all_mechanisms 可独立调用
"""

from __future__ import annotations

import pytest

from prometheus_nexus.foundation.schema import ZConfig
from prometheus_nexus.life import Omega
from prometheus_nexus.omega.assembly import register_all_mechanisms


@pytest.fixture(scope="session")
def omega() -> Omega:
    o = Omega(ZConfig(database_path=":memory:"))
    yield o
    o.close()


def test_mechanisms_registered_into_nexus(omega: Omega):
    # 机制注册装配生效: nexus._mechanisms 非空
    assert len(omega.nexus._mechanisms) > 0
    # 部分已知子系统应注册
    assert "store" not in omega.nexus._mechanisms  # store 在排除列表
    # 至少一个业务机制注册(如 dopamine / bank)
    assert any(k in omega.nexus._mechanisms for k in ("dopamine", "bank", "constitution"))


def test_pipelines_wrapped_with_mark_invoked(omega: Omega):
    # learn 被 NexusProxy 包裹前, 管道方法应已被 _wrapped 包(调一次 mark_invoked)
    before = omega.nexus._mechanisms.get("learn", {}).get("invoke_count", 0)
    omega.learn(source="web", query="x", max_results=1)
    after = omega.nexus._mechanisms.get("learn", {}).get("invoke_count", 0)
    assert after > before  # 管道调用被记账


def test_register_all_mechanisms_idempotent_callable(omega: Omega):
    # 可直接调 assembly 函数(纯函数式装配)
    register_all_mechanisms(omega)  # 二次调用不应崩
    assert len(omega.nexus._mechanisms) > 0
