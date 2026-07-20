"""Regression: Omega engine helper methods must surface failures, not swallow them.

life.py 4768-4856 contains a cluster of enrichment helpers (_compute_success_rate,
_get_reasoning_chain, _collect_failure_paths, ...) used by StrategySwitcher / MCTS
retriever / CARA / COMPASS / ReflectiveSampler. Each wraps its store/failure_log read
in `except Exception: return <safe-default>` with NO logging -- so when the store or
failure log is actually down, the engine silently returns an empty/medium value and the
downstream subsystem happily degrades while ops see nothing (monitoring blind spot).

These helpers are pure functions of `self.store` / `self.failure_log`; we bind the
unbound methods to a fake `self` whose store/log raises, and assert that (a) the safe
default is still returned (no behavior change) and (b) a WARNING is emitted so the
failure is visible.
"""
import logging
import types

import pytest

from prometheus_nexus.life import Omega


class _FailStore:
    def get_active_nodes(self, limit=10):
        raise RuntimeError("store unavailable")


class _FailLog:
    def get_failures(self, limit=10):
        raise RuntimeError("failure_log unavailable")


class FakeSelf:
    def __init__(self):
        self.store = _FailStore()
        self.failure_log = _FailLog()


def _bind(name):
    return getattr(Omega, name).__get__(FakeSelf())


def test_compute_success_rate_surfaces_failure(caplog):
    caplog.set_level(logging.WARNING, logger="prometheus_nexus.life")
    fn = _bind("_compute_success_rate")
    with caplog.at_level(logging.WARNING, logger="prometheus_nexus.life"):
        result = fn()
    # Safe default preserved (no behavior change for callers).
    assert result == 0.5
    # Failure must be visible, not swallowed.
    assert any(r.levelno == logging.WARNING for r in caplog.records), \
        "store failure in _compute_success_rate was swallowed (no WARNING)"


def test_get_reasoning_chain_surfaces_failure(caplog):
    caplog.set_level(logging.WARNING, logger="prometheus_nexus.life")
    fn = _bind("_get_reasoning_chain")
    with caplog.at_level(logging.WARNING, logger="prometheus_nexus.life"):
        result = fn()
    assert result == []
    assert any(r.levelno == logging.WARNING for r in caplog.records), \
        "store failure in _get_reasoning_chain was swallowed (no WARNING)"


def test_collect_failure_paths_surfaces_failure(caplog):
    caplog.set_level(logging.WARNING, logger="prometheus_nexus.life")
    fn = _bind("_collect_failure_paths")
    with caplog.at_level(logging.WARNING, logger="prometheus_nexus.life"):
        result = fn()
    assert result == []
    assert any(r.levelno == logging.WARNING for r in caplog.records), \
        "failure_log failure in _collect_failure_paths was swallowed (no WARNING)"
