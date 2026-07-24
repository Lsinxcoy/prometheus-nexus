"""issue_handler — 日志→问题账本处理器(架构优化: 从 life.py 外置).

外置动机
--------
life.py 的 _attach_issue_handler(1207-1230) 含: NOISE 常量 + _IssueHandler
(logging.Handler 子类, emit 调 self.record_issue 记问题)。

_IssueHandler 隐式依赖 Omega self(调 self.record_issue), 与上帝耦合。
外置为独立类 IssueLogHandler(record_issue_fn), 通过回调注入记录函数,
不再依赖 Omega; 噪声过滤抽成纯函数 should_skip_issue。

按"保留上帝调度权、外置器官"原则:
- mechanisms.issue_handler.IssueLogHandler(record_issue_fn) 独立可测
- life.py._attach_issue_handler 仅 return IssueLogHandler(self.record_issue)
- 行为逐行不变(NOISE 过滤 + WARNING 阈值 + level 判定 + record_issue 调用)
"""

from __future__ import annotations

import logging
from typing import Callable, Sequence

logger = logging.getLogger(__name__)

# 噪声模式: 这些子系统日志高频且无诊断价值, 过滤掉不记问题
ISSUE_NOISE_PATTERNS: tuple[str, ...] = (
    "owner_harm", "WAL LCRP rejected",
    "batch_update_utilities received booleans",
    "A2A delegate_task failed", "httpx", "urllib3",
)


def should_skip_issue(text: str, noise: Sequence[str] = ISSUE_NOISE_PATTERNS) -> bool:
    """判断该日志文本是否应被过滤(噪声). 纯函数."""
    low = (text or "").lower()
    return any(n.lower() in low for n in noise)


class IssueLogHandler(logging.Handler):
    """把 WARNING+ 日志转记到问题账本的 Handler.

    record_issue_fn(level, source, msg) 由调用方注入(通常是 Omega.record_issue),
    使本类不依赖 Omega, 可独立单测。
    """

    def __init__(self, record_issue_fn: Callable[[str, str, str], None]):
        super().__init__()
        self._record_issue = record_issue_fn
        self.setLevel(logging.WARNING)

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.WARNING:
            return
        text = record.getMessage()
        if should_skip_issue(text):
            return
        level = "error" if record.levelno >= logging.ERROR else "warning"
        src = record.name.split(".")[-1] if record.name else "?"
        try:
            self._record_issue(level, src, text)
        except Exception:
            pass


__all__ = ["ISSUE_NOISE_PATTERNS", "should_skip_issue", "IssueLogHandler"]
