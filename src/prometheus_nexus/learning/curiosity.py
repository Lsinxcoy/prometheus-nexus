"""Curiosity — 内在好奇心驱动探索.

基于:
- "Intrinsic Motivation and Automatic Curiosity Modeling" (Schmidhuber, 1991)
  - 信息增益: 预测错误越大,好奇心越高
  - 熵驱动: 高熵区域优先探索
  - 衰减机制: 重复探索区域好奇心降低
  - 多源好奇: 结合信息增益+新颖性+不确定性

算法:
    compute_curiosity(prediction, actual):
        1. 计算预测误差(信息增益)
        2. 计算新颖性(与历史相似度)
        3. 计算不确定性(预测熵)
        4. 加权合成好奇心评分

复杂度:
    compute(): O(N) 其中N=历史样本窗口
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import math


class Curiosity:
    """内在好奇心引擎.
    
    基于预测误差的内在动机信号.
    """
    
    def __init__(self, novelty_weight: float = 0.3, entropy_weight: float = 0.2,
                 decay_rate: float = 0.1):
        """初始化.
        
        Args:
            novelty_weight: 新颖性权重
            entropy_weight: 熵权重
            decay_rate: 好奇心衰减率(0-1)
        """
        self._novelty_weight = novelty_weight
        self._entropy_weight = entropy_weight
        self._error_weight = 1 - novelty_weight - entropy_weight
        self._decay_rate = decay_rate
        self._seen: dict[str, float] = {}
        self._curiosity_history: list[float] = []
        self._total_exploration = 0
    
    def compute_curiosity(self, prediction: list[float], actual: list[float],
                         key: str = "") -> dict:
        """计算好奇心评分.
        
        Args:
            prediction: 预测值
            actual: 实际值
            key: 探索区域标识
        
        Returns:
            dict: 好奇心评分详情
        """
        # 1. 预测误差 (信息增益)
        error = self._compute_error(prediction, actual)
        
        # 2. 新颖性 (与历史比较)
        novelty = self._compute_novelty(key)
        
        # 3. 不确定性 (预测熵)
        entropy = self._compute_entropy(prediction)
        
        # 4. 加权合成
        score = (
            self._error_weight * error +
            self._novelty_weight * novelty +
            self._entropy_weight * entropy
        )
        
        # 5. 衰减 (已探索区域)
        if key in self._seen:
            self._seen[key] *= (1 - self._decay_rate)
            score *= (1 + self._seen[key]) / 2
        
        self._seen[key] = score
        self._curiosity_history.append(score)
        self._total_exploration += score
        
        return {
            "score": round(score, 4),
            "components": {
                "prediction_error": round(error, 4),
                "novelty": round(novelty, 4),
                "uncertainty": round(entropy, 4),
            },
            "weights": {
                "error": self._error_weight,
                "novelty": self._novelty_weight,
                "entropy": self._entropy_weight,
            },
            "key": key,
        }
    
    def _compute_error(self, prediction: list[float], actual: list[float]) -> float:
        """计算归一化预测误差."""
        if not prediction or not actual:
            return 0.5
        
        # MSE误差
        n = min(len(prediction), len(actual))
        mse = sum((prediction[i] - actual[i]) ** 2 for i in range(n)) / n
        
        # 归一化到[0, 1] (sigmoid近似)
        return 1.0 / (1.0 + math.exp(-3 * (mse - 0.5)))
    
    def _compute_novelty(self, key: str) -> float:
        """计算新颖性."""
        if key not in self._seen:
            return 1.0  # 全新区域
        
        # 重复探索度 (越低越新颖)
        return max(0, 1.0 - self._seen[key])
    
    def _compute_entropy(self, prediction: list[float]) -> float:
        """计算预测不确定性(熵)."""
        if not prediction or len(prediction) < 2:
            return 0.5
        
        # 归一化为概率分布
        total = sum(max(0, p) for p in prediction)
        if total <= 0:
            return 0.5
        
        probs = [max(0, p) / total for p in prediction]
        entropy = -sum(p * math.log2(p + 1e-10) for p in probs)
        
        # 归一化到[0, 1]
        max_entropy = math.log2(len(prediction))
        return entropy / max_entropy if max_entropy > 0 else 0.5
    
    def should_explore(self, score: float = None, threshold: float = 0.3) -> bool:
        """是否应该探索.
        
        Args:
            score: 好奇心评分
            threshold: 探索阈值
        
        Returns:
            bool: 是否探索
        """
        if score is not None:
            return score > threshold
        if self._curiosity_history:
            return self._curiosity_history[-1] > threshold
        return False
    
    def get_stats(self) -> dict:
        """获取统计."""
        if not self._curiosity_history:
            return {
                "explorations": 0,
                "avg_curiosity": 0,
                "max_curiosity": 0,
                "total_exploration": 0,
                "unique_regions": len(self._seen),
            }
        
        avg = sum(self._curiosity_history) / len(self._curiosity_history)
        max_val = max(self._curiosity_history)
        
        return {
            "explorations": len(self._curiosity_history),
            "avg_curiosity": round(avg, 4),
            "max_curiosity": round(max_val, 4),
            "recent_curiosity": round(self._curiosity_history[-1], 4),
            "total_exploration": round(self._total_exploration, 2),
            "unique_regions": len(self._seen),
        }
    
    # 兼容别名: life.py 调用 add() / pop() / _queue
    def add(self, item: str, priority: int = 5) -> None:
        """添加探索项 (兼容队列接口)."""
        score = min(priority / 5.0, 1.0)
        self._seen[item] = score
        self._curiosity_history.append(score)
        self._total_exploration += score
    
    def pop(self) -> dict | None:
        """弹出最高优先级探索项."""
        if not self._seen:
            return None
        key = max(self._seen, key=self._seen.get)
        score = self._seen.pop(key)
        return {"item": key, "score": round(score, 4)}
    
    @property
    def _queue(self) -> list[str]:
        """兼容 _queue 属性访问."""
        return list(self._seen.keys())


# 兼容别名
CuriosityQueue = Curiosity