"""CapabilityCeiling — 能力上限检测.

基于:
- MiMo Knowledge #7: "当单Agent基线超45%时加Agent负收益"
  - 基线跟踪: 记录单Agent性能
  - 边际收益: 计算额外Agent的增量
  - 上限检测: 判断是否超过收益拐点
  - 优化建议: 推荐最优Agent数量

算法:
    should_add_agents():
        1. 计算近期基线均值
        2. 比较与上限阈值
        3. 评估边际收益趋势
        4. 返回建议

复杂度:
    should_add_agents(): O(M) 其中M=基线窗口
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import math


class CapabilityCeiling:
    """能力上限检测器.
    
    检测单Agent性能上限,避免无意义的Agent扩展.
    """
    
    CEILING_THRESHOLD = 0.45  # 45%上限
    
    def __init__(self, baseline_window: int = 10, trend_samples: int = 5):
        """初始化.
        
        Args:
            baseline_window: 基线窗口大小
            trend_samples: 趋势评估样本数
        """
        self._baseline_window = baseline_window
        self._trend_samples = trend_samples
        self._baseline_scores: list[float] = []
        self._agent_records: list[dict] = []
        self._decisions: list[dict] = []
    
    def record_baseline(self, score: float):
        """记录基线分数.
        
        Args:
            score: 单Agent性能分数(0-1)
        """
        self._baseline_scores.append(min(1.0, max(0.0, score)))
    
    def record_agent_performance(self, agent_count: int, score: float):
        """记录多Agent性能.
        
        Args:
            agent_count: Agent数量
            score: 性能分数
        """
        self._agent_records.append({
            "agents": agent_count,
            "score": score,
        })
    
    def should_add_agents(self) -> tuple[bool, str]:
        """是否应该添加Agent.
        
        Returns:
            tuple: (是否添加, 原因)
        """
        if len(self._baseline_scores) < 3:
            decision = {"action": "add", "reason": "insufficient_baseline_data"}
            self._decisions.append(decision)
            return True, "insufficient_baseline_data"
        
        # 近期基线均值
        recent = self._baseline_scores[-self._baseline_window:]
        recent_baseline = sum(recent) / len(recent)
        
        # 上限检测
        if recent_baseline > self.CEILING_THRESHOLD:
            decision = {
                "action": "stop",
                "reason": "baseline_above_ceiling",
                "baseline": recent_baseline,
            }
            self._decisions.append(decision)
            return False, "baseline_above_ceiling (%.2f > %.2f)" % (
                recent_baseline, self.CEILING_THRESHOLD
            )
        
        # 边际收益分析
        marginal = self._compute_marginal_gain()
        if marginal < 0.02:
            decision = {
                "action": "stop",
                "reason": "diminishing_returns",
                "marginal_gain": marginal,
            }
            self._decisions.append(decision)
            return False, "diminishing_returns (marginal=%.3f)" % marginal
        
        decision = {"action": "add", "reason": "room_for_improvement"}
        self._decisions.append(decision)
        return True, "baseline_below_ceiling (%.2f)" % recent_baseline
    
    def _compute_marginal_gain(self) -> float:
        """计算边际收益."""
        if len(self._agent_records) < 2:
            return 0.1  # 默认正收益
        
        # 排序
        sorted_records = sorted(self._agent_records, key=lambda r: r["agents"])
        
        # 计算相邻点的收益差
        gains = []
        for i in range(1, min(len(sorted_records), self._trend_samples + 1)):
            delta_agents = sorted_records[i]["agents"] - sorted_records[i - 1]["agents"]
            delta_score = sorted_records[i]["score"] - sorted_records[i - 1]["score"]
            if delta_agents > 0:
                gains.append(delta_score / delta_agents)
        
        if not gains:
            return 0.05
        
        # 最近几次平均边际收益
        return sum(gains[-min(3, len(gains)):]) / min(3, len(gains))
    
    def estimate_optimal_agents(self) -> int:
        """估算最优Agent数量.
        
        Returns:
            int: 推荐Agent数
        """
        if len(self._agent_records) < 2:
            return 2
        
        # 找性能峰值
        best = max(self._agent_records, key=lambda r: r["score"])
        optimal = best["agents"]
        
        # 考虑基线
        if self._baseline_scores:
            avg_baseline = sum(self._baseline_scores[-5:]) / min(5, len(self._baseline_scores))
            if avg_baseline > self.CEILING_THRESHOLD:
                optimal = 1  # 单Agent就够了
        
        return max(1, optimal)
    
    def get_stats(self) -> dict:
        """获取统计."""
        recent_baseline = 0
        if self._baseline_scores:
            recent = self._baseline_scores[-5:]
            recent_baseline = sum(recent) / len(recent)
        
        return {
            "baseline_samples": len(self._baseline_scores),
            "recent_baseline": round(recent_baseline, 4),
            "ceiling_threshold": self.CEILING_THRESHOLD,
            "agent_records": len(self._agent_records),
            "optimal_agents": self.estimate_optimal_agents(),
            "decisions_made": len(self._decisions),
            "marginal_gain": round(self._compute_marginal_gain(), 4),
        }
