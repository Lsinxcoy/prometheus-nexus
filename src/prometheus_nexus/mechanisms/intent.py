"""intent — 意图分类与工具调用提取(架构优化: 从 life.py 外置纯函数器官).

外置动机
--------
life.py 的 _classify_intent / _extract_tool_calls 是两个纯函数(仅依赖入参字符串,
不碰 self 状态), 却被 recall / learn / dream 等多个管道内联调用。它们本不属于
5333 行上帝的"调度逻辑", 而是可复用的检索/解析工具。

按"保留上帝调度权、外置器官"原则, 将其抽到独立模块。life.py 改为委托调用,
行为不变(由 test_omega_smoke 护栏验证)。后续可由 wiring 统一收集, 进一步声明式化。

设计
----
- classify_intent(query) -> str: explanation/retrieval/generation/general
- extract_tool_calls(content) -> list[dict]: 从文本抽取 {...action...} 形态工具调用
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


_EXPLANATION_KW = ("how", "what", "why", "explain")
_RETRIEVAL_KW = ("search", "find", "look up")
_GENERATION_KW = ("create", "make", "build")

_INTENT_TOOL_CALL_PATTERN = r'\{[^}]*"action":\s*"([^"]+)"[^}]*\}'


def classify_intent(query: str) -> str:
    """分类用户意图(SimpleMem 检索用).

    Args:
        query: 用户查询文本

    Returns:
        str: "explanation" | "retrieval" | "generation" | "general"
    """
    if not query:
        return "general"
    query_lower = query.lower()
    if any(kw in query_lower for kw in _EXPLANATION_KW):
        return "explanation"
    if any(kw in query_lower for kw in _RETRIEVAL_KW):
        return "retrieval"
    if any(kw in query_lower for kw in _GENERATION_KW):
        return "generation"
    return "general"


def extract_tool_calls(content: str) -> list[dict]:
    """从内容字符串抽取工具调用.

    匹配 {... "action": "..." ...} 形态(JSON-ish 片段), 最多取前 5 个。

    Args:
        content: 待解析文本

    Returns:
        list[dict]: 每个元素 {"expected_params": {}, "actual_params": {}}
    """
    try:
        matches = re.findall(_INTENT_TOOL_CALL_PATTERN, content or "")
        return [{"expected_params": {}, "actual_params": {}} for _ in matches[:5]]
    except Exception as e:  # pragma: no cover - re 极难抛错
        logger.warning("intent.extract_tool_calls: parse failed: %s", e)
        return []


__all__ = ["classify_intent", "extract_tool_calls"]
