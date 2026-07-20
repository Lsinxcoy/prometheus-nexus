"""Cycle 35: KnowledgeRuminationEngine 状态持久化/晋升失败监控盲区修复验证.

薄弱点: knowledge_rumination.py 三处失败分支用 logger.debug 暴露, 生产默认
WARNING 级别不可见 -> 反刍调度状态(_persist/_load)跨重启静默丢失、晋升整体
异常(_promote_frequent_patterns 外层)静默失败, 心跳排程 next_rumination_due()
据此误判。修复: debug -> warning。

测试须真失败(旧代码仅 debug 不被 caplog WARNING 捕获)再真通过。
"""
import logging
import os
import tempfile
import types

import pytest

from prometheus_nexus.learning.knowledge_rumination import KnowledgeRuminationEngine

LOGGER = "prometheus_nexus.learning.knowledge_rumination"


def _make_engine(state_path=None):
    omega = types.SimpleNamespace(
        store=None, semantic_learner=None, knowledge_to_mechanism=None,
        learn_feedback=None, skill_registry=None,
    )
    return KnowledgeRuminationEngine(omega, state_path=state_path)


def test_persist_failure_emits_warning(caplog):
    """_persist IO 失败必须 WARNING 暴露, 不能静默 debug."""
    engine = _make_engine()
    blocker = tempfile.NamedTemporaryFile(delete=False)
    blocker.close()
    # 父目录是已存在的文件 -> os.makedirs 抛 NotADirectoryError -> 命中 except
    engine.state_path = os.path.join(blocker.name, "sub", "state.json")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        engine._persist()
    warns = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("persist failed" in m for m in warns), \
        f"persist IO 失败必须 WARNING 暴露, 实测记录: {warns}"


def test_load_corruption_emits_warning(caplog):
    """_load 损坏 JSON 必须 WARNING 暴露, 不能静默 debug 回退默认."""
    engine = _make_engine()
    fd, path = tempfile.mkstemp(suffix=".json")
    os.write(fd, b"{ this is not valid json ")
    os.close(fd)
    engine.state_path = path
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        engine._load()
    warns = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("load failed" in m for m in warns), \
        f"load 损坏必须 WARNING 暴露, 实测记录: {warns}"


def test_promote_outer_failure_emits_warning(caplog):
    """_promote_frequent_patterns 外层异常(如 _query_stats 非 dict)必须 WARNING."""
    engine = _make_engine()
    engine.skill_registry = object()  # 通过守卫
    engine.learn_feedback = types.SimpleNamespace(_query_stats=["not", "a", "dict"])
    result = types.SimpleNamespace(skills_promoted=0)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        engine._promote_frequent_patterns(result)
    warns = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("模式晋升失败" in m for m in warns), \
        f"晋升外层异常必须 WARNING 暴露, 实测记录: {warns}"
