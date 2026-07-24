"""Tests for mechanisms.issue_handler — 从 life.py 外置的日志→问题处理器.

验证意图(纯逻辑 + 独立 Handler, 无需 Omega):
1. should_skip_issue: NOISE 模式过滤(大小写不敏感); 正常文本不过滤
2. IssueLogHandler.emit: WARNING 以下忽略; WARNING→warning; ERROR→error;
   调用注入的 record_issue 回调; 噪声文本被过滤
3. 外置验收: Omega._attach_issue_handler 返回 IssueLogHandler 实例且能记 issue
"""

from __future__ import annotations

import logging

import pytest

from prometheus_nexus.mechanisms.issue_handler import (
    IssueLogHandler,
    should_skip_issue,
    ISSUE_NOISE_PATTERNS,
)
from prometheus_nexus.foundation.schema import ZConfig
from prometheus_nexus.life import Omega


def test_should_skip_noise_case_insensitive():
    assert should_skip_issue("owner_harm detected") is True
    assert should_skip_issue("HTTPX connection retry") is True
    assert should_skip_issue("WAL LCRP rejected: x") is True
    assert should_skip_issue("real error in evolution") is False


def test_handler_emits_with_level_and_callback():
    recorded = []
    h = IssueLogHandler(lambda level, src, msg: recorded.append((level, src, msg)))
    h.setLevel(logging.WARNING)

    # DEBUG 忽略
    h.emit(logging.LogRecord("prometheus_nexus.x", logging.DEBUG, __file__, 1, "dbg", None, None))
    assert recorded == []

    # WARNING → warning
    h.emit(logging.LogRecord("prometheus_nexus.evolution", logging.WARNING, __file__, 2, "warn msg", None, None))
    assert recorded == [("warning", "evolution", "warn msg")]

    # ERROR → error
    h.emit(logging.LogRecord("prometheus_nexus.cns", logging.ERROR, __file__, 3, "err msg", None, None))
    assert recorded[-1] == ("error", "cns", "err msg")


def test_handler_filters_noise():
    recorded = []
    h = IssueLogHandler(lambda level, src, msg: recorded.append((level, src, msg)))
    h.emit(logging.LogRecord("prometheus_nexus.x", logging.WARNING, __file__, 1, "httpx timeout", None, None))
    assert recorded == []


@pytest.fixture(scope="session")
def omega() -> Omega:
    o = Omega(ZConfig(database_path=":memory:"))
    yield o
    o.close()


def test_omega_attach_issue_handler_delegates(omega: Omega):
    handler = omega._attach_issue_handler()
    assert isinstance(handler, IssueLogHandler)
    # 经 handler 记一条 WARNING → record_issue 写入 _issues
    before = len(omega._issues)
    rec = logging.LogRecord("prometheus_nexus.test", logging.WARNING, __file__, 1, "omega wired issue", None, None)
    handler.emit(rec)
    assert len(omega._issues) == before + 1
    assert omega._issues[-1]["level"] == "warning"
    assert omega._issues[-1]["source"] == "test"


def test_issue_noise_patterns_nonempty():
    assert len(ISSUE_NOISE_PATTERNS) >= 5
