"""Phase 5 测试: 验证锚共享(EffectTracker 机制效果锚点接入 T1).

验证: (1) aggregate_mechanism_effect 聚合逻辑; (2) Omega.evolve 在 nexus 有
机制效果记录时, 把机制执行效果均值作为附加锚点传入 set_utility_anchor.
"""
from __future__ import annotations

import sys
import os
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from prometheus_nexus.life import Omega
from prometheus_nexus.evolution.effect_tracker import EffectTracker


def test_aggregate_empty():
    assert EffectTracker.aggregate_mechanism_effect({}) is None
    assert EffectTracker.aggregate_mechanism_effect({"a": []}) is None


def test_aggregate_mean():
    r = EffectTracker.aggregate_mechanism_effect({"m1": [0.5, 0.7], "m2": [0.1, 0.3]})
    assert abs(r - 0.4) < 1e-9


def test_aggregate_takes_recent_5():
    r = EffectTracker.aggregate_mechanism_effect({"m": [0.0, 0.0, 0.0, 0.0, 0.0, 1.0]})
    # 取最近 5 个 -> [0,0,0,0,1] 均值 0.2 (第 1 个 0.0 被截断)
    assert abs(r - 0.2) < 1e-9


class _AnchorCapture:
    """包裹真实 evolution_engine 的 set_utility_anchor, 捕获锚点值."""
    def __init__(self, engine):
        self._engine = engine
        self.anchor = None
        self._orig = engine.set_utility_anchor
    def set_utility_anchor(self, anchor):
        self.anchor = anchor
        return self._orig(anchor)
    def __getattr__(self, name):
        return getattr(self._engine, name)


def test_evolve_uses_mechanism_effect_anchor():
    """Omega.evolve 在有 nexus 机制效果时, 锚点=节点效用与机制效果均值."""
    db = os.path.join(tempfile.gettempdir(), "omega_phase5_test.db")
    if os.path.exists(db):
        os.remove(db)
    o = Omega(db_path=db)
    # 包裹真实 engine 的锚点设置(捕获值, 其他方法保持不变)
    o.evolution_engine = _AnchorCapture(o.evolution_engine)
    # 模拟 nexus 记录了机制执行效果
    o.nexus._effects = {"cand_x": [0.6, 0.8, 0.7]}
    # utility_tracker 无数据 -> 节点锚=0.5; 机制效果均值=0.7 -> 总锚=(0.5+0.7)/2=0.6
    o.evolve(context="phase5_anchor_test")
    assert o.evolution_engine.anchor is not None
    print(f"  anchor={o.evolution_engine.anchor:.3f}")
    assert abs(o.evolution_engine.anchor - 0.6) < 1e-6


def test_evolve_falls_back_when_no_effects():
    """无机制效果记录时, 锚点退回单信号(不崩)."""
    db = os.path.join(tempfile.gettempdir(), "omega_phase5_test2.db")
    if os.path.exists(db):
        os.remove(db)
    o = Omega(db_path=db)
    o.evolution_engine = _AnchorCapture(o.evolution_engine)
    o.nexus._effects = {}
    o.evolve(context="phase5_no_effect")
    assert o.evolution_engine.anchor is not None  # 不崩, 退回单信号
