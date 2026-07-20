"""推理轨迹分析引擎 — TraceEngine

记录、回放、压缩与分析模型推理过程的完整轨迹。
核心功能:
  - 推理步骤轨迹记录与回放
  - 关键决策点检测（confidence < threshold 的拐点）
  - 轨迹压缩与摘要（去除冗余步骤保留关键路径）
  - 反事实分析：如果某步决策不同，结果会如何
  - 轨迹相似度比较（编辑距离/Levenshtein）

基于 Omega 旧版 TraceEngine 重构增强。
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class TraceStep:
    """单步推理轨迹记录"""
    step_id: int
    trace_id: str
    action: str                   # 本步执行的操作名
    confidence: float             # 本步决策置信度
    result: str                   # 本步输出摘要
    dependencies: List[str] = field(default_factory=list)  # 依赖的上游结果键
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def __hash__(self) -> int:
        return hash((self.trace_id, self.step_id))


@dataclass
class TraceSummary:
    """轨迹压缩后的摘要"""
    trace_id: str
    total_steps: int
    key_steps: List[TraceStep]     # 关键路径步骤
    removed_steps: int             # 被压缩掉的冗余步骤数
    avg_confidence: float
    critical_points: List[TraceStep]  # 低置信度拐点
    decision_chain: List[str]      # 关键决策链摘要


@dataclass
class CounterfactualResult:
    """反事实分析结果"""
    original_step_id: int
    modified_action: str
    modified_confidence: float
    downstream_impact: List[Dict[str, Any]]  # 受影响的下游步骤
    result_changed: bool
    summary: str


class TraceEngine:
    """推理轨迹分析引擎

    完整记录模型推理过程的多步骤轨迹，支持回放、压缩、
    关键决策点检测、反事实分析与轨迹相似度比较。

    使用示例:
        engine = TraceEngine()
        trace_id = engine.start_trace("math_proving")
        engine.record_step(trace_id, 1, "parse_input", 0.95, "parsed")
        engine.record_step(trace_id, 2, "generate_proof", 0.3, "attempt_1")
        summary = engine.summarize(trace_id)
        critical = engine.detect_critical_points(trace_id)
    """

    def __init__(self, confidence_threshold: float = 0.5, max_traces: int = 500) -> None:
        """
        Args:
            confidence_threshold: 低于此值的步骤将被标记为关键决策点
            max_traces: 最大保留轨迹数，超出后最旧轨迹被清除
        """
        self._confidence_threshold = confidence_threshold
        self._max_traces = max_traces
        self._traces: Dict[str, List[TraceStep]] = {}
        self._trace_order: List[str] = []
        self._result_cache: Dict[str, Any] = {}

    # ---------------------------------------------------------------
    # 轨迹记录
    # ---------------------------------------------------------------

    def start_trace(self, name: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """开启一条新推理轨迹

        Args:
            name: 轨迹名称（如 "code_review"）
            metadata: 附加元数据

        Returns:
            轨迹ID
        """
        trace_id = f"{name}_{int(time.time() * 1000)}"
        self._traces[trace_id] = []
        self._trace_order.append(trace_id)
        if len(self._trace_order) > self._max_traces:
            oldest = self._trace_order.pop(0)
            self._traces.pop(oldest, None)
        # 保存轨迹名称到元数据
        self._traces[trace_id].append(TraceStep(
            step_id=-1, trace_id=trace_id, action="__start__",
            confidence=1.0, result=name,
            metadata=metadata or {},
        ))
        return trace_id

    def record_step(
        self,
        trace_id: str,
        step_id: int,
        action: str,
        confidence: float,
        result: str,
        dependencies: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TraceStep:
        """记录单步推理

        Args:
            trace_id: 轨迹ID
            step_id: 步骤序号（从1开始递增）
            action: 本步操作名
            confidence: 决策置信度 (0~1)
            result: 输出摘要
            dependencies: 依赖的上游结果键列表
            metadata: 附加元数据

        Returns:
            创建的 TraceStep 对象
        """
        if trace_id not in self._traces:
            raise ValueError(f"Trace {trace_id} not found")

        step = TraceStep(
            step_id=step_id,
            trace_id=trace_id,
            action=action,
            confidence=confidence,
            result=result,
            dependencies=dependencies or [],
            metadata=metadata or {},
        )
        self._traces[trace_id].append(step)
        return step

    def end_trace(self, trace_id: str, final_result: Optional[str] = None) -> Optional[List[TraceStep]]:
        """结束轨迹

        Args:
            trace_id: 轨迹ID
            final_result: 最终结果摘要

        Returns:
            完整轨迹步骤列表，若轨迹不存在则返回 None
        """
        if trace_id not in self._traces:
            return None
        self._traces[trace_id].append(TraceStep(
            step_id=max(s.step_id for s in self._traces[trace_id]) + 1,
            trace_id=trace_id,
            action="__end__",
            confidence=1.0,
            result=final_result or "completed",
        ))
        self._result_cache[trace_id] = final_result
        return self.replay(trace_id)

    # ---------------------------------------------------------------
    # 回放
    # ---------------------------------------------------------------

    def replay(self, trace_id: str) -> Optional[List[TraceStep]]:
        """回放完整推理轨迹

        Args:
            trace_id: 轨迹ID

        Returns:
            按 step_id 排序的步骤列表，不存在则返回 None
        """
        steps = self._traces.get(trace_id)
        if not steps:
            return None
        return sorted(
            [s for s in steps if s.step_id >= 0],
            key=lambda s: s.step_id,
        )

    # ---------------------------------------------------------------
    # 关键决策点检测
    # ---------------------------------------------------------------

    def detect_critical_points(
        self,
        trace_id: str,
        threshold: Optional[float] = None,
    ) -> List[TraceStep]:
        """检测低置信度的关键决策拐点

        当某步置信度低于阈值，且前后步骤置信度较高时，
        该步被视为关键决策点（模型在此处犹豫或不确定）。

        Args:
            trace_id: 轨迹ID
            threshold: 覆盖默认阈值的自定义值

        Returns:
            关键决策步骤列表
        """
        if trace_id not in self._traces:
            return []

        steps = self.replay(trace_id) or []
        th = threshold if threshold is not None else self._confidence_threshold
        critical: List[TraceStep] = []

        for i, step in enumerate(steps):
            if step.confidence < th:
                critical.append(step)

        return critical

    def decision_analysis(self, trace_id: str) -> Dict[str, Any]:
        """完整决策质量分析

        返回:
            包含置信度分布、关键点数、趋势等信息的分析报告
        """
        steps = self.replay(trace_id) or []
        if not steps:
            return {"trace_id": trace_id, "step_count": 0}

        confidences = [s.confidence for s in steps]
        n = len(confidences)
        sorted_conf = sorted(confidences)

        # 置信度趋势（分段平均）
        segments = max(1, n // 5)
        segment_avgs: List[float] = []
        for seg in range(segments):
            chunk = confidences[seg * (n // segments):(seg + 1) * (n // segments)]
            segment_avgs.append(sum(chunk) / len(chunk) if chunk else 0)

        critical = self.detect_critical_points(trace_id)

        # 检测置信度下降趋势
        declining = segment_avgs[0] > segment_avgs[-1] if len(segment_avgs) >= 2 else False

        return {
            "trace_id": trace_id,
            "step_count": n,
            "avg_confidence": sum(confidences) / n,
            "min_confidence": sorted_conf[0],
            "max_confidence": sorted_conf[-1],
            "median_confidence": sorted_conf[n // 2],
            "p10_confidence": sorted_conf[int(n * 0.1)] if n > 10 else sorted_conf[0],
            "critical_point_count": len(critical),
            "critical_steps": [s.step_id for s in critical],
            "segment_avgs": segment_avgs,
            "confidence_declining": declining,
        }

    # ---------------------------------------------------------------
    # 轨迹压缩与摘要
    # ---------------------------------------------------------------

    def summarize(self, trace_id: str, keep_ratio: float = 0.3) -> Optional[TraceSummary]:
        """压缩轨迹，保留关键路径

        策略：保留关键决策点 + 首尾步骤 + 按均匀采样补足目标比例。

        Args:
            trace_id: 轨迹ID
            keep_ratio: 保留步骤的比例 (0~1)

        Returns:
            TraceSummary 对象，轨迹不存在则返回 None
        """
        steps = self.replay(trace_id)
        if not steps:
            return None

        n = len(steps)
        critical = self.detect_critical_points(trace_id)
        critical_ids = {s.step_id for s in critical}

        # 目标保留数量
        target = max(3, math.ceil(n * keep_ratio))

        # 必留：首步、尾步、关键决策点
        must_keep: Dict[int, TraceStep] = {}
        must_keep[steps[0].step_id] = steps[0]
        must_keep[steps[-1].step_id] = steps[-1]
        for cs in critical:
            must_keep[cs.step_id] = cs

        # 均匀采样补足
        if len(must_keep) < target:
            fill_count = target - len(must_keep)
            stride = max(1, n // fill_count)
            for i in range(0, n, stride):
                if steps[i].step_id not in must_keep and len(must_keep) < target:
                    must_keep[steps[i].step_id] = steps[i]

        key_steps = sorted(must_keep.values(), key=lambda s: s.step_id)
        confidences = [s.confidence for s in steps]

        return TraceSummary(
            trace_id=trace_id,
            total_steps=n,
            key_steps=key_steps,
            removed_steps=n - len(key_steps),
            avg_confidence=sum(confidences) / len(confidences),
            critical_points=critical,
            decision_chain=[s.action for s in key_steps],
        )

    # ---------------------------------------------------------------
    # 反事实分析
    # ---------------------------------------------------------------

    def counterfactual_analysis(
        self,
        trace_id: str,
        step_id: int,
        new_action: str,
        new_confidence: float,
    ) -> CounterfactualResult:
        """反事实分析：如果某步决策不同，结果会如何

        修改指定步骤的动作和置信度，重新评估其对下游步骤的影响。

        Args:
            trace_id: 轨迹ID
            step_id: 要修改的步骤ID
            new_action: 替代动作
            new_confidence: 替代置信度

        Returns:
            反事实分析结果
        """
        steps = self.replay(trace_id) or []
        original_step = next((s for s in steps if s.step_id == step_id), None)
        if original_step is None:
            return CounterfactualResult(
                original_step_id=step_id,
                modified_action=new_action,
                modified_confidence=new_confidence,
                downstream_impact=[],
                result_changed=False,
                summary=f"Step {step_id} not found",
            )

        # 找到受影响的下游步骤（依赖此步骤输出的步骤）
        downstream: List[Dict[str, Any]] = []
        for s in steps:
            if s.step_id <= step_id:
                continue
            # 检查是否依赖被修改的步骤
            affected = False
            if original_step.action in s.dependencies:
                affected = True
            # 如果置信度变化超过阈值，视为影响
            if abs(new_confidence - original_step.confidence) > 0.3:
                affected = True
            if affected:
                downstream.append({
                    "step_id": s.step_id,
                    "action": s.action,
                    "original_confidence": s.confidence,
                    "impact_direction": "negative" if new_confidence < original_step.confidence else "positive",
                })

        result_changed = len(downstream) > 0
        summary = (
            f"Step {step_id}: '{original_step.action}'(conf={original_step.confidence:.2f}) "
            f"→ '{new_action}'(conf={new_confidence:.2f}). "
            f"{len(downstream)} downstream steps affected."
        )

        return CounterfactualResult(
            original_step_id=step_id,
            modified_action=new_action,
            modified_confidence=new_confidence,
            downstream_impact=downstream,
            result_changed=result_changed,
            summary=summary,
        )

    # ---------------------------------------------------------------
    # 轨迹相似度比较
    # ---------------------------------------------------------------

    @staticmethod
    def trace_similarity(
        trace_a: List[TraceStep],
        trace_b: List[TraceStep],
    ) -> float:
        """计算两条轨迹的相似度（基于编辑距离/Levenshtein）

        将轨迹的动作序列作为字符串序列，计算归一化的编辑距离相似度。

        Args:
            trace_a: 轨迹A的步骤列表
            trace_b: 轨迹B的步骤列表

        Returns:
            相似度分数 (0~1)，1 表示完全相同
        """
        seq_a = [s.action for s in trace_a if s.step_id >= 0]
        seq_b = [s.action for s in trace_b if s.step_id >= 0]

        if not seq_a and not seq_b:
            return 1.0
        if not seq_a or not seq_b:
            return 0.0

        dist = TraceEngine._levenshtein(seq_a, seq_b)
        max_len = max(len(seq_a), len(seq_b))
        return 1.0 - (dist / max_len)

    @staticmethod
    def _levenshtein(a: List[str], b: List[str]) -> int:
        """计算两个序列之间的编辑距离"""
        n, m = len(a), len(b)
        if n == 0:
            return m
        if m == 0:
            return n

        # 使用滚动数组优化空间
        prev = list(range(m + 1))
        curr = [0] * (m + 1)

        for i in range(1, n + 1):
            curr[0] = i
            for j in range(1, m + 1):
                cost = 0 if a[i - 1] == b[j - 1] else 1
                curr[j] = min(
                    curr[j - 1] + 1,      # 插入
                    prev[j] + 1,          # 删除
                    prev[j - 1] + cost,   # 替换
                )
            prev, curr = curr, prev

        return prev[m]

    def compare_traces(
        self,
        trace_a_id: str,
        trace_b_id: str,
    ) -> Dict[str, Any]:
        """比较两条完整轨迹的相似度

        Args:
            trace_a_id: 轨迹A的ID
            trace_b_id: 轨迹B的ID

        Returns:
            包含相似度、共同动作、差异分析的对比报告
        """
        steps_a = self.replay(trace_a_id) or []
        steps_b = self.replay(trace_b_id) or []

        similarity = self.trace_similarity(steps_a, steps_b)

        actions_a = {s.action for s in steps_a}
        actions_b = {s.action for s in steps_b}

        # 置信度分布对比
        conf_a = [s.confidence for s in steps_a]
        conf_b = [s.confidence for s in steps_b]

        return {
            "trace_a_id": trace_a_id,
            "trace_b_id": trace_b_id,
            "similarity": similarity,
            "steps_a": len(steps_a),
            "steps_b": len(steps_b),
            "common_actions": list(actions_a & actions_b),
            "unique_to_a": list(actions_a - actions_b),
            "unique_to_b": list(actions_b - actions_a),
            "avg_confidence_a": sum(conf_a) / len(conf_a) if conf_a else 0,
            "avg_confidence_b": sum(conf_b) / len(conf_b) if conf_b else 0,
        }

    # ---------------------------------------------------------------
    # 查询与统计
    # ---------------------------------------------------------------

    def get_trace(self, trace_id: str) -> Optional[List[Dict[str, Any]]]:
        """获取轨迹的字典格式数据

        Args:
            trace_id: 轨迹ID

        Returns:
            步骤字典列表，不存在则返回 None
        """
        steps = self.replay(trace_id)
        if not steps:
            return None
        return [
            {
                "step_id": s.step_id,
                "trace_id": s.trace_id,
                "action": s.action,
                "confidence": s.confidence,
                "result": s.result,
                "dependencies": s.dependencies,
                "metadata": s.metadata,
                "timestamp": s.timestamp,
            }
            for s in steps
        ]

    def get_stats(self) -> Dict[str, Any]:
        """获取引擎全局统计信息

        Returns:
            包含轨迹数、总步骤数、平均置信度等统计信息
        """
        total_steps = sum(len(s) for s in self._traces.values())
        all_confidences = [
            s.confidence for steps in self._traces.values() for s in steps
        ]
        return {
            "total_traces": len(self._traces),
            "total_steps": total_steps,
            "avg_confidence": (
                sum(all_confidences) / len(all_confidences) if all_confidences else 0
            ),
            "confidence_threshold": self._confidence_threshold,
            "trace_ids": list(self._traces.keys()),
        }

    def clear_trace(self, trace_id: str) -> bool:
        """清除指定轨迹

        Args:
            trace_id: 轨迹ID

        Returns:
            是否成功清除
        """
        if trace_id in self._traces:
            del self._traces[trace_id]
            self._trace_order.remove(trace_id)
            self._result_cache.pop(trace_id, None)
            return True
        return False
