"""SelfObservation — 系统自我观察层。

记录每条管道的运行指标，定期回看发现行为模式。
基于 2900+ 轮自主学习的经验教训：
- 连续 3 次零增益 → 方向降权
- 反刍学习：定期回顾已有知识
- 周循环：每 5 次 learn 后强制回顾
"""

from __future__ import annotations

import logging
import time
from collections import deque

logger = logging.getLogger(__name__)

# 周循环：每 N 次 learn 后触发回顾
REVIEW_INTERVAL = 5
# 连续零增益阈值
ZERO_GAIN_THRESHOLD = 3


class SelfObservation:
    """自我观察层——记录管道运行指标并检测行为模式。

    设计原则：
    - 不阻塞任何管道执行
    - 所有方法 try/except 保护
    - 只读现有数据，不写 store（避免副作用）
    """

    def __init__(self):
        self._lock = __import__('threading').Lock()
        self._learn_log: deque[dict] = deque(maxlen=50)
        self._learn_zero_gain_count = 0
        self._learn_rounds_since_review = 0
        self._last_review_time = time.time()
        self._review_count = 0

    def record_learn(self, query: str, new_nodes: int, source: str, utility: float = 0.5) -> dict | None:
        """记录一次 learn 调用，如果达到周循环则返回检查结果。

        Returns:
            None 表示未触发回顾。
            dict 表示触发回顾的检查报告。
        """
        with self._lock:
            self._learn_log.append({
                "query": query,
                "new_nodes": new_nodes,
                "source": source,
                "utility": utility,
                "timestamp": time.time(),
            })
            self._learn_rounds_since_review += 1

            # 连续零增益检测
            if new_nodes == 0:
                self._learn_zero_gain_count += 1
            else:
                self._learn_zero_gain_count = 0

            # 周循环检查
            if self._learn_rounds_since_review >= REVIEW_INTERVAL:
                return self._run_review_locked()
        return None

    def _run_review_locked(self) -> dict:
        """执行周循环回顾（已持有锁时调用）。"""
        self._review_count += 1
        self._learn_rounds_since_review = 0
        self._last_review_time = time.time()

        report = {
            "review_count": self._review_count,
            "total_learns": len(self._learn_log),
            "zero_gain_streak": self._learn_zero_gain_count,
            "patterns": [],
        }

        # Pattern: 连续零增益
        if self._learn_zero_gain_count >= ZERO_GAIN_THRESHOLD:
            report["patterns"].append({
                "type": "zero_gain",
                "message": f"连续 {self._learn_zero_gain_count} 次 learn 零增益，建议切换方向",
            })

        # Pattern: 同一 source 过于频繁
        source_counts = {}
        for entry in self._learn_log:
            src = entry.get("source", "unknown")
            source_counts[src] = source_counts.get(src, 0) + 1
        dominant_source = max(source_counts, key=source_counts.get)
        if source_counts[dominant_source] >= 4:
            report["patterns"].append({
                "type": "source_bias",
                "message": f"{dominant_source} 过去 5 次中使用 {source_counts[dominant_source]} 次",
                "source": dominant_source,
                "count": source_counts[dominant_source],
            })

        if report["patterns"]:
            logger.info("SelfObservation review #%d: %d patterns found",
                        self._review_count, len(report["patterns"]))
        return report

    def has_zero_gain_streak(self) -> bool:
        """是否处于连续零增益状态。"""
        return self._learn_zero_gain_count >= ZERO_GAIN_THRESHOLD

    def get_review_count(self) -> int:
        """获取回顾次数。"""
        return self._review_count

    def get_stats(self) -> dict:
        """获取状态统计。"""
        return {
            "total_learns": len(self._learn_log),
            "zero_gain_streak": self._learn_zero_gain_count,
            "reviews": self._review_count,
            "last_review_seconds_ago": time.time() - self._last_review_time,
        }
