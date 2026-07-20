"""DAGExecutor escalation boundary guard (cycle 36 weakness fix).

Weak point: DAGExecutor.execute() builds EscalationAction(escalation) deep
inside the execution loop. An invalid `escalation` string raises an opaque
ValueError *after* the failed node is already marked FAILED and appended to
the executed list -> the whole execute() crashes mid-run, leaving the DAG in
inconsistent partial state (some nodes DONE, dependent nodes never run) with a
confusing "X is not a valid EscalationAction" message.

Fix: validate the `escalation` string at the entry boundary of execute(),
fail-fast with a clear ValueError listing the valid actions. This prevents the
mid-loop crash and the inconsistent partial state.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from prometheus_nexus.execution.dag_executor import (
    DAGExecutor,
    EscalationAction,
    NodeState,
)

VALID_ACTIONS = [a.value for a in EscalationAction]


def _failing_handler(fail_node: str = "a"):
    def handler(node_id, data):
        if node_id == fail_node:
            return {"success": False, "error": "boom"}
        return {"success": True}

    return handler


def test_invalid_escalation_raises_clear_valueerror():
    ex = DAGExecutor()
    ex.add_node("a", data={})
    ex.add_node("b", data={}, dependencies=["a"])
    with pytest.raises(ValueError) as exc:
        ex.execute(node_handler=_failing_handler(), escalation="bogus_action")
    msg = str(exc.value)
    assert "valid actions" in msg.lower()
    assert "bogus_action" in msg
    for a in VALID_ACTIONS:
        assert a in msg


def test_invalid_escalation_no_partial_execution():
    """The guard must fire at the entry boundary, before any node runs."""
    ex = DAGExecutor()
    ex.add_node("a", data={})
    ex.add_node("b", data={}, dependencies=["a"])
    with pytest.raises(ValueError):
        ex.execute(node_handler=_failing_handler(), escalation="nope")
    # Nothing should have begun executing: every node stays PENDING.
    summary = ex.get_state_summary()
    assert summary == {"pending": 2}, summary


def test_valid_escalation_retry_still_works():
    ex = DAGExecutor()
    ex.add_node("a", data={})
    ex.add_node("b", data={}, dependencies=["a"])
    results = ex.execute(node_handler=_failing_handler(), escalation="retry")
    assert isinstance(results, list)
    states = {r["id"]: r["state"] for r in results}
    assert states["a"] == "failed"
    # b is a dependency of a but the DAG still returns all scheduled results.
    assert "b" in states


def test_valid_escalation_skip_works():
    ex = DAGExecutor()
    ex.add_node("a", data={})
    ex.add_node("b", data={}, dependencies=["a"])
    results = ex.execute(node_handler=_failing_handler(), escalation="skip")
    assert isinstance(results, list)
    states = {r["id"]: r["state"] for r in results}
    assert states["a"] == "failed"
