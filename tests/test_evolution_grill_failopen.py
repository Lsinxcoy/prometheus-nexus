"""Regression tests for EvolutionGrill.review() fail-open safety bug.

Weakness (cycle 28): governance/autonomy.py:216
    approved = sufficient and failed == 0 or len(checks) == 0
Due to Python operator precedence this parses as
    approved = (sufficient and (failed == 0)) or (len(checks) == 0)
so ANY change submitted with an empty checks list is auto-approved
(fail-open). Production calls review(change) with no checks at all
(life.py:2628), so the gate has *never* blocked anything and always
reports approved=True — a false safety signal. A high-risk-change
multi-level verification gate must be fail-CLOSED: without sufficient
passing checks it must NOT approve.

Run against buggy code -> test_review_empty_checks_not_approved FAILS
(fails open). After fix -> all pass.
"""
import pytest

from prometheus_nexus.governance.autonomy import EvolutionGrill


def _checks(*passed_flags):
    return [{"passed": bool(p)} for p in passed_flags]


class TestEvolutionGrillFailOpen:
    def test_review_empty_checks_not_auto_approved(self):
        """Empty checks list must NOT auto-approve (fail-open removed)."""
        grill = EvolutionGrill()
        report = grill.review({"description": "high-risk evolution"})
        assert report["approved"] is False
        assert report["checks_total"] == 0

    def test_review_no_arg_checks_not_approved(self):
        """Production call review(change) passes no checks -> not approved."""
        grill = EvolutionGrill()
        report = grill.review({"description": "x"})  # checks defaults to []
        assert report["approved"] is False

    def test_review_sufficient_all_passing_approved(self):
        """3 passing checks (== min_checks) -> approved."""
        grill = EvolutionGrill()
        report = grill.review({"description": "x"}, checks=_checks(True, True, True))
        assert report["approved"] is True
        assert report["checks_passed"] == 3
        assert report["checks_failed"] == 0

    def test_review_one_failed_blocks(self):
        """3 checks but one failed -> blocked (not all passed)."""
        grill = EvolutionGrill()
        report = grill.review({"description": "x"}, checks=_checks(True, True, False))
        assert report["approved"] is False
        assert report["checks_failed"] == 1

    def test_review_insufficient_checks_blocks(self):
        """Fewer than min_checks passing -> insufficient -> blocked."""
        grill = EvolutionGrill(min_checks=3)
        report = grill.review({"description": "x"}, checks=_checks(True, True))
        assert report["approved"] is False
        assert report["sufficient_checks"] is False

    def test_review_audit_log_records_decision(self):
        grill = EvolutionGrill()
        grill.review({"description": "x"}, checks=_checks(True, True, True))
        stats = grill.get_stats()
        assert stats["reviews"] == 1
        # 3/3 passed -> approval_rate 1.0, not a false 0
        assert stats["approval_rate"] == 1.0
