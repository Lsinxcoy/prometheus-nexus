"""UtilityTracker — Track utility values with decay and MiMo rules.

Based on: MiMo Daily Learning utility management.
Tracks utility values over time with time-based decay and
reference-based boosting.

Thread safety:
    UtilityTracker is a shared singleton (omega.utility_tracker) mutated by
    concurrent API requests (register / record_usage / record_reference /
    record_negative_reference) and read by get_all_averages / get_stats via
    uvicorn's thread pool. All access to shared mutable state (self._entries,
    self._stats, self._negative_decay) is guarded by self._lock (RLock, because
    get_all_averages / get_stats call get_average which also acquires the lock).
"""

from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)


class UtilityTracker:
    """Track utility values with decay and MiMo-style rules.

    Usage:
        tracker = UtilityTracker()
        tracker.register("node_123")
        tracker.record_usage("node_123", utility=0.8)
        avg = tracker.get_average("node_123")
    """

    def __init__(self, decay_rate: float = 0.01, reference_boost: float = 0.05, negative_decay: float = 0.05):
        # RLock: get_all_averages / get_stats call get_average, which also
        # acquires the lock — reentrant to avoid self-deadlock.
        self._lock = threading.RLock()
        self._entries: dict[str, dict] = {}
        self._decay_rate = decay_rate
        self._reference_boost = reference_boost
        self._negative_decay = negative_decay
        self._stats = {"registered": 0, "usages": 0}

    def register(self, node_id: str, initial_utility: float = 0.5):
        with self._lock:
            if node_id not in self._entries:
                self._entries[node_id] = {
                    "utilities": [initial_utility],
                    "timestamps": [time.time()],
                    "reference_count": 0,
                    "last_decay": time.time(),
                }
                self._stats["registered"] += 1

    def record_usage(self, node_id: str, utility: float = 0.5):
        with self._lock:
            if node_id in self._entries:
                entry = self._entries[node_id]
                entry["utilities"].append(utility)
                entry["timestamps"].append(time.time())
                if len(entry["utilities"]) > 100:
                    entry["utilities"] = entry["utilities"][-50:]
                    entry["timestamps"] = entry["timestamps"][-50:]
                self._stats["usages"] += 1

    def record_reference(self, node_id: str):
        with self._lock:
            if node_id in self._entries:
                entry = self._entries[node_id]
                entry["reference_count"] += 1
                if entry["utilities"]:
                    entry["utilities"][-1] = min(1.0, entry["utilities"][-1] + self._reference_boost)

    def apply_decay(self):
        current_time = time.time()
        with self._lock:
            for node_id, entry in self._entries.items():
                hours_since_decay = (current_time - entry["last_decay"]) / 3600
                if hours_since_decay >= 24:
                    days = hours_since_decay / 24
                    decay_factor = max(0.1, 1.0 - self._decay_rate * days)
                    entry["utilities"] = [u * decay_factor for u in entry["utilities"]]
                    entry["last_decay"] = current_time

    def get_average(self, node_id: str) -> float:
        with self._lock:
            if node_id in self._entries:
                utilities = self._entries[node_id]["utilities"]
                if utilities:
                    return sum(utilities) / len(utilities)
        return 0.5

    def record_negative_reference(self, node_id: str):
        """记录无效引用——加速衰减。"""
        with self._lock:
            if node_id in self._entries:
                entry = self._entries[node_id]
                entry["negative_refs"] = entry.get("negative_refs", 0) + 1
                if entry["utilities"]:
                    entry["utilities"][-1] = max(0.0, entry["utilities"][-1] - self._negative_decay)

    @property
    def negative_decay(self) -> float:
        with self._lock:
            return self._negative_decay

    @negative_decay.setter
    def negative_decay(self, value: float):
        with self._lock:
            self._negative_decay = max(0.0, min(1.0, value))

    def get_utility_history(self, node_id: str) -> list[float]:
        with self._lock:
            if node_id in self._entries:
                return list(self._entries[node_id]["utilities"])
        return []

    def get_reference_count(self, node_id: str) -> int:
        with self._lock:
            if node_id in self._entries:
                return self._entries[node_id]["reference_count"]
        return 0

    def get_all_averages(self) -> dict[str, float]:
        with self._lock:
            return {nid: self.get_average(nid) for nid in self._entries}

    def get_stats(self) -> dict:
        with self._lock:
            return {
                **self._stats,
                "tracked_nodes": len(self._entries),
                "avg_utility": sum(self.get_average(nid) for nid in self._entries) / max(len(self._entries), 1),
            }
