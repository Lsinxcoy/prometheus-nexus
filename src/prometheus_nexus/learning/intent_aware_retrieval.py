"""SimpleMem — 3-stage semantic compression + intent-aware retrieval pipeline.

Based on arXiv 2601.02553 (SimpleMem: Efficient Lifelong Memory for LLM Agents).

Pipeline:
    Stage 1 (SemanticStructuredCompressor):
        Distills unstructured interactions into compact, multi-view indexed
        memory units. Extracts entities, events, temporal markers, and actions
        via regex+NLP heuristics, then structures each sentence as a
        StructuredUnit with multi-views (entity/event/time/action).

    Stage 2 (OnlineSemanticSynthesis):
        Intra-session process that merges related memory units into unified
        abstract representations. Deduplicates by cosine similarity of
        entity/event/time signatures and temporally proximal units.

    Stage 3 (IntentAwareRetrieval):
        Intent classification becomes the retrieval PLANNER. Instead of
        directly filtering results, the inferred intent dynamically determines
        which views to search (entity/event/temporal/action), how broadly to
        search, and how to rank results.

Usage:
    sm = SimpleMem()
    units = sm.compress("long conversation text...")
    synthesized = sm.synthesize(units)
    results = sm.retrieve("what did we discuss about project X?")
"""

from __future__ import annotations
import logging
import math
import re
import time
from collections import Counter, defaultdict
from typing import Any

logger = logging.getLogger(__name__)

# ── Intent classification patterns ──
_INTENT_PATTERNS = {
    "factual": [
        "what is", "who is", "where is", "when did", "how many",
        "define", "explain", "describe", "what are", "what was",
    ],
    "conceptual": [
        "how does", "why does", "what causes", "relationship between",
        "compare", "difference", "how are", "what is the reason",
        "explain how", "mechanism",
    ],
    "operational": [
        "how to", "steps to", "procedure", "instructions", "guide",
        "tutorial", "way to", "process for", "method for",
    ],
    "affective": [
        "i feel", "i think", "opinion", "recommend", "suggest",
        "prefer", "like", "what do you think", "how do you feel",
    ],
}

# ── Regex patterns for structured extraction ──
_ENTITY_PATTERN = re.compile(r"\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)*(?:\s[A-Z][a-z]+)*\b")
_TEMPORAL_PATTERN = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|"
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}|\d{4})\b"
)
_EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.+-]+\b")
_URL_PATTERN = re.compile(r"https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[^\s]*", re.IGNORECASE)
_ACTION_PATTERN = re.compile(
    r"\b(?:run|execute|call|invoke|created?|deleted?|updated?|written?|"
    r"read|sending?|received?|start(?:ed|ing)?|stop(?:ped|ing)?|"
    r"restart(?:ed|ing)?|install(?:ed|ing)?|configur(?:e|ed|ing)|"
    r"build(?:ing|t)?|deploy(?:ed|ing)?|test(?:ed|ing)?|analyz(?:e|ed|ing)|"
    r"comput(?:e|ed|ing)|train(?:ed|ing)?|sav(?:e|ed|ing)|load(?:ed|ing)?|"
    r"import(?:ed|ing)?|export(?:ed|ing)?|launch(?:ed|ing)?)\b",
    re.IGNORECASE,
)
_NUMERIC_PATTERN = re.compile(r"\b(\d+[.,]?\d*)\b")
_EVENT_TRIGGER_PATTERN = re.compile(
    r"\b(?:happened|occurred|took place|was held|was conducted|"
    r"resulted in|caused|triggered|led to)\b",
    re.IGNORECASE,
)


# ===========================================================================
#  StructuredUnit — a single multi-view indexed memory unit
# ===========================================================================

class StructuredUnit:
    """A compact, multi-view indexed memory unit.

    Attributes:
        content: Compressed text representation.
        entities: Extracted named entities (people, places, organizations).
        events: Extracted event descriptions.
        temporal: Temporal markers (dates, times).
        actions: Extracted action verbs/operations.
        metadata: Additional metadata (source, timestamp, confidence).
    """

    def __init__(
        self,
        content: str,
        entities: list[str] | None = None,
        events: list[str] | None = None,
        temporal: list[str] | None = None,
        actions: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.content = content
        self.entities = entities or []
        self.events = events or []
        self.temporal = temporal or []
        self.actions = actions or []
        self.metadata = metadata or {}

    def views(self) -> dict[str, list[str]]:
        """Return all views as a dict."""
        return {
            "entities": self.entities,
            "events": self.events,
            "temporal": self.temporal,
            "actions": self.actions,
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "content": self.content,
            "entities": self.entities,
            "events": self.events,
            "temporal": self.temporal,
            "actions": self.actions,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StructuredUnit:
        """Deserialize from dict."""
        return cls(
            content=d["content"],
            entities=d.get("entities", []),
            events=d.get("events", []),
            temporal=d.get("temporal", []),
            actions=d.get("actions", []),
            metadata=d.get("metadata", {}),
        )

    def view_signature(self) -> str:
        """A signature string for deduplication: sorted entity+event+action."""
        parts = sorted(self.entities) + sorted(self.events) + sorted(self.actions)
        return "|".join(parts[:20])

    def __repr__(self) -> str:
        return (
            f"StructuredUnit(content={self.content[:60]!r}, "
            f"entities={self.entities[:3]}...)"
        )


# ===========================================================================
#  Stage 1: Semantic Structured Compression
# ===========================================================================

class SemanticStructuredCompressor:
    """Stage 1: Semantic Structured Compression.

    Distills unstructured interactions into compact, multi-view indexed memory
    units. Each sentence is parsed for entities, temporal markers, actions,
    and event descriptions.

    Compression strategy:
        - Sentence-level segmentation
        - Multi-view extraction (entity/event/time/action)
        - Filter low-information sentences (too short, too generic)
        - Keep structured units up to max_units
    """

    MIN_SENTENCE_LENGTH = 20

    def __init__(self, max_units: int = 100) -> None:
        self.max_units = max_units

    # ── Public API ──

    def compress(self, text: str) -> list[StructuredUnit]:
        """Compress raw text into structured memory units.

        Args:
            text: Raw unstructured text to compress.

        Returns:
            List of StructuredUnit instances.
        """
        if not text or not text.strip():
            return []

        sentences = self._split_sentences(text)
        units: list[StructuredUnit] = []

        for sent in sentences:
            sent = sent.strip()
            if len(sent) < self.MIN_SENTENCE_LENGTH:
                continue

            entities = self._extract_entities(sent)
            temporal = self._extract_temporal(sent)
            actions = self._extract_actions(sent)
            events = self._extract_events(sent, entities, actions)

            # Keep sentence if it has extractable content or is informative
            has_signal = bool(entities or temporal or actions or events)
            if not has_signal and len(sent) < 40:
                continue

            unit = StructuredUnit(
                content=sent,
                entities=entities[:8],
                events=events[:5],
                temporal=temporal[:3],
                actions=actions[:5],
                metadata={"length": len(sent)},
            )
            units.append(unit)

            if len(units) >= self.max_units:
                break

        # Fallback: if nothing extracted, create at least one unit
        if not units and text.strip():
            units.append(
                StructuredUnit(
                    content=text.strip()[:500],
                    entities=self._extract_entities(text)[:8],
                    temporal=self._extract_temporal(text)[:3],
                    actions=self._extract_actions(text)[:5],
                )
            )

        return units

    def compress_single(self, text: str) -> StructuredUnit:
        """Compress text into a single structured unit (for short text)."""
        entities = self._extract_entities(text)
        temporal = self._extract_temporal(text)
        actions = self._extract_actions(text)
        events = self._extract_events(text, entities, actions)
        return StructuredUnit(
            content=text[:500],
            entities=entities[:8],
            events=events[:5],
            temporal=temporal[:3],
            actions=actions[:5],
        )

    # ── Sentence splitting ──

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Split text into sentences using punctuation boundaries."""
        # Handle common abbreviations that shouldn't split
        text = re.sub(r"\b(Dr|Mr|Mrs|Ms|Prof|Sr|Jr|St|vs|etc)\.", r"\1<DOT>", text)
        # Split on sentence-ending punctuation
        parts = re.split(r"(?<=[.!?])\s+", text)
        # Restore dots
        parts = [p.replace("<DOT>", ".") for p in parts]
        return [p.strip() for p in parts if p.strip()]

    # ── View extractors ──

    @staticmethod
    def _extract_entities(text: str) -> list[str]:
        """Extract named entities (proper nouns with capital letters)."""
        found = _ENTITY_PATTERN.findall(text)
        # Filter out noise — words that are not proper entities
        filtered: list[str] = []
        for ent in found:
            # Skip single capitalized words that are common English
            if ent.lower() in {
                "the", "this", "that", "these", "those", "there", "their",
                "what", "when", "where", "which", "who", "whom", "whose",
                "a", "an", "and", "or", "but", "not", "for", "with",
                "it", "its", "they", "them", "we", "our", "you", "your",
            }:
                continue
            # Skip very long strings that are probably not entities
            if len(ent) > 80:
                # Could be an action sentence, extract potential entities from it
                words = ent.split()
                for w in words:
                    if w[0].isupper() and len(w) > 2 and w.lower() not in {
                        "the", "this", "that", "what", "when", "where"
                    }:
                        filtered.append(w)
                continue
            # Remove trailing punctuation
            ent_clean = ent.rstrip(".,;:!?)")
            if len(ent_clean) > 1:
                filtered.append(ent_clean)

        # Deduplicate preserving order
        seen: set[str] = set()
        result: list[str] = []
        for e in filtered:
            if e.lower() not in seen:
                seen.add(e.lower())
                result.append(e)
        return result

    @staticmethod
    def _extract_temporal(text: str) -> list[str]:
        """Extract temporal markers (dates, years, timestamps)."""
        found = _TEMPORAL_PATTERN.findall(text)
        return list(dict.fromkeys(found))  # dedup preserving order

    @staticmethod
    def _extract_actions(text: str) -> list[str]:
        """Extract action verbs/operations."""
        found = _ACTION_PATTERN.findall(text)
        # Normalize to lowercase
        normalized = [a.lower() for a in found]
        return list(dict.fromkeys(normalized))

    @staticmethod
    def _extract_events(text: str, entities: list[str], actions: list[str]) -> list[str]:
        """Extract event descriptions combining entities + actions + triggers."""
        events: list[str] = []

        # Check for event trigger words
        has_event_trigger = bool(_EVENT_TRIGGER_PATTERN.search(text))

        # If entities and actions co-occur, it's likely an event
        if entities and actions:
            # Build event description from entity + action pairs
            for action in actions[:3]:
                for entity in entities[:3]:
                    event_desc = f"{action}: {entity}"
                    events.append(event_desc)

        # If explicit event trigger, include the sentence subject
        if has_event_trigger:
            # Try to extract the subject (first noun phrase)
            match = re.match(
                r"\b(The\s+)?([A-Z][a-z]+[\sA-Za-z]*?)\s+(?:has|have|was|were|is|are)\s+",
                text,
            )
            if match:
                events.append(match.group(2).strip())

        return events


# ===========================================================================
#  Stage 2: Online Semantic Synthesis
# ===========================================================================

class OnlineSemanticSynthesis:
    """Stage 2: Online Semantic Synthesis.

    Intra-session process that merges related memory units into unified
    abstract representations. Uses signature-based deduplication and
    temporal proximity to detect related units.

    Merge strategies:
        1. Signature match: identical entity/event/action signatures → merge
        2. Entity overlap: >50% entity overlap → group and summarize
        3. Temporal proximity: units within a time window → synthesize
    """

    def __init__(
        self,
        similarity_threshold: float = 0.5,
        temporal_window: float = 300.0,  # 5 minutes in seconds
        max_synthesized: int = 50,
    ) -> None:
        self.similarity_threshold = similarity_threshold
        self.temporal_window = temporal_window
        self.max_synthesized = max_synthesized
        self._session_units: list[StructuredUnit] = []
        self._session_time: list[float] = []

    # ── Public API ──

    def synthesize(self, units: list[StructuredUnit]) -> list[StructuredUnit]:
        """Synthesize a batch of units, merging related ones.

        Args:
            units: List of StructuredUnit from Stage 1.

        Returns:
            Synthesized (deduplicated, merged) list of StructuredUnit.
        """
        if not units:
            return []

        # Update session state
        now = time.time()
        self._session_units.extend(units)
        self._session_time.extend([now] * len(units))

        # Merge pipeline
        merged = self._deduplicate_by_signature(units)
        merged = self._merge_by_entity_overlap(merged)
        merged = self._synthesize_recent_window(now, merged)

        # Limit output
        return merged[: self.max_synthesized]

    def get_session_state(self) -> dict[str, Any]:
        """Get current session synthesis state."""
        return {
            "total_units_seen": len(self._session_units),
            "current_synthesized": len(self._session_units),
        }

    def reset_session(self) -> None:
        """Reset session tracking."""
        self._session_units.clear()
        self._session_time.clear()

    # ── Internal methods ──

    @staticmethod
    def _deduplicate_by_signature(units: list[StructuredUnit]) -> list[StructuredUnit]:
        """Remove units with identical view signatures (keep first)."""
        seen: set[str] = set()
        result: list[StructuredUnit] = []
        for u in units:
            sig = u.view_signature()
            if sig and sig in seen:
                continue
            if sig:
                seen.add(sig)
            result.append(u)
        return result

    def _merge_by_entity_overlap(self, units: list[StructuredUnit]) -> list[StructuredUnit]:
        """Merge units with significant entity overlap."""
        if len(units) < 2:
            return units

        merged: list[StructuredUnit] = []
        used: set[int] = set()

        for i, u1 in enumerate(units):
            if i in used:
                continue
            cluster: list[StructuredUnit] = [u1]
            used.add(i)

            for j, u2 in enumerate(units):
                if j in used:
                    continue
                if self._entity_overlap(u1, u2) >= self.similarity_threshold:
                    cluster.append(u2)
                    used.add(j)

            if len(cluster) > 1:
                merged.append(self._merge_cluster(cluster))
            else:
                merged.append(u1)

        return merged

    def _synthesize_recent_window(
        self, now: float, units: list[StructuredUnit]
    ) -> list[StructuredUnit]:
        """Synthesize units within the temporal window into combined summaries."""
        if len(units) < 2:
            return units

        # Units are not timestamped individually here;
        # this is a placeholder for temporal proximity merging.
        # For a production system, each unit would carry a timestamp.
        return units

    @staticmethod
    def _entity_overlap(u1: StructuredUnit, u2: StructuredUnit) -> float:
        """Compute Jaccard overlap between entity sets."""
        e1 = set(e.lower() for e in u1.entities)
        e2 = set(e.lower() for e in u2.entities)
        if not e1 or not e2:
            return 0.0
        intersection = e1 & e2
        union = e1 | e2
        return len(intersection) / max(len(union), 1)

    @staticmethod
    def _merge_cluster(cluster: list[StructuredUnit]) -> StructuredUnit:
        """Merge a cluster of related units into one."""
        all_entities: list[str] = []
        all_events: list[str] = []
        all_temporal: list[str] = []
        all_actions: list[str] = []
        contents: list[str] = []

        seen_entities: set[str] = set()
        seen_events: set[str] = set()
        seen_temporal: set[str] = set()
        seen_actions: set[str] = set()

        for unit in cluster:
            if unit.content not in contents:
                contents.append(unit.content)
            for e in unit.entities:
                if e.lower() not in seen_entities:
                    seen_entities.add(e.lower())
                    all_entities.append(e)
            for e in unit.events:
                key = e.lower()
                if key not in seen_events:
                    seen_events.add(key)
                    all_events.append(e)
            for t in unit.temporal:
                if t not in seen_temporal:
                    seen_temporal.add(t)
                    all_temporal.append(t)
            for a in unit.actions:
                if a not in seen_actions:
                    seen_actions.add(a)
                    all_actions.append(a)

        # Create merged content summary
        if len(contents) > 1:
            merged_content = " | ".join(contents)
        else:
            merged_content = contents[0] if contents else ""

        return StructuredUnit(
            content=merged_content[:500],
            entities=all_entities[:8],
            events=all_events[:5],
            temporal=all_temporal[:3],
            actions=all_actions[:5],
            metadata={
                "merged_from": len(cluster),
                "merge_strategy": "entity_overlap",
            },
        )


# ===========================================================================
#  Stage 3: Intent-Aware Retrieval Planning
# ===========================================================================

_INTENT_VIEW_WEIGHTS: dict[str, dict[str, float]] = {
    "factual": {"entities": 0.5, "events": 0.2, "temporal": 0.2, "actions": 0.1},
    "conceptual": {"entities": 0.3, "events": 0.4, "temporal": 0.1, "actions": 0.2},
    "operational": {"entities": 0.2, "events": 0.3, "temporal": 0.1, "actions": 0.4},
    "affective": {"entities": 0.4, "events": 0.3, "temporal": 0.1, "actions": 0.2},
}

_INTENT_SCOPE_MULTIPLIER: dict[str, float] = {
    "factual": 1.0,
    "conceptual": 1.5,
    "operational": 0.8,
    "affective": 1.2,
}


class IntentAwareRetrieval:
    """Stage 3: Intent-Aware Retrieval (formerly just IntentAwareRetrieval).

    Intent classification serves as the retrieval PLANNER — it determines:
        - Which views to search (entity/event/temporal/action weights)
        - How broadly to search (scope multiplier)
        - How to rank results (view-weighted scoring)

    This replaces the old approach where intent was just a label on results.
    """

    def __init__(
        self,
        retriever: Any | None = None,
        compressor: SemanticStructuredCompressor | None = None,
        synthesizer: OnlineSemanticSynthesis | None = None,
    ) -> None:
        self._retriever = retriever
        self._compressor = compressor or SemanticStructuredCompressor()
        self._synthesizer = synthesizer or OnlineSemanticSynthesis()
        self._intent_counts: dict[str, int] = {}
        self._total_queries = 0

    # ── Intent Classification ──

    def classify_intent(self, query: str) -> str:
        """Classify query intent (factual/conceptual/operational/affective).

        Args:
            query: The user query string.

        Returns:
            Intent label string.
        """
        q = query.lower().strip()
        best_intent = "factual"
        best_score = 0
        for intent, patterns in _INTENT_PATTERNS.items():
            score = sum(1 for p in patterns if p in q)
            if score > best_score:
                best_score = score
                best_intent = intent
        self._intent_counts[best_intent] = self._intent_counts.get(best_intent, 0) + 1
        self._total_queries += 1
        return best_intent

    # ── Stage 1: Compress ──

    def compress(self, content: str) -> list[StructuredUnit]:
        """Run Stage 1: Semantic Structured Compression.

        Args:
            content: Raw text to compress.

        Returns:
            List of StructuredUnit.
        """
        return self._compressor.compress(content)

    def compress_single(self, content: str) -> StructuredUnit:
        """Compress short content into a single structured unit."""
        return self._compressor.compress_single(content)

    # ── Stage 2: Synthesize ──

    def synthesize(self, units: list[StructuredUnit]) -> list[StructuredUnit]:
        """Run Stage 2: Online Semantic Synthesis on a batch of units.

        Args:
            units: Structured units from Stage 1.

        Returns:
            Synthesized (merged) units.
        """
        return self._synthesizer.synthesize(units)

    # ── Stage 3: Retrieve ──

    def retrieve(
        self, query: str, limit: int = 10, index: list[StructuredUnit] | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        """Intent-aware retrieval with multi-view scoring.

        The intent classification drives a retrieval PLAN:
            1. Classify intent
            2. Compute view weights from intent
            3. Extract query views (entities, temporal, actions)
            4. If index provided, score each index unit by weighted view match
            5. Rank and return top results

        Args:
            query: User query string.
            limit: Max results to return.
            index: Optional list of StructuredUnit to search. If None, falls
                   back to _retriever callable.

        Returns:
            Dict with keys: intent, results, query, plan, entities, temporal.
        """
        intent = self.classify_intent(query)

        # Build retrieval plan from intent
        view_weights = _INTENT_VIEW_WEIGHTS.get(intent, _INTENT_VIEW_WEIGHTS["factual"])
        scope_mult = _INTENT_SCOPE_MULTIPLIER.get(intent, 1.0)

        # Extract query views
        query_entities = set(e.lower() for e in self._compressor._extract_entities(query))
        query_temporal = self._compressor._extract_temporal(query)
        query_actions = self._compressor._extract_actions(query)

        plan = {
            "intent": intent,
            "view_weights": view_weights,
            "scope_multiplier": scope_mult,
            "effective_limit": max(1, int(limit * scope_mult)),
        }

        results: list[dict[str, Any]] = []

        if index is not None:
            # Score each indexed unit
            scored: list[tuple[float, StructuredUnit]] = []
            for unit in index:
                score = self._score_unit_for_query(
                    unit, query_entities, query_temporal, query_actions, view_weights
                )
                if score > 0:
                    scored.append((score, unit))
            scored.sort(key=lambda x: x[0], reverse=True)
            top_k = scored[: plan["effective_limit"]]
            results = [
                {"unit": u.to_dict(), "score": round(s, 4)} for s, u in top_k
            ]

        elif self._retriever:
            # Fallback to external retriever
            raw_results = self._retriever(query, limit=plan["effective_limit"], **kwargs)
            results = list(raw_results) if raw_results else []

        return {
            "intent": intent,
            "results": results,
            "query": query,
            "plan": plan,
            "entities": list(query_entities)[:10],
            "temporal": query_temporal[:5],
        }

    # ── Full pipeline convenience ──

    def pipeline(
        self,
        content: str,
        query: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Run the full SimpleMem 3-stage pipeline.

        Args:
            content: Raw text to compress and index.
            query: Optional query for retrieval (if None, only compress+synthesize).
            limit: Max results if retrieving.

        Returns:
            Dict with stage outputs.
        """
        # Stage 1
        units = self.compress(content)

        # Stage 2
        synthesized = self.synthesize(units)

        result: dict[str, Any] = {
            "stage1_compressed": [u.to_dict() for u in units],
            "stage2_synthesized": [u.to_dict() for u in synthesized],
            "stage1_count": len(units),
            "stage2_count": len(synthesized),
        }

        # Stage 3 (if query provided)
        if query:
            retrieval = self.retrieve(query, limit=limit, index=synthesized)
            result["stage3_retrieval"] = retrieval

        return result

    # ── Internal helpers ──

    @staticmethod
    def _score_unit_for_query(
        unit: StructuredUnit,
        query_entities: set[str],
        query_temporal: list[str],
        query_actions: list[str],
        view_weights: dict[str, float],
    ) -> float:
        """Score a StructuredUnit against query views with intent weights."""
        score = 0.0

        # Entity match
        if query_entities:
            unit_entities = set(e.lower() for e in unit.entities)
            ent_overlap = len(query_entities & unit_entities)
            ent_max = max(len(query_entities), 1)
            score += view_weights.get("entities", 0.25) * (ent_overlap / ent_max)

        # Temporal match
        if query_temporal and unit.temporal:
            unit_temporal = set(t.lower() for t in unit.temporal)
            temp_overlap = sum(
                1 for qt in query_temporal if qt.lower() in unit_temporal
            )
            temp_max = max(len(query_temporal), 1)
            score += view_weights.get("temporal", 0.25) * (temp_overlap / temp_max)

        # Action match
        if query_actions and unit.actions:
            unit_actions = set(a.lower() for a in unit.actions)
            act_overlap = len(set(query_actions) & unit_actions)
            act_max = max(len(query_actions), 1)
            score += view_weights.get("actions", 0.25) * (act_overlap / act_max)

        return score

    # ── Stats ──

    def get_stats(self) -> dict[str, Any]:
        """Get retrieval statistics."""
        return {
            "total_queries": self._total_queries,
            "intent_distribution": dict(self._intent_counts),
            "compressor": "SemanticStructuredCompressor",
            "synthesizer": "OnlineSemanticSynthesis",
        }


# ===========================================================================
#  Convenience alias
# ===========================================================================

SimpleMem = IntentAwareRetrieval
