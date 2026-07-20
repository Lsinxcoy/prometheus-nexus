"""BootstrapCI — Bootstrap置信区间计算.

基于:
- "An Introduction to the Bootstrap" (Efron & Tibshirani, 1993)
  - 重采样估计: 有放回抽取构建经验分布
  - 百分位区间: 直接从经验分布取分位数
  - BCa修正: 偏差校正和加速因子
  - 稳健统计: 中位数/IQR辅助验证

算法:
    compute(samples):
        1. 验证输入(>=2个样本)
        2. B次重采样(有放回)
        3. 计算每次统计量(均值/中位数)
        4. 排序经验分布
        5. 提取百分位区间
        6. 计算BCa修正
        7. 返回区间+统计

复杂度:
    compute(): O(B × N log B) 其中B=重采样次数,N=样本数
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import random
import math
from collections import deque


class BootstrapCI:
    """Bootstrap置信区间计算器.
    
    支持百分位法和BCa修正.
    """
    
    def __init__(self, n_bootstrap: int = 1000, confidence: float = 0.95):
        """初始化.
        
        Args:
            n_bootstrap: 重采样次数(默认1000)
            confidence: 置信水平(默认0.95)
        """
        self._n = n_bootstrap
        self._confidence = confidence
        self._alpha = 1 - confidence
        self._results: list[dict] = []
        self._recent_stats: deque = deque(maxlen=50)
    
    def compute(self, samples: list[float], stat_func=None) -> dict:
        """计算Bootstrap置信区间.
        
        Args:
            samples: 原始样本
            stat_func: 统计量函数(默认均值)
        
        Returns:
            dict: 包含统计量、区间、宽度的结果
        """
        if len(samples) < 2:
            return {
                "mean": samples[0] if samples else 0,
                "ci_lower": 0,
                "ci_upper": 0,
                "width": 0,
                "method": "insufficient_data",
            }
        
        if stat_func is None:
            stat_func = lambda x: sum(x) / len(x)
        
        # B次重采样
        bootstrap_stats = []
        n = len(samples)
        
        for _ in range(self._n):
            # 有放回重采样
            bootstrap_sample = [random.choice(samples) for _ in range(n)]
            stat_value = stat_func(bootstrap_sample)
            bootstrap_stats.append(stat_value)
        
        # 排序
        bootstrap_stats.sort()
        
        # 百分位法区间
        lower_idx = int(self._alpha / 2 * self._n)
        upper_idx = int((1 - self._alpha / 2) * self._n)
        
        ci_lower = bootstrap_stats[max(0, lower_idx)]
        ci_upper = bootstrap_stats[min(self._n - 1, upper_idx)]
        
        # 原始统计量
        original_stat = stat_func(samples)
        
        # 标准误差
        mean_bs = sum(bootstrap_stats) / self._n
        se = math.sqrt(
            sum((s - mean_bs) ** 2 for s in bootstrap_stats) / (self._n - 1)
        )
        
        # BCa修正 (偏差校正)
        p0 = sum(1 for s in samples if s <= original_stat) / n
        z0 = self._norm_ppf(max(0.001, min(0.999, p0)))
        
        # 加速因子 (jackknife)
        acc = self._compute_acceleration(samples, stat_func)
        
        # BCa修正分位数
        z_alpha = self._norm_ppf(self._alpha / 2)
        z_1_alpha = self._norm_ppf(1 - self._alpha / 2)
        
        def bca_quantile(z):
            num = z0 + z
            denom = 1 - acc * num
            return num / denom if abs(denom) > 1e-10 else z
        
        adj_lower = bca_quantile(z_alpha)
        adj_upper = bca_quantile(z_1_alpha)
        
        # 将修正后的z值映射到索引
        bca_lower_idx = max(0, int(self._norm_cdf(adj_lower) * self._n))
        bca_upper_idx = min(self._n - 1, int(self._norm_cdf(adj_upper) * self._n))
        
        bca_ci_lower = bootstrap_stats[bca_lower_idx]
        bca_ci_upper = bootstrap_stats[bca_upper_idx]
        
        result = {
            "statistic": original_stat,
            "ci_lower": ci_lower,
            "ci_upper": ci_upper,
            "bca_ci_lower": bca_ci_lower,
            "bca_ci_upper": bca_ci_upper,
            "width": ci_upper - ci_lower,
            "bca_width": bca_ci_upper - bca_ci_lower,
            "standard_error": se,
            "n_bootstrap": self._n,
            "confidence": self._confidence,
            "method": "percentile+bca",
            "sample_size": n,
        }
        
        self._results.append(result)
        self._recent_stats.append({
            "width": result["width"],
            "se": se,
            "n": n,
        })
        
        return result
    
    def _compute_acceleration(self, samples: list[float], stat_func) -> float:
        """计算BCa加速因子(jackknife)."""
        n = len(samples)
        if n < 3:
            return 0.0
        
        jackknife_stats = []
        for i in range(n):
            leave_one_out = samples[:i] + samples[i + 1:]
            jackknife_stats.append(stat_func(leave_one_out))
        
        mean_j = sum(jackknife_stats) / n
        numerator = sum((mean_j - j) ** 3 for j in jackknife_stats)
        denominator = sum((mean_j - j) ** 2 for j in jackknife_stats) ** 1.5
        
        if abs(denominator) < 1e-10:
            return 0.0
        
        return numerator / (6 * denominator)
    
    @staticmethod
    def _norm_ppf(p: float) -> float:
        """标准正态分位数函数(Approximation)."""
        # Rational approximation (Abramowitz & Stegun)
        if p <= 0:
            return -10.0
        if p >= 1:
            return 10.0
        if p == 0.5:
            return 0.0
        
        t = math.sqrt(-2.0 * math.log(min(p, 1 - p)))
        c0, c1, c2 = 2.515517, 0.802853, 0.010328
        d1, d2, d3 = 1.432788, 0.189269, 0.001308
        
        result = t - (c0 + c1 * t + c2 * t * t) / (1 + d1 * t + d2 * t * t + d3 * t * t * t)
        return result if p > 0.5 else -result
    
    @staticmethod
    def _norm_cdf(x: float) -> float:
        """标准正态累积分布函数."""
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))
    
    def compute_median_ci(self, samples: list[float]) -> dict:
        """计算中位数置信区间."""
        return self.compute(samples, stat_func=lambda x: sorted(x)[len(x) // 2])
    
    def get_stats(self) -> dict:
        """获取统计."""
        avg_width = 0
        avg_se = 0
        if self._recent_stats:
            widths = [s["width"] for s in self._recent_stats]
            ses = [s["se"] for s in self._recent_stats]
            avg_width = sum(widths) / len(widths)
            avg_se = sum(ses) / len(ses)
        
        return {
            "computations": len(self._results),
            "avg_width": round(avg_width, 4),
            "avg_se": round(avg_se, 4),
            "confidence_level": self._confidence,
        }
