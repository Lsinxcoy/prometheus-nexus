"""Tests for LearnFeedbackTracker — P0修复验证

验证learn→recall反馈环是否工作正常。
"""
import pytest
from prometheus_nexus.learning.learn_feedback import LearnFeedbackTracker


class TestLearnFeedbackTracker:
    """LearnFeedbackTracker单元测试"""

    def test_register_and_hit(self):
        """注册节点后标记命中，命中率应>0"""
        tracker = LearnFeedbackTracker()
        tracker.register("node_1", source="web", query="AI agent")
        tracker.mark_hit("node_1", "AI agent")
        assert tracker.get_hit_rate("web", "AI agent") == 1.0

    def test_miss_no_hit(self):
        """未命中时命中率为0"""
        tracker = LearnFeedbackTracker()
        tracker.register("node_1", source="web", query="AI agent")
        # 不调用mark_hit
        assert tracker.get_hit_rate("web", "AI agent") == 0.0

    def test_global_hit_rate(self):
        """全局命中率计算正确"""
        tracker = LearnFeedbackTracker()
        tracker.register("n1", "web", "query1")
        tracker.register("n2", "web", "query2")
        tracker.register("n3", "arxiv", "query1")
        tracker.mark_hit("n1", "query1")
        tracker.mark_hit("n3", "query1")
        # 2 hits / 3 registered = 0.667
        assert abs(tracker.get_hit_rate() - 0.667) < 0.01

    def test_stats_by_source(self):
        """按来源统计正确"""
        tracker = LearnFeedbackTracker()
        tracker.register("n1", "web", "q1")
        tracker.register("n2", "web", "q2")
        tracker.register("n3", "arxiv", "q1")
        tracker.mark_hit("n1", "q1")
        stats = tracker.get_stats()
        assert stats["total_registered"] == 3
        assert stats["total_hits"] == 1
        assert stats["by_source"]["web"]["registered"] == 2
        assert stats["by_source"]["web"]["hits"] == 1
        assert stats["by_source"]["arxiv"]["registered"] == 1
        assert stats["by_source"]["arxiv"]["hits"] == 0

    def test_reset(self):
        """重置后所有数据清空"""
        tracker = LearnFeedbackTracker()
        tracker.register("n1", "web", "q1")
        tracker.mark_hit("n1", "q1")
        tracker.reset()
        assert tracker.get_hit_rate() == 0.0
        assert tracker.get_stats()["total_registered"] == 0

    def test_empty_query_returns_zero(self):
        """无查询参数时返回全局命中率"""
        tracker = LearnFeedbackTracker()
        assert tracker.get_hit_rate() == 0.0

    def test_unknown_query_returns_zero(self):
        """未知查询返回0"""
        tracker = LearnFeedbackTracker()
        tracker.register("n1", "web", "q1")
        assert tracker.get_hit_rate("web", "unknown") == 0.0
