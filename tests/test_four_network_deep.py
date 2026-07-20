"""Deep tests for FourNetworkMemory module.

Phase 1 Day 1: Core functionality tests (500+ lines)
Target coverage: 9% → 60%
"""
import time
import math
import pytest
from prometheus_nexus.memory.four_network import FourNetworkMemory


class TestFourNetworkInitialization:
    """Test FourNetworkMemory initialization."""

    def test_default_initialization(self):
        """Should initialize with default parameters."""
        mem = FourNetworkMemory()
        assert mem.NETWORK_NAMES == ("experience", "semantic", "procedural", "episodic")
        assert len(mem._networks) == 4
        assert mem._max_entries == 1000
        assert mem._recency_decay == 0.95
        assert mem._total_retained == 0

    def test_custom_initialization(self):
        """Should accept custom parameters."""
        mem = FourNetworkMemory(max_entries_per_network=500, recency_decay=0.9)
        assert mem._max_entries == 500
        assert mem._recency_decay == 0.9

    def test_networks_initialized_empty(self):
        """All networks should start empty."""
        mem = FourNetworkMemory()
        for name in mem.NETWORK_NAMES:
            assert len(mem._networks[name]) == 0

    def test_tag_index_initialized(self):
        """Tag index should be initialized as defaultdict."""
        mem = FourNetworkMemory()
        assert hasattr(mem, '_tag_index')
        result = mem._tag_index["nonexistent"]
        assert isinstance(result, list)

    def test_reflection_state_initialized(self):
        """Reflection and plan state should be initialized."""
        mem = FourNetworkMemory()
        assert mem._reflections == []
        assert mem._plans == []
        assert mem._last_reflection_time == 0.0


class TestAutoClassification:
    """Test auto-classification logic."""

    def test_auto_classify_experience(self):
        """Should classify experience content correctly."""
        mem = FourNetworkMemory()
        result = mem._auto_classify("Something happened yesterday at the meeting")
        assert result == "experience"

    def test_auto_classify_semantic(self):
        """Should classify semantic content correctly."""
        mem = FourNetworkMemory()
        result = mem._auto_classify("Python is a programming language")
        assert result == "semantic"

    def test_auto_classify_procedural(self):
        """Should classify procedural content correctly."""
        mem = FourNetworkMemory()
        result = mem._auto_classify("How to implement a neural network step by step")
        assert result == "procedural"

    def test_auto_classify_episodic(self):
        """Should classify episodic content correctly."""
        mem = FourNetworkMemory()
        result = mem._auto_classify("Where did we meet last week")
        assert result == "episodic"

    def test_auto_classify_default_experience(self):
        """Should default to experience when no keywords match."""
        mem = FourNetworkMemory()
        result = mem._auto_classify("Random unrelated text without keywords")
        assert result == "experience"

    def test_auto_classify_multiple_keywords(self):
        """Should pick network with highest keyword overlap."""
        mem = FourNetworkMemory()
        result = mem._auto_classify("How is how this process works")
        assert result == "procedural"

    def test_auto_classify_case_insensitive(self):
        """Should handle case insensitivity."""
        mem = FourNetworkMemory()
        result = mem._auto_classify("PYTHON IS A PROGRAMMING LANGUAGE")
        assert result == "semantic"

    def test_auto_classify_empty_string(self):
        """Should handle empty string gracefully."""
        mem = FourNetworkMemory()
        result = mem._auto_classify("")
        assert result == "experience"


class TestRetain:
    """Test retain functionality."""

    def test_retain_to_specific_network(self):
        """Should retain to specified network."""
        mem = FourNetworkMemory()
        result = mem.retain("Test memory", network="semantic")
        assert result is True
        assert len(mem._networks["semantic"]) == 1

    def test_retain_with_auto_classification(self):
        """Should auto-classify when network not specified."""
        mem = FourNetworkMemory()
        result = mem.retain("Python is a programming language")
        assert result is True
        assert len(mem._networks["semantic"]) == 1

    def test_retain_with_tags(self):
        """Should store tags with entry."""
        mem = FourNetworkMemory()
        result = mem.retain("Test memory", tags=["test", "important"])
        assert result is True
        entry = mem._networks["experience"][0]
        assert entry["tags"] == ["test", "important"]

    def test_retain_with_importance(self):
        """Should store importance score."""
        mem = FourNetworkMemory()
        result = mem.retain("Test memory", importance=0.8)
        assert result is True
        entry = mem._networks["experience"][0]
        assert entry["importance"] == 0.8

    def test_retain_increments_total(self):
        """Should increment total retained counter."""
        mem = FourNetworkMemory()
        mem.retain("Memory 1")
        mem.retain("Memory 2")
        assert mem._total_retained == 2

    def test_retain_invalid_network(self):
        """Should return False for invalid network."""
        mem = FourNetworkMemory()
        result = mem.retain("Test memory", network="invalid")
        assert result is False

    def test_retain_adds_to_tag_index(self):
        """Should add entries to tag index."""
        mem = FourNetworkMemory()
        mem.retain("Test memory", tags=["python", "code"])
        assert "python" in mem._tag_index
        assert "code" in mem._tag_index

    def test_retain_entry_structure(self):
        """Should create properly structured entry."""
        mem = FourNetworkMemory()
        mem.retain("Test content", network="semantic", tags=["test"], importance=0.7)
        entry = mem._networks["semantic"][0]
        assert entry["content"] == "Test content"
        assert entry["importance"] == 0.7
        assert entry["tags"] == ["test"]
        assert entry["network"] == "semantic"
        assert entry["access_count"] == 0
        assert "last_access" in entry

    def test_retain_max_entries_eviction(self):
        """Should evict oldest entry when max reached."""
        mem = FourNetworkMemory(max_entries_per_network=2)
        mem.retain("First", network="semantic")
        mem.retain("Second", network="semantic")
        mem.retain("Third", network="semantic")
        assert len(mem._networks["semantic"]) == 2
        assert mem._networks["semantic"][0]["content"] == "Second"
        assert mem._networks["semantic"][1]["content"] == "Third"


class TestRecall:
    """Test recall functionality."""

    @pytest.fixture
    def populated_memory(self):
        """Create memory with sample data."""
        mem = FourNetworkMemory()
        mem.retain("Python is a programming language", network="semantic", tags=["python"])
        mem.retain("How to write code step by step", network="procedural", tags=["code"])
        mem.retain("The meeting happened yesterday", network="experience", tags=["meeting"])
        return mem

    def test_recall_basic(self, populated_memory):
        """Should return relevant memories."""
        results = populated_memory.recall("python")
        assert len(results) > 0
        assert results[0]["content"] == "Python is a programming language"

    def test_recall_top_k(self, populated_memory):
        """Should respect top_k parameter."""
        results = populated_memory.recall("test", top_k=2)
        assert len(results) <= 2

    def test_recall_by_network(self, populated_memory):
        """Should filter by network."""
        results = populated_memory.recall("code", network="procedural")
        assert all(r["network"] == "procedural" for r in results)

    def test_recall_score_calculation(self, populated_memory):
        """Should calculate scores using Generative Agents formula."""
        results = populated_memory.recall("python")
        assert len(results) > 0
        result = results[0]
        assert "score" in result
        assert result["score"] > 0
        assert result["importance"] > 0
        assert result["relevance"] > 0

    def test_recall_updates_access_count(self, populated_memory):
        """Should increment access count on recall."""
        mem = populated_memory
        mem.recall("python")
        entry = mem._networks["semantic"][0]
        assert entry["access_count"] == 1

    def test_recall_no_matches(self, populated_memory):
        """Should return empty list when no matches."""
        results = populated_memory.recall("xyznonexistent")
        assert len(results) == 0

    def test_recall_recency_factor(self):
        """Should factor in recency."""
        mem = FourNetworkMemory()
        mem.retain("Old memory", network="semantic")
        time.sleep(0.1)
        mem.retain("New memory", network="semantic")
        results = mem.recall("memory")
        assert results[0]["content"] == "New memory"

    def test_recall_importance_factor(self):
        """Should factor in importance score."""
        mem = FourNetworkMemory()
        mem.retain("Low importance", network="semantic", importance=0.1)
        mem.retain("High importance", network="semantic", importance=0.9)
        results = mem.recall("importance")
        assert results[0]["importance"] >= results[1]["importance"]

    def test_recall_relevance_exact_match(self):
        """Should give high relevance for exact match."""
        mem = FourNetworkMemory()
        mem.retain("python programming", network="semantic")
        results = mem.recall("python programming")
        assert len(results) > 0
        # Exact match gives relevance=1.0, plus word overlap bonus
        assert results[0]["relevance"] >= 1.0


class TestReflection:
    """Test reflection functionality."""

    @pytest.fixture
    def memory_with_themes(self):
        """Create memory with recurring themes."""
        mem = FourNetworkMemory()
        for i in range(5):
            mem.retain(f"Python is great for programming task {i}", network="semantic")
        return mem

    def test_reflect_basic(self, memory_with_themes):
        """Should generate reflections from memories."""
        reflections = memory_with_themes.reflect("programming")
        assert len(reflections) > 0

    def test_reflect_stores_internally(self, memory_with_themes):
        """Should store reflections internally."""
        mem = memory_with_themes
        mem.reflect("programming")
        assert len(mem._reflections) > 0

    def test_reflect_theme_extraction(self, memory_with_themes):
        """Should extract recurring themes."""
        reflections = memory_with_themes.reflect("programming")
        theme_reflections = [r for r in reflections if "Recurring theme" in r]
        assert len(theme_reflections) > 0

    def test_reflect_contradiction_detection(self):
        """Should detect contradictory memories."""
        mem = FourNetworkMemory()
        mem.retain("Python is good", network="semantic")
        mem.retain("Python is not good", network="semantic")
        reflections = mem.reflect("good")
        contradiction_reflections = [r for r in reflections if "Contradiction" in r]
        assert len(contradiction_reflections) > 0

    def test_reflect_cross_network_synthesis(self):
        """Should synthesize across multiple networks."""
        mem = FourNetworkMemory()
        mem.retain("Python is a language", network="semantic")
        mem.retain("How to use Python", network="procedural")
        reflections = mem.reflect("python")
        cross_network = [r for r in reflections if "Cross-network" in r]
        assert len(cross_network) > 0

    def test_get_reflections(self, memory_with_themes):
        """Should return stored reflections."""
        mem = memory_with_themes
        mem.reflect("programming")
        reflections = mem.get_reflections()
        assert len(reflections) > 0
        assert "content" in reflections[0]


class TestPlanning:
    """Test planning functionality."""

    @pytest.fixture
    def memory_with_reflections(self):
        """Create memory with reflections."""
        mem = FourNetworkMemory()
        mem.retain("Python is useful", network="semantic")
        mem.reflect("python")
        return mem

    def test_plan_basic(self, memory_with_reflections):
        """Should generate action plans."""
        plans = memory_with_reflections.plan()
        assert len(plans) > 0

    def test_plan_structure(self, memory_with_reflections):
        """Should return properly structured plans."""
        plans = memory_with_reflections.plan()
        plan = plans[0]
        assert "goal" in plan
        assert "actions" in plan
        assert "priority" in plan
        assert "prerequisites" in plan

    def test_execute_plan(self, memory_with_reflections):
        """Should simulate executing a plan."""
        mem = memory_with_reflections
        mem.plan()
        result = mem.execute_plan()
        assert result["status"] == "executed"

    def test_execute_plan_no_plans(self):
        """Should return error when no plans exist."""
        mem = FourNetworkMemory()
        result = mem.execute_plan()
        assert "error" in result

    def test_get_plans(self, memory_with_reflections):
        """Should return stored plans."""
        mem = memory_with_reflections
        mem.plan()
        plans = mem.get_plans()
        assert len(plans) > 0


class TestExtractThemes:
    """Test theme extraction."""

    def test_extract_themes_basic(self):
        """Should extract common words as themes."""
        mem = FourNetworkMemory()
        memories = [
            {"content": "Python programming is fun"},
            {"content": "Python is powerful"},
            {"content": "Python programming language"},
        ]
        themes = mem._extract_themes(memories, top_n=2)
        assert len(themes) > 0
        assert any(t["word"] == "python" for t in themes)

    def test_extract_themes_filters_stopwords(self):
        """Should filter out stopwords."""
        mem = FourNetworkMemory()
        memories = [
            {"content": "The quick brown fox jumps over the lazy dog"},
            {"content": "The dog was lazy"},
        ]
        themes = mem._extract_themes(memories, top_n=5)
        for theme in themes:
            assert theme["word"] != "the"

    def test_extract_themes_empty_memories(self):
        """Should handle empty memories list."""
        mem = FourNetworkMemory()
        themes = mem._extract_themes([], top_n=3)
        assert themes == []


class TestDetectContradictions:
    """Test contradiction detection."""

    def test_detect_contradictions_basic(self):
        """Should detect contradictory statements."""
        mem = FourNetworkMemory()
        memories = [
            {"content": "Python is good"},
            {"content": "Python is not good"},
        ]
        contradictions = mem._detect_contradictions(memories)
        assert len(contradictions) > 0

    def test_detect_contradictions_no_contradiction(self):
        """Should not flag non-contradictory memories."""
        mem = FourNetworkMemory()
        memories = [
            {"content": "Python is good"},
            {"content": "Java is also good"},
        ]
        contradictions = mem._detect_contradictions(memories)
        assert len(contradictions) == 0


class TestGetStats:
    """Test statistics reporting."""

    def test_get_stats_empty(self):
        """Should return stats for empty memory."""
        mem = FourNetworkMemory()
        stats = mem.get_stats()
        assert stats["experience"] == 0
        assert stats["semantic"] == 0
        assert stats["procedural"] == 0
        assert stats["episodic"] == 0
        assert stats["total"] == 0

    def test_get_stats_after_retain(self):
        """Should reflect retained entries."""
        mem = FourNetworkMemory()
        mem.retain("Test 1", network="semantic")
        mem.retain("Test 2", network="semantic")
        mem.retain("Test 3", network="procedural")
        stats = mem.get_stats()
        assert stats["semantic"] == 2
        assert stats["procedural"] == 1
        assert stats["total"] == 3

    def test_get_stats_after_reflection(self):
        """Should reflect reflection count."""
        mem = FourNetworkMemory()
        mem.retain("Test", network="semantic")
        mem.reflect("test")
        stats = mem.get_stats()
        assert stats["reflections"] == 1
