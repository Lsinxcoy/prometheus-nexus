"""safety_utils — 越狱/注入检测(架构优化: 从 life.py 外置安全器官).

外置动机
--------
life.py 的 _detect_jailbreak(5257-5263) 核心逻辑是"扫描文本是否含已知恶意短语",
返回 {type, phrase} 或 None。这段检测纯函数式(输入文本, 输出命中),
本不属于上帝的调度流程, 是可外置、可单测、可随安全情报扩展的器官。

按"保留上帝调度权、外置器官"原则:
- detect_jailbreak(text, phrases=None): 纯检测函数外置到本模块, 默认短语列表可覆盖。
- life.py._detect_jailbreak 改为: 取 store 活跃节点文本 → 调 detect_jailbreak(text),
  行为逐行不变(由 smoke/本模块单测双重保证)。

安全语义
--------
命中即返回首个命中的恶意短语; 无命中返回 None。大小写不敏感。
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

# 默认越狱/提示注入短语(可经 phrases 参数扩展, 接入外部威胁情报)
DEFAULT_MALICIOUS_PHRASES: tuple[str, ...] = (
    "ignore previous instructions",
    "forget everything",
    "system prompt",
    "disregard rules",
)


def detect_jailbreak(
    text: str,
    phrases: Optional[Iterable[str]] = None,
) -> dict | None:
    """检测文本是否含已知越狱/提示注入短语.

    Args:
        text: 待检测文本(通常为近期活跃节点内容拼接)
        phrases: 自定义短语列表(默认用 DEFAULT_MALICIOUS_PHRASES)

    Returns:
        dict | None: 命中时 {"type": "jailbreak", "phrase": <命中短语>};
                    未命中时 None
    """
    if not text:
        return None
    phrase_list = list(phrases) if phrases is not None else list(DEFAULT_MALICIOUS_PHRASES)
    lowered = text.lower()
    for phrase in phrase_list:
        if phrase.lower() in lowered:
            return {"type": "jailbreak", "phrase": phrase}
    return None


__all__ = ["detect_jailbreak", "DEFAULT_MALICIOUS_PHRASES"]
