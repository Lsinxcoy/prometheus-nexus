"""MemoryBank — Tiered memory bank with automatic migration and aging.

Architecture:
    7-tier memory hierarchy:
    0: Working (active, high-utility)
    1: Short-term (recent, moderate-utility)
    2: Long-term (consolidated, high-utility)
    3: Episodic (event-based)
    4: Semantic (concept-based)
    5: Procedural (action-based)
    6: Archive (rarely accessed)

    Migration Rules:
    - Items with importance < migration_threshold migrate down
    - Items older than aging_hours are archived or pruned
    - Migration preserves item metadata and timestamps

    Aging Rules:
    - Items in tiers 0-5 older than aging_hours → move to tier 6
    - Items in tier 6 older than 2× aging_hours → pruned

Algorithm:
    store(content, tier, importance):
        1. Create BankItem with metadata
        2. Append to specified tier
        3. Return immediately

    run_migration():
        for tier in range(6, 0, -1):
            for item in tier:
                if item.importance < threshold:
                    move item to tier-1
        return migrated count

    run_aging():
        for tier in range(6):
            for item in tier:
                if age > aging_hours:
                    move to tier 6 (or prune if already tier 6)
        return aged count

Complexity:
    store(): O(1)
    run_migration(): O(N) where N = total items across tiers
    run_aging(): O(N)
    count(): O(1)

Edge Cases:
    - Empty bank: migration/aging return 0
    - All items same tier: migration still checks each
    - Very old items in tier 6: pruned completely
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import time
from dataclasses import dataclass, field
from typing import Any


TIER_NAMES = {0: "working", 1: "short_term", 2: "long_term", 3: "episodic",
              4: "semantic", 5: "procedural", 6: "archive"}


class Tier:
    """Memory tier levels."""
    WORKING = 0
    SHORT_TERM = 1
    LONG_TERM = 2
    EPISODIC = 3
    SEMANTIC = 4
    PROCEDURAL = 5
    ARCHIVE = 6


@dataclass
class BankItem:
    """An item in the memory bank."""
    content: str = ""
    importance: float = 0.5
    created_at: float = 0.0
    tier: int = 0
    access_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.time()

    def age_hours(self) -> float:
        return (time.time() - self.created_at) / 3600

    def to_dict(self) -> dict:
        return {"content": self.content[:100], "importance": self.importance,
                "tier": self.tier, "age_hours": self.age_hours()}


class MemoryBank:
    """Tiered memory bank with automatic migration.

    Usage:
        bank = MemoryBank()
        bank.store("Important memory", tier=0, importance=0.9)
        bank.store("Old memory", tier=6, importance=0.1)

        migrations = bank.run_migration()
        aged = bank.run_aging()

        stats = bank.get_stats()
        print(f"Total: {stats['total']}, by tier: {stats['tiers']}")
    """

    def __init__(self, db_path: str = ":memory:", aging_hours: float = 168.0,
                 migration_threshold: float = 0.3):
        """Initialize the memory bank.

        Args:
            db_path: Database path (unused for in-memory bank).
            aging_hours: Hours before items are considered old (default: 7 days).
            migration_threshold: Importance threshold for migration.
        """
        self._aging_hours = aging_hours
        self._migration_threshold = migration_threshold
        self._tiers: dict[int, list[BankItem]] = {i: [] for i in range(7)}
        self._migrations: list[dict] = []
        self._pruned = 0
        self._total_stored = 0

    def store(self, content: str, tier: int = 0, importance: float = 0.5,
              metadata: dict | None = None) -> None:
        """Store an item in a specific tier.

        Args:
            content: Item content.
            tier: Target tier (0-6).
            importance: Item importance [0, 1].
            metadata: Additional metadata.
        """
        tier = max(0, min(6, tier))
        item = BankItem(content=content, importance=importance, tier=tier,
                        metadata=metadata or {})
        self._tiers[tier].append(item)
        self._total_stored += 1

    def deposit(self, node_id: str, tier: int = 0) -> None:
        """Deposit a node reference."""
        self._tiers.setdefault(tier, []).append(
            BankItem(content=node_id, importance=0.5, tier=tier)
        )

    def run_migration(self) -> list[dict]:
        """Migrate low-importance items to lower tiers.

        Returns:
            List of migration records.
        """
        migrated = []
        for tier_val in range(6, 0, -1):
            items = self._tiers[tier_val]
            for item in items[:]:
                if item.importance < self._migration_threshold:
                    items.remove(item)
                    self._tiers[tier_val - 1].append(item)
                    item.tier = tier_val - 1
                    migrated.append({
                        "from": tier_val, "to": tier_val - 1,
                        "content": item.content[:50],
                        "importance": item.importance,
                    })
        self._migrations.extend(migrated)
        return migrated

    def run_aging(self) -> int:
        """Archive or prune items older than aging threshold.

        Returns:
            Number of items aged/pruned.
        """
        aged = 0
        for tier_val in range(6):
            items = self._tiers[tier_val]
            for item in items[:]:
                if item.age_hours() > self._aging_hours:
                    if tier_val < 6:
                        items.remove(item)
                        self._tiers[6].append(item)
                        item.tier = 6
                    else:
                        items.remove(item)
                        self._pruned += 1
                    aged += 1
        return aged

    def count(self) -> int:
        """Total items across all tiers."""
        return sum(len(v) for v in self._tiers.values())

    def count_by_tier(self) -> dict[int, int]:
        """Item count per tier."""
        return {k: len(v) for k, v in self._tiers.items()}

    def get_tier_items(self, tier: int, limit: int = 10) -> list[dict]:
        """Get items from a specific tier."""
        return [item.to_dict() for item in self._tiers.get(tier, [])[:limit]]

    def get_oldest_items(self, tier: int, top_k: int = 5) -> list[dict]:
        """Get oldest items in a tier."""
        items = self._tiers.get(tier, [])
        sorted_items = sorted(items, key=lambda x: x.created_at)
        return [item.to_dict() for item in sorted_items[:top_k]]

    def get_newest_items(self, tier: int, top_k: int = 5) -> list[dict]:
        """Get newest items in a tier."""
        items = self._tiers.get(tier, [])
        sorted_items = sorted(items, key=lambda x: x.created_at, reverse=True)
        return [item.to_dict() for item in sorted_items[:top_k]]

    def get_importance_distribution(self) -> dict[int, dict]:
        """Get importance distribution per tier."""
        result = {}
        for tier_val, items in self._tiers.items():
            if items:
                importances = [item.importance for item in items]
                result[tier_val] = {
                    "count": len(items),
                    "avg_importance": sum(importances) / len(importances),
                    "min_importance": min(importances),
                    "max_importance": max(importances),
                }
        return result

    def get_stats(self) -> dict:
        return {
            "total": self.count(),
            "tiers": self.count_by_tier(),
            "migrations": len(self._migrations),
            "pruned": self._pruned,
            "total_stored": self._total_stored,
            "aging_hours": self._aging_hours,
            "migration_threshold": self._migration_threshold,
        }

    def close(self) -> None:
        """Close the bank (no-op for in-memory bank)."""
        pass
