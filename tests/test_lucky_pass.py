"""Tests for LuckyPassDetector — Agent "Lucky Pass" detection."""

import pytest
from prometheus_nexus.evaluation.lucky_pass import (
    LuckyPassDetector,
    LuckyPassAnalysis,
)


class TestLuckyPassAnalysisDataclass:
    """Verify LuckyPassAnalysis dataclass structure."""

    def test_default_construction(self):
        a = LuckyPassAnalysis()
        assert a.lucky_probability == 0.0
        assert a.ideal_path_probability == 0.0
        assert a.missing_steps == []
        assert a.failure_recovery_count == 0
        assert a.is_lucky_pass is False
        assert a.heuristic_signals == {}
        assert a.path_count == 0
        assert a.total_steps == 0
        assert a.explanation_token_estimate == 0

    def test_round_trip_fields(self):
        a = LuckyPassAnalysis(
            lucky_probability=0.6667,
            ideal_path_probability=0.3333,
            missing_steps=["too_few_steps", "no_causal_reasoning"],
            failure_recovery_count=2,
            is_lucky_pass=True,
            heuristic_signals={
                "single_path": True,
                "no_explanation": True,
                "missing_steps": True,
            },
            path_count=1,
            total_steps=2,
            explanation_token_estimate=5,
        )
        assert a.lucky_probability == 0.6667
        assert a.is_lucky_pass is True
        assert len(a.missing_steps) == 2


class TestLuckyPassDetector:
    """Main test suite for LuckyPassDetector."""

    # ------------------------------------------------------------------
    # Fixtures — reusable trajectory dicts
    # ------------------------------------------------------------------

    @pytest.fixture
    def detector(self) -> LuckyPassDetector:
        return LuckyPassDetector()

    @pytest.fixture
    def lucky_trajectory(self) -> dict:
        """Trajectory where all 3 lucky-pass heuristics fire."""
        return {
            "paths": [{"id": "only_path", "result": "correct"}],
            "steps": [],
            "actions": ["output_final"],
            "success": True,
            "explanation": "",
            "reasoning": "",
        }

    @pytest.fixture
    def ideal_trajectory(self) -> dict:
        """Trajectory where none of the lucky-pass heuristics fire."""
        return {
            "paths": [
                {"id": "path_a", "result": "wrong"},
                {"id": "path_b", "result": "correct"},
            ],
            "steps": [
                {
                    "action": "analysis",
                    "content": (
                        "Because the first approach failed, I need to try an "
                        "alternative method since the edge case is not handled."
                    ),
                },
                {
                    "action": "check",
                    "content": "therefore, the second approach should work",
                },
                {
                    "action": "verify",
                    "content": "Comparing outputs to ensure correctness",
                },
            ],
            "actions": ["analyze", "check", "verify"],
            "success": True,
            "explanation": (
                "I used enumeration because the problem requires exhaustive "
                "search, and since the constraint space is small, this is efficient."
            ),
            "reasoning": "analyze → enumerate candidates → verify correctness.",
        }

    # ------------------------------------------------------------------
    # is_lucky_pass
    # ------------------------------------------------------------------

    def test_lucky_trajectory(self, detector, lucky_trajectory):
        assert detector.is_lucky_pass(lucky_trajectory) is True

    def test_ideal_trajectory(self, detector, ideal_trajectory):
        assert detector.is_lucky_pass(ideal_trajectory) is False

    def test_failure_trajectory_not_lucky(self, detector):
        """A failed trajectory should never be considered a lucky pass."""
        traj = {
            "paths": [{"id": "p1", "result": "wrong"}],
            "steps": [{"action": "attempt", "content": "tried something"}],
            "actions": ["attempt"],
            "success": False,
            "explanation": "",
            "reasoning": "",
        }
        assert detector.is_lucky_pass(traj) is False

    def test_single_path_no_explanation_is_lucky(self, detector):
        """2/3 heuristics: single_path + no_explanation = lucky."""
        traj = {
            "paths": [{"id": "only"}],
            "steps": [{"action": "output", "content": "answer"}],
            "actions": ["output"],
            "success": True,
            "explanation": "",
            "reasoning": "brief",
        }
        assert detector.is_lucky_pass(traj) is True

    def test_single_path_with_explanation_not_lucky(self, detector):
        """1/3 heuristics: only single_path fires — not lucky."""
        traj = {
            "paths": [{"id": "only"}],
            "steps": [
                {"action": "analysis", "content": "Because X, I choose Y."},
                {"action": "verify", "content": "Check results."},
            ],
            "actions": ["analysis", "verify"],
            "success": True,
            "explanation": "This approach works because it handles edge cases efficiently and is simple to implement.",
            "reasoning": "",
        }
        assert detector.is_lucky_pass(traj) is False

    def test_no_path_data(self, detector):
        """path_count=0 should not fire single_path heuristic."""
        traj = {
            "paths": [],
            "steps": [
                {"action": "analysis", "content": "Because of constraints, I choose this."},
                {"action": "verify", "content": "Check results."},
            ],
            "actions": ["analysis", "verify"],
            "success": True,
            "explanation": "This is why.",
            "reasoning": "",
        }
        assert detector.is_lucky_pass(traj) is False

    # ------------------------------------------------------------------
    # analyze
    # ------------------------------------------------------------------

    def test_analyze_returns_analysis_dataclass(self, detector, ideal_trajectory):
        result = detector.analyze(ideal_trajectory)
        assert isinstance(result, LuckyPassAnalysis)

    def test_analyze_lucky_probability_happy(self, detector, lucky_trajectory):
        result = detector.analyze(lucky_trajectory)
        assert result.lucky_probability == 1.0
        assert result.is_lucky_pass is True
        assert result.heuristic_signals["single_path"] is True
        assert result.heuristic_signals["no_explanation"] is True
        assert result.heuristic_signals["missing_steps"] is True

    def test_analyze_ideal_probability(self, detector, ideal_trajectory):
        result = detector.analyze(ideal_trajectory)
        assert result.ideal_path_probability == 1.0
        assert result.lucky_probability == 0.0
        assert result.is_lucky_pass is False
        assert result.heuristic_signals["single_path"] is False
        assert result.heuristic_signals["no_explanation"] is False
        assert result.heuristic_signals["missing_steps"] is False

    def test_analyze_missing_steps_reported(self, detector, lucky_trajectory):
        result = detector.analyze(lucky_trajectory)
        assert "too_few_steps" in result.missing_steps
        assert "no_intermediate_markers" in result.missing_steps
        assert "no_causal_reasoning" in result.missing_steps

    def test_analyze_failure_recovery_count(self, detector):
        traj = {
            "paths": [],
            "steps": [
                {"action": "error", "content": "Exception: timeout"},
                {"action": "retry", "content": "Retrying after failure"},
            ],
            "actions": ["error", "retry"],
            "success": True,
            "explanation": "",
            "reasoning": "",
        }
        result = detector.analyze(traj)
        assert result.failure_recovery_count >= 1

    def test_analyze_path_count_and_step_count(self, detector, ideal_trajectory):
        result = detector.analyze(ideal_trajectory)
        assert result.path_count == 2
        assert result.total_steps == 3

    # ------------------------------------------------------------------
    # get_stats
    # ------------------------------------------------------------------

    def test_get_stats_empty(self):
        d = LuckyPassDetector()
        stats = d.get_stats()
        assert stats["total_analyses"] == 0
        assert stats["lucky_count"] == 0
        assert stats["ideal_count"] == 0
        assert stats["avg_lucky_probability"] == 0.0
        assert stats["avg_ideal_probability"] == 0.0

    def test_get_stats_after_analyses(self, detector, lucky_trajectory, ideal_trajectory):
        detector.analyze(lucky_trajectory)
        detector.analyze(ideal_trajectory)
        stats = detector.get_stats()
        assert stats["total_analyses"] == 2
        assert stats["lucky_count"] == 1
        assert stats["ideal_count"] == 1
        assert stats["avg_lucky_probability"] == 0.5

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_empty_trajectory(self, detector):
        result = detector.analyze({})
        assert result.lucky_probability == 0.0
        assert result.is_lucky_pass is False
        assert result.path_count == 0
        assert result.total_steps == 0

    def test_partial_trajectory(self, detector):
        """Only success=True, no other fields — should not be lucky."""
        result = detector.analyze({"success": True})
        assert result.is_lucky_pass is False

    def test_trajectory_with_causal_reasoning_in_steps(self, detector):
        """Causal reasoning in step content should satisfy no_causal_reasoning check."""
        traj = {
            "paths": [{"id": "only"}],
            "steps": [
                {"content": "I choose this because it handles edge cases."},
            ],
            "actions": ["output"],
            "success": True,
            "explanation": "",
            "reasoning": "",
        }
        result = detector.analyze(traj)
        assert "no_causal_reasoning" not in result.missing_steps

    # ------------------------------------------------------------------
    # Re-use / idempotency
    # ------------------------------------------------------------------

    def test_detector_reuse(self, detector):
        """Same detector instance can analyse multiple trajectories."""
        for i in range(5):
            detector.analyze({"paths": [{"id": f"p{i}"}], "success": True})
        assert detector.get_stats()["total_analyses"] == 5

    # ------------------------------------------------------------------
    # Heuristic isolation
    # ------------------------------------------------------------------

    def test_single_path_heuristic_false_when_no_paths(self, detector):
        """path_count=0 should not be 'single path'."""
        result = detector.analyze({"paths": [], "success": True})
        assert result.heuristic_signals["single_path"] is False

    def test_single_path_heuristic_false_when_fail(self, detector):
        result = detector.analyze({"paths": [{"id": "p1"}], "success": False})
        assert result.heuristic_signals["single_path"] is False

    def test_no_explanation_heuristic_large_explanation(self, detector):
        result = detector.analyze({
            "paths": [],
            "success": True,
            "explanation": "a b c d e f g h i j k l m n o p",
        })
        assert result.heuristic_signals["no_explanation"] is False
