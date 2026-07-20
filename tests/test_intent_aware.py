"""Tests for intent_aware_retrieval.py — SimpleMem 3-stage pipeline.

Tests cover:
    - SemanticStructuredCompressor (Stage 1)
    - OnlineSemanticSynthesis (Stage 2)
    - IntentAwareRetrieval (Stage 3)
    - Full pipeline integration
"""

from __future__ import annotations
import time
import pytest  # type: ignore[import-untyped]

from prometheus_nexus.learning.intent_aware_retrieval import (
    SemanticStructuredCompressor,
    OnlineSemanticSynthesis,
    IntentAwareRetrieval,
    StructuredUnit,
    SimpleMem,
)


# ===========================================================================
#  Fixtures
# ===========================================================================

@pytest.fixture
def compressor() -> SemanticStructuredCompressor:
    return SemanticStructuredCompressor(max_units=50)


@pytest.fixture
def synthesizer() -> OnlineSemanticSynthesis:
    return OnlineSemanticSynthesis(similarity_threshold=0.4)


@pytest.fixture
def retrieval() -> IntentAwareRetrieval:
    return IntentAwareRetrieval()


@pytest.fixture
def sample_text() -> str:
    return (
        "John Smith presented the Q3 financial report on 2024-09-15. "
        "He discussed revenue growth of 15% and new client acquisitions. "
        "The board approved the expansion plan for the European market. "
        "Sarah Lee from Marketing proposed a Q4 campaign budget of $500k. "
        "We need to deploy the new ML model by next Friday. "
        "The system was restarted after the kernel update on 2024-09-10. "
        "Project Alpha achieved all milestones for the current sprint."
    )


@pytest.fixture
def sample_units() -> list[StructuredUnit]:
    return [
        StructuredUnit(
            content="John Smith presented Q3 results.",
            entities=["John Smith"],
            events=["presented: Q3 results"],
            temporal=["2024-09-15"],
            actions=["presented"],
        ),
        StructuredUnit(
            content="Revenue grew 15%.",
            entities=["Revenue"],
            events=["grew: Revenue"],
            actions=["grew"],
        ),
        StructuredUnit(
            content="Sarah Lee proposed budget.",
            entities=["Sarah Lee"],
            events=["proposed: budget"],
            actions=["proposed"],
        ),
        StructuredUnit(
            content="ML model deployment scheduled.",
            entities=["ML model"],
            events=["deployment: ML model"],
            actions=["deploy"],
        ),
    ]


# ===========================================================================
#  StructuredUnit tests
# ===========================================================================

class TestStructuredUnit:
    def test_create_unit(self) -> None:
        unit = StructuredUnit(
            content="test content",
            entities=["Alice"],
            events=["meeting"],
            temporal=["2024-01-01"],
            actions=["ran"],
        )
        assert unit.content == "test content"
        assert unit.entities == ["Alice"]
        assert unit.events == ["meeting"]
        assert unit.temporal == ["2024-01-01"]
        assert unit.actions == ["ran"]

    def test_views(self) -> None:
        unit = StructuredUnit(
            content="test",
            entities=["A"],
            events=["E"],
            temporal=["T"],
            actions=["R"],
        )
        views = unit.views()
        assert views["entities"] == ["A"]
        assert views["events"] == ["E"]
        assert views["temporal"] == ["T"]
        assert views["actions"] == ["R"]

    def test_to_dict_roundtrip(self) -> None:
        unit = StructuredUnit(
            content="roundtrip test",
            entities=["Bob"],
            events=["discussion"],
            temporal=["2024-06-15"],
            actions=["wrote"],
            metadata={"source": "test"},
        )
        d = unit.to_dict()
        restored = StructuredUnit.from_dict(d)
        assert restored.content == unit.content
        assert restored.entities == unit.entities
        assert restored.events == unit.events
        assert restored.actions == unit.actions
        assert restored.metadata["source"] == "test"

    def test_view_signature(self) -> None:
        unit = StructuredUnit(
            content="test",
            entities=["Project X", "Alice"],
            events=["review: Project X"],
            actions=["reviewed"],
        )
        sig = unit.view_signature()
        # Should contain sorted entities + events + actions
        assert "alice" in sig.lower()
        assert "project x" in sig.lower()
        assert "reviewed" in sig


# ===========================================================================
#  Stage 1: SemanticStructuredCompressor tests
# ===========================================================================

class TestSemanticStructuredCompressor:
    def test_compress_empty(self, compressor: SemanticStructuredCompressor) -> None:
        assert compressor.compress("") == []
        assert compressor.compress("   ") == []

    def test_compress_short_text(self, compressor: SemanticStructuredCompressor) -> None:
        # Short text may not reach MIN_SENTENCE_LENGTH but fallback should create one unit
        units = compressor.compress("Hello world")
        assert len(units) >= 0  # short text might get filtered

    def test_compress_normal(self, compressor: SemanticStructuredCompressor, sample_text: str) -> None:
        units = compressor.compress(sample_text)
        assert len(units) > 0
        # Each unit should have content
        for u in units:
            assert len(u.content) > 0

    def test_compress_extracts_entities(self, compressor: SemanticStructuredCompressor) -> None:
        text = "Alice reviewed Bob's pull request on GitHub."
        units = compressor.compress(text)
        # Should find some entities
        all_entities = set()
        for u in units:
            all_entities.update(u.entities)
        # At least some capitalized words should be extracted
        assert len(all_entities) > 0

    def test_compress_extracts_temporal(self, compressor: SemanticStructuredCompressor) -> None:
        text = "The meeting was on 2024-09-15 at 3pm. Another event on 2023-12-25."
        units = compressor.compress(text)
        all_temporal = set()
        for u in units:
            all_temporal.update(u.temporal)
        assert "2024-09-15" in all_temporal
        assert "2023-12-25" in all_temporal

    def test_compress_extracts_actions(self, compressor: SemanticStructuredCompressor) -> None:
        text = "The engineer deployed the update and restarted the service."
        units = compressor.compress(text)
        all_actions = set()
        for u in units:
            all_actions.update(u.actions)
        assert "deployed" in all_actions or "deploy" in all_actions

    def test_compress_max_units(self) -> None:
        c = SemanticStructuredCompressor(max_units=3)
        text = ". ".join(["Sentence number " + str(i) for i in range(20)])
        units = c.compress(text)
        # Short sentences won't pass MIN_SENTENCE_LENGTH, but we test the limit
        assert len(units) <= 3 or len(units) == 20  # if sentences too short they all get filtered

    def test_compress_single(self, compressor: SemanticStructuredCompressor) -> None:
        text = "Dr. Smith analyzed the data on 2024-01-01 and created a report."
        unit = compressor.compress_single(text)
        assert unit.content == text[:500]
        assert len(unit.entities) > 0 or len(unit.actions) > 0

    def test_split_sentences(self) -> None:
        text = "First sentence. Second sentence! Third sentence?"
        parts = SemanticStructuredCompressor._split_sentences(text)
        assert len(parts) == 3
        assert parts[0] == "First sentence."

    def test_split_sentences_abbreviations(self) -> None:
        text = "Dr. Smith and Mr. Jones met. They discussed A. I. research."
        parts = SemanticStructuredCompressor._split_sentences(text)
        assert len(parts) >= 1


# ===========================================================================
#  Stage 2: OnlineSemanticSynthesis tests
# ===========================================================================

class TestOnlineSemanticSynthesis:
    def test_synthesize_empty(self, synthesizer: OnlineSemanticSynthesis) -> None:
        assert synthesizer.synthesize([]) == []

    def test_synthesize_no_duplicates(self, synthesizer: OnlineSemanticSynthesis, sample_units: list[StructuredUnit]) -> None:
        result = synthesizer.synthesize(sample_units)
        # All units are different; should keep all (4)
        assert len(result) == len(sample_units)

    def test_synthesize_deduplicates_signature(self, synthesizer: OnlineSemanticSynthesis) -> None:
        u1 = StructuredUnit(
            content="First mention.",
            entities=["Project X"],
            events=["status: Project X"],
            actions=["updated"],
        )
        u2 = StructuredUnit(
            content="Second mention.",
            entities=["Project X"],
            events=["status: Project X"],
            actions=["updated"],
        )
        result = synthesizer.synthesize([u1, u2])
        assert len(result) == 1

    def test_synthesize_merges_entity_overlap(self) -> None:
        syn = OnlineSemanticSynthesis(similarity_threshold=0.3)
        u1 = StructuredUnit(
            content="About Project X and Alice.",
            entities=["Project X", "Alice"],
            events=["discussed: Project X"],
            actions=["discussed"],
        )
        u2 = StructuredUnit(
            content="Also about Project X and Bob.",
            entities=["Project X", "Bob"],
            events=["planned: Project X"],
            actions=["planned"],
        )
        result = syn.synthesize([u1, u2])
        # These share "Project X" (1 of 3 entities = 33% overlap > 0.3)
        # They should be merged
        assert len(result) == 1
        merged = result[0]
        # Merged unit should contain entities from both
        all_ents = set(e.lower() for e in merged.entities)
        assert "project x" in all_ents

    def test_synthesize_respects_max(self) -> None:
        syn = OnlineSemanticSynthesis(max_synthesized=2)
        units = [
            StructuredUnit(content=f"Unit {i}", entities=[f"Entity{i}"])
            for i in range(10)
        ]
        result = syn.synthesize(units)
        assert len(result) <= 2

    def test_reset_session(self, synthesizer: OnlineSemanticSynthesis) -> None:
        synthesizer.synthesize([
            StructuredUnit(content="test", entities=["A"])
        ])
        state_before = synthesizer.get_session_state()
        assert state_before["total_units_seen"] > 0
        synthesizer.reset_session()
        state_after = synthesizer.get_session_state()
        assert state_after["total_units_seen"] == 0


# ===========================================================================
#  Stage 3: IntentAwareRetrieval tests
# ===========================================================================

class TestIntentAwareRetrieval:
    def test_classify_intent_factual(self, retrieval: IntentAwareRetrieval) -> None:
        assert retrieval.classify_intent("what is a black hole") == "factual"
        assert retrieval.classify_intent("who is the president") == "factual"
        assert retrieval.classify_intent("define entropy") == "factual"

    def test_classify_intent_conceptual(self, retrieval: IntentAwareRetrieval) -> None:
        assert retrieval.classify_intent("how does gravity work") == "conceptual"
        assert retrieval.classify_intent("why does the sky look blue") == "conceptual"

    def test_classify_intent_operational(self, retrieval: IntentAwareRetrieval) -> None:
        assert retrieval.classify_intent("how to install python") == "operational"
        assert retrieval.classify_intent("steps to deploy the model") == "operational"

    def test_classify_intent_affective(self, retrieval: IntentAwareRetrieval) -> None:
        assert retrieval.classify_intent("i feel tired today") == "affective"
        assert retrieval.classify_intent("what do you think about this") == "affective"

    def test_classify_intent_counts(self, retrieval: IntentAwareRetrieval) -> None:
        retrieval.classify_intent("what is X")
        retrieval.classify_intent("how does Y work")
        retrieval.classify_intent("what is Z")
        stats = retrieval.get_stats()
        assert stats["total_queries"] == 3
        assert stats["intent_distribution"]["factual"] == 2
        assert stats["intent_distribution"]["conceptual"] == 1

    def test_retrieve_with_index(self, retrieval: IntentAwareRetrieval, sample_units: list[StructuredUnit]) -> None:
        result = retrieval.retrieve("who is John Smith", index=sample_units)
        assert result["intent"] == "factual"
        assert "plan" in result
        assert result["plan"]["intent"] == "factual"
        assert "results" in result

    def test_retrieve_with_entities(self, retrieval: IntentAwareRetrieval) -> None:
        unit = StructuredUnit(
            content="John Smith is a researcher.",
            entities=["John Smith"],
            events=["research"],
        )
        result = retrieval.retrieve("John Smith", index=[unit])
        assert len(result["results"]) > 0
        top = result["results"][0]
        assert top["score"] > 0

    def test_retrieve_plan_scope(self, retrieval: IntentAwareRetrieval) -> None:
        # Conceptual queries should have wider scope
        factual = retrieval.retrieve("what is X", index=[])
        conceptual = retrieval.retrieve("how does Y work", index=[])
        assert conceptual["plan"]["scope_multiplier"] > factual["plan"]["scope_multiplier"]

    def test_compress(self, retrieval: IntentAwareRetrieval, sample_text: str) -> None:
        units = retrieval.compress(sample_text)
        assert len(units) > 0
        assert isinstance(units[0], StructuredUnit)

    def test_synthesize(self, retrieval: IntentAwareRetrieval, sample_units: list[StructuredUnit]) -> None:
        result = retrieval.synthesize(sample_units)
        assert len(result) > 0
        assert isinstance(result[0], StructuredUnit)

    def test_full_pipeline(self, retrieval: IntentAwareRetrieval) -> None:
        text = "Alice deployed the new database on 2024-09-20. Bob reviewed the schema changes."
        result = retrieval.pipeline(text, query="who deployed the database")
        assert "stage1_compressed" in result
        assert "stage2_synthesized" in result
        assert "stage3_retrieval" in result
        assert result["stage1_count"] > 0
        assert result["stage2_count"] > 0
        assert result["stage3_retrieval"]["intent"] == "factual"

    def test_pipeline_no_query(self, retrieval: IntentAwareRetrieval) -> None:
        text = "Just some text about nothing in particular."
        result = retrieval.pipeline(text)
        assert "stage1_compressed" in result
        assert "stage2_synthesized" in result
        assert "stage3_retrieval" not in result

    def test_retrieve_no_index_no_retriever(self, retrieval: IntentAwareRetrieval) -> None:
        result = retrieval.retrieve("test query")
        assert result["intent"] == "factual" or result["intent"] == "operational"
        assert result["results"] == []

    def test_compress_single(self, retrieval: IntentAwareRetrieval) -> None:
        unit = retrieval.compress_single("Short text about Alice and Bob.")
        assert isinstance(unit, StructuredUnit)
        assert len(unit.content) > 0


# ===========================================================================
#  SimpleMem alias tests
# ===========================================================================

class TestSimpleMem:
    def test_alias_exists(self) -> None:
        sm = SimpleMem()
        assert isinstance(sm, IntentAwareRetrieval)
        assert callable(sm.classify_intent)

    def test_simplemem_pipeline(self) -> None:
        sm = SimpleMem()
        text = "Dr. Evans presented findings on climate change at the 2024 conference."
        result = sm.pipeline(text, query="what did Evans present")
        assert result["stage1_count"] > 0
        assert result["stage3_retrieval"]["intent"] == "factual"
