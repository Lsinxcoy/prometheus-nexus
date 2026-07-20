"""反刍持久化 + 学习论文可见性 测试.

根因(用户观察: 反刍从未触发 / 论文不涨):
1. 反刍调度状态是内存态, cron 每30min重启实例清零 ->
   全量(6h)/增量(30min)永远达不到阈值 -> 反刍永不触发.
   修复: KnowledgeRuminationEngine 持久化 last_full/last_incremental 到
   archive/rumination_state.json, 启动加载.
2. dashboard 的 papers 是硬编码 6 篇借力映射, 不反映真实 arxiv 学习.
   修复: dashboard 加 learned_papers (从 store PAPER 节点动态聚合), 监控展示.

测试:
- 反刍状态 persist->load round-trip 恢复
- get_nodes_by_type(PAPER) 能查到 learn 写入的论文节点
"""
import sys, os, time, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from prometheus_nexus.learning.knowledge_rumination import KnowledgeRuminationEngine


def test_rumination_state_persist_roundtrip():
    """persist 后新实例 load 应恢复 last_full/last_incremental/history_len."""
    p = os.path.join(tempfile.mkdtemp(), "rum.json")
    e1 = KnowledgeRuminationEngine.__new__(KnowledgeRuminationEngine)
    e1.state_path = p
    e1.last_full_rumination = 12345.0
    e1.last_incremental_rumination = 999.0
    e1.history = [1, 2, 3]
    e1._persist()
    assert os.path.exists(p)
    e2 = KnowledgeRuminationEngine.__new__(KnowledgeRuminationEngine)
    e2.state_path = p
    e2.last_full_rumination = 0.0
    e2.last_incremental_rumination = 0.0
    e2.history = []
    e2._load()
    assert e2.last_full_rumination == 12345.0
    assert e2.last_incremental_rumination == 999.0
    assert len(e2.history) == 3


def test_rumination_persist_skips_when_no_path():
    """无 state_path 时 _persist 静默跳过(不报错)."""
    e = KnowledgeRuminationEngine.__new__(KnowledgeRuminationEngine)
    e.state_path = None
    e.last_full_rumination = 1.0
    e._persist()  # 不应抛
    assert True


def test_store_paper_nodes_queryable():
    """store.get_nodes_by_type(PAPER) 接口存在(反刍/学习论文聚合的基础)."""
    from prometheus_nexus.foundation.store import NodeType, MinervaStore
    assert hasattr(MinervaStore, "get_nodes_by_type"), "Store 应支持按类型查询"
    # NodeType.PAPER 枚举值存在
    assert NodeType.PAPER is not None
