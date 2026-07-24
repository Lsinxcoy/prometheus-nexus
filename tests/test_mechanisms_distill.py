"""Tests for mechanisms.distill — 从 life.py 外置的蒸馏奖励器官.

验证意图(纯函数, 无需 Omega):
1. distill_bonus: n<=0 → 0.0; n>0 → alpha*log1p(n)
2. alpha 可覆盖
3. 外置验收: Omega._distill_bonus 委托一致(空 miner → 0.0)
"""

from __future__ import annotations

import pytest

from prometheus_nexus.mechanisms.distill import distill_bonus, DEFAULT_ALPHA
from prometheus_nexus.foundation.schema import ZConfig
from prometheus_nexus.life import Omega


def test_distill_zero_for_nonpositive():
    assert distill_bonus(0) == 0.0
    assert distill_bonus(-5) == 0.0


def test_distill_formula():
    import math
    for n in [1, 5, 10, 100]:
        assert distill_bonus(n) == pytest.approx(DEFAULT_ALPHA * math.log1p(n))


def test_distill_alpha_override():
    import math
    assert distill_bonus(10, alpha=0.1) == pytest.approx(0.1 * math.log1p(10))
    assert distill_bonus(10, alpha=0.05) == pytest.approx(0.05 * math.log1p(10))


@pytest.fixture(scope="session")
def omega() -> Omega:
    o = Omega(ZConfig(database_path=":memory:"))
    yield o
    o.close()


def test_omega_distill_bonus_delegates(omega: Omega):
    # 新实例 hindsight_miner._seen 可能为空或少数 → 非负且符合公式
    r = omega._distill_bonus()
    assert r >= 0.0
    # 委托行为: 返回 distill_bonus 的结果(n_seen 取 miner._seen)
    try:
        n = len(omega._hindsight_miner._seen) if omega._hindsight_miner else 0
    except Exception:
        n = 0
    assert r == pytest.approx(distill_bonus(n))
