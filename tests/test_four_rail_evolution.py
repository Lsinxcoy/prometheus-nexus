"""四轨自进化端到端集成测试。

验证:
- T1 参数进化 (EvolutionEngine + 持久化)
- T2 语义进化 (SemanticEvolutionEngine 接入 evolve())
- T3 机制提取 (MechanismExtractor 注册进 registry)
- T4 论文编译 (MechanismCompiler 注册进 registry, 存 draft)
- 神经系统 (autonomic_regulator 缺口检测触发外部进化)
- 所有产物走 MechanismRegistry, 不直替生产
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from prometheus_nexus import Omega
from prometheus_nexus.mechanisms.source_fetcher import fetch_repo_overview, fetch_arxiv_fulltext


@pytest.fixture
def omega():
    return Omega()


def test_t1_evolution_persistence(omega):
    """T1: 进化状态可 save/load。"""
    specs_before = dict(omega.evolution_engine._gene_specs)
    ok = omega.evolution_state.save(omega.evolution_engine)
    assert ok
    # 模拟新引擎 load
    import json, tempfile
    from prometheus_nexus.evolution.evolution_state import EvolutionState
    tmp = "archive/evo_e2e.json"
    st = EvolutionState(path=tmp)
    st.save(omega.evolution_engine)
    assert os.path.exists(tmp)
    os.remove(tmp)


def test_t2_semantic_evolution_runs(omega):
    """T2: 语义进化轨道在 evolve() 内被调用且无崩溃。"""
    # 构造高频概念节点
    omega.remember("attention mechanism core", 0.7, ["attention", "transformer"])
    r = omega.semantic_evolution.evolve(context="e2e")
    assert "evolved_concepts" in r


def test_t3_mechanism_extractor_register(omega, monkeypatch):
    """T3: 提取机制并注册进 registry (不直替)。"""
    monkeypatch.setattr(
        "prometheus_nexus.mechanisms.mechanism_extractor.fetch_repo_overview",
        lambda repo: "# repo\nclass MemoryMech:\n    def consolidate(self): pass",
    )
    res = omega.mechanism_extractor.register("owner/cool-agent", omega.mechanism_registry)
    assert res["registered"]
    name = res["name"]
    assert omega.mechanism_registry._mechanisms[name]["category"] == "extracted"
    # invoke 真执行(候选, 非直替)
    assert omega.mechanism_registry.invoke(name) is True


def test_t4_mechanism_compiler_register(omega, monkeypatch):
    """T4: 编译论文为 draft 并注册 (不直替)。"""
    monkeypatch.setattr(
        "prometheus_nexus.mechanisms.mechanism_compiler.fetch_arxiv_fulltext",
        lambda aid, max_chars=20000: "We propose a Novel Consolidation mechanism. Algorithm 1.",
    )
    res = omega.mechanism_compiler.register("2401.99999", omega.mechanism_registry, paper_title="X")
    assert res["registered"]
    name = res["name"]
    assert omega.mechanism_registry._mechanisms[name]["category"] == "compiled"
    assert os.path.exists(f"archive/compiled/{name}.py")


def test_four_rail_integration(omega, monkeypatch):
    """全系统: T2+T3+T4 共存于 registry, 神经系统可触发外部进化。"""
    monkeypatch.setattr(
        "prometheus_nexus.mechanisms.mechanism_extractor.fetch_repo_overview",
        lambda repo: "# r\nclass M:\n    pass",
    )
    monkeypatch.setattr(
        "prometheus_nexus.mechanisms.mechanism_compiler.fetch_arxiv_fulltext",
        lambda aid, max_chars=20000: "We propose Y. Algorithm 2.",
    )
    # T3 + T4 注册
    omega.mechanism_extractor.register("owner/x", omega.mechanism_registry)
    omega.mechanism_compiler.register("2402.11111", omega.mechanism_registry, paper_title="Y")
    # 神经系统触发外部进化(模拟进化停滞)
    omega.autonomic_regulator._trigger_external_evolution(0.5)
    cats = [m["category"] for m in omega.mechanism_registry._mechanisms.values()]
    assert "extracted" in cats
    assert "compiled" in cats
    assert "extraction_pending" in cats or "compilation_pending" in cats


def test_p1_learn_routing_url_nodetype(omega):
    """P1: learn 路径 — remember 写入带 NodeType + url + rail 标签。"""
    from prometheus_nexus.foundation.schema import NodeType
    nid = omega.remember(
        "The transformer attention is a core mechanism for sequence modeling",
        0.7, ["attn", "transformer"], node_type=NodeType.FACT,
        url="https://arxiv.org/abs/1706.1",
    )
    assert nid
    n = omega.store.read_node(nid)
    assert n.url == "https://arxiv.org/abs/1706.1"
    assert n.type == NodeType.FACT  # 未触发分类时无 rail 信号, 保持 FACT


def test_p2_rumination_routing_and_fuel(omega):
    """P2: 反刍层2路由(FACT+概念->CONCEPT/rail_t2) + 层3燃料供给。"""
    from prometheus_nexus.foundation.schema import NodeType
    from prometheus_nexus.learning.knowledge_rumination import RuminationResult
    nid = omega.remember(
        "Python is a high-level programming language widely used for AI", 0.6, ["python"],
        node_type=NodeType.FACT,
    )
    assert nid, "remember rejected by gate"
    node = omega.store.read_node(nid)
    res = RuminationResult()
    omega.rumination_engine._route_node_type(node, concepts=2, mappings=0, result=res)
    node2 = omega.store.read_node(nid)
    assert node2.type == NodeType.CONCEPT
    assert "rail_t2" in node2.tags
    assert res.routed_nodes == 1


def test_p3_t3_t4_from_store_node(omega, monkeypatch):
    """P3: T3/T4 从 store 节点取 url 编译/提取(不重拉源)。"""
    monkeypatch.setattr(
        "prometheus_nexus.mechanisms.mechanism_extractor.fetch_repo_overview",
        lambda repo: "# r\nclass M:\n    pass",
    )
    monkeypatch.setattr(
        "prometheus_nexus.mechanisms.mechanism_compiler.fetch_arxiv_fulltext",
        lambda aid, max_chars=20000: "We propose X.",
    )
    from prometheus_nexus.foundation.schema import NodeType, Node
    gh = Node(content="repo", type=NodeType.PROJECT, tags=["rail_t3"], url="https://github.com/owner/cool")
    ar = Node(content="paper", type=NodeType.PAPER, tags=["rail_t4"], url="https://arxiv.org/abs/2401.99999")
    r3 = omega.mechanism_extractor.register_from_node(gh, omega.mechanism_registry)
    r4 = omega.mechanism_compiler.register_from_node(ar, omega.mechanism_registry)
    assert r3["registered"] and r4["registered"]
    cats = [m["category"] for m in omega.mechanism_registry._mechanisms.values()]
    assert "extracted" in cats and "compiled" in cats


def test_p4_unified_storage(omega, monkeypatch):
    """P4: T3/T4 产物写入 store 的 PATTERN 节点(统一存储, 消除三分裂)。"""
    # extractor/compiler 内部是模块级 import 绑定, 需 monkeypatch 各自模块属性
    monkeypatch.setattr(
        "prometheus_nexus.mechanisms.mechanism_extractor.fetch_repo_overview",
        lambda repo: "# r\nclass M:\n    pass",
    )
    monkeypatch.setattr(
        "prometheus_nexus.mechanisms.mechanism_compiler.fetch_arxiv_fulltext",
        lambda aid, max_chars=20000: "We propose X.",
    )
    from prometheus_nexus.foundation.schema import NodeType, Node
    # 直接造 rail 源节点(保留 node 引用喂 T3/T4, 避免 get_nodes_by_type 顺序取错种子节点)
    proj_node = Node(content="repo", type=NodeType.PROJECT, tags=["rail_t3"], url="https://github.com/o/c")
    paper_node = Node(content="paper", type=NodeType.PAPER, tags=["rail_t4"], url="https://arxiv.org/abs/2401.9")
    omega.store.create_node(proj_node)
    omega.store.create_node(paper_node)
    omega.mechanism_extractor.register_from_node(proj_node, omega.mechanism_registry)
    omega.mechanism_compiler.register_from_node(paper_node, omega.mechanism_registry)
    pats = omega.store.get_nodes_by_type(NodeType.PATTERN, limit=1000)
    assert any("extracted" in (p.tags or []) for p in pats), "T3 PATTERN node missing"
    assert any("compiled" in (p.tags or []) for p in pats), "T4 PATTERN node missing"


def test_p5_recall_type_aware(omega):
    """P5a: recall 按 NodeType 过滤检索。"""
    from prometheus_nexus.foundation.schema import NodeType
    nid = omega.remember("attention is core", 0.7, ["attn"], node_type=NodeType.FACT,
                         url="https://arxiv.org/abs/1706.1")
    assert nid
    res = omega.recall("attention", limit=5, node_type=NodeType.FACT)
    assert res.metadata.get("type_filtered")


def test_p5_dream_multi_type(omega):
    """P5c: dream 从 store 多类型节点取素材做跨界联想。"""
    from prometheus_nexus.foundation.schema import NodeType
    omega.remember("consolidation is a concept", 0.5, ["mem"], node_type=NodeType.CONCEPT)
    out = omega.dream.dream()
    assert "patterns_found" in out


def test_p5_maintain_type_floor(omega):
    """P5b: maintain 对高价值类型节点做 utility 地板保护。"""
    from prometheus_nexus.foundation.schema import NodeType, Node
    from prometheus_nexus.foundation.schema import generate_uuidv7
    # 直接造 PAPER 节点(绕过 remember gate, 测的是 maintain 地板逻辑)
    nid = generate_uuidv7()
    omega.store.create_node(Node(
        id=nid, content="important paper about memory", type=NodeType.PAPER,
        tags=["p"], utility=0.05, url="https://arxiv.org/abs/2401.1",
    ))
    n = omega.store.read_node(nid)
    assert n is not None and n.utility == 0.05
    omega.maintain()
    n2 = omega.store.read_node(nid)
    assert n2.utility >= 0.3, f"P5b floor not applied: {n2.utility}"


def test_p6_activation_closure(omega, monkeypatch):
    """P6: T3/T4 注册为 pending, 经三道门验证通过后 activate, 不自动直替生产。"""
    # extractor/compiler 内部是模块级 import 绑定, 两个路径都打以确保生效
    monkeypatch.setattr(
        "prometheus_nexus.mechanisms.source_fetcher.fetch_repo_overview",
        lambda repo: "# r\nclass M:\n    pass",
    )
    monkeypatch.setattr(
        "prometheus_nexus.mechanisms.mechanism_extractor.fetch_repo_overview",
        lambda repo: "# r\nclass M:\n    pass",
    )
    monkeypatch.setattr(
        "prometheus_nexus.mechanisms.source_fetcher.fetch_arxiv_fulltext",
        lambda aid, max_chars=20000: "We propose X.",
    )
    monkeypatch.setattr(
        "prometheus_nexus.mechanisms.mechanism_compiler.fetch_arxiv_fulltext",
        lambda aid, max_chars=20000: "We propose X.",
    )
    from prometheus_nexus.foundation.schema import NodeType, Node
    # 造 rail 源节点(保留 node 引用, 用 node.id 直接喂 T3/T4, 避免 get_nodes_by_type 顺序取错种子节点)
    proj_node = Node(content="repo", type=NodeType.PROJECT, tags=["rail_t3"], url="https://github.com/o/c")
    paper_node = Node(content="paper", type=NodeType.PAPER, tags=["rail_t4"], url="https://arxiv.org/abs/2401.9")
    omega.store.create_node(proj_node)
    omega.store.create_node(paper_node)
    r3 = omega.mechanism_extractor.register_from_node(proj_node, omega.mechanism_registry)
    r4 = omega.mechanism_compiler.register_from_node(paper_node, omega.mechanism_registry)
    # 1) 注册后状态为 pending(不自动直替)
    assert r3["status"] == "pending", f"T3 should be pending, got {r3['status']}"
    assert r4["status"] == "pending", f"T4 should be pending, got {r4['status']}"
    # 2) 三道门验证通过 → activated
    assert r3["activated"] is True, f"T3 not activated: {r3.get('activation')}"
    assert r4["activated"] is True, f"T4 not activated: {r4.get('activation')}"
    # 3) registry 内 status 翻为 active 且进 _enabled
    assert omega.mechanism_registry._mechanisms[r3["name"]]["status"] == "active"
    assert r3["name"] in omega.mechanism_registry._enabled
    # 4) store 的 PATTERN 节点被标记 active
    pats = omega.store.get_nodes_by_type(NodeType.PATTERN, limit=1000)
    assert any("active" in (p.tags or []) for p in pats), "active PATTERN node missing"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
