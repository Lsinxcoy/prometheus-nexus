"""Cycle 31 — KnowledgeScanner._scans unbounded growth (memory leak on long-running instance).

The shared singleton self.knowledge_scanner appends every scan to self._scans
(scanner.py:153) with NO cap. On the 24/7 9200 instance this list grows without
bound -> slow memory leak + get_stats()['scans'] becomes a meaningless ever-growing
number. get_stats()/probe_sources() are read from the API dashboard
(api_server.py:820) cross-thread while the main loop keeps appending.

Fix: trim self._scans to MAX_SCAN_HISTORY after each append (cumulative counters
_total_results/_source_stats are intentionally NOT capped).

NOTE: to verify this is not a fake-green test, run it against the un-fixed code:
len(self._scans) grows past MAX_SCAN_HISTORY and the assertions below fail.
"""
import pytest

from prometheus_nexus.learning.scanner import (
    KnowledgeScanner,
    ScanResult,
    ScanSource,
)
import prometheus_nexus.learning.scanner as scanner_mod


@pytest.fixture
def capped_scanner(monkeypatch):
    # Avoid real network: every scan returns one dummy result.
    monkeypatch.setattr(
        KnowledgeScanner, "_scan_arxiv",
        lambda self, q, m: [ScanResult(title="x")],
    )
    # Deterministic, small cap so the test is fast and independent of the
    # production constant value.
    monkeypatch.setattr(scanner_mod, "MAX_SCAN_HISTORY", 50, raising=False)
    return KnowledgeScanner()


def test_scans_history_is_capped(capped_scanner):
    for i in range(200):
        capped_scanner.scan(ScanSource.ARXIV, f"q{i}", max_results=1)
    # Most-recent retained, old entries trimmed.
    assert len(capped_scanner._scans) == 50
    assert capped_scanner._scans[-1]["query"] == "q199"
    assert capped_scanner._scans[0]["query"] == "q150"


def test_get_stats_reports_capped_scan_count_but_cumulative_totals(capped_scanner):
    for i in range(200):
        capped_scanner.scan(ScanSource.ARXIV, f"q{i}", max_results=1)
    stats = capped_scanner.get_stats()
    assert stats["scans"] == 50                      # bounded history
    assert stats["total_results"] == 200             # cumulative counter not capped
    assert stats["source_distribution"]["arxiv"] == 200
