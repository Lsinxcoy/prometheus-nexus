"""RareValidDetector — Rare-but-valid pattern detection.

基于:
- "Rare Event Detection in Streaming Data" (Gionis et al., 2007) + Omega稀有模式发现
  - 分箱频率统计: 将值离散化为10个bin
  - 稀有阈值: 频率 < rarity_threshold → 标记为稀有
  - 有效性判断: utility > 0.05 → 稀有但有效

算法:
    observe(value):
        1. bin_idx = int(value * 10) → 分箱
        2. 更新bin计数

    detect(items):
        1. 对每个item计算bin频率
        2. freq < rarity_threshold → 稀有
        3. utility > 0.05 → 有效

来源: Omega系统 rare_valid 稀有有效模式检测模块
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

from collections import Counter


class RareValidDetector:
    """Detect rare but valid patterns.

    Usage:
        rvd = RareValidDetector(rarity_threshold=0.1)
        for item in items:
            rvd.observe(item.utility)
        rare = rvd.detect(items)
    """

    def __init__(self, rarity_threshold: float = 0.1):
        self._rarity_threshold = rarity_threshold
        self._detections: list[dict] = []
        self._histogram: Counter = Counter()
        self._total = 0

    def observe(self, value: float) -> None:
        bin_idx = int(value * 10)
        self._histogram[bin_idx] += 1
        self._total += 1

    def detect(self, items: list | None = None) -> list[dict]:
        rare = []
        if items:
            for item in items:
                if hasattr(item, 'utility') and item.utility is not None:
                    freq = self._histogram.get(int(item.utility * 10), 0) / max(self._total, 1)
                    if freq < self._rarity_threshold:
                        rare.append({
                            "id": getattr(item, 'id', ''),
                            "utility": item.utility,
                            "frequency": freq,
                            "valid": item.utility > 0.05,
                        })
        self._detections.extend(rare)
        return rare

    def get_rare_values(self) -> list[int]:
        total = max(self._total, 1)
        return [bin_idx for bin_idx, count in self._histogram.items()
                if count / total < self._rarity_threshold]

    def get_stats(self) -> dict:
        return {
            "observations": self._total,
            "detections": len(self._detections),
            "valid_detections": sum(1 for d in self._detections if d.get("valid")),
            "rarity_threshold": self._rarity_threshold,
        }
