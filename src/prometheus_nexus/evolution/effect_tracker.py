"""EffectTracker — 机制执行效果量化(Phase 0 共享脊柱).

问题实证:
- nexus.dispatch 只记账 + 转调, 从不量化机制"做了什么"(nexus.py:131).
- nexus.record_effect 已存在存储(_effects), 但 dispatch 从不自动调用它.

本模块负责"执行前后测量"与"candidate vs base 对比", 不重复 record_effect 的存储.
SelectionGate 据此做影子 A/B 选择(优则 promote, 劣则 prune).
"""
from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


def snapshot_system(store=None, productions_fn: Callable[[], int] | None = None) -> dict:
    """抓取轻量系统快照, 供 measure_side_effects 对比.

    before/after 各抓一次, diff 即副作用强度. 仅取廉价、可序列化的信号,
    不触发重 IO(避免测量本身污染机制执行).
    """
    snap: dict[str, Any] = {}
    if store is not None:
        try:
            snap["node_count"] = getattr(store, "get_node_count", lambda: 0)()
        except Exception:
            snap["node_count"] = 0
    if productions_fn is not None:
        try:
            snap["write_count"] = productions_fn()
        except Exception:
            snap["write_count"] = 0
    return snap


class EffectTracker:
    """量化机制执行效果, 供 SelectionGate 选择."""

    def __init__(self, store=None, productions_fn: Callable[[], int] | None = None):
        self._store = store
        self._productions_fn = productions_fn

    def measure_side_effects(self, before: dict, after: dict) -> float:
        """对比执行前后系统状态, 量化副作用强度(-1~1).

        before/after 由 snapshot_system 抓取(轻量快照).
        信号:
          1) 写入/产出增量 (权重 0.4)
          2) 输出结构性变化非平凡 (权重 0.3)
          3) 异常惩罚 (权重 -0.5)
        """
        score = 0.0
        d_write = after.get("write_count", 0) - before.get("write_count", 0)
        score += min(1.0, abs(d_write) / 5.0) * 0.4

        out_before, out_after = before.get("output"), after.get("output")
        if isinstance(out_after, dict) and out_after.get("ok") and out_after != out_before:
            score += 0.3

        if after.get("error"):
            score -= 0.5
        return max(-1.0, min(1.0, score))

    def measure_invocation(self, fn: Callable, context: dict | None,
                           store=None, productions_fn=None) -> tuple[float, dict]:
        """测量单次机制调用的效果. 返回 (effect_score, after_snapshot).

        before/after 快照 + 捕获异常. 不吞异常(向上传播), 仅记录 error 标记.
        """
        store = store or self._store
        productions_fn = productions_fn or self._productions_fn
        before = snapshot_system(store, productions_fn)
        before["output"] = None
        after = dict(before)
        try:
            result = fn(context)
            after["output"] = result
        except Exception as e:  # 测量层记录, 不吞
            after["error"] = str(e)[:60]
        return self.measure_side_effects(before, after), after

    @staticmethod
    def aggregate_mechanism_effect(effects_dict: dict[str, list[float]]) -> float | None:
        """聚合所有机制的最近执行效果均值(Phase 5: T1 验证锚共享).

        effects_dict: name -> [effect, ...] (nexus._effects 格式).
        返回最近 N 次效果均值; 无数据返回 None(调用方退回单信号锚).
        """
        if not effects_dict:
            return None
        recent: list[float] = []
        for vals in effects_dict.values():
            if vals:
                recent.extend(vals[-5:])  # 每机制取最近 5 次
        if not recent:
            return None
        return sum(recent) / len(recent)

    def run_probe(self, candidate_fn: Callable, base_fn: Callable,
                  probes: list[dict]) -> tuple[float, float]:
        """对固定 probe 集并行跑 candidate vs base, 返回 (cand_avg, base_avg) effect.

        注意: 这里测的是"机制自身执行增益"(candidate 与 base 各自对 probe 的效果),
        非两者对比 delta — 对比 delta 由 SelectionGate 用 record_effect 历史算.
        """
        cand, base = [], []
        for p in probes:
            cb = dict(snapshot_system(self._store, self._productions_fn))
            bb = dict(cb)
            try:
                rc = candidate_fn(p); cb["output"] = rc
            except Exception as e:
                cb["error"] = str(e)[:60]
            try:
                rb = base_fn(p); bb["output"] = rb
            except Exception as e:
                bb["error"] = str(e)[:60]
            cand.append(self.measure_side_effects(cb, cb))
            base.append(self.measure_side_effects(bb, bb))
        avg = lambda xs: sum(xs) / len(xs) if xs else 0.0
        return avg(cand), avg(base)
