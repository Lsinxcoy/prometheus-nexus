"""RLPathology — RL病理检测.

基于:
- "Reward Hacking Detection in Reinforcement Learning" (Amodei et al., 2016)
  - 奖励黑客: 检测到奖励值异常增长
  - 分布偏移: 动作分布突然变化
  - 退化检测: 策略质量下降
  - 发散预警: 价值函数发散

算法:
    detect(rewards, actions):
        1. 计算奖励统计
        2. 检测奖励黑客(奖励增长>正常3倍)
        3. 检测分布偏移(动作分布变化)
        4. 返回病理报告

复杂度:
    detect(): O(N) N=数据点数
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import time
import math
from collections import Counter, deque


class RLPathologyDetector:
    """RL病理检测器 — 检测强化学习中的异常模式.
    
    监控奖励黑客、分布偏移和策略退化.
    """
    
    def __init__(self, reward_history_size: int = 100,
                 hacking_threshold: float = 3.0):
        """初始化.
        
        Args:
            reward_history_size: 奖励历史窗口
            hacking_threshold: 奖励黑客阈值(标准差倍数)
        """
        self._reward_history: deque = deque(maxlen=reward_history_size)
        self._action_history: deque = deque(maxlen=reward_history_size)
        self._hacking_threshold = hacking_threshold
        self._pathologies: list[dict] = []
    
    def record(self, reward: float, action: str | None = None) -> None:
        """记录奖励和动作.
        
        Args:
            reward: 奖励值
            action: 动作标签
        """
        self._reward_history.append({
            "reward": reward,
            "action": action,
            "ts": time.time(),
        })
        if action:
            self._action_history.append(action)
    
    # 兼容别名: life.py 调用 observe()
    def observe(self, reward: float, action: str | None = None) -> None:
        """观察奖励信号 (兼容别名)."""
        self.record(reward, action)
    
    def detect(self) -> dict:
        """检测病理.
        
        Returns:
            dict: 检测报告
        """
        if len(self._reward_history) < 10:
            return {
                "pathologies": [],
                "reason": "insufficient data",
                "data_points": len(self._reward_history),
            }
        
        pathologies = []
        rewards = [r["reward"] for r in self._reward_history]
        
        # 1. 奖励黑客检测
        hacking = self._detect_reward_hacking(rewards)
        if hacking:
            pathologies.append(hacking)
        
        # 2. 奖励发散检测
        divergence = self._detect_divergence(rewards)
        if divergence:
            pathologies.append(divergence)
        
        # 3. 动作分布偏移检测
        distribution_shift = self._detect_action_shift()
        if distribution_shift:
            pathologies.append(distribution_shift)
        
        report = {
            "pathologies": pathologies,
            "total_detected": len(pathologies),
            "data_points": len(rewards),
            "reward_mean": round(sum(rewards) / len(rewards), 4),
            "reward_std": round(self._std(rewards), 4),
            "ts": time.time(),
        }
        
        if pathologies:
            self._pathologies.append(report)
            if len(self._pathologies) > 100:
                self._pathologies = self._pathologies[-50:]
        
        return report
    
    def _detect_reward_hacking(self, rewards: list[float]) -> dict | None:
        """检测奖励黑客.
        
        Args:
            rewards: 奖励列表
        
        Returns:
            dict | None: 检测结果
        """
        if len(rewards) < 20:
            return None
        
        # 前后半段比较
        half = len(rewards) // 2
        first_half = rewards[:half]
        second_half = rewards[half:]
        
        first_mean = sum(first_half) / len(first_half)
        second_mean = sum(second_half) / len(second_half)
        
        overall_std = self._std(rewards)
        
        if overall_std == 0:
            return None
        
        # 奖励增长是否异常
        increase = second_mean - first_mean
        z_score = increase / (overall_std * math.sqrt(2 / len(rewards)))
        
        if z_score > self._hacking_threshold:
            return {
                "type": "reward_hacking",
                "severity": "high" if z_score > self._hacking_threshold * 2 else "medium",
                "z_score": round(z_score, 4),
                "first_half_mean": round(first_mean, 4),
                "second_half_mean": round(second_mean, 4),
                "increase": round(increase, 4),
            }
        
        return None
    
    def _detect_divergence(self, rewards: list[float]) -> dict | None:
        """检测��励发散.
        
        Args:
            rewards: 奖励列表
        
        Returns:
            dict | None: 检测结果
        """
        if len(rewards) < 20:
            return None
        
        # 检测方差是否持续增长
        window = min(20, len(rewards) // 2)
        first_var = self._variance(rewards[:window])
        last_var = self._variance(rewards[-window:])
        
        if first_var > 0 and last_var / first_var > 10:
            return {
                "type": "divergence",
                "severity": "high",
                "variance_ratio": round(last_var / first_var, 4),
                "first_variance": round(first_var, 4),
                "last_variance": round(last_var, 4),
            }
        
        return None
    
    def _detect_action_shift(self) -> dict | None:
        """检测动作分布偏移.
        
        Returns:
            dict | None: 检测结果
        """
        if len(self._action_history) < 20:
            return None
        
        actions = list(self._action_history)
        half = len(actions) // 2
        
        first_dist = Counter(actions[:half])
        second_dist = Counter(actions[half:])
        
        # 计算Jensen-Shannon散度
        all_actions = set(first_dist.keys()) | set(second_dist.keys())
        if not all_actions:
            return None
        
        js_divergence = 0.0
        total_first = sum(first_dist.values())
        total_second = sum(second_dist.values())
        
        for a in all_actions:
            p = first_dist.get(a, 0) / total_first
            q = second_dist.get(a, 0) / total_second
            m = (p + q) / 2
            
            if p > 0 and m > 0:
                js_divergence += p * math.log2(p / m)
            if q > 0 and m > 0:
                js_divergence += q * math.log2(q / m)
        
        js_divergence /= 2
        
        if js_divergence > 0.5:
            return {
                "type": "distribution_shift",
                "severity": "medium",
                "js_divergence": round(js_divergence, 4),
            }
        
        return None
    
    def _std(self, values: list[float]) -> float:
        """计算标准差."""
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        return math.sqrt(self._variance(values))
    
    def _variance(self, values: list[float]) -> float:
        """计算方差."""
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        return sum((v - mean) ** 2 for v in values) / len(values)
    
    def get_stats(self) -> dict:
        """获取统计."""
        return {
            "data_points": len(self._reward_history),
            "pathologies_detected": len(self._pathologies),
        }
