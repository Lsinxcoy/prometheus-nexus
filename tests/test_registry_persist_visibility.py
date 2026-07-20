"""Cycle 33 — MechanismRegistry._persist 持久化失败监控盲区修复验证.

根因: registry.py:_persist 失败仅 logger.debug(生产默认 WARNING 级别不可见),
导致机制注册表(机制启用/禁用态 + 消费标记 consumed_at, 支撑 consumption_score
维度)持久化静默失败时无人知晓 —— 同类盲区 cycle12(store) / cycle17(evolution_state)
已修, 本类被遗漏。修复: debug -> warning 暴露.

非假绿: test_persist_failure_is_exposed_at_warning 在旧 debug 代码下必失败
(无 WARNING 记录), 修复后通过。
"""
import logging
import os
import tempfile

import pytest

from prometheus_nexus.mechanisms.registry import MechanismRegistry


def test_persist_failure_is_exposed_at_warning(caplog, monkeypatch):
    """Registry durability failure must surface at WARNING (production-visible),
    not be hidden at DEBUG. Regression guard: with the old debug-level log this
    assertion fails because no WARNING records are captured."""
    reg = MechanismRegistry(path=os.path.join(tempfile.mkdtemp(), "reg.json"))

    def _boom(*a, **k):
        raise OSError("simulated disk write failure")

    # _persist does `import os` locally -> resolves to sys.modules['os'], the same
    # object the test imports; patch os.replace to force the failure deterministically.
    monkeypatch.setattr(os, "replace", _boom)

    with caplog.at_level(logging.WARNING, logger="prometheus_nexus.mechanisms.registry"):
        reg._persist()

    warns = [
        r
        for r in caplog.records
        if r.levelno >= logging.WARNING
        and "MechanismRegistry._persist failed" in r.getMessage()
    ]
    assert warns, (
        "registry durability failure must be logged at WARNING, "
        "not silently swallowed at DEBUG"
    )


def test_persist_success_emits_no_warning(caplog):
    """Healthy persist writes the file and emits no WARNING-level noise."""
    d = tempfile.mkdtemp()
    reg = MechanismRegistry(path=os.path.join(d, "reg.json"))
    with caplog.at_level(logging.WARNING, logger="prometheus_nexus.mechanisms.registry"):
        reg.register("m1")
    warns = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not warns, "healthy persist should not emit warnings"
    assert os.path.exists(reg._path), "registry file should have been written"
