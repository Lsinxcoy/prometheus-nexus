"""MemoryStream — Real-time memory event stream with windowing.

基于:
- Kleppmann (2017) Designing Data-Intensive Applications: 不可变日志 + 滑动窗口
  - 追加日志: 事件按时间戳顺序追加, 不可修改
  - 滑动窗口: max_size限制, 超限时头部截断并同步更新计数器
  - 事件类型过滤: 按event_type快速检索, 支持recent(n, type)
  - 重要性聚合: total_importance累加, 支持avg_importance统计

算法:
    add(event_type, content, importance):
        1. 创建StreamEvent(含时间戳)
        2. 追加到stream, 更新type_counts
        3. 超过max_size→截断头部, 同步修正计数器

来源: Omega系统 memory stream 实时记忆流模块 + 数据密集型应用设计
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import re
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StreamEvent:
    """A memory stream event."""
    event_type: str = ""
    content: str = ""
    importance: float = 0.5
    timestamp: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class MemoryStream:
    """Real-time memory event stream.

    Usage:
        stream = MemoryStream(max_size=10000)
        stream.add("remember", "AI research finding", importance=0.8)
        stream.add("recall", "Found relevant paper", importance=0.6)

        recent = stream.recent(10)
        count = stream.get_count("remember")
        stats = stream.get_stats()
    """

    def __init__(self, max_size: int = 10000):
        """Initialize the memory stream.

        Args:
            max_size: Maximum events to keep.
        """
        self._max_size = max_size
        self._stream: list[StreamEvent] = []
        self._type_counts: dict[str, int] = {}
        self._total_importance = 0.0

    def add(self, event_type: str, content: str, importance: float = 0.5,
            metadata: dict | None = None) -> None:
        """Add an event to the stream.

        Args:
            event_type: Event category (e.g., "remember", "recall").
            content: Event content.
            importance: Importance score [0, 1].
            metadata: Additional metadata.
        """
        event = StreamEvent(
            event_type=event_type, content=content,
            importance=importance, timestamp=time.time(),
            metadata=metadata or {},
        )
        self._stream.append(event)
        self._type_counts[event_type] = self._type_counts.get(event_type, 0) + 1
        self._total_importance += importance

        # Window truncation
        if len(self._stream) > self._max_size:
            removed = self._stream[:len(self._stream) - self._max_size]
            self._stream = self._stream[-self._max_size:]
            for r in removed:
                self._type_counts[r.event_type] = self._type_counts.get(r.event_type, 0) - 1
                self._total_importance -= r.importance

    def recent(self, n: int = 10, event_type: str | None = None) -> list[dict]:
        """Get recent events.

        Args:
            n: Maximum events to return.
            event_type: Filter by event type.

        Returns:
            List of event dicts.
        """
        events = self._stream
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        return [{"type": e.event_type, "content": e.content[:200],
                 "importance": e.importance, "ts": e.timestamp,
                 "metadata": e.metadata}
                for e in events[-n:]]

    def get_count(self, event_type: str | None = None) -> int:
        """Get event count.

        Args:
            event_type: If specified, count only this type.

        Returns:
            Event count.
        """
        if event_type:
            return self._type_counts.get(event_type, 0)
        return len(self._stream)

    def get_type_distribution(self) -> dict[str, int]:
        """Get event type distribution."""
        return dict(self._type_counts)

    def get_avg_importance(self) -> float:
        """Get average importance across all events."""
        return self._total_importance / max(len(self._stream), 1)

    def search_content(self, query: str, limit: int = 10) -> list[dict]:
        """Search events by content.

        Args:
            query: Search query.
            limit: Maximum results.

        Returns:
            List of matching events.
        """
        query_lower = query.lower()
        matches = []
        for e in self._stream:
            if query_lower in e.content.lower():
                matches.append({"type": e.event_type, "content": e.content[:200],
                                "importance": e.importance, "ts": e.timestamp})
        return matches[-limit:]

    def get_stats(self) -> dict:
        return {
            "stream_size": len(self._stream),
            "max_size": self._max_size,
            "type_counts": dict(self._type_counts),
            "total_events": sum(self._type_counts.values()),
            "avg_importance": self.get_avg_importance(),
        }

    # ── Temporal Weighting + Primacy Bias (B3-4, arXiv 2603.00270) ──────────

    def apply_recency_bias(self, results: list[dict]) -> list[dict]:
        """Apply recency bias to retrieval results.

        Each result dict should have 'utility' and 'created_at' keys.
        weight = min(1.0, max(0.1, 1.0 - elapsed_hours * 0.01))
        final_score = utility * recency
        Returns results sorted by final_score descending.
        """
        now = time.time()
        for r in results:
            created = r.get("created_at", now)
            elapsed_hours = max(0.0, (now - created) / 3600.0)
            recency = max(0.1, min(1.0, 1.0 - elapsed_hours * 0.01))
            utility = r.get("utility", 0.5)
            r["recency_score"] = round(recency, 4)
            r["final_score"] = round(utility * recency, 4)
        results.sort(key=lambda x: x["final_score"], reverse=True)
        return results

    def get_primacy_risk(self, results: list[dict]) -> dict:
        """Assess primacy bias risk.

        High risk: old AND frequently accessed result dominating top position.
        """
        if not results:
            return {"risk": 0.0, "dominated_by": "", "domination_score": 0.0}
        top = results[0]
        now = time.time()
        created = top.get("created_at", now)
        age_days = max(0.0, (now - created) / 86400.0)
        access_count = top.get("access_count", 0)
        risk = min(1.0, (age_days / 30.0) * min(1.0, access_count / max(access_count, 10)))
        return {
            "risk": round(risk, 4),
            "dominated_by": top.get("id", top.get("node_id", "")),
            "domination_score": round(top.get("utility", 0.5) * risk, 4),
        }


# ---------------------------------------------------------------------------
# B3-4: Temporal weighting + conflict detection
# Based on arXiv 2603.00270 (Transformers Remember First, Forget Last):
#   Proactive interference dominates universally (Cohen's d=1.73, p<0.0001).
#   56% of errors come from primacy bias — architectural, not fixable by scaling.
# And arXiv 2606.08457 (Consistency Illusion):
#   Multi-agent debate creates consistency illusion: same answer, different paths.
# ---------------------------------------------------------------------------


def apply_temporal_weights(results: list[dict]) -> list[dict]:
    """Apply recency-bias temporal weights to a list of result dicts.

    Each result dict must have a ``ts`` key (Unix timestamp, float).
    Weight formula::

        weight = min(1.0, max(0.1, 1.0 - elapsed_hours * 0.01))

    where ``elapsed_hours`` is the wall-clock time between *now* and
    ``result["ts"]``.

    Parameters
    ----------
    results : list[dict]
        Each dict must contain at least ``"ts": float``.

    Returns
    -------
    list[dict]
        Results sorted by recency weight (highest first), each annotated with
        a ``"temporal_weight"`` key.
    """
    if not results:
        return []

    now = time.time()
    weighted = []
    for r in results:
        ts = r.get("ts", now)
        elapsed_hours = max(0.0, (now - ts) / 3600.0)
        weight = min(1.0, max(0.1, 1.0 - elapsed_hours * 0.01))
        weighted.append({**r, "temporal_weight": round(weight, 4)})

    weighted.sort(key=lambda x: x["temporal_weight"], reverse=True)
    return weighted


def detect_conflicts(results: list[dict]) -> list[dict]:
    """Detect logical contradictions between result dicts.

    Checks three types of conflict:
      1. **Opposing numerical values** — e.g. "70%" vs "30%"
      2. **Direct factual contradictions** — e.g. "is true" vs "is false"
      3. **Temporal inconsistencies** — e.g. "before X" vs "after X"

    Parameters
    ----------
    results : list[dict]
        Each dict must contain at least ``"content": str``. A ``"source_id"``
        or ``"id"`` key is used for conflict tracking; falls back to the
        result index as a string.

    Returns
    -------
    list[dict]
        Each conflict dict has the shape::

            {"type": str, "source_ids": list[str], "confidence": float}
    """
    conflicts: list[dict] = []

    if len(results) < 2:
        return conflicts

    _extract_id = lambda r, i: str(r.get("source_id") or r.get("id") or str(i))

    # --- 1. Opposing numerical values ----------------------------------------
    _NUM_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*%")
    for i in range(len(results)):
        for j in range(i + 1, len(results)):
            content_a = results[i].get("content", "")
            content_b = results[j].get("content", "")
            nums_a = _NUM_PATTERN.findall(content_a)
            nums_b = _NUM_PATTERN.findall(content_b)
            if nums_a and nums_b:
                for na_s in nums_a:
                    na = float(na_s)
                    for nb_s in nums_b:
                        nb = float(nb_s)
                        if 0.0 <= na <= 100.0 and 0.0 <= nb <= 100.0:
                            ratio = max(na, nb) / max(min(na, nb), 1e-9)
                            if ratio >= 2.0:
                                conflicts.append({
                                    "type": "numerical_opposition",
                                    "source_ids": [
                                        _extract_id(results[i], i),
                                        _extract_id(results[j], j),
                                    ],
                                    "confidence": min(1.0, (ratio - 1.0) / 5.0),
                                })

    # --- 2. Direct factual contradictions ------------------------------------
    _FACT_PAIRS = [
        (" is true", " is false"),
        (" is correct", " is incorrect"),
        (" is valid", " is invalid"),
        ("supports", "contradicts"),
        (" agrees", " disagrees"),
        (" confirmed", " disproved"),
        (" confirmed", " refuted"),
        (" proven", " disproven"),
    ]
    for i in range(len(results)):
        for j in range(i + 1, len(results)):
            content_a = results[i].get("content", "").lower()
            content_b = results[j].get("content", "").lower()
            for pos, neg in _FACT_PAIRS:
                pos_hit_a = pos in content_a
                neg_hit_b = neg in content_b
                pos_hit_b = pos in content_b
                neg_hit_a = neg in content_a
                if (pos_hit_a and neg_hit_b) or (pos_hit_b and neg_hit_a):
                    conflicts.append({
                        "type": "factual_contradiction",
                        "source_ids": [
                            _extract_id(results[i], i),
                            _extract_id(results[j], j),
                        ],
                        "confidence": 0.85,
                    })
                    break  # one conflict per pair is enough

    # --- 3. Temporal inconsistencies -----------------------------------------
    _TEMP_PATTERNS = [
        (r"\bbefore\s+(\w+)", r"\bafter\s+(\w+)"),
        (r"\bearlier\s+than\s+(\w+)", r"\blater\s+than\s+(\w+)"),
        (r"\bpreceding\s+(\w+)", r"\bfollowing\s+(\w+)"),
    ]
    for i in range(len(results)):
        for j in range(i + 1, len(results)):
            content_a = results[i].get("content", "").lower()
            content_b = results[j].get("content", "").lower()
            for before_pat, after_pat in _TEMP_PATTERNS:
                before_a = set(re.findall(before_pat, content_a))
                after_b = set(re.findall(after_pat, content_b))
                before_b = set(re.findall(before_pat, content_b))
                after_a = set(re.findall(after_pat, content_a))
                shared = (before_a & after_b) | (before_b & after_a)
                if shared:
                    conflicts.append({
                        "type": "temporal_inconsistency",
                        "source_ids": [
                            _extract_id(results[i], i),
                            _extract_id(results[j], j),
                        ],
                        "confidence": 0.75,
                    })
                    break

    return conflicts
