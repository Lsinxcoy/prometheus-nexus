"""Tests for SignalFusionLayer — 100% coverage target."""
import time
from unittest.mock import MagicMock
import pytest
from prometheus_nexus.lifecycle.signal_fusion import SignalFusionLayer


class TestInit:
    def test_init(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        assert sfl._omega == omega
        assert sfl._chain_stack == []
        assert sfl._chains == {}
        assert sfl._chain_history == []
        assert sfl._chain_context == {}
        assert sfl._pipe_results == {}
        assert sfl._feedback_queue == []
        assert sfl._merge_hints == {}
        assert sfl._merge_hint_expiry == {}
        assert sfl._last_threshold_adjust == {}


class TestSubscribe:
    def test_subscribe_success(self):
        omega = MagicMock()
        bus = MagicMock()
        sfl = SignalFusionLayer(omega)
        sfl.subscribe(bus)
        # Should subscribe to all 8 pipe events (7 + rumination)
        assert bus.subscribe.call_count == 8

    def test_subscribe_no_method(self):
        omega = MagicMock()
        bus = MagicMock()
        del bus.subscribe
        sfl = SignalFusionLayer(omega)
        sfl.subscribe(bus)


class TestChainStart:
    def test_chain_start(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        cid = sfl.chain_start("test")
        assert cid in sfl._chains
        assert sfl._chains[cid]["trigger"] == "test"
        assert cid in sfl._chain_stack

    def test_chain_start_unique(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        c1 = sfl.chain_start("t")
        c2 = sfl.chain_start("t")
        assert c1 != c2


class TestChainEnd:
    def test_chain_end(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        cid = sfl.chain_start("test")
        sfl.chain_end(cid)
        assert cid not in sfl._chains
        assert cid not in sfl._chain_stack

    def test_chain_end_history(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        cid = sfl.chain_start("test")
        sfl.chain_end(cid)
        assert len(sfl._chain_history) == 1
        assert sfl._chain_history[0]["trigger"] == "test"

    def test_chain_end_cleans_context(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        cid = sfl.chain_start("test")
        sfl.set_chain_context("remember", {"score": 0.9})
        sfl.chain_end(cid)
        assert cid not in sfl._chain_context

    def test_chain_end_nonexistent(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        sfl.chain_end("nonexistent")

    def test_chain_end_truncates(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        for i in range(55):
            c = sfl.chain_start(f"t{i}")
            sfl.chain_end(c)
        # 源码逻辑: > 50 时截断为 [-25:]
        # 前 50 条不触发截断，第 51 条触发截断为 25 条，然后继续添加 4 条 = 29 条
        assert len(sfl._chain_history) == 29


class TestSetChainContext:
    def test_set_context(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        cid = sfl.chain_start("test")
        sfl.set_chain_context("remember", {"score": 0.9})
        assert sfl._chain_context[cid]["trigger_pipe"] == "remember"

    def test_set_context_no_active(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        sfl.set_chain_context("remember", {"score": 0.9})
        assert sfl._chain_context == {}

    def test_set_context_cc_insights(self):
        omega = MagicMock()
        omega.cerebral_cortex = MagicMock()
        omega.cerebral_cortex.get_insights = MagicMock(return_value={"insight": "test"})
        sfl = SignalFusionLayer(omega)
        cid = sfl.chain_start("test")
        sfl.set_chain_context("remember", {"score": 0.9})
        assert sfl._chain_context[cid]["cc_insights"]["insight"] == "test"

    def test_set_context_ar_health(self):
        omega = MagicMock()
        omega.autonomic_regulator = MagicMock()
        omega.autonomic_regulator.get_stats = MagicMock(return_value={"fitness_log_size": 10})
        sfl = SignalFusionLayer(omega)
        cid = sfl.chain_start("test")
        sfl.set_chain_context("remember", {"score": 0.9})
        assert sfl._chain_context[cid]["ar_health"]["fitness_log_size"] == 10

    def test_set_context_cc_exception(self):
        omega = MagicMock()
        omega.cerebral_cortex = MagicMock()
        omega.cerebral_cortex.get_insights = MagicMock(side_effect=Exception("err"))
        sfl = SignalFusionLayer(omega)
        cid = sfl.chain_start("test")
        sfl.set_chain_context("remember", {"score": 0.9})
        assert sfl._chain_context[cid]["cc_insights"] == {}

    def test_set_context_ar_exception(self):
        omega = MagicMock()
        omega.autonomic_regulator = MagicMock()
        omega.autonomic_regulator.get_stats = MagicMock(side_effect=Exception("err"))
        sfl = SignalFusionLayer(omega)
        cid = sfl.chain_start("test")
        sfl.set_chain_context("remember", {"score": 0.9})
        assert sfl._chain_context[cid]["ar_health"] == {}


class TestGetChainContext:
    def test_get_context(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        cid = sfl.chain_start("test")
        sfl.set_chain_context("remember", {"score": 0.9})
        context = sfl.get_chain_context()
        assert context["trigger_pipe"] == "remember"

    def test_get_context_empty(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        sfl.chain_start("test")
        assert sfl.get_chain_context() is None

    def test_get_context_no_active(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        assert sfl.get_chain_context() is None


class TestCleanChainContext:
    def test_clean(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        cid = sfl.chain_start("test")
        sfl.set_chain_context("remember", {"score": 0.9})
        sfl._clean_chain_context(cid)
        assert cid not in sfl._chain_context

    def test_clean_nonexistent(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        sfl._clean_chain_context("nonexistent")


class TestOnPipeEvent:
    def test_on_event(self):
        omega = MagicMock()
        omega.telemetry = MagicMock()
        omega.telemetry.query = MagicMock(return_value=MagicMock(signals={"score": 0.9}))
        sfl = SignalFusionLayer(omega)
        cid = sfl.chain_start("test")
        sfl._on_pipe_event({"data": {"type": "remember_completed"}})
        assert len(sfl._chains[cid]["snapshots"]) == 1

    def test_on_event_no_active(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        sfl._on_pipe_event({"data": {"type": "remember_completed"}})

    def test_on_event_no_type(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        sfl.chain_start("test")
        sfl._on_pipe_event({"data": {}})

    def test_on_event_telemetry_none(self):
        omega = MagicMock()
        omega.telemetry = MagicMock()
        omega.telemetry.query = MagicMock(return_value=None)
        sfl = SignalFusionLayer(omega)
        sfl.chain_start("test")
        sfl._on_pipe_event({"data": {"type": "remember_completed"}})

    def test_on_event_exception(self):
        omega = MagicMock()
        omega.telemetry = MagicMock()
        omega.telemetry.query = MagicMock(side_effect=Exception("err"))
        sfl = SignalFusionLayer(omega)
        sfl.chain_start("test")
        sfl._on_pipe_event({"data": {"type": "remember_completed"}})


class TestChainAnalysis:
    def test_analysis_active(self):
        omega = MagicMock()
        omega.telemetry = MagicMock()
        omega.telemetry.query = MagicMock(return_value=MagicMock(signals={"composite_score": 0.9}))
        sfl = SignalFusionLayer(omega)
        cid = sfl.chain_start("test")
        sfl._on_pipe_event({"data": {"type": "reflect_completed"}})
        result = sfl.chain_analysis(cid)
        assert result["trigger"] == "test"

    def test_analysis_history(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        cid = sfl.chain_start("test")
        sfl.chain_end(cid)
        result = sfl.chain_analysis(cid)
        assert result["trigger"] == "test"

    def test_analysis_nonexistent(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        assert sfl.chain_analysis("nonexistent") is None

    def test_analysis_evolve_delta(self):
        omega = MagicMock()
        omega.telemetry = MagicMock()
        omega.telemetry.query = MagicMock(return_value=MagicMock(signals={"fitness_before": 0.5, "fitness_after": 0.6}))
        sfl = SignalFusionLayer(omega)
        cid = sfl.chain_start("test")
        sfl._on_pipe_event({"data": {"type": "evolve_completed"}})
        result = sfl.chain_analysis(cid)
        # 浮点精度问题：使用近似比较
        assert abs(result["fitness"]["delta"] - 0.1) < 0.001


class TestTrimChains:
    def test_trim_stale(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        sfl._chains["old"] = {"trigger": "t", "started_at": time.time() - 4000, "snapshots": []}
        sfl._chain_stack = []
        sfl._trim_chains()
        assert "old" not in sfl._chains

    def test_trim_keeps_active(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        sfl._chains["old"] = {"trigger": "t", "started_at": time.time() - 4000, "snapshots": []}
        sfl._chain_stack = ["old"]
        sfl._trim_chains()
        assert "old" in sfl._chains


class TestSetPipeResult:
    def test_set_result(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        sfl.set_pipe_result("remember", {"key": "value"})
        assert sfl._pipe_results["remember"]["result"]["key"] == "value"

    def test_set_result_with_chain(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        cid = sfl.chain_start("test")
        # 必须先设置 chain_context，否则 pipe_results 不会被设置
        sfl.set_chain_context("remember", {"score": 0.9})
        sfl.set_pipe_result("remember", {"key": "value"})
        assert "pipe_results" in sfl._chain_context[cid]


class TestGetPipeResult:
    def test_get_result(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        sfl.set_pipe_result("remember", {"key": "value"})
        result = sfl.get_pipe_result("remember")
        assert result["key"] == "value"

    def test_get_result_expired(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        sfl.set_pipe_result("remember", {"key": "value"})
        sfl._pipe_results["remember"]["ts"] = time.time() - 10
        assert sfl.get_pipe_result("remember") is None

    def test_get_result_nonexistent(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        assert sfl.get_pipe_result("nonexistent") is None


class TestPushFeedback:
    def test_push(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        sfl.push_feedback({"from": "learn", "to": "evolve"})
        assert len(sfl._feedback_queue) == 1

    def test_push_adds_ts(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        sfl.push_feedback({"from": "learn"})
        assert "ts" in sfl._feedback_queue[0]

    def test_push_truncates(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        for i in range(105):
            sfl.push_feedback({"from": f"p{i}", "to": "evolve"})
        # 源码逻辑: > 100 时截断为 [-50:]
        # 前 100 条不触发截断，第 101 条触发截断为 50 条，然后继续添加 4 条 = 54 条
        assert len(sfl._feedback_queue) == 54


class TestPopFeedback:
    def test_pop(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        sfl.push_feedback({"from": "learn", "to": "evolve"})
        feedback = sfl.pop_feedback("evolve")
        assert len(feedback) == 1

    def test_pop_clears(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        sfl.push_feedback({"from": "learn", "to": "evolve"})
        sfl.pop_feedback("evolve")
        assert len(sfl._feedback_queue) == 0

    def test_pop_empty(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        assert sfl.pop_feedback("evolve") == []

    def test_pop_only_target(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        sfl.push_feedback({"from": "l", "to": "evolve"})
        sfl.push_feedback({"from": "l", "to": "dream"})
        feedback = sfl.pop_feedback("evolve")
        assert len(feedback) == 1
        assert len(sfl._feedback_queue) == 1


class TestGetPipeSignals:
    def test_get_signals(self):
        omega = MagicMock()
        omega.telemetry = MagicMock()
        snap = MagicMock()
        snap.signals = {"score": 0.9}
        omega.telemetry.query = MagicMock(return_value=snap)
        sfl = SignalFusionLayer(omega)
        assert sfl.get_pipe_signals("remember")["score"] == 0.9

    def test_get_signals_empty(self):
        omega = MagicMock()
        omega.telemetry = MagicMock()
        omega.telemetry.query = MagicMock(return_value=None)
        sfl = SignalFusionLayer(omega)
        assert sfl.get_pipe_signals("remember") == {}

    def test_get_signals_exception(self):
        omega = MagicMock()
        omega.telemetry = MagicMock()
        omega.telemetry.query = MagicMock(side_effect=Exception("err"))
        sfl = SignalFusionLayer(omega)
        assert sfl.get_pipe_signals("remember") == {}


class TestSignal:
    def test_signal_window_1(self):
        omega = MagicMock()
        omega.telemetry = MagicMock()
        snap = MagicMock()
        snap.signals = {"score": 0.9}
        omega.telemetry.query = MagicMock(return_value=snap)
        sfl = SignalFusionLayer(omega)
        assert sfl.signal("remember", "score", window=1) == 0.9

    def test_signal_avg(self):
        omega = MagicMock()
        omega.telemetry = MagicMock()
        snaps = [MagicMock(signals={"score": 0.8}), MagicMock(signals={"score": 0.9})]
        omega.telemetry.query = MagicMock(return_value=snaps)
        sfl = SignalFusionLayer(omega)
        result = sfl.signal("remember", "score", window=2)
        assert abs(result - 0.85) < 0.01  # Allow small floating point error

    def test_signal_no_data(self):
        omega = MagicMock()
        omega.telemetry = MagicMock()
        omega.telemetry.query = MagicMock(return_value=None)
        sfl = SignalFusionLayer(omega)
        assert sfl.signal("remember", "score") is None

    def test_signal_exception(self):
        omega = MagicMock()
        omega.telemetry = MagicMock()
        omega.telemetry.query = MagicMock(side_effect=Exception("err"))
        sfl = SignalFusionLayer(omega)
        assert sfl.signal("remember", "score") is None


class TestReportMerge:
    def test_report_merge(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        sfl.report_merge("reflect", 30.0, 120)
        assert sfl._merge_hints["reflect"] == 120


class TestCheckMergeHint:
    def test_no_hint(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        assert sfl.check_merge_hint("reflect") == 0

    def test_valid(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        sfl.report_merge("reflect", 30.0, 120)
        assert sfl.check_merge_hint("reflect") == 120

    def test_expired(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        sfl.report_merge("reflect", 30.0, 1)
        time.sleep(1.1)
        assert sfl.check_merge_hint("reflect") == 0


class TestSuggestThreshold:
    def test_reflect_to_evolve(self):
        omega = MagicMock()
        omega.telemetry = MagicMock()
        omega.telemetry.query = MagicMock(return_value=[MagicMock(signals={"composite_score": 0.2})] * 10)
        sfl = SignalFusionLayer(omega)
        assert sfl.suggest_threshold("reflect_to_evolve_max_score") == 0.55

    def test_reflect_to_dream(self):
        omega = MagicMock()
        omega.telemetry = MagicMock()
        omega.telemetry.query = MagicMock(return_value=[MagicMock(signals={"patterns_found": 0})] * 10)
        sfl = SignalFusionLayer(omega)
        assert sfl.suggest_threshold("reflect_to_dream_min_score") == 0.85

    def test_evolve_to_dream(self):
        omega = MagicMock()
        omega.telemetry = MagicMock()
        omega.telemetry.query = MagicMock(return_value=[MagicMock(signals={"delta": 0.005})] * 10)
        sfl = SignalFusionLayer(omega)
        assert sfl.suggest_threshold("evolve_to_dream_min_delta") == 0.04

    def test_learn_to_reflect(self):
        omega = MagicMock()
        omega.telemetry = MagicMock()
        omega.telemetry.query = MagicMock(return_value=[MagicMock(signals={"new_nodes": 5})] * 10)
        sfl = SignalFusionLayer(omega)
        assert sfl.suggest_threshold("learn_to_reflect_min_nodes") == 3

    def test_dream_to_maintain(self):
        omega = MagicMock()
        omega.telemetry = MagicMock()
        omega.telemetry.query = MagicMock(return_value=[MagicMock(signals={"patterns_found": 0})] * 10)
        sfl = SignalFusionLayer(omega)
        assert sfl.suggest_threshold("dream_to_maintain_min_patterns") == 2

    def test_evolve_to_heal(self):
        omega = MagicMock()
        omega.telemetry = MagicMock()
        omega.telemetry.query = MagicMock(return_value=[MagicMock(signals={"delta": -0.1})] * 10)
        sfl = SignalFusionLayer(omega)
        assert sfl.suggest_threshold("evolve_to_heal_max_delta") == -0.03

    def test_remember_interval(self):
        omega = MagicMock()
        omega.telemetry = MagicMock()
        omega.telemetry.last_signal = MagicMock(return_value=100)
        sfl = SignalFusionLayer(omega)
        assert sfl.suggest_threshold("remember_reflect_interval") == 100

    def test_unknown_key(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        assert sfl.suggest_threshold("unknown") is None

    def test_too_few_samples(self):
        omega = MagicMock()
        omega.telemetry = MagicMock()
        omega.telemetry.query = MagicMock(return_value=[])
        sfl = SignalFusionLayer(omega)
        assert sfl.suggest_threshold("reflect_to_evolve_max_score") is None

    def test_exception(self):
        omega = MagicMock()
        omega.telemetry = MagicMock()
        omega.telemetry.query = MagicMock(side_effect=Exception("err"))
        sfl = SignalFusionLayer(omega)
        assert sfl.suggest_threshold("reflect_to_evolve_max_score") is None


class TestApplyThresholdAdjustments:
    def test_cooldown(self):
        omega = MagicMock()
        omega.cns = MagicMock()
        omega.cns._thresholds = {}
        omega.cns.update_threshold = MagicMock()
        sfl = SignalFusionLayer(omega)
        sfl._last_threshold_adjust["_last_apply"] = time.time()
        assert sfl.apply_threshold_adjustments() == []

    def test_no_cns(self):
        omega = MagicMock()
        # Remove cns attribute entirely
        if hasattr(omega, 'cns'):
            delattr(omega, 'cns')
        sfl = SignalFusionLayer(omega)
        assert sfl.apply_threshold_adjustments() == []

    def test_success(self):
        omega = MagicMock()
        omega.cns = MagicMock()
        omega.cns._thresholds = {"reflect_to_evolve_max_score": 0.5}
        omega.cns.update_threshold = MagicMock()
        omega.telemetry = MagicMock()
        omega.telemetry.query = MagicMock(return_value=[MagicMock(signals={"composite_score": 0.8})] * 10)
        sfl = SignalFusionLayer(omega)
        result = sfl.apply_threshold_adjustments()
        assert len(result) > 0

    def test_pending_threshold(self):
        omega = MagicMock()
        omega.cns = MagicMock()
        omega.cns._thresholds = {"reflect_to_evolve_max_score": 0.5}
        omega.cns.update_threshold = MagicMock()
        omega.cerebral_cortex = MagicMock()
        omega.cerebral_cortex._pending_threshold = 0.3
        omega.telemetry = MagicMock()
        omega.telemetry.query = MagicMock(return_value=[MagicMock(signals={"composite_score": 0.8})] * 10)
        sfl = SignalFusionLayer(omega)
        result = sfl.apply_threshold_adjustments()
        # Should use min of suggested and pending
        assert len(result) > 0


class TestGetState:
    def test_get_state(self):
        omega = MagicMock()
        sfl = SignalFusionLayer(omega)
        state = sfl.get_state()
        assert state["active_chains"] == 0
        assert state["chains"] == 0
        assert state["chain_history"] == 0
        assert state["chain_contexts"] == 0
        assert state["feedback_queue"] == 0
