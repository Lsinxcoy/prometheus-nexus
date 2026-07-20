"""Tests for FiveGates — P2修复验证

验证自适应阈值是否生效，pass_rate应在合理范围。
"""
import pytest
from prometheus_nexus.safety.five_gates import FiveGates
from prometheus_nexus.foundation.schema import Node, NodeType


class TestFiveGatesAdaptive:
    """五道门自适应阈值测试"""

    def test_low_utility_rejected(self):
        """低utility节点应被拒绝"""
        gates = FiveGates()
        node = Node(id="test", type=NodeType.FACT, content="test", utility=0.05)
        result = gates.evaluate(node, {"current_node_count": 10})
        assert not result.passed
        # 检查details中是否有utility门失败
        failed_gates = [g.gate_name for g in result.details if not g.passed]
        assert "utility" in failed_gates

    def test_high_utility_accepted(self):
        """高utility节点应通过"""
        gates = FiveGates()
        node = Node(id="test", type=NodeType.FACT, content="test content", utility=0.8)
        result = gates.evaluate(node, {"current_node_count": 10})
        assert result.passed

    def test_empty_content_rejected(self):
        """空内容应被拒绝"""
        gates = FiveGates()
        node = Node(id="test", type=NodeType.FACT, content="", utility=0.7)
        result = gates.evaluate(node, {"current_node_count": 10})
        assert not result.passed

    def test_adaptive_threshold_adjustment(self):
        """自适应阈值应调整"""
        gates = FiveGates(adaptive=True)
        # 先让大量低utility节点通过（提高min_utility）
        for i in range(20):
            node = Node(id=f"n{i}", type=NodeType.FACT, content="test", utility=0.6)
            gates.evaluate(node, {"current_node_count": 10})
        # 现在min_utility应该提高了
        assert gates._current_min_utility > 0.1

    def test_max_surprise_rejects(self):
        """过高surprise应被拒绝"""
        gates = FiveGates()
        node = Node(id="test", type=NodeType.FACT, content="test", utility=0.7, surprise=1.0)
        result = gates.evaluate(node, {"current_node_count": 10})
        # max_surprise默认1.0，所以surprise=1.0应该通过
        # 但如果设置更低的max_surprise，应该拒绝
        gates2 = FiveGates(config=type('C', (), {'max_nodes': 100_000, 'min_utility': 0.1, 'max_surprise': 0.7})())
        node2 = Node(id="test", type=NodeType.FACT, content="test", utility=0.7, surprise=0.9)
        result2 = gates2.evaluate(node2, {"current_node_count": 10})
        assert not result2.passed
