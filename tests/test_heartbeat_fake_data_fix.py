"""Regression — Heartbeat4Cycle must not misrepresent a static bootstrap seed
as skills "discovered from external sources" (假数据 / phantom declaration).

Before the fix:
  * ``_scan_external_sources()`` documented scanning HuggingFace/GitHub/arXiv
    but returned a hardcoded static list (zero network I/O).
  * ``_devour_cycle`` logged ``scanned_{N}_sources`` — claiming N external
    sources were queried when in fact none were.

After the fix the cycle honestly reports a bootstrap seed and emits a WARNING
that external scanning is disabled, while still installing the seed skills.
"""
import logging

import pytest

from prometheus_nexus.monitor.heartbeat_4cycle import Heartbeat4Cycle


@pytest.fixture
def hb(tmp_path):
    reg = tmp_path / "skill_registry.json"
    return Heartbeat4Cycle(skill_registry_path=str(reg))


def test_no_fake_external_scan_claim(hb):
    """_devour_cycle must NOT report having scanned external sources."""
    actions, _ = hb._devour_cycle()
    fake = [a for a in actions if a.startswith("scanned_") and a.endswith("_sources")]
    assert not fake, f"devour misreports external scan: {fake}"


def test_seeds_bootstrap_candidates_honestly(hb):
    """The static seed is reported as a bootstrap seed, not an external scan."""
    actions, metrics = hb._devour_cycle()
    assert any(
        a.startswith("seeded_") and a.endswith("_bootstrap_candidates") for a in actions
    )
    # Real effect preserved: seed skills were installed into the registry.
    assert metrics["new_skills"] >= 1
    assert metrics["total_skills"] >= 1


def test_seed_is_static_not_live_scan(hb):
    """Calling the source twice yields the identical deterministic list,
    proving it is a static seed and not a live external scan."""
    a = hb._bootstrap_seed_skills()
    b = hb._bootstrap_seed_skills()
    assert [s["name"] for s in a] == [s["name"] for s in b]
    assert len(a) >= 1


def test_external_scan_disabled_warned(hb, caplog):
    """A clear WARNING must expose that external scanning is disabled."""
    with caplog.at_level(
        logging.WARNING, logger="prometheus_nexus.monitor.heartbeat_4cycle"
    ):
        hb._devour_cycle()
    assert any(
        "external skill scanning is DISABLED" in r.message for r in caplog.records
    ), "no warning exposing disabled external scanning"
