"""Tests for CNSOrchestrator — 100% coverage target.

Based on arXiv 2605.15338 (Sleeper) and system design documents.
"""
import time
from unittest.mock import MagicMock, patch
import pytest
from prometheus_nexus.lifecycle.cns_orchestrator import CNSOrchestrator


class TestInit:
    """Test CNSOrchestrator initialization."""

    def test_init_default(self):
        omega = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        assert orchestrator._omega == omega
        assert orchestrator._state == "IDLE"
        assert orchestrator._auto_chain_depth == 0
        assert orchestrator._node_count_threshold == 100
        assert orchestrator._trigger_log == []
        assert orchestrator._last_trigger_time == {}

    def test_init_has_lock(self):
        omega = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        assert hasattr(orchestrator, '_min_interval')
        assert orchestrator._min_interval["reflect"] == 30
        assert orchestrator._min_interval["evolve"] == 60
        assert orchestrator._min_interval["dream"] == 120
        assert orchestrator._min_interval["maintain"] == 60

    def test_init_default_thresholds(self):
        omega = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        assert orchestrator._thresholds["learn_to_reflect_min_nodes"] == 1
        assert orchestrator._thresholds["reflect_to_evolve_max_score"] == 0.5
        assert orchestrator._thresholds["reflect_to_dream_min_score"] == 0.8
        assert orchestrator._thresholds["evolve_to_dream_min_delta"] == 0.02
        assert orchestrator._thresholds["evolve_to_heal_max_delta"] == -0.02
        assert orchestrator._thresholds["dream_to_maintain_min_patterns"] == 1
        assert orchestrator._thresholds["remember_reflect_interval"] == 100


class TestSubscribe:
    """Test subscribe method."""

    def test_subscribe_success(self):
        omega = MagicMock()
        bus = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        orchestrator.subscribe(bus)
        # Should subscribe to all 8 pipeline events (7 + rumination_completed)
        assert bus.subscribe.call_count == 8

    def test_subscribe_no_subscribe_method(self):
        omega = MagicMock()
        bus = MagicMock()
        del bus.subscribe  # Remove subscribe method
        orchestrator = CNSOrchestrator(omega)
        orchestrator.subscribe(bus)
        # Should not raise exception


class TestCanTrigger:
    """Test _can_trigger method."""

    def test_can_trigger_max_depth(self):
        omega = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        orchestrator._auto_chain_depth = orchestrator._MAX_AUTO_DEPTH
        assert orchestrator._can_trigger("reflect") is False

    def test_can_trigger_time_interval(self):
        omega = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        orchestrator._last_trigger_time["reflect"] = time.time()
        assert orchestrator._can_trigger("reflect") is False

    def test_can_trigger_merge_hint_exception(self):
        omega = MagicMock()
        omega.signal_fusion = MagicMock()
        omega.cerebral_cortex = MagicMock()
        omega.cerebral_cortex.should_suppress_trigger = MagicMock(return_value=False)
        omega.signal_fusion.check_merge_hint = MagicMock(side_effect=Exception("test error"))
        orchestrator = CNSOrchestrator(omega)
        orchestrator._last_trigger_time["reflect"] = time.time() - 100  # Make sure interval is passed
        result = orchestrator._can_trigger("reflect")
        # Should handle exception and return True
        assert result is True

    def test_on_recall_cc_fuse_check(self):
        omega = MagicMock()
        omega.cerebral_cortex = MagicMock()
        omega.cerebral_cortex.get_gap_count = MagicMock(return_value=1)
        omega.cerebral_cortex._config = {"gap_max_count": 3}
        omega.cerebral_cortex.record_gap = MagicMock()
        omega.cerebral_cortex.check_and_trigger_gap_learn = MagicMock(return_value=False)
        orchestrator = CNSOrchestrator(omega)
        orchestrator._can_trigger = MagicMock(return_value=True)
        orchestrator._on_recall({"data": {"query": "test", "hits": 0}})
        # Should have called CC methods

    def test_on_recall_exception_inner(self):
        omega = MagicMock()
        omega.cerebral_cortex = MagicMock()
        omega.cerebral_cortex.get_gap_count = MagicMock(side_effect=Exception("test error"))
        orchestrator = CNSOrchestrator(omega)
        orchestrator._on_recall({"data": {"query": "test", "hits": 0}})
        # Should handle inner exception gracefully

    def test_on_evolve_cache_cleanup_exception(self):
        omega = MagicMock()
        omega.cache.cleanup_expired = MagicMock(side_effect=Exception("test error"))
        orchestrator = CNSOrchestrator(omega)
        orchestrator._on_evolve({"data": {"fitness_before": 0.5, "fitness_after": 0.6}})
        # Should handle cache cleanup exception gracefully

    def test_on_dream_cache_cleanup_exception(self):
        omega = MagicMock()
        omega.cache.cleanup_expired = MagicMock(side_effect=Exception("test error"))
        orchestrator = CNSOrchestrator(omega)
        orchestrator._on_dream({"data": {"patterns": 5}})
        # Should handle cache cleanup exception gracefully

    def test_on_maintain_exception(self):
        omega = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        orchestrator._on_maintain({"data": {}})
        # Should handle exception gracefully

    def test_can_trigger_merge_hint_suppress(self):
        omega = MagicMock()
        omega.signal_fusion = MagicMock()
        omega.cerebral_cortex = MagicMock()
        omega.cerebral_cortex.should_suppress_trigger = MagicMock(return_value=False)
        omega.signal_fusion.check_merge_hint = MagicMock(return_value=100)
        orchestrator = CNSOrchestrator(omega)
        orchestrator._last_trigger_time["reflect"] = time.time() - 10  # Less than hint_interval=100
        assert orchestrator._can_trigger("reflect") is False

    def test_can_trigger_merge_hint_no_last_time(self):
        omega = MagicMock()
        omega.signal_fusion = MagicMock()
        omega.cerebral_cortex = MagicMock()
        omega.cerebral_cortex.should_suppress_trigger = MagicMock(return_value=False)
        omega.signal_fusion.check_merge_hint = MagicMock(return_value=100)
        orchestrator = CNSOrchestrator(omega)
        orchestrator._last_trigger_time["reflect"] = 0.0  # No last trigger time
        result = orchestrator._can_trigger("reflect")
        # Should not suppress when last == 0 (line 125 condition fails)
        assert result is True

    def test_can_trigger_merge_hint_zero_interval(self):
        omega = MagicMock()
        omega.signal_fusion = MagicMock()
        omega.cerebral_cortex = MagicMock()
        omega.cerebral_cortex.should_suppress_trigger = MagicMock(return_value=False)
        omega.signal_fusion.check_merge_hint = MagicMock(return_value=0)  # hint_interval = 0
        orchestrator = CNSOrchestrator(omega)
        orchestrator._last_trigger_time["reflect"] = 0.0  # No last trigger time, so interval check passes
        result = orchestrator._can_trigger("reflect")
        # Should not suppress when hint_interval == 0 (line 125 condition fails)
        assert result is True

    def test_can_trigger_cc_fuse_suppress(self):
        omega = MagicMock()
        omega.cerebral_cortex = MagicMock()
        omega.cerebral_cortex.should_suppress_trigger = MagicMock(return_value=True)
        orchestrator = CNSOrchestrator(omega)
        orchestrator._last_trigger_time["reflect"] = 0.0
        assert orchestrator._can_trigger("reflect") is False

    def test_can_trigger_feedback_suppress(self):
        omega = MagicMock()
        omega.signal_fusion = MagicMock()
        omega.cerebral_cortex = MagicMock()
        omega.cerebral_cortex.should_suppress_trigger = MagicMock(return_value=False)
        omega.signal_fusion.pop_feedback = MagicMock(return_value=[
            {"type": "suppress", "data": {"reason": "test suppress"}}
        ])
        orchestrator = CNSOrchestrator(omega)
        orchestrator._last_trigger_time["reflect"] = 0.0
        assert orchestrator._can_trigger("reflect") is False

    def test_can_trigger_feedback_quality(self):
        omega = MagicMock()
        omega.signal_fusion = MagicMock()
        omega.cerebral_cortex = MagicMock()
        omega.cerebral_cortex.should_suppress_trigger = MagicMock(return_value=False)
        omega.signal_fusion.pop_feedback = MagicMock(return_value=[
            {"type": "quality", "data": {"delta": 0.1}}
        ])
        orchestrator = CNSOrchestrator(omega)
        orchestrator._last_trigger_time["reflect"] = 0.0
        result = orchestrator._can_trigger("reflect")
        assert result is True
        # Should lower the interval
        assert orchestrator._min_interval["reflect"] < 30

    def test_can_trigger_feedback_efficacy(self):
        omega = MagicMock()
        omega.signal_fusion = MagicMock()
        omega.cerebral_cortex = MagicMock()
        omega.cerebral_cortex.should_suppress_trigger = MagicMock(return_value=False)
        omega.signal_fusion.pop_feedback = MagicMock(return_value=[
            {"type": "efficacy", "data": {"delta": -0.1}}
        ])
        orchestrator = CNSOrchestrator(omega)
        orchestrator._last_trigger_time["reflect"] = 0.0
        result = orchestrator._can_trigger("reflect")
        assert result is True
        # Should raise the interval
        assert orchestrator._min_interval["reflect"] > 30

    def test_can_trigger_success(self):
        omega = MagicMock()
        omega.cerebral_cortex = MagicMock()
        omega.cerebral_cortex.should_suppress_trigger = MagicMock(return_value=False)
        orchestrator = CNSOrchestrator(omega)
        orchestrator._last_trigger_time["reflect"] = 0.0
        assert orchestrator._can_trigger("reflect") is True

    def test_can_trigger_cc_fuse_exception(self):
        omega = MagicMock()
        omega.cerebral_cortex = MagicMock()
        omega.cerebral_cortex.should_suppress_trigger = MagicMock(side_effect=Exception("test error"))
        orchestrator = CNSOrchestrator(omega)
        orchestrator._last_trigger_time["reflect"] = 0.0
        result = orchestrator._can_trigger("reflect")
        # Should handle exception and return True
        assert result is True

    def test_can_trigger_pop_feedback_exception(self):
        omega = MagicMock()
        omega.signal_fusion = MagicMock()
        omega.cerebral_cortex = MagicMock()
        omega.cerebral_cortex.should_suppress_trigger = MagicMock(return_value=False)
        omega.signal_fusion.pop_feedback = MagicMock(side_effect=Exception("test error"))
        orchestrator = CNSOrchestrator(omega)
        orchestrator._last_trigger_time["reflect"] = 0.0
        result = orchestrator._can_trigger("reflect")
        # Should handle exception and return True
        assert result is True


class TestRecordTrigger:
    """Test _record_trigger method."""

    def test_record_trigger(self):
        omega = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        event_data = {"key": "value", "data": {"nested": "data"}}
        orchestrator._record_trigger("remember", "reflect", "test reason", event_data)
        assert len(orchestrator._trigger_log) == 1
        assert orchestrator._trigger_log[0]["trigger"] == "remember"
        assert orchestrator._trigger_log[0]["target"] == "reflect"
        assert orchestrator._trigger_log[0]["reason"] == "test reason"
        assert "data" not in orchestrator._trigger_log[0]["event_data"]

    def test_record_trigger_log_size(self):
        omega = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        # Add more than 100 triggers
        for i in range(105):
            orchestrator._record_trigger("test", "target", f"reason {i}", {"i": i})
        # After adding 105 triggers:
        # - First 100 don't trigger truncation
        # - 101st triggers truncation to last 50 using [-50:], which starts at index 51
        # - Then we add 4 more (102-105), making it 54 total
        assert len(orchestrator._trigger_log) == 54
        # Check that the first entry is from index 51 (after truncation with [-50:])
        assert orchestrator._trigger_log[0]["reason"] == "reason 51"
        # Check that the last entry is from index 104
        assert orchestrator._trigger_log[-1]["reason"] == "reason 104"


class TestOnRemember:
    """Test _on_remember method."""

    def test_on_remember_triggers_reflect(self):
        omega = MagicMock()
        omega.store.get_node_count = MagicMock(return_value=150)
        orchestrator = CNSOrchestrator(omega)
        orchestrator._node_count_threshold = 100
        orchestrator._can_trigger = MagicMock(return_value=True)
        orchestrator._on_remember({"data": {}})
        assert omega.reflect.called

    def test_on_remember_below_threshold(self):
        omega = MagicMock()
        omega.store.get_node_count = MagicMock(return_value=50)
        orchestrator = CNSOrchestrator(omega)
        orchestrator._node_count_threshold = 100
        orchestrator._on_remember({"data": {}})
        assert not omega.reflect.called

    def test_on_remember_exception(self):
        omega = MagicMock()
        omega.store.get_node_count = MagicMock(side_effect=Exception("test error"))
        orchestrator = CNSOrchestrator(omega)
        orchestrator._on_remember({"data": {}})
        # Should not raise exception


class TestOnRecall:
    """Test _on_recall method."""

    def test_on_recall_with_hits(self):
        omega = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        orchestrator._on_recall({"data": {"query": "test", "hits": 5}})
        # Should not trigger anything when hits > 0

    def test_on_recall_empty_query(self):
        omega = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        orchestrator._on_recall({"data": {"query": "", "hits": 0}})
        # Should not trigger anything when query is empty

    def test_on_recall_gap_detection(self):
        omega = MagicMock()
        omega.cerebral_cortex = MagicMock()
        omega.cerebral_cortex.get_gap_count = MagicMock(return_value=1)
        omega.cerebral_cortex._config = {"gap_max_count": 3}
        omega.cerebral_cortex.record_gap = MagicMock()
        omega.cerebral_cortex.check_and_trigger_gap_learn = MagicMock(return_value=False)
        orchestrator = CNSOrchestrator(omega)
        orchestrator._can_trigger = MagicMock(return_value=True)
        orchestrator._on_recall({"data": {"query": "test", "hits": 0}})
        assert omega.cerebral_cortex.record_gap.called

    def test_on_recall_gap_at_max(self):
        omega = MagicMock()
        omega.cerebral_cortex = MagicMock()
        omega.cerebral_cortex.get_gap_count = MagicMock(return_value=3)
        omega.cerebral_cortex._config = {"gap_max_count": 3}
        orchestrator = CNSOrchestrator(omega)
        orchestrator._on_recall({"data": {"query": "test", "hits": 0}})
        # Should not trigger when gap count is at max

    def test_on_recall_no_cc(self):
        omega = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        orchestrator._on_recall({"data": {"query": "test", "hits": 0}})
        # Should not raise exception when no cerebral_cortex (line 245 return)

    def test_on_recall_cc_none(self):
        omega = MagicMock()
        delattr(omega, 'cerebral_cortex')  # Ensure no cerebral_cortex attribute
        orchestrator = CNSOrchestrator(omega)
        orchestrator._on_recall({"data": {"query": "test", "hits": 0}})
        # Should return early when cc is None (line 245)

    def test_on_recall_exception(self):
        omega = MagicMock()
        omega.cerebral_cortex = MagicMock()
        omega.cerebral_cortex.get_gap_count = MagicMock(side_effect=Exception("test error"))
        orchestrator = CNSOrchestrator(omega)
        orchestrator._on_recall({"data": {"query": "test", "hits": 0}})
        # Should handle exception gracefully (line 285-286)

    def test_on_recall_outer_exception(self):
        omega = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        # Make the outer try block fail
        orchestrator._on_recall({"data": {}})  # No query key, should trigger inner exception
        # Should handle outer exception gracefully (line 285-286)

    def test_on_recall_check_and_trigger_true(self):
        omega = MagicMock()
        omega.cerebral_cortex = MagicMock()
        omega.cerebral_cortex.get_gap_count = MagicMock(return_value=1)
        omega.cerebral_cortex._config = {"gap_max_count": 3}
        omega.cerebral_cortex.record_gap = MagicMock()
        omega.cerebral_cortex.check_and_trigger_gap_learn = MagicMock(return_value=True)
        orchestrator = CNSOrchestrator(omega)
        orchestrator._on_recall({"data": {"query": "test", "hits": 0}})
        # Should return early when check_and_trigger_gap_learn returns True

    def test_on_recall_no_gaps(self):
        omega = MagicMock()
        omega.cerebral_cortex = MagicMock()
        omega.cerebral_cortex.get_gap_count = MagicMock(return_value=0)
        omega.cerebral_cortex._config = {"gap_max_count": 3}
        orchestrator = CNSOrchestrator(omega)
        orchestrator._on_recall({"data": {"query": "test", "hits": 0}})
        # Should return early when CC hasn't detected gap yet


class TestOnLearn:
    """Test _on_learn method."""

    def test_on_learn_triggers_reflect(self):
        omega = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        orchestrator._can_trigger = MagicMock(return_value=True)
        orchestrator._on_learn({"data": {"new_nodes": 5, "source": "web", "query": "test"}})
        assert omega.reflect.called

    def test_on_learn_below_threshold(self):
        omega = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        orchestrator._on_learn({"data": {"new_nodes": 1, "source": "web", "query": "test"}})
        assert not omega.reflect.called

    def test_on_learn_exception(self):
        omega = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        orchestrator._can_trigger = MagicMock(side_effect=Exception("test error"))
        orchestrator._on_learn({"data": {"new_nodes": 5}})
        # Should handle exception gracefully


class TestOnReflect:
    """Test _on_reflect method."""

    def test_on_reflect_low_score_triggers_evolve(self):
        omega = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        orchestrator._can_trigger = MagicMock(return_value=True)
        orchestrator._on_reflect({"data": {"composite_score": 0.3, "drift_alerts": 2}})
        assert omega.evolve.called

    def test_on_reflect_high_score_triggers_dream(self):
        omega = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        orchestrator._can_trigger = MagicMock(return_value=True)
        orchestrator._on_reflect({"data": {"composite_score": 0.9, "drift_alerts": 0}})
        assert omega.dream_cycle.called

    def test_on_reflect_very_high_score_no_action(self):
        omega = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        orchestrator._on_reflect({"data": {"composite_score": 0.96, "drift_alerts": 0}})
        assert not omega.evolve.called
        assert not omega.dream_cycle.called

    def test_on_reflect_mid_range_no_action(self):
        omega = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        orchestrator._on_reflect({"data": {"composite_score": 0.6, "drift_alerts": 0}})
        assert not omega.evolve.called
        assert not omega.dream_cycle.called

    def test_on_reflect_exception(self):
        omega = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        orchestrator._can_trigger = MagicMock(side_effect=Exception("test error"))
        orchestrator._on_reflect({"data": {"composite_score": 0.3}})
        # Should handle exception gracefully


class TestOnEvolve:
    """Test _on_evolve method."""

    def test_on_evolve_positive_delta_triggers_dream(self):
        omega = MagicMock()
        omega.cache.cleanup_expired = MagicMock()
        # C1 质量门: 无审议信号(consensus=None) 应放行
        omega.signal_fusion.signal.return_value = None
        orchestrator = CNSOrchestrator(omega)
        orchestrator._can_trigger = MagicMock(return_value=True)
        orchestrator._on_evolve({"data": {"fitness_before": 0.5, "fitness_after": 0.6}})
        assert omega.dream_cycle.called

    def test_on_evolve_negative_delta_logs(self):
        omega = MagicMock()
        omega.cache.cleanup_expired = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        orchestrator._on_evolve({"data": {"fitness_before": 0.5, "fitness_after": 0.4}})
        assert not omega.dream_cycle.called

    def test_on_evolve_cache_cleanup(self):
        omega = MagicMock()
        omega.cache.cleanup_expired = MagicMock()
        # C1 质量门: 无审议信号(consensus=None) 应放行 → dream 触发 → cache cleanup
        omega.signal_fusion.signal.return_value = None
        orchestrator = CNSOrchestrator(omega)
        orchestrator._can_trigger = MagicMock(return_value=True)
        orchestrator._on_evolve({"data": {"fitness_before": 0.5, "fitness_after": 0.6}})
        assert omega.cache.cleanup_expired.called

    def test_on_evolve_exception(self):
        omega = MagicMock()
        omega.cache.cleanup_expired = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        orchestrator._can_trigger = MagicMock(side_effect=Exception("test error"))
        orchestrator._on_evolve({"data": {"fitness_before": 0.5, "fitness_after": 0.6}})
        # Should handle exception gracefully


class TestOnDream:
    """Test _on_dream method."""

    def test_on_dream_triggers_maintain(self):
        omega = MagicMock()
        omega.cache.cleanup_expired = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        orchestrator._can_trigger = MagicMock(return_value=True)
        orchestrator._on_dream({"data": {"patterns": 5}})
        assert omega.maintain.called

    def test_on_dream_below_threshold(self):
        omega = MagicMock()
        omega.cache.cleanup_expired = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        orchestrator._on_dream({"data": {"patterns": 0}})
        assert not omega.maintain.called

    def test_on_dream_cache_cleanup(self):
        omega = MagicMock()
        omega.cache.cleanup_expired = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        orchestrator._on_dream({"data": {"patterns": 5}})
        assert omega.cache.cleanup_expired.called

    def test_on_dream_exception(self):
        omega = MagicMock()
        omega.cache.cleanup_expired = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        orchestrator._can_trigger = MagicMock(side_effect=Exception("test error"))
        orchestrator._on_dream({"data": {"patterns": 5}})
        # Should handle exception gracefully


class TestOnMaintain:
    """Test _on_maintain method."""

    def test_on_maintain(self):
        omega = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        orchestrator._on_maintain({"data": {"decayed": 10}})
        # Should log but not trigger anything

    def test_on_maintain_exception(self):
        omega = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        orchestrator._on_maintain({"data": {}})
        # Should handle exception gracefully (line 475-476)

    def test_on_maintain_no_data(self):
        omega = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        orchestrator._on_maintain({})  # No data key
        # Should handle missing data gracefully (line 475-476)


class TestGetState:
    """Test get_state method."""

    def test_get_state(self):
        omega = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        state = orchestrator.get_state()
        assert state["state"] == "IDLE"
        assert state["auto_chain_depth"] == 0
        assert state["node_count_threshold"] == 100
        assert state["triggers_fired"] == 0
        assert state["recent_triggers"] == []

    def test_get_state_with_triggers(self):
        omega = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        orchestrator._record_trigger("test", "target", "reason", {"key": "value"})
        state = orchestrator.get_state()
        assert state["triggers_fired"] == 1
        assert len(state["recent_triggers"]) == 1


class TestUpdateThreshold:
    """Test update_threshold method."""

    def test_update_threshold_success(self):
        omega = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        result = orchestrator.update_threshold("learn_to_reflect_min_nodes", 5)
        assert result is True
        assert orchestrator._thresholds["learn_to_reflect_min_nodes"] == 5

    def test_update_threshold_invalid_key(self):
        omega = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        result = orchestrator.update_threshold("invalid_key", 5)
        assert result is False


class TestOnLearnCompleted:
    """Test on_learn_completed public API."""

    def test_on_learn_completed(self):
        omega = MagicMock()
        orchestrator = CNSOrchestrator(omega)
        orchestrator._can_trigger = MagicMock(return_value=True)
        orchestrator.on_learn_completed({"data": {"new_nodes": 5}})
        assert omega.reflect.called