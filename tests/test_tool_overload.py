"""Tests for ToolOverloadDetector — 80%+ coverage target.

Based on arXiv:2411.15399 (Tool Overload paper).
"""
import time
import pytest
from prometheus_nexus.safety.tool_overload import (
    ToolOverloadDetector,
    ToolRecord,
    OverloadReport,
)


class TestToolRecord:
    """Test ToolRecord dataclass."""

    def test_default_values(self):
        """Test ToolRecord with default values."""
        record = ToolRecord()
        assert record.name == ""
        assert record.registered_at == 0.0
        assert record.selection_count == 0
        assert record.success_count == 0

    def test_custom_values(self):
        """Test ToolRecord with custom values."""
        record = ToolRecord(
            name="search",
            registered_at=time.time(),
            selection_count=10,
            success_count=8,
        )
        assert record.name == "search"
        assert record.selection_count == 10
        assert record.success_count == 8

    def test_success_rate_no_selections(self):
        """Test success_rate when no selections recorded."""
        record = ToolRecord()
        # Should return 0.0 when selection_count is 0 (division by max(0, 1))
        assert record.success_rate == 0.0

    def test_success_rate_all_success(self):
        """Test success_rate when all selections succeeded."""
        record = ToolRecord(selection_count=10, success_count=10)
        assert record.success_rate == 1.0

    def test_success_rate_partial_success(self):
        """Test success_rate with partial successes."""
        record = ToolRecord(selection_count=10, success_count=7)
        assert record.success_rate == 0.7

    def test_success_rate_zero_success(self):
        """Test success_rate when no successes."""
        record = ToolRecord(selection_count=5, success_count=0)
        assert record.success_rate == 0.0


class TestOverloadReport:
    """Test OverloadReport dataclass."""

    def test_default_values(self):
        """Test OverloadReport with default values."""
        report = OverloadReport()
        assert report.is_overloaded is False
        assert report.tool_count == 0
        assert report.threshold == 20
        assert report.accuracy_trend == 0.0
        assert report.recommended_prune_count == 0
        assert report.tools_to_prune == []

    def test_custom_values(self):
        """Test OverloadReport with custom values."""
        report = OverloadReport(
            is_overloaded=True,
            tool_count=25,
            threshold=15,
            accuracy_trend=-0.2,
            recommended_prune_count=10,
            tools_to_prune=["tool1", "tool2"],
        )
        assert report.is_overloaded is True
        assert report.tool_count == 25
        assert report.threshold == 15
        assert report.accuracy_trend == -0.2
        assert report.recommended_prune_count == 10
        assert report.tools_to_prune == ["tool1", "tool2"]


class TestToolOverloadDetectorInit:
    """Test ToolOverloadDetector initialization."""

    def test_default_thresholds(self):
        """Test detector with default thresholds."""
        detector = ToolOverloadDetector()
        assert detector._soft == 15
        assert detector._hard == 30

    def test_custom_thresholds(self):
        """Test detector with custom thresholds."""
        detector = ToolOverloadDetector(soft_threshold=10, hard_threshold=25)
        assert detector._soft == 10
        assert detector._hard == 25

    def test_initial_state(self):
        """Test detector starts with empty state."""
        detector = ToolOverloadDetector()
        assert len(detector._tools) == 0
        assert len(detector._accuracy_history) == 0
        assert len(detector._reports) == 0


class TestRegisterTool:
    """Test register_tool method."""

    def test_register_single_tool(self):
        """Test registering a single tool."""
        detector = ToolOverloadDetector()
        detector.register_tool("search")
        assert "search" in detector._tools
        assert detector._tools["search"].name == "search"

    def test_register_multiple_tools(self):
        """Test registering multiple tools."""
        detector = ToolOverloadDetector()
        detector.register_tool("search")
        detector.register_tool("calculator")
        detector.register_tool("memory")
        assert len(detector._tools) == 3

    def test_register_tool_has_timestamp(self):
        """Test that registered tool has timestamp."""
        detector = ToolOverloadDetector()
        before = time.time()
        detector.register_tool("search")
        after = time.time()
        assert detector._tools["search"].registered_at >= before
        assert detector._tools["search"].registered_at <= after

    def test_register_duplicate_tool(self):
        """Test registering same tool twice overwrites."""
        detector = ToolOverloadDetector()
        detector.register_tool("search")
        first_time = detector._tools["search"].registered_at
        time.sleep(0.01)
        detector.register_tool("search")
        second_time = detector._tools["search"].registered_at
        assert second_time > first_time


class TestUnregisterTool:
    """Test unregister_tool method."""

    def test_unregister_existing_tool(self):
        """Test unregistering an existing tool."""
        detector = ToolOverloadDetector()
        detector.register_tool("search")
        detector.unregister_tool("search")
        assert "search" not in detector._tools

    def test_unregister_nonexistent_tool(self):
        """Test unregistering non-existent tool does nothing."""
        detector = ToolOverloadDetector()
        detector.register_tool("search")
        # Should not raise error
        detector.unregister_tool("nonexistent")
        assert len(detector._tools) == 1

    def test_unregister_then_check_count(self):
        """Test tool count decreases after unregister."""
        detector = ToolOverloadDetector()
        detector.register_tool("a")
        detector.register_tool("b")
        detector.register_tool("c")
        assert len(detector._tools) == 3
        detector.unregister_tool("b")
        assert len(detector._tools) == 2


class TestRecordSelection:
    """Test record_selection method."""

    def test_record_selection_success(self):
        """Test recording successful selection."""
        detector = ToolOverloadDetector()
        detector.record_selection("search", success=True)
        assert detector._tools["search"].selection_count == 1
        assert detector._tools["search"].success_count == 1

    def test_record_selection_failure(self):
        """Test recording failed selection."""
        detector = ToolOverloadDetector()
        detector.record_selection("search", success=False)
        assert detector._tools["search"].selection_count == 1
        assert detector._tools["search"].success_count == 0

    def test_record_selection_auto_registers(self):
        """Test that tool is auto-registered if not present."""
        detector = ToolOverloadDetector()
        detector.record_selection("new_tool", success=True)
        assert "new_tool" in detector._tools

    def test_record_selection_updates_accuracy_history(self):
        """Test that accuracy history is updated."""
        detector = ToolOverloadDetector()
        detector.record_selection("search", success=True)
        assert len(detector._accuracy_history) == 1
        assert detector._accuracy_history[0] == 1.0

    def test_record_selection_multiple_tools(self):
        """Test recording selections across multiple tools."""
        detector = ToolOverloadDetector()
        detector.record_selection("search", success=True)
        detector.record_selection("calculator", success=False)
        assert detector._tools["search"].success_count == 1
        assert detector._tools["calculator"].success_count == 0
        assert len(detector._accuracy_history) == 2

    def test_record_selection_accumulates(self):
        """Test that selections accumulate correctly."""
        detector = ToolOverloadDetector()
        detector.record_selection("search", success=True)
        detector.record_selection("search", success=True)
        detector.record_selection("search", success=False)
        assert detector._tools["search"].selection_count == 3
        assert detector._tools["search"].success_count == 2

    def test_accuracy_history_truncation(self):
        """Test that accuracy history is truncated at 200 entries."""
        detector = ToolOverloadDetector()
        # Add 201 entries
        for i in range(201):
            detector.record_selection("tool", success=(i % 2 == 0))
        assert len(detector._accuracy_history) == 100
        # Last entry should be from the most recent selection
        # After 201 iterations, even indices are success (True), odd are failure (False)
        # 201 is odd, so last selection was failure (False)
        # Accuracy will be based on all selections up to that point
        assert isinstance(detector._accuracy_history[-1], float)


class TestDetect:
    """Test detect method."""

    def test_detect_empty_state(self):
        """Test detection with no tools registered."""
        detector = ToolOverloadDetector()
        report = detector.detect()
        assert report.is_overloaded is False
        assert report.tool_count == 0
        assert report.recommended_prune_count == 0
        assert report.tools_to_prune == []

    def test_detect_below_soft_threshold(self):
        """Test detection below soft threshold."""
        detector = ToolOverloadDetector(soft_threshold=15, hard_threshold=30)
        for i in range(10):
            detector.register_tool(f"tool_{i}")
        report = detector.detect()
        assert report.is_overloaded is False
        assert report.tool_count == 10

    def test_detect_at_soft_threshold(self):
        """Test detection at soft threshold."""
        detector = ToolOverloadDetector(soft_threshold=15, hard_threshold=30)
        for i in range(15):
            detector.register_tool(f"tool_{i}")
        report = detector.detect()
        # Not overloaded unless accuracy trend drops
        assert report.tool_count == 15

    def test_detect_at_hard_threshold(self):
        """Test detection at hard threshold triggers overload."""
        detector = ToolOverloadDetector(soft_threshold=15, hard_threshold=30)
        for i in range(30):
            detector.register_tool(f"tool_{i}")
        report = detector.detect()
        assert report.is_overloaded is True
        assert report.tool_count == 30

    def test_detect_above_hard_threshold(self):
        """Test detection above hard threshold."""
        detector = ToolOverloadDetector(soft_threshold=15, hard_threshold=30)
        for i in range(35):
            detector.register_tool(f"tool_{i}")
        report = detector.detect()
        assert report.is_overloaded is True
        assert report.tool_count == 35

    def test_detect_accuracy_trend_decline(self):
        """Test detection with declining accuracy trend."""
        detector = ToolOverloadDetector(soft_threshold=5, hard_threshold=10)
        # Register enough tools
        for i in range(6):
            detector.register_tool(f"tool_{i}")
        # Record selections with declining accuracy
        # First 5 successes (high accuracy)
        for _ in range(5):
            detector.record_selection("tool_0", success=True)
        # Then 5 failures (low accuracy)
        for _ in range(5):
            detector.record_selection("tool_0", success=False)
        report = detector.detect()
        # Accuracy trend should be negative
        assert report.accuracy_trend < 0

    def test_detect_accuracy_trend_improvement(self):
        """Test detection with improving accuracy trend."""
        detector = ToolOverloadDetector(soft_threshold=5, hard_threshold=10)
        for i in range(6):
            detector.register_tool(f"tool_{i}")
        # Record selections with improving accuracy
        # First 5 failures (low accuracy)
        for _ in range(5):
            detector.record_selection("tool_0", success=False)
        # Then 5 successes (high accuracy)
        for _ in range(5):
            detector.record_selection("tool_0", success=True)
        report = detector.detect()
        # Accuracy trend should be positive
        assert report.accuracy_trend > 0

    def test_detect_stores_report(self):
        """Test that detect stores report internally."""
        detector = ToolOverloadDetector()
        detector.register_tool("search")
        detector.detect()
        assert len(detector._reports) == 1
        assert detector._reports[0]["tool_count"] == 1

    def test_detect_multiple_calls(self):
        """Test multiple detect calls accumulate reports."""
        detector = ToolOverloadDetector()
        detector.register_tool("search")
        detector.detect()
        detector.register_tool("calculator")
        detector.detect()
        assert len(detector._reports) == 2

    def test_detect_prune_recommendation(self):
        """Test prune recommendation calculation."""
        detector = ToolOverloadDetector(soft_threshold=15, hard_threshold=20)
        for i in range(25):
            detector.register_tool(f"tool_{i}")
        report = detector.detect()
        # Should recommend pruning 10 tools (25 - 15) since over hard threshold
        assert report.recommended_prune_count == 10

    def test_detect_tools_to_prune_ordered(self):
        """Test that tools to prune are least used first."""
        detector = ToolOverloadDetector(soft_threshold=5, hard_threshold=10)
        for i in range(8):
            detector.register_tool(f"tool_{i}")
        # Make some tools more used
        for _ in range(10):
            detector.record_selection("tool_0", success=True)
        for _ in range(5):
            detector.record_selection("tool_1", success=True)
        report = detector.detect()
        # Most used tools should NOT be in prune list
        assert "tool_0" not in report.tools_to_prune

    def test_detect_no_prune_when_not_overloaded(self):
        """Test no prune recommendation when not overloaded."""
        detector = ToolOverloadDetector(soft_threshold=15, hard_threshold=30)
        for i in range(10):
            detector.register_tool(f"tool_{i}")
        report = detector.detect()
        assert report.recommended_prune_count == 0
        assert report.tools_to_prune == []

    def test_detect_accuracy_trend_insufficient_history(self):
        """Test accuracy trend is 0 when history too short."""
        detector = ToolOverloadDetector()
        detector.register_tool("search")
        # Only record 5 selections (need 10 for trend calculation)
        for _ in range(5):
            detector.record_selection("search", success=True)
        report = detector.detect()
        assert report.accuracy_trend == 0.0

    def test_detect_accuracy_trend_exactly_ten_entries(self):
        """Test accuracy trend with exactly 10 history entries."""
        detector = ToolOverloadDetector(soft_threshold=5, hard_threshold=10)
        for i in range(6):
            detector.register_tool(f"tool_{i}")
        # Record exactly 10 selections
        for _ in range(10):
            detector.record_selection("tool_0", success=True)
        report = detector.detect()
        # Trend should be calculated (recent - older)
        assert isinstance(report.accuracy_trend, float)


class TestGetStats:
    """Test get_stats method."""

    def test_get_stats_empty(self):
        """Test stats with no tools."""
        detector = ToolOverloadDetector()
        stats = detector.get_stats()
        assert stats["tool_count"] == 0
        assert stats["total_selections"] == 0
        assert stats["overall_accuracy"] == 0.0

    def test_get_stats_with_tools(self):
        """Test stats with registered tools."""
        detector = ToolOverloadDetector()
        detector.register_tool("search")
        detector.register_tool("calculator")
        stats = detector.get_stats()
        assert stats["tool_count"] == 2

    def test_get_stats_with_selections(self):
        """Test stats include selection counts."""
        detector = ToolOverloadDetector()
        detector.record_selection("search", success=True)
        detector.record_selection("search", success=True)
        detector.record_selection("calculator", success=False)
        stats = detector.get_stats()
        assert stats["total_selections"] == 3
        assert stats["overall_accuracy"] == 2 / 3

    def test_get_stats_accuracy_calculation(self):
        """Test overall accuracy is calculated correctly."""
        detector = ToolOverloadDetector()
        detector.record_selection("search", success=True)
        detector.record_selection("search", success=True)
        detector.record_selection("search", success=True)
        detector.record_selection("calculator", success=False)
        stats = detector.get_stats()
        assert stats["overall_accuracy"] == 0.75

    def test_get_stats_returns_dict(self):
        """Test get_stats returns a dictionary."""
        detector = ToolOverloadDetector()
        stats = detector.get_stats()
        assert isinstance(stats, dict)
        assert "tool_count" in stats
        assert "total_selections" in stats
        assert "overall_accuracy" in stats


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_zero_thresholds(self):
        """Test behavior with zero thresholds."""
        detector = ToolOverloadDetector(soft_threshold=0, hard_threshold=0)
        detector.register_tool("search")
        report = detector.detect()
        # Hard threshold is 0, so any tool triggers overload
        assert report.is_overloaded is True

    def test_very_high_thresholds(self):
        """Test behavior with very high thresholds."""
        detector = ToolOverloadDetector(soft_threshold=1000, hard_threshold=2000)
        for i in range(100):
            detector.register_tool(f"tool_{i}")
        report = detector.detect()
        assert report.is_overloaded is False

    def test_rapid_selection_recording(self):
        """Test rapid selection recording doesn't break."""
        detector = ToolOverloadDetector()
        for i in range(1000):
            detector.record_selection("tool", success=(i % 2 == 0))
        assert detector._tools["tool"].selection_count == 1000

    def test_many_tools_simultaneous(self):
        """Test registering many tools simultaneously."""
        detector = ToolOverloadDetector()
        for i in range(100):
            detector.register_tool(f"tool_{i}")
        assert len(detector._tools) == 100

    def test_mixed_success_failure_pattern(self):
        """Test mixed success/failure patterns."""
        detector = ToolOverloadDetector()
        patterns = [True, False, True, True, False, True, False, True]
        for success in patterns:
            detector.record_selection("tool", success=success)
        stats = detector.get_stats()
        assert stats["total_selections"] == 8
        # 5 successes out of 8 selections = 0.625
        assert abs(stats["overall_accuracy"] - 0.625) < 0.001

    def test_tool_name_special_characters(self):
        """Test tool names with special characters."""
        detector = ToolOverloadDetector()
        detector.register_tool("tool-with-dashes")
        detector.register_tool("tool_with_underscores")
        detector.register_tool("tool.with.dots")
        assert len(detector._tools) == 3

    def test_unicode_tool_names(self):
        """Test tool names with Unicode characters."""
        detector = ToolOverloadDetector()
        detector.register_tool("搜索工具")
        detector.register_tool("ツール")
        assert len(detector._tools) == 2

    def test_empty_string_tool_name(self):
        """Test empty string as tool name."""
        detector = ToolOverloadDetector()
        detector.register_tool("")
        assert "" in detector._tools

    def test_long_tool_name(self):
        """Test very long tool name."""
        detector = ToolOverloadDetector()
        long_name = "a" * 1000
        detector.register_tool(long_name)
        assert long_name in detector._tools

    def test_detect_after_unregister(self):
        """Test detection after unregistering tools."""
        detector = ToolOverloadDetector(soft_threshold=5, hard_threshold=10)
        for i in range(10):
            detector.register_tool(f"tool_{i}")
        detector.unregister_tool("tool_0")
        detector.unregister_tool("tool_1")
        report = detector.detect()
        assert report.tool_count == 8

    def test_accuracy_history_precision(self):
        """Test accuracy history maintains precision."""
        detector = ToolOverloadDetector()
        detector.record_selection("tool", success=True)
        detector.record_selection("tool", success=True)
        detector.record_selection("tool", success=True)
        detector.record_selection("tool", success=False)
        # Should be 0.75
        assert abs(detector._accuracy_history[-1] - 0.75) < 0.001

    def test_concurrent_operations(self):
        """Test interleaving operations don't cause issues."""
        detector = ToolOverloadDetector()
        detector.register_tool("a")
        detector.record_selection("a", success=True)
        detector.register_tool("b")
        detector.record_selection("b", success=False)
        detector.unregister_tool("a")
        detector.register_tool("c")
        report = detector.detect()
        assert report.tool_count == 2
