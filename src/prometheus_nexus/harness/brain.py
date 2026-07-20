"""Brain — 决策引擎 with 效用评估+多臂赌博机探索.

基于:
- "Multi-Armed Bandit with Upper Confidence Bound (UCB)" (Auer et al., 2002)
  - UCB探索: 平衡探索与利用
  - 效用加权: 多维度效用评估
  - 后悔度追踪: 累积后悔评估决策质量
  - 上下文感知: 根据上下文调整策略

算法:
    decide(context):
        1. 计算各候选动作的UCB值
        2. 结合上下文效用评估
        3. 选择UCB最高的动作
        4. 更新历史统计

复杂度:
    decide(): O(C log N) 其中C=候选数,N=决策数
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import math
import time


class Brain:
    """决策引擎 — 基于UCB的效用驱动决策.
    
    结合历史效用估计与探索奖励,实现探索-利用平衡.
    """
    
    def __init__(self, exploration_weight: float = 2.0, util_alpha: float = 0.1,
                 utility_halflife: float = 0.9):
        """初始化.
        
        Args:
            exploration_weight: UCB探索权重
            util_alpha: 效用更新学习率
            utility_halflife: 效用衰减因子
        """
        self._exploration = exploration_weight
        self._util_alpha = util_alpha
        self._halflife = utility_halflife
        
        self._decisions: list[dict] = []
        self._action_values: dict[str, float] = {}
        self._action_counts: dict[str, int] = {}
        self._action_rewards: dict[str, list[float]] = {}
        self._total_decisions = 0
        self._cumulative_regret = 0.0
    
    def decide(self, context: dict | None = None) -> dict:
        """做出决策.
        
        使用UCB策略平衡探索与利用.
        
        Args:
            context: 上下文信息
        
        Returns:
            dict: 决策结果
        """
        ctx = context or {}
        self._total_decisions += 1
        
        # 获取候选动作
        primary_action = ctx.get("action", "unknown")
        candidates = ctx.get("candidates", [primary_action])
        
        if not candidates:
            candidates = ["unknown"]
        
        # 计算每个候选的UCB值
        best_action = None
        best_ucb = -float('inf')
        ucb_values = {}
        
        for action in candidates:
            ucb = self._compute_ucb(action)
            ucb_values[action] = round(ucb, 4)
            if ucb > best_ucb:
                best_ucb = ucb
                best_action = action
        
        # 估计当前效用
        utility = self._estimate_utility(ctx)
        
        # 衰减旧效用值
        self._decay_utilities()
        
        # 更新选中动作的价值
        action = best_action or primary_action
        old_value = self._action_values.get(action, 0.5)
        self._action_values[action] = old_value * (1 - self._util_alpha) + utility * self._util_alpha
        self._action_counts[action] = self._action_counts.get(action, 0) + 1
        
        # 记录奖励历史
        if action not in self._action_rewards:
            self._action_rewards[action] = []
        self._action_rewards[action].append(utility)
        if len(self._action_rewards[action]) > 100:
            self._action_rewards[action] = self._action_rewards[action][-100:]
        
        # 计算置信度
        confidence = min(1.0, self._action_counts[action] / 10)
        
        decision = {
            "selected": action,
            "utility": round(utility, 4),
            "ucb_values": ucb_values,
            "confidence": round(confidence, 4),
            "is_explore": action != self._get_best_exploit(candidates),
            "ts": time.time(),
        }
        self._decisions.append(decision)
        
        return decision
    
    def _compute_ucb(self, action: str) -> float:
        """计算UCB值.
        
        Args:
            action: 动作名称
        
        Returns:
            float: UCB值
        """
        count = self._action_counts.get(action, 0)
        value = self._action_values.get(action, 0.5)
        
        if count == 0:
            return float('inf')  # 优先探索未尝试的动作
        
        exploitation = value
        exploration = self._exploration * math.sqrt(math.log(self._total_decisions + 1) / count)
        
        return exploitation + exploration
    
    def _get_best_exploit(self, candidates: list[str]) -> str | None:
        """获取纯利用策略的最优动作.
        
        Args:
            candidates: 候选动作列表
        
        Returns:
            str: 最优动作或None
        """
        best = None
        best_value = -1
        for action in candidates:
            value = self._action_values.get(action, 0)
            if value > best_value:
                best_value = value
                best = action
        return best
    
    def _estimate_utility(self, ctx: dict) -> float:
        """估计效用分数.
        
        多维度综合评估: 基础效用 + 结果奖励 + 历史性能.
        
        Args:
            ctx: 上下文
        
        Returns:
            float: 效用分数 [0, 1]
        """
        # 基础效用
        utility = ctx.get("utility", 0.5)
        
        # 结果奖励 (有结果比没有好)
        if ctx.get("result_count", 0) > 0:
            utility += 0.1
        
        # 成功标志
        if ctx.get("success", False):
            utility += 0.15
        
        # 错误惩罚
        if ctx.get("error", False):
            utility -= 0.2
        
        # 动作历史表现
        action = ctx.get("action", "")
        historical = self._action_values.get(action, 0.5)
        
        # 加权合并
        combined = utility * 0.7 + historical * 0.3
        
        return max(0.0, min(1.0, combined))
    
    def _decay_utilities(self):
        """衰减旧效用值."""
        for action in self._action_values:
            self._action_values[action] *= self._halflife
            # 拉回中间值 (防止衰减到0)
            if self._action_values[action] < 0.1:
                self._action_values[action] += 0.01
    
    def record_feedback(self, action: str, reward: float):
        """记录反馈.
        
        Args:
            action: 动作名称
            reward: 奖励值 [0, 1]
        """
        reward = max(0.0, min(1.0, reward))
        
        old_value = self._action_values.get(action, 0.5)
        self._action_values[action] = old_value * (1 - self._util_alpha) + reward * self._util_alpha
        
        if action not in self._action_rewards:
            self._action_rewards[action] = []
        self._action_rewards[action].append(reward)
    
    def get_regret(self) -> float:
        """计算累积后悔度.
        
        Returns:
            float: 平均后悔度
        """
        if self._total_decisions == 0:
            return 0.0
        
        best_value = max(self._action_values.values()) if self._action_values else 0.5
        total_regret = sum(
            best_value - self._action_values.get(d["selected"], 0.5)
            for d in self._decisions[-100:]
        )
        return total_regret / min(len(self._decisions), 100)
    
    def get_stats(self) -> dict:
        """获取统计."""
        return {
            "total_decisions": self._total_decisions,
            "unique_actions": len(self._action_values),
            "top_actions": sorted(
                self._action_values.items(),
                key=lambda x: x[1],
                reverse=True
            )[:5],
            "avg_regret": round(self.get_regret(), 4),
            "exploration_rate": round(
                sum(1 for d in self._decisions[-20:] if d.get("is_explore")) / max(len(self._decisions[-20:]), 1),
                4
            ),
        }
