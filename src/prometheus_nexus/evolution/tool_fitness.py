"""工具Fitness评估器 — ToolFitness

评估工具调用的质量、效率、适配度。
核心功能:
  - 工具调用成功率和耗时分析
  - 工具选择策略评估（是否选择了最优工具）
  - 参数质量评分（参数是否在有效范围内）
  - 工具组合效率分析（多工具链的有效性）
  - 自适应工具推荐（基于历史表现）

基于 Omega 旧版 ToolFitnessPredictor 重构增强。
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import math
import random
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ToolCallRecord:
    """单次工具调用记录"""
    tool_name: str
    parameters: Dict[str, Any]
    success: bool
    latency_ms: float
    timestamp: float = field(default_factory=time.time)
    error_message: Optional[str] = None
    output_size: int = 0  # 输出大小（字节或tokens）

    @property
    def status(self) -> str:
        return "success" if self.success else "failed"


@dataclass
class ToolProfile:
    """工具性能画像"""
    name: str
    total_calls: int = 0
    successful_calls: int = 0
    total_latency_ms: float = 0.0
    latencies: List[float] = field(default_factory=list)
    parameter_scores: List[float] = field(default_factory=list)
    errors: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        return (self.successful_calls / self.total_calls) if self.total_calls > 0 else 0.0

    @property
    def avg_latency_ms(self) -> float:
        return (self.total_latency_ms / self.total_calls) if self.total_calls > 0 else 0.0

    @property
    def p95_latency_ms(self) -> float:
        if not self.latencies:
            return 0.0
        sorted_l = sorted(self.latencies)
        idx = min(int(len(sorted_l) * 0.95), len(sorted_l) - 1)
        return sorted_l[idx]

    @property
    def avg_parameter_score(self) -> float:
        return (sum(self.parameter_scores) / len(self.parameter_scores)) if self.parameter_scores else 0.0


@dataclass
class ToolFitnessScore:
    """工具fitness综合评分"""
    tool_name: str
    overall_score: float       # 综合评分 (0~1)
    success_score: float       # 成功率得分 (0~1)
    latency_score: float       # 延迟得分 (0~1)
    parameter_score: float     # 参数质量得分 (0~1)
    consistency_score: float   # 稳定性得分 (0~1)
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolChainAnalysis:
    """工具链组合分析结果"""
    chain: List[str]
    total_latency_ms: float
    overall_success: bool
    bottleneck_tool: str
    efficiency_score: float
    suggestions: List[str] = field(default_factory=list)


class ToolFitness:
    """工具调用fitness评估器

    基于历史调用数据对工具性能进行多维度评估，
    提供自适应工具推荐与工具链优化建议。

    使用示例:
        fitness = ToolFitness()
        fitness.record_call("search", {"query": "xxx"}, True, 120.5)
        score = fitness.evaluate("search")
        best = fitness.recommend(["search", "browse", "execute"], context={"type": "web"})
    """

    # 延迟权重基准（用于延迟评分归一化，单位: ms）
    DEFAULT_LATENCY_BASLINE_MS = 500.0

    def __init__(
        self,
        latency_baseline_ms: float = DEFAULT_LATENCY_BASLINE_MS,
        decay_factor: float = 0.95,
        max_history_per_tool: int = 1000,
    ) -> None:
        """
        Args:
            latency_baseline_ms: 延迟评分基准线，低于此值的延迟视为优秀
            decay_factor: 历史数据衰减因子，越旧的记录权重越低
            max_history_per_tool: 每个工具最多保留的历史记录数
        """
        self._latency_baseline_ms = latency_baseline_ms
        self._decay_factor = decay_factor
        self._max_history = max_history_per_tool

        self._profiles: Dict[str, ToolProfile] = {}
        self._call_history: Dict[str, List[ToolCallRecord]] = defaultdict(list)
        self._tool_chains: List[List[str]] = []
        self._context_tool_map: Dict[str, List[str]] = defaultdict(list)

    # ---------------------------------------------------------------
    # 记录工具调用
    # ---------------------------------------------------------------

    def record_call(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        success: bool,
        latency_ms: float,
        error_message: Optional[str] = None,
        output_size: int = 0,
    ) -> ToolCallRecord:
        """记录一次工具调用结果

        Args:
            tool_name: 工具名称
            parameters: 传入参数
            success: 是否成功
            latency_ms: 调用耗时（毫秒）
            error_message: 失败时的错误信息
            output_size: 输出大小

        Returns:
            创建的调用记录
        """
        record = ToolCallRecord(
            tool_name=tool_name,
            parameters=parameters,
            success=success,
            latency_ms=latency_ms,
            error_message=error_message,
            output_size=output_size,
        )

        # 更新工具画像
        if tool_name not in self._profiles:
            self._profiles[tool_name] = ToolProfile(name=tool_name)

        profile = self._profiles[tool_name]
        profile.total_calls += 1
        profile.total_latency_ms += latency_ms
        profile.latencies.append(latency_ms)
        if success:
            profile.successful_calls += 1
        else:
            profile.errors[error_message or "unknown"] += 1

        # 评估参数质量
        param_score = self._score_parameters(tool_name, parameters)
        profile.parameter_scores.append(param_score)

        # 维护历史记录（限制大小）
        history = self._call_history[tool_name]
        history.append(record)
        if len(history) > self._max_history:
            self._call_history[tool_name] = history[-self._max_history:]

        return record

    def record_chain(self, tools: List[str], latencies: List[float], success: bool) -> None:
        """记录工具链调用

        Args:
            tools: 工具链顺序
            latencies: 各工具耗时列表
            success: 整体是否成功
        """
        self._tool_chains.append(tools)

    # ---------------------------------------------------------------
    # 参数质量评分
    # ---------------------------------------------------------------

    def _score_parameters(self, tool_name: str, parameters: Dict[str, Any]) -> float:
        """评估参数质量

        评分维度:
          - 参数完整性：是否提供了所有必要参数
          - 参数范围：数值参数是否在合理范围内
          - 参数合理性：字符串参数长度是否合理

        Args:
            tool_name: 工具名称
            parameters: 参数字典

        Returns:
            参数质量分数 (0~1)
        """
        if not parameters:
            return 0.3  # 空参数给低分

        scores: List[float] = []

        for key, value in parameters.items():
            if value is None:
                scores.append(0.2)  # None 参数扣分
            elif isinstance(value, str):
                # 字符串非空即合理
                score = 1.0 if value.strip() else 0.1
                # 过长的字符串可能不合理
                if len(value) > 10000:
                    score *= 0.7
                scores.append(score)
            elif isinstance(value, (int, float)):
                # 数值参数：在合理范围内给高分
                if -1e6 <= value <= 1e6:
                    scores.append(1.0)
                elif -1e9 <= value <= 1e9:
                    scores.append(0.7)
                else:
                    scores.append(0.3)
            elif isinstance(value, (list, tuple)):
                score = 1.0 if value else 0.5
                scores.append(score)
            elif isinstance(value, dict):
                # 嵌套字典递归评分
                scores.append(
                    self._score_parameters(tool_name, value)
                )
            else:
                scores.append(0.8)  # 其他类型默认中等

        return sum(scores) / len(scores) if scores else 0.5

    def parameter_quality_report(self, tool_name: str) -> Dict[str, Any]:
        """获取工具参数质量报告

        Args:
            tool_name: 工具名称

        Returns:
            包含平均参数分、最低/最高分等统计
        """
        profile = self._profiles.get(tool_name)
        if not profile or not profile.parameter_scores:
            return {"tool_name": tool_name, "sample_count": 0}

        scores = profile.parameter_scores
        return {
            "tool_name": tool_name,
            "sample_count": len(scores),
            "avg_parameter_score": sum(scores) / len(scores),
            "min_parameter_score": min(scores),
            "max_parameter_score": max(scores),
            "recent_scores": scores[-10:],
        }

    # ---------------------------------------------------------------
    # 工具评估
    # ---------------------------------------------------------------

    def evaluate(self, tool_name: str) -> Optional[ToolFitnessScore]:
        """评估单个工具的fitness综合评分

        综合评分 = 0.35*成功率 + 0.25*延迟 + 0.2*参数质量 + 0.2*稳定性

        Args:
            tool_name: 工具名称

        Returns:
            ToolFitnessScore，工具无数据则返回 None
        """
        profile = self._profiles.get(tool_name)
        if not profile or profile.total_calls == 0:
            return None

        # 成功率得分
        success_score = profile.success_rate

        # 延迟得分（越低越好，使用指数衰减）
        avg_lat = profile.avg_latency_ms
        latency_score = math.exp(-avg_lat / self._latency_baseline_ms)

        # 参数质量得分
        param_score = profile.avg_parameter_score

        # 稳定性得分（基于延迟标准差，标准差越小越稳定）
        if len(profile.latencies) >= 2:
            mean_lat = sum(profile.latencies) / len(profile.latencies)
            variance = sum((l - mean_lat) ** 2 for l in profile.latencies) / len(profile.latencies)
            std_dev = math.sqrt(variance)
            # 变异系数越小越稳定
            cv = std_dev / mean_lat if mean_lat > 0 else 0
            consistency_score = math.exp(-cv)
        else:
            consistency_score = 0.5  # 数据不足时给中等分

        # 综合评分
        overall = (
            0.35 * success_score
            + 0.25 * latency_score
            + 0.20 * param_score
            + 0.20 * consistency_score
        )

        return ToolFitnessScore(
            tool_name=tool_name,
            overall_score=round(overall, 4),
            success_score=round(success_score, 4),
            latency_score=round(latency_score, 4),
            parameter_score=round(param_score, 4),
            consistency_score=round(consistency_score, 4),
            details={
                "total_calls": profile.total_calls,
                "avg_latency_ms": round(avg_lat, 2),
                "p95_latency_ms": round(profile.p95_latency_ms, 2),
                "error_distribution": dict(profile.errors),
            },
        )

    def evaluate_all(self) -> List[ToolFitnessScore]:
        """评估所有已记录工具的fitness

        Returns:
            按综合评分降序排列的评分列表
        """
        scores = []
        for name in self._profiles:
            score = self.evaluate(name)
            if score:
                scores.append(score)
        scores.sort(key=lambda s: s.overall_score, reverse=True)
        return scores

    # ---------------------------------------------------------------
    # 工具选择策略评估
    # ---------------------------------------------------------------

    def evaluate_selection(self, chosen: str, candidates: List[str]) -> Dict[str, Any]:
        """评估工具选择是否正确

        对比已选工具和候选工具的fitness评分，判断是否为最优选择。

        Args:
            chosen: 实际选择的工具
            candidates: 候选工具列表

        Returns:
            包含选择质量、最优工具、差距分析的报告
        """
        scores: Dict[str, ToolFitnessScore] = {}
        for name in candidates:
            score = self.evaluate(name)
            if score:
                scores[name] = score

        if not scores:
            return {
                "chosen": chosen,
                "candidates": candidates,
                "has_data": False,
                "message": "无历史数据可供评估",
            }

        best_tool = max(scores, key=lambda n: scores[n].overall_score)
        best_score = scores[best_tool].overall_score

        chosen_score = scores.get(chosen)
        if chosen_score:
            gap = best_score - chosen_score.overall_score
            is_optimal = chosen == best_tool
        else:
            gap = best_score
            is_optimal = False

        return {
            "chosen": chosen,
            "chosen_score": chosen_score.overall_score if chosen_score else None,
            "best_tool": best_tool,
            "best_score": best_score,
            "is_optimal": is_optimal,
            "gap_to_optimal": round(gap, 4),
            "all_scores": {n: s.overall_score for n, s in scores.items()},
            "recommendation": (
                f"建议选择 '{best_tool}' (fitness={best_score:.4f})"
                if not is_optimal else "当前选择已是最优"
            ),
        }

    # ---------------------------------------------------------------
    # 工具链效率分析
    # ---------------------------------------------------------------

    def analyze_chain(self, chain: List[str]) -> Optional[ToolChainAnalysis]:
        """分析工具链组合效率

        Args:
            chain: 工具链顺序

        Returns:
            工具链分析结果，缺少数据则返回 None
        """
        if not chain:
            return None

        scores = []
        latencies = []
        all_success = True

        for tool_name in chain:
            score = self.evaluate(tool_name)
            profile = self._profiles.get(tool_name)
            if score:
                scores.append(score)
                latencies.append(profile.avg_latency_ms if profile else 0)
                if profile.success_rate < 0.5:
                    all_success = False
            else:
                scores.append(None)
                latencies.append(0)
                all_success = False

        if not any(scores):
            return None

        total_latency = sum(latencies)

        # 找出瓶颈工具（延迟最高或成功率最低的）
        bottleneck = chain[0]
        for i, tool_name in enumerate(chain):
            profile = self._profiles.get(tool_name)
            if profile and (profile.avg_latency_ms > self._profiles.get(bottleneck, ToolProfile("")).avg_latency_ms):
                bottleneck = tool_name

        # 效率评分
        valid_scores = [s for s in scores if s is not None]
        if valid_scores:
            efficiency = sum(s.overall_score for s in valid_scores) / len(valid_scores)
        else:
            efficiency = 0

        # 生成建议
        suggestions: List[str] = []
        for tool_name in chain:
            score = self.evaluate(tool_name)
            if score and score.overall_score < 0.3:
                suggestions.append(f"工具 '{tool_name}' fitness 过低({score.overall_score:.2f})，考虑替换")
            if score and score.success_score < 0.7:
                suggestions.append(f"工具 '{tool_name}' 成功率偏低({score.success_score:.2f})")
            if score and score.latency_score < 0.3:
                suggestions.append(f"工具 '{tool_name}' 延迟过高，考虑优化")

        return ToolChainAnalysis(
            chain=chain,
            total_latency_ms=total_latency,
            overall_success=all_success,
            bottleneck_tool=bottleneck,
            efficiency_score=round(efficiency, 4),
            suggestions=suggestions,
        )

    def frequent_chains(self, top_n: int = 5) -> List[Tuple[List[str], int]]:
        """统计最常使用的工具链

        Args:
            top_n: 返回前N个

        Returns:
            (工具链, 出现次数) 列表
        """
        chain_counts: Dict[str, int] = defaultdict(int)
        for chain in self._tool_chains:
            key = " -> ".join(chain)
            chain_counts[key] += 1

        sorted_chains = sorted(chain_counts.items(), key=lambda x: -x[1])
        return [
            (key.split(" -> "), count)
            for key, count in sorted_chains[:top_n]
        ]

    # ---------------------------------------------------------------
    # 自适应工具推荐
    # ---------------------------------------------------------------

    def register_context(self, context: str, tool_name: str) -> None:
        """注册上下文-工具映射关系

        用于构建自适应推荐模型。

        Args:
            context: 任务上下文标签（如 "code_review", "web_search"）
            tool_name: 在该上下文中使用过的工具
        """
        self._context_tool_map[context].append(tool_name)

    def recommend(
        self,
        candidates: List[str],
        context: Optional[Dict[str, Any]] = None,
        top_n: int = 1,
    ) -> List[Dict[str, Any]]:
        """自适应工具推荐

        基于历史表现和上下文信息，从候选工具中推荐最优工具。

        Args:
            candidates: 候选工具列表
            context: 任务上下文信息（可选）
            top_n: 返回推荐数量

        Returns:
            包含工具名、评分、推荐理由的推荐列表
        """
        scored: List[Tuple[str, ToolFitnessScore]] = []

        for name in candidates:
            score = self.evaluate(name)
            if score:
                scored.append((name, score))

        if not scored:
            return [{"tool": c, "score": 0, "reason": "无历史数据"} for c in candidates[:top_n]]

        # 上下文加权：如果上下文匹配历史偏好，给予额外权重
        if context:
            context_key = context.get("type", "")
            preferred = self._context_tool_map.get(context_key, [])
            if preferred:
                pref_set = set(preferred)
                # 对偏好工具给予加权
                for i, (name, score) in enumerate(scored):
                    if name in pref_set:
                        weighted = score.overall_score * 1.15
                        scored[i] = (name, ToolFitnessScore(
                            tool_name=name,
                            overall_score=round(weighted, 4),
                            success_score=score.success_score,
                            latency_score=score.latency_score,
                            parameter_score=score.parameter_score,
                            consistency_score=score.consistency_score,
                            details={**score.details, "context_boost": True},
                        ))

        scored.sort(key=lambda x: x[1].overall_score, reverse=True)

        reasons = {
            "high_success": "高成功率",
            "low_latency": "低延迟",
            "consistent": "表现稳定",
            "context_match": "匹配任务上下文",
        }
        recommendations: List[Dict[str, Any]] = []
        for name, score in scored[:top_n]:
            reason_parts = []
            if score.success_score > 0.8:
                reason_parts.append(reasons["high_success"])
            if score.latency_score > 0.6:
                reason_parts.append(reasons["low_latency"])
            if score.consistency_score > 0.7:
                reason_parts.append(reasons["consistent"])
            if score.details.get("context_boost"):
                reason_parts.append(reasons["context_match"])
            if not reason_parts:
                reason_parts.append("基于综合评分")

            recommendations.append({
                "tool": name,
                "score": score.overall_score,
                "reason": " + ".join(reason_parts),
                "details": {
                    "success_rate": score.success_score,
                    "latency_score": score.latency_score,
                    "parameter_score": score.parameter_score,
                    "consistency": score.consistency_score,
                },
            })

        return recommendations

    # ---------------------------------------------------------------
    # 全局统计
    # ---------------------------------------------------------------

    def get_profile(self, tool_name: str) -> Optional[ToolProfile]:
        """获取工具性能画像

        Args:
            tool_name: 工具名称

        Returns:
            工具画像，不存在则返回 None
        """
        return self._profiles.get(tool_name)

    def get_stats(self) -> Dict[str, Any]:
        """获取全局工具调用统计

        Returns:
            全局统计信息
        """
        total_calls = sum(p.total_calls for p in self._profiles.values())
        total_success = sum(p.successful_calls for p in self._profiles.values())
        return {
            "total_tools": len(self._profiles),
            "total_calls": total_calls,
            "total_success": total_success,
            "overall_success_rate": (total_success / total_calls) if total_calls > 0 else 0,
            "tool_names": list(self._profiles.keys()),
            "recorded_chains": len(self._tool_chains),
            "contexts": dict(self._context_tool_map),
        }
