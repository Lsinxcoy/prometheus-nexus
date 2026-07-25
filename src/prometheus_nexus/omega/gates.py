"""omega 包 — 在线安全门决策外置(真拆收尾).

真拆 life.py 最后一块可外置逻辑(用户授权高风险项):
把 remember 里的 dopamine gate 决策判断抽成纯决策函数。副作用(rollback/
failure_log/return)仍留 life.py(上帝职责), 本模块只回答"是否拒绝"。

约束: 调度集中是上帝不可肢解; 只外置决策判断, 不接管写入副作用。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def should_reject_dopamine(self, utility: float, surprise: float, bypass_dopamine: bool) -> bool:
    """Dopamine gate 决策: 是否拒绝本次 remember 写入.

    Args:
        utility / surprise: 节点效用 / 惊奇度
        bypass_dopamine: 跳过门(种子场景)时为 False 拒绝

    Returns:
        bool: True=拒绝写入(调用方负责 rollback/log/return "")
    """
    if bypass_dopamine:
        return False
    try:
        gate = self.dopamine.evaluate(utility=utility, surprise=surprise)
        return gate.decision == "reject"
    except Exception as e:
        logger.debug("dopamine gate eval failed (treat as pass): %s", e)
        return False
