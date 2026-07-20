"""InfoGainCalculator — 信息增益计算.

基于:
- "Mutual Information for Feature Selection" (Cover & Thomas, 2006)
  - 熵计算: H(X) = -Σ p(x)log(p(x))
  - 条件熵: H(Y|X) = H(X,Y) - H(X)
  - 互信息: I(X;Y) = H(Y) - H(Y|X)
  - 信息增益: 选择最大化互信息的特征

算法:
    entropy(values):
        1. 计算概率分布
        2. 计算香农熵
    
    mutual_information(X, Y):
        1. 计算联合分布
        2. 计算互信息

复杂度:
    entropy(): O(N)
    mutual_information(): O(N)
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import math
from collections import Counter, defaultdict


class InfoGainCalculator:
    """信息增益计算器 — 基于互信息评估信息价值.
    
    使用熵和互信息量化信息获取的价值.
    """
    
    def __init__(self, smoothing: float = 1e-10):
        """初始化.
        
        Args:
            smoothing: 平滑因子,防止log(0)
        """
        self._smoothing = smoothing
        # 信息增益历史(供 record_gain / diminishing_returns 做边际递减检测)
        self._gains: list[float] = []
    
    def entropy(self, values: list) -> float:
        """计算香农熵.
        
        Args:
            values: 值列表
        
        Returns:
            float: 熵值 (bits)
        """
        if not values:
            return 0.0
        
        counts = Counter(values)
        total = len(values)
        entropy = 0.0
        
        for count in counts.values():
            p = (count + self._smoothing) / (total + self._smoothing * len(counts))
            if p > 0:
                entropy -= p * math.log2(p)
        
        return entropy
    
    def conditional_entropy(self, X: list, Y: list) -> float:
        """计算条件熵 H(Y|X).
        
        Args:
            X: 条件变量列表
            Y: 目标变量列表
        
        Returns:
            float: 条件熵
        """
        if len(X) != len(Y) or not X:
            return 0.0
        
        # 按X分组
        groups: dict = defaultdict(list)
        for x, y in zip(X, Y):
            groups[x].append(y)
        
        total = len(X)
        cond_entropy = 0.0
        
        for x_val, y_values in groups.items():
            p_x = len(y_values) / total
            h_y_given_x = self.entropy(y_values)
            cond_entropy += p_x * h_y_given_x
        
        return cond_entropy
    
    def mutual_information(self, X: list, Y: list) -> float:
        """计算互信息 I(X;Y).
        
        Args:
            X: 变量X
            Y: 变量Y
        
        Returns:
            float: 互信息 (bits)
        """
        h_y = self.entropy(Y)
        h_y_given_x = self.conditional_entropy(X, Y)
        
        return max(0, h_y - h_y_given_x)
    
    def info_gain(self, feature: list, target: list) -> float:
        """计算信息增益.
        
        Args:
            feature: 特征值列表
            target: 目标值列表
        
        Returns:
            float: 信息增益
        """
        return self.mutual_information(feature, target)
    
    def rank_features(self, features: dict[str, list], target: list) -> list[dict]:
        """排序特征(按信息增益).
        
        Args:
            features: 特征字典 {name: values}
            target: 目标值列表
        
        Returns:
            list: 排序后的特征列表
        """
        rankings = []
        
        for name, values in features.items():
            gain = self.info_gain(values, target)
            rankings.append({
                "feature": name,
                "info_gain": round(gain, 6),
                "entropy": round(self.entropy(values), 6),
            })
        
        rankings.sort(key=lambda x: x["info_gain"], reverse=True)
        return rankings
    
    def kldivergence(self, p: list[float], q: list[float]) -> float:
        """计算KL散度 D_KL(P||Q).
        
        Args:
            p: 分布P
            q: 分布Q
        
        Returns:
            float: KL散度
        """
        if len(p) != len(q):
            return float('inf')
        
        kl = 0.0
        for pi, qi in zip(p, q):
            pi_s = pi + self._smoothing
            qi_s = qi + self._smoothing
            if pi_s > 0:
                kl += pi_s * math.log2(pi_s / qi_s)
        
        return max(0, kl)
    
    # 兼容别名: life.py 调用 record_gain()
    def record_gain(self, source: str = "", value: float = 0.0) -> float:
        """记录信息增益(真实落地: 追加进历史, 供 diminishing_returns 检测边际递减).

        Args:
            source: 来源标签
            value: 增益值

        Returns:
            float: 记录的增益值(原样返回, 保持兼容)
        """
        v = float(value)
        self._gains.append(v)
        if len(self._gains) > 1000:  # 防止无限增长
            self._gains = self._gains[-500:]
        return v
    
    def diminishing_returns(self, window: int = 3, ratio: float = 0.6) -> bool:
        """检测是否存在边际递减(基于 record_gain 累积的历史).

        比较最近 window 个增益均值与之前 window 个增益均值:
        若 近期均值 < 前期均值 * ratio, 判定为边际递减。

        Args:
            window: 每侧对比窗口大小(样本数)
            ratio: 近期/前期均值比阈值, 低于此值判定递减

        Returns:
            bool: 是否处于边际递减状态(样本不足时返回 False)
        """
        g = self._gains
        if len(g) < 2 * window:
            return False  # 样本不足, 默认不递减
        recent = g[-window:]
        prior = g[-2 * window:-window]
        prior_mean = sum(prior) / len(prior)
        if prior_mean <= 0:
            return False
        recent_mean = sum(recent) / len(recent)
        return recent_mean < prior_mean * ratio


# 兼容别名
InformationGainTracker = InfoGainCalculator
