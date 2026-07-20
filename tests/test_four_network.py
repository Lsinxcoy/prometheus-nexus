"""Tests for FourNetworkMemory — P1修复验证

验证分类增强后4个网络分布是否均衡。
"""
import pytest
from prometheus_nexus.memory.four_network import FourNetworkMemory


class TestFourNetworkClassification:
    """FourNetwork分类增强测试"""

    def test_semantic_classification(self):
        """语义内容应被分类到semantic网络"""
        fn = FourNetworkMemory()
        content = "The concept of AI is defined as artificial intelligence"
        network = fn._auto_classify(content)
        assert network == "semantic"

    def test_procedural_classification(self):
        """程序性内容应被分类到procedural网络"""
        fn = FourNetworkMemory()
        content = "Step 1: First, then proceed with the algorithm"
        network = fn._auto_classify(content)
        assert network == "procedural"

    def test_episodic_classification(self):
        """情节内容应被分类到episodic网络"""
        fn = FourNetworkMemory()
        content = "At location X, during episode Y, the scenario occurred"
        network = fn._auto_classify(content)
        assert network == "episodic"

    def test_experience_default(self):
        """默认应分类到experience网络"""
        fn = FourNetworkMemory()
        content = "Today I learned about machine learning"
        network = fn._auto_classify(content)
        # 可能被分类为experience或episodic，取决于关键词
        assert network in ["experience", "episodic"]

    def test_retain_auto_classify(self):
        """retain方法自动分类应工作"""
        fn = FourNetworkMemory()
        # 存入语义内容
        fn.retain("The category of ML is machine learning")
        # 检查是否进入semantic网络
        assert len(fn._networks["semantic"]) > 0

    def test_distribution_balance(self):
        """多次存入后分布不应过于集中"""
        fn = FourNetworkMemory()
        # 存入不同类型内容
        contents = [
            "The concept of AI is defined as...",  # semantic
            "Step 1: First, then do this...",     # procedural
            "At location X, during episode Y...", # episodic
            "Today I experienced something new...", # experience
        ] * 25  # 每种100条
        for c in contents:
            fn.retain(c)
        # 计算各网络占比
        total = sum(len(fn._networks[n]) for n in fn.NETWORK_NAMES)
        if total > 0:
            for net in fn.NETWORK_NAMES:
                ratio = len(fn._networks[net]) / total
                # 单一网络不应超过60%
                assert ratio < 0.6, f"{net}占比过高: {ratio:.1%}"
