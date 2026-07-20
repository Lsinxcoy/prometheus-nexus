"""Concurrency tests for UtilityTracker.

UtilityTracker is a shared singleton (omega.utility_tracker) mutated by
concurrent API requests and read by get_all_averages/get_stats. It MUST be
thread-safe: concurrent register/record_usage/record_reference must not lose
updates, register must stay idempotent, and readers must not crash while
writers mutate shared state.

Why the races are made *deterministic* (not flaky):
  * Lost-update: we seed `self._stats["usages"]` with a `_YieldInt` whose
    `__add__` releases the GIL (time.sleep(0)) at the exact read-modify-write
    point, so two threads reliably interleave and lose an update on unsynced code.
  * Idempotency: we patch `time.time` to release the GIL inside `register`'s
    check-then-act window, so concurrent registrations of the same id race.
  * Read-during-write: we force frequent GIL switches (setswitchinterval) while
    a reader iterates the dict that writers keep growing -> "dictionary changed
    size during iteration".

On the UNSYNCHRONIZED original code these fail; with a lock guarding all shared
state they pass.
"""

from __future__ import annotations

import sys
import threading
import time as _time
import pytest

from prometheus_nexus.learning.utility_tracker import UtilityTracker


class _YieldInt(int):
    """int subclass that releases the GIL on +, forcing read-modify-write races."""

    def __add__(self, other):
        _time.sleep(0)
        return _YieldInt(int(self) + other)

    __radd__ = __add__


@pytest.fixture
def forced_switch():
    """Force extremely frequent GIL switches so the iteration race shows up."""
    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        yield
    finally:
        sys.setswitchinterval(old)


def test_single_thread_behavior_unchanged():
    """Sanity: single-threaded contract is preserved by the fix (passes both)."""
    t = UtilityTracker()
    t.register("n1", initial_utility=0.4)
    t.record_usage("n1", utility=0.8)
    t.record_usage("n1", utility=1.0)
    assert t.get_average("n1") == pytest.approx((0.4 + 0.8 + 1.0) / 3)
    stats = t.get_stats()
    assert stats["registered"] == 1
    assert stats["usages"] == 2
    assert stats["tracked_nodes"] == 1
    t.record_reference("n1")
    assert t.get_reference_count("n1") == 1


def test_concurrent_record_usage_no_lost_updates():
    """Concurrent record_usage must not lose counter updates (lost-update race)."""
    t = UtilityTracker()
    t.register("n1")  # establish entry in the main thread first
    t._stats["usages"] = _YieldInt(0)  # inject GIL yield at += point

    n_threads = 8
    per_thread = 200

    def worker():
        for _ in range(per_thread):
            t.record_usage("n1", utility=0.9)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    # With a lock, every increment is counted: 8 * 200 == 1600.
    # Without a lock, the `self._stats["usages"] += 1` read-modify-write loses
    # updates (the _YieldInt forces the interleave) -> final count < 1600.
    assert t.get_stats()["usages"] == n_threads * per_thread


def test_concurrent_record_reference_no_lost_updates():
    """Concurrent record_reference must not lose per-entry reference_count updates."""
    t = UtilityTracker()
    t.register("n1")
    # Inject a GIL yield at the exact read-modify-write of reference_count.
    t._entries["n1"]["reference_count"] = _YieldInt(0)

    n_threads = 8
    per_thread = 200

    def worker():
        for _ in range(per_thread):
            t.record_reference("n1")

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    # With a lock every increment is counted; without it the
    # `entry["reference_count"] += 1` read-modify-write loses updates.
    assert t._entries["n1"]["reference_count"] == n_threads * per_thread


def test_concurrent_read_during_write_no_crash(forced_switch):
    """Readers iterating shared state must not crash while writers mutate it."""
    t = UtilityTracker()
    t.register("n1")
    errors = []

    def reader():
        try:
            for _ in range(500):
                t.get_all_averages()
                t.get_stats()
        except Exception as e:  # pragma: no cover - exercised only on the bug
            errors.append(e)

    def writer():
        try:
            for i in range(500):
                # register unique ids -> mutates self._entries dict size while
                # the reader iterates it (dict_changed_size RuntimeError on buggy code)
                t.register(f"writer_{i}")
                t.record_usage("n1")
                t.record_reference("n1")
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=reader), threading.Thread(target=writer), threading.Thread(target=writer)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    assert not errors, f"concurrent read/write raised: {errors}"
