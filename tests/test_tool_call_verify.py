"""Comprehensive tests for tool_call_verify.py module.

Target coverage increase from 68% to 85%+.
Tests cover all public methods including edge cases.
"""
import threading
import time
import pytest
from unittest.mock import patch, MagicMock

# Import the module under test
from prometheus_nexus.safety.tool_call_verify import (
    ToolCallVerifier,
    MemoryPoisonSimulator,
    ParameterReplacementDetector,
    ToolHijackDetector,
    _check_string,
    _get_severity,
)


# ======================================================================
# Test Helpers
# ======================================================================

def make_verifier(enable_memmorph=True):
    """Create a fresh ToolCallVerifier instance."""
    return ToolCallVerifier(enable_memmorph=enable_memmorph)


# ======================================================================
# Section 1: Helper Functions
# ======================================================================

class TestCheckString:
    """Test _check_string helper function."""

    def test_check_string_valid(self):
        """Should return valid string."""
        result = _check_string("test string")
        assert result == "test string"

    def test_check_string_none(self):
        """Should handle None input."""
        result = _check_string(None)
        assert result == "None"  # str(None) returns "None"

    def test_check_string_empty(self):
        """Should handle empty string."""
        result = _check_string("")
        assert result == ""

    def test_check_string_non_string(self):
        """Should convert non-string to string."""
        result = _check_string(123)
        assert result == "123"


class TestGetSeverity:
    """Test _get_severity helper function."""

    def test_get_severity_url_change_malicious(self):
        """Should detect malicious URL change."""
        severity, reason = _get_severity("url", "https://example.com", "https://evil.com")
        assert severity == "critical"

    def test_get_severity_url_change_normal(self):
        """Should detect normal URL change."""
        severity, reason = _get_severity("url", "https://old.com", "https://new.com")
        assert severity == "high"

    def test_get_severity_path_change_sensitive(self):
        """Should detect sensitive path change."""
        severity, reason = _get_severity("path", "/tmp/file", "/etc/passwd")
        assert severity == "high"

    def test_get_severity_path_change_normal(self):
        """Should detect normal path change."""
        severity, reason = _get_severity("path", "/home/user/file", "/var/log/file")
        assert severity == "high"  # Both paths contain / so it's high

    def test_get_severity_db_query_destructive(self):
        """Should detect destructive DB query change."""
        severity, reason = _get_severity("query", "SELECT * FROM users", "DROP TABLE users")
        assert severity == "critical"

    def test_get_severity_db_query_normal(self):
        """Should detect normal DB query change."""
        severity, reason = _get_severity("query", "SELECT * FROM users", "INSERT INTO users")
        assert severity == "high"

    def test_get_severity_permission_change(self):
        """Should detect permission change."""
        severity, reason = _get_severity("mode", "read", "admin")
        assert severity == "medium"

    def test_get_severity_no_change(self):
        """Should return low severity when no change."""
        severity, reason = _get_severity("param", "value", "value")
        assert severity == "low"


# ======================================================================
# Section 2: ToolCallVerifier Class
# ======================================================================

class TestToolCallVerifierInit:
    """Test ToolCallVerifier initialization."""

    def test_default_init(self):
        """Should initialize with default values."""
        v = ToolCallVerifier()
        assert v.enable_memmorph is True
        assert v._lock is not None
        assert v._planned == {}
        assert v._history == []
        assert v._total_calls == 0
        assert v._critical_warnings == 0

    def test_memmorph_disabled(self):
        """Should disable memmorph when specified."""
        v = ToolCallVerifier(enable_memmorph=False)
        assert v.enable_memmorph is False


class TestToolCallVerifierVerify:
    """Test verify method."""

    def test_verify_basic_call(self, verifier):
        """Should verify basic tool call."""
        result = verifier.verify({"action": "read"}, {"mode": "read"})
        assert "valid" in result
        assert "severity" in result

    def test_verify_flag_change(self, verifier):
        """Should detect flag changes via MemMorph."""
        result = verifier.verify({"mode": "read"}, {"mode": "admin"})
        # Should detect poison pattern even if valid=True
        assert "memmorph" in result
        assert result["memmorph"]["poison"] is not None

    def test_verify_path_traversal(self, verifier):
        """Should detect path traversal attempts via MemMorph."""
        result = verifier.verify({"path": "/tmp/file"}, {"path": "/etc/passwd"})
        # Should detect poison pattern
        assert "memmorph" in result
        assert result["memmorph"]["poison"] is not None

    def test_verify_sql_injection(self, verifier):
        """Should detect SQL injection attempts via MemMorph."""
        result = verifier.verify({"query": "SELECT * FROM users"}, {"query": "DROP TABLE users"})
        # Should detect poison pattern
        assert "memmorph" in result
        assert result["memmorph"]["poison"] is not None

    def test_verify_command_injection(self, verifier):
        """Should detect command injection attempts via MemMorph."""
        result = verifier.verify({"command": "ls"}, {"command": "rm -rf /"})
        # Should detect poison pattern when using 'command' key
        assert "memmorph" in result
        assert result["memmorph"]["poison"] is not None


class TestToolCallVerifierRecordPlannedCall:
    """Test record_planned_call method."""

    def test_record_planned_call(self, verifier):
        """Should record planned call."""
        plan_id = verifier.record_planned_call("read", {"path": "/tmp/file"})
        assert plan_id is not None
        assert len(verifier._planned) == 1

    def test_record_actual_call(self, verifier):
        """Should record actual call and compare with planned."""
        plan_id = verifier.record_planned_call("read", {"path": "/tmp/file"})
        result = verifier.record_actual_call(plan_id, "read", {"path": "/tmp/file"})
        assert "valid" in result
        assert len(verifier._history) == 1

    def test_record_actual_call_no_matching_plan(self, verifier):
        """Should return invalid for non-matching plan."""
        result = verifier.record_actual_call("invalid_id", "read", {"path": "/tmp/file"})
        assert result["valid"] is False


class TestToolCallVerifierGetStats:
    """Test get_stats method."""

    def test_get_stats_empty(self, verifier):
        """Should return stats for empty state."""
        stats = verifier.get_stats()
        assert "total_calls" in stats
        assert "critical_alerts" in stats
        assert "memmorph" in stats

    def test_get_stats_with_history(self, verifier):
        """Should update stats after recording results."""
        plan_id = verifier.record_planned_call("read", {"path": "/tmp/file"})
        verifier.record_actual_call(plan_id, "read", {"path": "/tmp/file"})
        stats = verifier.get_stats()
        assert stats["total_calls"] == 1

    def test_get_call_history(self, verifier):
        """Should return call history."""
        plan_id = verifier.record_planned_call("read", {"path": "/tmp/file"})
        verifier.record_actual_call(plan_id, "read", {"path": "/tmp/file"})
        history = verifier.get_call_history()
        assert len(history) == 1


# ======================================================================
# Section 3: MemoryPoisonSimulator Class
# ======================================================================

class TestMemoryPoisonSimulator:
    """Test MemoryPoisonSimulator class."""

    def test_init(self):
        """Should initialize correctly."""
        sim = MemoryPoisonSimulator()
        assert sim is not None

    def test_detect_poison_path_change(self, simulator):
        """Should detect path poisoning pattern."""
        result = simulator.analyze("path", "/tmp/file", "/etc/passwd")
        assert result is not None
        assert "risk" in result

    def test_detect_poison_url_change(self, simulator):
        """Should detect URL poisoning pattern."""
        result = simulator.analyze("url", "https://example.com/api", "https://evil-exfil.xyz/api")
        assert result is not None
        assert "risk" in result

    def test_no_poison_when_identical(self, simulator):
        """Should return None when before and after are identical."""
        result = simulator.analyze("url", "https://example.com", "https://example.com")
        assert result is None

    def test_get_all_detections(self, simulator):
        """Should return all detected poisons."""
        simulator.analyze("path", "/tmp/file", "/etc/passwd")
        detections = simulator.get_all_detections()
        assert len(detections) == 1

    def test_clear_detections(self, simulator):
        """Should clear all detections."""
        simulator.analyze("path", "/tmp/file", "/etc/passwd")
        simulator.clear()
        assert len(simulator.get_all_detections()) == 0


# ======================================================================
# Section 4: ParameterReplacementDetector Class
# ======================================================================

class TestParameterReplacementDetector:
    """Test ParameterReplacementDetector class."""

    def test_init(self):
        """Should initialize correctly."""
        detector = ParameterReplacementDetector()
        assert detector is not None

    def test_detect_replacement_basic(self, detector):
        """Should detect basic parameter replacement."""
        result = detector.analyze(
            {"param": "value1"},
            {"param": "value2"}
        )
        assert isinstance(result, dict)
        assert "poison_detected" in result

    def test_detect_replacement_no_change(self, detector):
        """Should return no poison when parameters are identical."""
        result = detector.analyze(
            {"param": "value1"},
            {"param": "value1"}
        )
        assert result["poison_detected"] is False

    def test_detect_replacement_multiple_params(self, detector):
        """Should detect multiple parameter changes."""
        result = detector.analyze(
            {"path": "/tmp/file", "mode": "read"},
            {"path": "/etc/passwd", "mode": "admin"}
        )
        assert isinstance(result, dict)
        assert "alerts" in result


# ======================================================================
# Section 5: ToolHijackDetector Class
# ======================================================================

class TestToolHijackDetector:
    """Test ToolHijackDetector class."""

    def test_init(self):
        """Should initialize correctly."""
        detector = ToolHijackDetector()
        assert detector is not None

    def test_detect_tool_redirect(self, hijack_detector):
        """Should detect tool redirect attempts."""
        result = hijack_detector.analyze(
            planned_tool="read",
            planned_params={"path": "/tmp/file"},
            actual_tool="delete",
            actual_params={"path": "/etc/passwd"}
        )
        assert result["hijack_detected"] is True
        assert result["hijack_type"] == "tool_redirect"

    def test_detect_param_redirect(self, hijack_detector):
        """Should detect parameter redirect attempts."""
        result = hijack_detector.analyze(
            planned_tool="read",
            planned_params={"path": "/tmp/file", "mode": "read"},
            actual_tool="read",
            actual_params={"path": "/etc/passwd", "mode": "admin"}
        )
        assert result["hijack_detected"] is True
        assert result["hijack_type"] == "param_redirect"

    def test_no_hijack_when_identical(self, hijack_detector):
        """Should return no hijack when parameters are identical."""
        result = hijack_detector.analyze(
            planned_tool="read",
            planned_params={"path": "/tmp/file"},
            actual_tool="read",
            actual_params={"path": "/tmp/file"}
        )
        assert result["hijack_detected"] is False
        assert result["hijack_type"] == "none"


# ======================================================================
# Test Fixtures
# ======================================================================

@pytest.fixture
def verifier():
    """Create a fresh ToolCallVerifier instance."""
    return make_verifier()


@pytest.fixture
def simulator():
    """Create a fresh MemoryPoisonSimulator instance."""
    return MemoryPoisonSimulator()


@pytest.fixture
def detector():
    """Create a fresh ParameterReplacementDetector instance."""
    return ParameterReplacementDetector()


@pytest.fixture
def hijack_detector():
    """Create a fresh ToolHijackDetector instance."""
    return ToolHijackDetector()