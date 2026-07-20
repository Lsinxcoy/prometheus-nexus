"""Regression tests for XMemoryAdapter type-converter silent failure (cycle 44).

Root cause: XMemoryAdapter._to_timestamp / _to_float / _to_int swallowed
(ValueError, TypeError) and returned 0.0/0 with NO logging. Because the
converters catch the exception internally, the intended `logger.warning`
in adapt() (x_adapter.py:117-118) could NEVER fire — dead observability code.
Malformed memory utility/timestamp/access_count fields were silently zeroed
on the production `remember` path (life.py:1264), corrupting memory ranking
with zero signal (监控盲区).

These tests assert the conversion failures are now surfaced via logger.warning
while the safe fallback value (0.0 / 0) is preserved. They fail against the
pre-fix code (no warning emitted), proving they are not false-green.
"""
import logging

import pytest

from prometheus_nexus.mechanisms.x_adapter import XMemoryAdapter


def test_to_float_logs_on_bad_input(caplog):
    with caplog.at_level(logging.WARNING, logger="prometheus_nexus.mechanisms.x_adapter"):
        result = XMemoryAdapter._to_float("not_a_number")
    assert result == 0.0
    assert any("XMemoryAdapter._to_float" in r.message for r in caplog.records), caplog.text


def test_to_int_logs_on_bad_input(caplog):
    with caplog.at_level(logging.WARNING, logger="prometheus_nexus.mechanisms.x_adapter"):
        result = XMemoryAdapter._to_int("bad")
    assert result == 0
    assert any("XMemoryAdapter._to_int" in r.message for r in caplog.records), caplog.text


def test_to_timestamp_logs_on_bad_string(caplog):
    with caplog.at_level(logging.WARNING, logger="prometheus_nexus.mechanisms.x_adapter"):
        result = XMemoryAdapter._to_timestamp("garbage")
    assert result == 0.0
    assert any("XMemoryAdapter._to_timestamp" in r.message for r in caplog.records), caplog.text


def test_to_timestamp_logs_on_non_numeric_type(caplog):
    with caplog.at_level(logging.WARNING, logger="prometheus_nexus.mechanisms.x_adapter"):
        result = XMemoryAdapter._to_timestamp({"a": 1})
    assert result == 0.0
    assert any("XMemoryAdapter._to_timestamp" in r.message for r in caplog.records), caplog.text


def test_adapt_surfaces_malformed_utility(caplog):
    """Malformed importance(->utility)/created(->timestamp)/access_count(->frequency)
    must be zeroed AND logged by the converters (adapt()'s own warning can't fire)."""
    with caplog.at_level(logging.WARNING, logger="prometheus_nexus.mechanisms.x_adapter"):
        res = XMemoryAdapter().adapt(
            {"id": "n1", "content": "c", "importance": "high",
             "created": "not-a-date", "access_count": "many"}
        )
    assert res["adapted"] is True
    assert res["data"]["utility"] == 0.0
    assert res["data"]["timestamp"] == 0.0
    assert res["data"]["frequency"] == 0
    assert any("XMemoryAdapter._to_" in r.message for r in caplog.records), caplog.text


def test_good_values_do_not_warn(caplog):
    with caplog.at_level(logging.WARNING, logger="prometheus_nexus.mechanisms.x_adapter"):
        res = XMemoryAdapter().adapt(
            {"id": "n1", "content": "c", "importance": 0.9,
             "created": 123.0, "access_count": 5}
        )
    assert res["adapted"] is True
    assert res["data"]["utility"] == 0.9
    assert res["data"]["frequency"] == 5
    assert not any("XMemoryAdapter._to_" in r.message for r in caplog.records), caplog.text
