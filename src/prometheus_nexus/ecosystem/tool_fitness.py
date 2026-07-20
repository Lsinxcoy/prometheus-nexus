"""ToolFitnessPredictor — 工具效能评估模型.

基于:
- "Multi-armed Bandit for Tool Selection" (Auer et al., 2002)
  - 工具效能评分: 成功率 × 0.5 + 延迟评分 × 0.3 + 多样性奖励 × 0.2
  - 指数移动平均: 近期数据权重更高
  - 冷启动探索: 未使用工具给高先验

算法:
    record_usage(tool, action, success, latency):
        1. 更新成功/失败计数
        2. 计算EMA延迟
        3. 更新动作分布
    
    predict(tool, action):
        1. 计算成功率 (EMA)
        2. 计算延迟评分 (1 - norm_latency)
        3. 计算多样性奖励 (entropy of action distribution)
        4. 返回加权fitness

复杂度:
    record(): O(1), predict(): O(A) 其中A=动作数
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

from collections import defaultdict
import math


class ToolFitnessPredictor:
    """工具效能预测器.
    
    基于成功率和延迟的工具效能评估.
    """
    
    def __init__(self, alpha: float = 0.1, cold_start_bonus: float = 0.3):
        """初始化.
        
        Args:
            alpha: EMA衰减系数 (0-1, 越大越关注近期数据)
            cold_start_bonus: 冷启动奖励
        """
        self._alpha = alpha
        self._cold_start_bonus = cold_start_bonus
        self._tool_stats: dict[str, dict] = {}
        self._history: list[dict] = []
    
    def record_usage(self, tool: str, action: str, success: bool, latency_ms: float = 0):
        """记录工具使用.
        
        Args:
            tool: 工具名称
            action: 执行的动作
            success: 是否成功
            latency_ms: 延迟(毫秒)
        """
        if tool not in self._tool_stats:
            self._tool_stats[tool] = {
                "uses": 0,
                "successes": 0,
                "ema_latency": 0.0,
                "actions": defaultdict(int),
                "recent_success_rate": 0.5,
                "last_n_results": [],  # 最近20次结果
            }
        
        stats = self._tool_stats[tool]
        stats["uses"] += 1
        if success:
            stats["successes"] += 1
        
        # EMA延迟更新
        if stats["ema_latency"] == 0:
            stats["ema_latency"] = latency_ms
        else:
            stats["ema_latency"] = (
                self._alpha * latency_ms + (1 - self._alpha) * stats["ema_latency"]
            )
        
        # 记录最近N次结果用于滑动窗口成功率
        stats["last_n_results"].append(1 if success else 0)
        if len(stats["last_n_results"]) > 20:
            stats["last_n_results"] = stats["last_n_results"][-20:]
        
        # 更新滑动窗口成功率
        recent = stats["last_n_results"]
        stats["recent_success_rate"] = sum(recent) / len(recent)
        
        stats["actions"][action] += 1
        
        self._history.append({
            "tool": tool,
            "action": action,
            "success": success,
            "latency_ms": latency_ms,
        })
    
    def predict(self, tool: str, action: str = "") -> dict:
        """预测工具效能.
        
        Args:
            tool: 工具名称
            action: 特定动作(可选)
        
        Returns:
            dict: 包含fitness评分的详细预测
        """
        stats = self._tool_stats.get(tool)
        
        if not stats or stats["uses"] == 0:
            # 冷启动: 给中等偏高评分鼓励探索
            return {
                "tool": tool,
                "fitness": 0.5 + self._cold_start_bonus,
                "action": action,
                "confidence": "low",
                "uses": 0,
                "breakdown": {"success": 0.5, "latency": 0.5, "diversity": 0.5},
            }
        
        # 成功率评分 (使用滑动窗口)
        success_score = stats["recent_success_rate"]
        
        # 延迟评分 (归一化到0-1, 5秒为上限)
        norm_latency = min(stats["ema_latency"] / 5000.0, 1.0)
        latency_score = max(0, 1.0 - norm_latency)
        
        # 多样性奖励 (动作分布的entropy)
        action_counts = list(stats["actions"].values())
        total_actions = sum(action_counts)
        if total_actions > 0 and len(action_counts) > 1:
            probs = [c / total_actions for c in action_counts]
            entropy = -sum(p * math.log2(p) for p in probs if p > 0)
            max_entropy = math.log2(len(action_counts))
            diversity_score = entropy / max_entropy if max_entropy > 0 else 0
        else:
            diversity_score = 0.5
        
        # 加权fitness
        fitness = (
            success_score * 0.5 +
            latency_score * 0.3 +
            diversity_score * 0.2
        )
        
        # 动作特定调整
        action_bonus = 0.0
        if action and action in stats["actions"]:
            action_uses = stats["actions"][action]
            if action_uses >= 3:
                action_bonus = 0.05  # 熟悉动作小奖励
        
        fitness = min(1.0, fitness + action_bonus)
        
        # 置信度评估
        confidence = "low"
        if stats["uses"] >= 5:
            confidence = "medium"
        if stats["uses"] >= 20:
            confidence = "high"
        
        return {
            "tool": tool,
            "fitness": fitness,
            "action": action,
            "confidence": confidence,
            "uses": stats["uses"],
            "breakdown": {
                "success": round(success_score, 3),
                "latency": round(latency_score, 3),
                "diversity": round(diversity_score, 3),
            },
        }
    
    def get_top_tools(self, n: int = 5) -> list[dict]:
        """获取前N个最优工具."""
        predictions = []
        for tool in self._tool_stats:
            pred = self.predict(tool)
            pred["tool"] = tool
            predictions.append(pred)
        
        predictions.sort(key=lambda p: p["fitness"], reverse=True)
        return predictions[:n]
    
    def get_stats(self) -> dict:
        """获取统计."""
        total = sum(s["uses"] for s in self._tool_stats.values())
        total_success = sum(s["successes"] for s in self._tool_stats.values())
        
        return {
            "tools_tracked": len(self._tool_stats),
            "total_uses": total,
            "overall_success_rate": total_success / max(total, 1),
            "history_size": len(self._history),
        }
