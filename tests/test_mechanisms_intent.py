"""Tests for mechanisms.intent — 从 life.py 外置的纯函数器官.

验证意图:
1. classify_intent: explanation/retrieval/generation/general 分类正确
2. extract_tool_calls: 抽取 {action} 形态工具调用, 上限 5, 异常返回空
3. 外置验收: Omega._classify_intent / _extract_tool_calls 委托壳行为
   与直接调模块函数一致(由 life.py 委托 + smoke 护栏双重保证)
"""

from __future__ import annotations

import pytest

from prometheus_nexus.mechanisms.intent import classify_intent, extract_tool_calls
from prometheus_nexus.foundation.schema import ZConfig
from prometheus_nexus.life import Omega


@pytest.mark.parametrize("query,expected", [
    ("How does gradient descent work?", "explanation"),
    ("What is the meaning of life?", "explanation"),
    ("Why does the model overfit?", "explanation"),
    ("Search for recent papers on AGI", "retrieval"),
    ("Find the config file", "retrieval"),
    ("Look up the API docs", "retrieval"),
    ("Create a new mechanism", "generation"),
    ("Make a report", "generation"),
    ("Build a scheduler", "generation"),
    ("hello there", "general"),
    ("", "general"),
])
def test_classify_intent_categories(query, expected):
    assert classify_intent(query) == expected


def test_extract_tool_calls_finds_actions():
    content = 'do {"action": "search"} then {"action": "summarize"} end'
    calls = extract_tool_calls(content)
    assert len(calls) == 2
    assert all("expected_params" in c and "actual_params" in c for c in calls)


def test_extract_tool_calls_caps_at_five():
    content = " ".join('{"action": "x"}' for _ in range(8))
    calls = extract_tool_calls(content)
    assert len(calls) == 5


def test_extract_tool_calls_empty_on_no_match():
    assert extract_tool_calls("no tool calls here") == []
    assert extract_tool_calls("") == []


# === 外置验收: life.py 委托壳行为一致 ===


@pytest.fixture(scope="session")
def omega() -> Omega:
    o = Omega(ZConfig(database_path=":memory:"))
    yield o
    o.close()


def test_omega_classify_intent_delegates(omega: Omega):
    # Omega._classify_intent 应委托给 mechanisms.intent.classify_intent
    assert omega._classify_intent("How does it work?") == "explanation"
    assert omega._classify_intent("Search the web") == "retrieval"
    assert omega._classify_intent("Build a tool") == "generation"


def test_omega_extract_tool_calls_delegates(omega: Omega):
    content = 'run {"action": "recall"} now'
    res = omega._extract_tool_calls(content)
    assert len(res) == 1
    assert "actual_params" in res[0]
