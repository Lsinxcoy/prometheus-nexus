"""RTKCache — High-performance LRU cache with TTL eviction.

Architecture:
    OrderedDict-based LRU cache with per-entry TTL (time-to-live).
    Entries are evicted when:
    1. Cache exceeds max_size (LRU eviction)
    2. Entry TTL expires (time-based eviction)

Algorithm:
    - LRU: OrderedDict with move_to_end on access
    - TTL: Check expiry on get(), lazy eviction
    - Stats: Track hit/miss rates for performance monitoring

Complexity:
    get(): O(1) amortized
    put(): O(1) amortized, O(1) for LRU eviction
    get_stats(): O(1)

Edge Cases:
    - max_size=0: Cache disabled (always returns None)
    - ttl=0: No expiration (pure LRU)
    - Duplicate keys: Overwrite existing entry
    - Concurrent access: Not thread-safe (use external lock)

Thread Safety:
    - Not thread-safe. Use external lock if needed.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ============================================================
# Cache Entry
# ============================================================

@dataclass
class CacheEntry:
    """A single cache entry with metadata.

    Attributes:
        key: Cache key.
        value: Cached value.
        created_at: Creation timestamp.
        last_accessed: Last access timestamp.
        access_count: Number of times accessed.
        ttl: Time-to-live in seconds (0 = no expiry).
    """
    key: str = ""
    value: Any = None
    created_at: float = 0.0
    last_accessed: float = 0.0
    access_count: int = 0
    ttl: float = 0.0

    def __post_init__(self):
        now = time.time()
        if self.created_at == 0.0:
            self.created_at = now
        if self.last_accessed == 0.0:
            self.last_accessed = now

    def is_expired(self) -> bool:
        """Check if entry has expired."""
        if self.ttl <= 0:
            return False
        return time.time() - self.created_at > self.ttl

    def touch(self) -> None:
        """Update access timestamp."""
        self.last_accessed = time.time()
        self.access_count += 1


# ============================================================
# RTKCache
# ============================================================

class RTKCache:
    """High-performance LRU cache with TTL eviction.

    Uses OrderedDict for O(1) LRU operations and lazy TTL eviction.

    Usage:
        cache = RTKCache(max_size=1000, ttl=300.0)

        # Put with default TTL
        cache.put("query1", {"results": [...]})

        # Put with custom TTL
        cache.put("query2", {"results": [...]}, ttl=60.0)

        # Get (returns None if expired or missing)
        result = cache.get("query1")

        # Stats
        stats = cache.get_stats()
        print(f"Hit rate: {stats['hit_rate']:.1%}")

    Eviction Strategy:
        1. TTL: Entries expire after ttl seconds
        2. LRU: When full, least recently used entry is evicted

    Performance:
        - get(): O(1) amortized
        - put(): O(1) amortized
        - Memory: O(max_size) entries
    """

    def __init__(self, max_size: int = 1000, ttl: float = 300.0):
        """Initialize the cache.

        Args:
            max_size: Maximum number of entries (0 = disabled).
            ttl: Default time-to-live in seconds (0 = no expiry).
        """
        if max_size < 0:
            raise ValueError(f"max_size must be >= 0, got {max_size}")
        if ttl < 0:
            raise ValueError(f"ttl must be >= 0, got {ttl}")

        self._max_size = max_size
        self._ttl = ttl
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.Lock()

        # Statistics
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expired_evictions = 0

    def get(self, key: str) -> Any | None:
        """Get a value from the cache.

        Args:
            key: Cache key.

        Returns:
            Cached value if found and not expired, None otherwise.

        Complexity: O(1) amortized.
        """
        if self._max_size == 0:
            self._misses += 1
            return None

        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None

            # Check TTL
            if entry.is_expired():
                del self._cache[key]
                self._expired_evictions += 1
                self._misses += 1
                return None

            # Move to end (most recently used)
            self._cache.move_to_end(key)
            entry.touch()
            self._hits += 1
            return entry.value

    def put(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Put a value in the cache.

        Args:
            key: Cache key.
            value: Value to cache.
            ttl: Custom TTL (uses default if None).

        Complexity: O(1) amortized.
        """
        if self._max_size == 0:
            return

        entry_ttl = ttl if ttl is not None else self._ttl

        with self._lock:
            # Update existing
            if key in self._cache:
                self._cache.move_to_end(key)
                self._cache[key] = CacheEntry(
                    key=key, value=value, ttl=entry_ttl,
                )
                return

            # Evict if full
            while len(self._cache) >= self._max_size:
                self._cache.popitem(last=False)
                self._evictions += 1

            # Add new
            self._cache[key] = CacheEntry(
                key=key, value=value, ttl=entry_ttl,
            )

    def delete(self, key: str) -> bool:
        """Delete an entry from the cache.

        Args:
            key: Cache key.

        Returns:
            True if deleted, False if not found.
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> int:
        """Clear all entries from the cache.

        Returns:
            Number of entries cleared.
        """
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            return count

    def close(self) -> None:
        """Close the cache and release resources."""
        self.clear()

    def contains(self, key: str) -> bool:
        """Check if key exists and is not expired.

        Args:
            key: Cache key.

        Returns:
            True if key exists and is valid.
        """
        if self._max_size == 0:
            return False

        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return False
            if entry.is_expired():
                del self._cache[key]
                return False
            return True

    def cleanup_expired(self) -> int:
        """Remove all expired entries.

        Returns:
            Number of entries removed.
        """
        with self._lock:
            expired_keys = [k for k, v in self._cache.items() if v.is_expired()]
            for key in expired_keys:
                del self._cache[key]
            self._expired_evictions += len(expired_keys)
            return len(expired_keys)

    def get_entry_info(self, key: str) -> dict | None:
        """Get metadata for a cache entry.

        Args:
            key: Cache key.

        Returns:
            Dictionary with entry metadata, or None if not found.
        """
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            return {
                "key": entry.key,
                "created_at": entry.created_at,
                "last_accessed": entry.last_accessed,
                "access_count": entry.access_count,
                "ttl": entry.ttl,
                "is_expired": entry.is_expired(),
                "age_seconds": time.time() - entry.created_at,
            }

    # ============================================================
    # Statistics
    # ============================================================

    def get_stats(self) -> dict:
        """Get cache statistics.

        Returns:
            Dictionary with hit/miss rates, size, evictions.
        """
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": self._hits / max(total, 1),
                "total_requests": total,
                "evictions": self._evictions,
                "expired_evictions": self._expired_evictions,
                "ttl": self._ttl,
            }

    def __len__(self) -> int:
        return len(self._cache)

    def __contains__(self, key: str) -> bool:
        return self.contains(key)
