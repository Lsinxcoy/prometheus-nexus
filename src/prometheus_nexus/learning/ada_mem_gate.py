"""AdaMEMGate — 自适应记忆检索门控。

不是所有查询都需要检索记忆。无条件检索会导致：
1. 上下文窗口被无关记忆污染
2. 检索延迟增加响应时间
3. 记忆中的过时信息误导推理

文档依据：30% 的查询选择不检索时，整体任务表现提升 8%。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# 短查询跳过阈值：不超过此 token 数的短查询跳过检索
SHORT_QUERY_TOKEN_THRESHOLD = 1


class AdaMEMGate:
    """自适应记忆检索门控——决定是否应该检索记忆。

    判断依据：
    - 查询长度（短查询跳过）
    - 同一查询是否刚被检索过（去重）
    - 任务类型（推理型 vs 创作型 vs 对话型 vs 执行型）
    """

    def __init__(self):
        self._recent_queries: dict[str, float] = {}
        self._skip_count = 0
        self._total_count = 0

    def should_retrieve(self, query: str, task_type: str = "reasoning") -> bool:
        """判断是否应该检索记忆。

        Args:
            query: 查询字符串。
            task_type: 任务类型（reasoning, creative, dialogue, execution）。

        Returns:
            True 表示应该检索，False 表示跳过。
        """
        try:
            self._total_count += 1
            query_lower = query.strip().lower()

            # 1. 空查询 → 跳过
            if not query_lower:
                self._skip_count += 1
                return False

            # 2. 极短查询（≤2个词）→ 跳过（防止"AI"这类合法查询被跳过）
            token_count = len(query_lower.split())
            if token_count <= SHORT_QUERY_TOKEN_THRESHOLD:
                self._skip_count += 1
                return False

            # 3. 同一查询 60 秒内重复 → 跳过
            import time
            now = time.time()
            last_seen = self._recent_queries.get(query_lower, 0)
            if now - last_seen < 60.0:
                self._skip_count += 1
                return False
            self._recent_queries[query_lower] = now

            # 4. 创作型任务 → 低检索频率
            if task_type == "creative":
                self._skip_count += 1
                return False

            return True
        except Exception:
            logger.warning("AdaMemGate: exception in should_skip, fail-safe returning True")
            # fail-safe: 异常时默认检索（不放走查询比跳过安全）
            return True

    def get_skip_rate(self) -> float:
        """获取跳过率。"""
        if self._total_count == 0:
            return 0.0
        return self._skip_count / self._total_count

    def reset_stats(self):
        """重置统计。"""
        self._skip_count = 0
        self._total_count = 0
