"""Cycle 32 — 修复 KnowledgeRuminationEngine._promote_frequent_patterns 中
技能晋升注册失败的静默吞掉 (bare `except Exception: pass`)。

根因: learning/knowledge_rumination.py:431 在 self.skill_registry.register(...)
失败时 `pass`, 把'一个本应晋升为 skill 的高频知识模式'的注册异常完全丢弃,
既不日志也不影响计数 —— 真实薄弱(能力晋升静默丢失 + 监控盲区)。

验证策略(非假绿):
- test_skill_promotion_failure_is_surfaced: 令 skill_registry.register 抛错,
  断言必须出现 WARNING 日志(修复前 bare pass -> 无日志 -> 失败)。
- test_skill_promotion_success_still_counts: 正常路径仍晋升并计数, 修复无回归。
"""
import logging
import types

import pytest

from prometheus_nexus.learning.knowledge_rumination import KnowledgeRuminationEngine


class _FakeLearnFeedback:
    def __init__(self, stats):
        self._query_stats = stats


class _FailingSkillRegistry:
    def register(self, *args, **kwargs):
        raise RuntimeError("boom: registry capacity exceeded")


class _OkSkillRegistry:
    def __init__(self):
        self.calls = 0

    def register(self, *args, **kwargs):
        self.calls += 1


def _query_stats_two_sources(query="qA"):
    # 两个来源各自 registered>=3 -> freq[qA] = 6 >= 3 -> 晋升一个 skill
    return {
        ("s1", query): {"registered": 3},
        ("s2", query): {"registered": 3},
    }


def _make_engine(registry):
    omega = types.SimpleNamespace(
        learn_feedback=_FakeLearnFeedback(_query_stats_two_sources()),
        skill_registry=registry,
    )
    return KnowledgeRuminationEngine(omega=omega)


def test_skill_promotion_failure_is_surfaced(caplog):
    """注册失败时 MUST 暴露 WARNING, 禁止裸 pass 静默吞掉(修复前失败)。"""
    caplog.set_level(logging.WARNING)
    engine = _make_engine(_FailingSkillRegistry())
    result = types.SimpleNamespace(skills_promoted=0)

    engine._promote_frequent_patterns(result)

    assert any(
        "技能晋升注册失败" in rec.message for rec in caplog.records
    ), f"失败被静默吞掉, 无 WARNING 日志:\n{caplog.text}"
    # 控制流不变: 失败的 skill 不应计入已晋升
    assert result.skills_promoted == 0


def test_skill_promotion_success_still_counts(caplog):
    """正常路径: 高频模式仍晋升为 skill 并计数(修复无回归)。"""
    caplog.set_level(logging.WARNING)
    registry = _OkSkillRegistry()
    engine = _make_engine(registry)
    result = types.SimpleNamespace(skills_promoted=0)

    engine._promote_frequent_patterns(result)

    assert result.skills_promoted == 1
    assert registry.calls == 1
    # 成功路径不应产生失败告警
    assert not any(
        "技能晋升注册失败" in rec.message for rec in caplog.records
    )
