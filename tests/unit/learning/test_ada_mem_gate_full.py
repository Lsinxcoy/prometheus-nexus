"""Tests for AdaMEMGate — 自适应记忆检索门控。"""

import time
from unittest.mock import MagicMock, patch

import pytest

from prometheus_nexus.learning.ada_mem_gate import AdaMEMGate


class TestAdaMEMGateInit:
    """测试初始化。"""

    def test_init(self):
        gate = AdaMEMGate()
        assert gate._recent_queries == {}
        assert gate._skip_count == 0
        assert gate._total_count == 0


class TestShouldRetrieve:
    """测试 should_retrieve 方法。"""

    def test_empty_query(self):
        """空查询 → 跳过。"""
        gate = AdaMEMGate()
        assert gate.should_retrieve("") is False
        assert gate._skip_count == 1
        assert gate._total_count == 1

    def test_whitespace_query(self):
        """纯空白查询 → 跳过。"""
        gate = AdaMEMGate()
        assert gate.should_retrieve("   ") is False

    def test_single_word_query(self):
        """单词查询（≤2个词）→ 跳过。"""
        gate = AdaMEMGate()
        assert gate.should_retrieve("AI") is False
        assert gate.should_retrieve("hello") is False

    def test_two_word_query(self):
        """两词查询 → 应该检索（阈值是 ≤1）。"""
        gate = AdaMEMGate()
        assert gate.should_retrieve("hello world") is True

    def test_three_word_query(self):
        """三词查询 → 应该检索。"""
        gate = AdaMEMGate()
        assert gate.should_retrieve("what is ai") is True

    def test_long_query(self):
        """长查询 → 应该检索。"""
        gate = AdaMEMGate()
        assert gate.should_retrieve("what is the meaning of artificial intelligence and machine learning") is True

    def test_duplicate_query_within_60s(self):
        """同一查询 60 秒内重复 → 跳过。"""
        gate = AdaMEMGate()
        gate.should_retrieve("what is artificial intelligence")
        # 第二次调用应该跳过
        assert gate.should_retrieve("What is artificial intelligence") is False

    def test_duplicate_query_after_60s(self):
        """同一查询超过 60 秒后 → 应该检索。"""
        gate = AdaMEMGate()
        gate.should_retrieve("what is artificial intelligence")
        # 模拟时间流逝
        with patch.object(time, 'time', return_value=time.time() + 61):
            assert gate.should_retrieve("what is artificial intelligence") is True

    def test_creative_task_type(self):
        """创作型任务 → 低检索频率。"""
        gate = AdaMEMGate()
        assert gate.should_retrieve("write a story about cats", task_type="creative") is False

    def test_reasoning_task_type(self):
        """推理型任务 → 应该检索。"""
        gate = AdaMEMGate()
        assert gate.should_retrieve("solve this math problem", task_type="reasoning") is True

    def test_dialogue_task_type(self):
        """对话型任务 → 应该检索。"""
        gate = AdaMEMGate()
        assert gate.should_retrieve("how are you today", task_type="dialogue") is True

    def test_execution_task_type(self):
        """执行型任务 → 应该检索。"""
        gate = AdaMEMGate()
        assert gate.should_retrieve("run this command", task_type="execution") is True

    def test_case_insensitive(self):
        """大小写不敏感。"""
        gate = AdaMEMGate()
        gate.should_retrieve("What is AI")
        # 不同大小写视为相同查询
        assert gate.should_retrieve("what is ai") is False

    def test_exception_handling(self):
        """异常时 fail-safe 返回 True。"""
        gate = AdaMEMGate()
        # 模拟 query 抛出异常
        with patch.object(gate, '_total_count', side_effect=Exception("test")):
            result = gate.should_retrieve("normal query")
            assert result is True

    def test_increments_counters(self):
        """正常流程增加计数器。"""
        gate = AdaMEMGate()
        gate.should_retrieve("valid query")
        assert gate._total_count == 1
        assert gate._skip_count == 0

    def test_skip_increments_on_failure(self):
        """跳过时增加 skip_count。"""
        gate = AdaMEMGate()
        gate.should_retrieve("")
        gate.should_retrieve("short")
        gate.should_retrieve("creative task", task_type="creative")
        assert gate._skip_count == 3
        assert gate._total_count == 3


class TestGetSkipRate:
    """测试 get_skip_rate 方法。"""

    def test_initial_skip_rate(self):
        """初始状态跳过率为 0。"""
        gate = AdaMEMGate()
        assert gate.get_skip_rate() == 0.0

    def test_skip_rate_after_skips(self):
        """有跳过时的跳过率。"""
        gate = AdaMEMGate()
        gate.should_retrieve("")
        gate.should_retrieve("a")
        gate.should_retrieve("valid query")
        assert gate.get_skip_rate() == pytest.approx(2 / 3)

    def test_skip_rate_all_skipped(self):
        """全部跳过时跳过率为 1。"""
        gate = AdaMEMGate()
        gate.should_retrieve("")
        gate.should_retrieve("a")
        gate.should_retrieve("b")
        assert gate.get_skip_rate() == 1.0

    def test_skip_rate_none_skipped(self):
        """无跳过时跳过率为 0。"""
        gate = AdaMEMGate()
        gate.should_retrieve("valid query one")
        gate.should_retrieve("valid query two")
        gate.should_retrieve("valid query three")
        assert gate.get_skip_rate() == 0.0


class TestResetStats:
    """测试 reset_stats 方法。"""

    def test_reset_stats(self):
        """重置统计信息。"""
        gate = AdaMEMGate()
        gate.should_retrieve("")
        gate.should_retrieve("valid query")
        assert gate._skip_count == 1
        assert gate._total_count == 2
        gate.reset_stats()
        assert gate._skip_count == 0
        assert gate._total_count == 0

    def test_reset_preserves_recent_queries(self):
        """重置不影响最近查询记录。"""
        gate = AdaMEMGate()
        gate.should_retrieve("valid query")
        gate.reset_stats()
        # recent_queries 不应被清空（用于去重）
        assert "valid query" in gate._recent_queries


class TestIntegration:
    """集成测试。"""

    def test_full_workflow(self):
        """完整工作流。"""
        gate = AdaMEMGate()

        # 短查询跳过
        assert gate.should_retrieve("hi") is False
        assert gate.should_retrieve("ok") is False

        # 有效查询通过
        assert gate.should_retrieve("what is the weather") is True

        # 重复查询跳过
        assert gate.should_retrieve("what is the weather") is False

        # 创作型任务跳过
        assert gate.should_retrieve("write a poem", task_type="creative") is False

        # 检查跳过率
        assert gate.get_skip_rate() > 0

    def test_mixed_operations(self):
        """混合操作。"""
        gate = AdaMEMGate()

        # 各种查询
        results = [
            gate.should_retrieve(""),  # False
            gate.should_retrieve("a"),  # False
            gate.should_retrieve("what is ai"),  # True
            gate.should_retrieve("tell me a story", task_type="creative"),  # False
            gate.should_retrieve("explain quantum computing"),  # True
        ]

        assert results == [False, False, True, False, True]
        assert gate._total_count == 5
        assert gate._skip_count == 3

    def test_statistics_tracking(self):
        """统计跟踪。"""
        gate = AdaMEMGate()

        # 执行多次操作
        for i in range(10):
            gate.should_retrieve(f"query number {i}")

        # 添加一些跳过
        for i in range(5):
            gate.should_retrieve("")

        assert gate._total_count == 15
        assert gate._skip_count == 5
        assert gate.get_skip_rate() == pytest.approx(5 / 15)
