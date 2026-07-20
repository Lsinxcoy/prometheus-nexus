"""ProgressiveCheckpoints — Three-tier progressive state saving.

Based on: MiMo Self-Evolution System #八 (Working Buffer Protocol)

Key insight from MiMo: "渐进式保存比单点60%保存信息丢失率低60%"

Three tiers:
    Level 1 (20% context): Light save — key decisions + current task state
    Level 2 (45% context): Medium save — full state + plan + key snippets
    Level 3 (70% context): Heavy save — full compression + state file, prepare rebuild

Recovery order:
    1. Read working buffer → restore work state
    2. Read session state → restore continuity
    3. Read memory rules → restore behavior rules
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import time
from dataclasses import dataclass, field


@dataclass
class CheckpointData:
    level: int = 0
    context_usage: float = 0.0
    content: dict = field(default_factory=dict)
    timestamp: float = 0.0
    compressed: bool = False


class ProgressiveCheckpoints:
    """Three-tier progressive state saving.

    Based on MiMo Self-Evolution System.

    Usage:
        pc = ProgressiveCheckpoints()

        # At 20% context usage
        pc.save_checkpoint(level=1, context_usage=0.20,
                          content={"task": "analyze memory", "status": "in_progress"})

        # At 45% context usage
        pc.save_checkpoint(level=2, context_usage=0.45,
                          content={"task": "analyze memory", "plan": "step 3 of 5",
                                   "key_fragments": ["insight A", "insight B"]})

        # At 70% context usage
        pc.save_checkpoint(level=3, context_usage=0.70,
                          content={"full_state": True, "ready_for_rebuild": True})

        # Recovery
        state = pc.recover()
    """

    LEVEL_DESCRIPTIONS = {
        1: "Light save: key decisions + current task state",
        2: "Medium save: full state + plan + key snippets",
        3: "Heavy save: full compression + state file, prepare rebuild",
    }

    def __init__(self):
        self._checkpoints: list[CheckpointData] = []
        self._stats = {"saves": 0, "recovers": 0}

    def save_checkpoint(self, level: int, context_usage: float,
                        content: dict) -> CheckpointData:
        """Save a checkpoint at the specified level.

        Level 1 (20%): Save only critical decisions
        Level 2 (45%): Save full working state
        Level 3 (70%): Save everything for rebuild
        """
        checkpoint = CheckpointData(
            level=level,
            context_usage=context_usage,
            content=content,
            timestamp=time.time(),
            compressed=(level >= 3),
        )

        self._checkpoints.append(checkpoint)
        self._stats["saves"] += 1

        return checkpoint

    def should_save(self, context_usage: float) -> int | None:
        """Determine if a checkpoint should be saved based on context usage.

        Returns level (1/2/3) or None if no save needed.
        """
        if context_usage >= 0.70:
            return 3
        elif context_usage >= 0.45:
            return 2
        elif context_usage >= 0.20:
            return 1
        return None

    def recover(self) -> dict | None:
        """Recover state from the most recent checkpoint.

        Recovery order:
        1. Read level 3 (full state)
        2. Read level 2 (working state)
        3. Read level 1 (decisions)
        """
        if not self._checkpoints:
            return None

        # Find most recent checkpoint of each level
        latest = {}
        for cp in reversed(self._checkpoints):
            if cp.level not in latest:
                latest[cp.level] = cp

        # Merge from highest to lowest level
        recovered = {}
        for level in sorted(latest.keys(), reverse=True):
            cp = latest[level]
            recovered.update(cp.content)

        self._stats["recovers"] += 1
        return recovered

    def get_checkpoints(self) -> list[dict]:
        """Get all checkpoints."""
        return [{"level": cp.level, "usage": cp.context_usage,
                 "timestamp": cp.timestamp, "compressed": cp.compressed}
                for cp in self._checkpoints]

    def get_stats(self) -> dict:
        return dict(self._stats)
