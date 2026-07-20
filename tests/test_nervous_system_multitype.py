import pytest
from prometheus_nexus.learning.knowledge_rumination import KnowledgeRuminationEngine

def test_rumination_publishes_event():
    published = []
    class StubBus:
        def publish(self, ev): published.append(ev)
        def subscribe(self, *a, **k): pass
    class StubOmega:
        event_bus = StubBus()
        def _compute_fitness(self): return 0.5
    eng = KnowledgeRuminationEngine.__new__(KnowledgeRuminationEngine)
    eng.omega = StubOmega()
    eng.history = []
    eng.last_full_rumination = 0
    eng.last_incremental_rumination = 0
    eng.full_interval_seconds = 999999
    eng.incremental_interval_seconds = 999999
    eng._select_nodes = lambda mode, limit: []
    res = eng.ruminate(mode="full", force=True)
    assert any(e.get("type") == "rumination_completed" for e in published), "rumination 必须 publish rumination_completed"
    ev = [e for e in published if e.get("type")=="rumination_completed"][0]
    # 真实总线(CIPEventBus.publish)会把整个 dict 包进 event["data"]，
    # 因此真实字段在顶层(与 remember/evolve 等管道一致)。StubBus 不包层，故直接顶层断言。
    assert "total_scanned" in ev, "rumination_completed 必须含 total_scanned 字段(顶层)"

def test_cns_subscribes_rumination():
    from prometheus_nexus.lifecycle.cns_orchestrator import CNSOrchestrator
    subs = []
    class StubBus:
        def subscribe(self, topic, handler, priority=0.5):
            subs.append(topic)
    cns = CNSOrchestrator.__new__(CNSOrchestrator)
    cns.subscribe(StubBus())
    assert "rumination_completed" in subs, "CNS 必须订阅 rumination_completed"

def test_fitness_has_new_dimensions(monkeypatch):
    """验证 _compute_fitness 能跑通（含新增的三维度分支）且不抛异常、返回 [0,1] float。

    Omega 在 prometheus_nexus.life 中定义；用 __new__ 构造裸对象，
    monkeypatch 掉所有外部依赖（store / evolution_engine / harness_x /
    utility_tracker / thermodynamic / mechanism_registry / knowledge_rumination /
    _compute_health），直接测试 _compute_fitness 代码路径。
    """
    from prometheus_nexus.life import Omega
    from types import SimpleNamespace

    omega = Omega.__new__(Omega)  # 跳过 __init__，手动注入依赖

    class StubStore:
        def get_node_count(self): return 100
        def get_edge_count(self): return 50
        def get_active_nodes(self, limit=200): return []
        def get_nodes_by_type(self, nt, limit=100000):
            # 返回 list（非 int），验证新维度 8 的 isinstance 分支
            return [1, 2, 3]

    class StubStats:
        def get_stats(self):
            return {"generations": 1, "evolutions": 1, "avg_utility": 0.6}

    class StubThermo:
        def get_energy(self): return 0.5

    omega.store = StubStore()
    omega.evolution_engine = StubStats()
    omega.harness_x = StubStats()
    omega.utility_tracker = StubStats()
    omega.thermodynamic = StubThermo()

    # 机制注册表：含 consumed_at / emit_accepted 字段，验证维度 9
    omega.mechanism_registry = SimpleNamespace(
        _mechanisms={
            "m1": {"consumed_at": 1.0, "emit_accepted": True},
            "m2": {"consumed_at": None, "emit_accepted": None},
        }
    )

    # 反刍历史：最新一条含 skills_promoted / routed_nodes，验证维度 10
    omega.knowledge_rumination = SimpleNamespace(
        history=[SimpleNamespace(skills_promoted=3, routed_nodes=5)]
    )

    # 避免 _compute_health 拉起重量级依赖链
    omega._compute_health = lambda: "healthy"

    score = omega._compute_fitness()
    assert isinstance(score, float), "_compute_fitness 必须返回 float"
    assert 0.0 <= score <= 1.0, "fitness 必须在 [0, 1] 区间"

def test_telemetry_evolve_captures_consensus():
    from prometheus_nexus.lifecycle.telemetry_pipeline import TelemetryPipeline
    tp = TelemetryPipeline.__new__(TelemetryPipeline)
    tp._history = {p: [] for p in ["remember","recall","evolve","learn","reflect","dream","maintain","rumination"]}
    tp._max_window = 50
    # 真实 EvolutionOutcome.metadata 是 dict（含 diagnostics 子 dict）
    class Ret:
        fitness_before = 0.5
        fitness_after = 0.55
        result = "SUCCESS"
        metadata = {"diagnostics": {"camp_vote": 3, "camp_panel": 5, "speculative_result": {"x":1}}}
    class Omega:
        _telemetry = {"evolve": Ret()}
    tp._omega = Omega()
    tp._on_event({"data": {"type": "evolve_completed"}})
    s = tp.query("evolve")
    assert s.signals.get("consensus_rate") is not None
    assert s.signals.get("speculative_flag") is True

def test_adapter_publishes_capability_consumed():
    from prometheus_nexus.integration.host_agent import GenericAgentAdapter
    published = []
    class StubBus:
        def publish(self, ev): published.append(ev)
        def subscribe(self, *a, **k): pass
    class StubOmega:
        event_bus = StubBus()
    ad = GenericAgentAdapter(host_id="test", endpoint="http://x")
    ad._omega = StubOmega()   # 模拟 Omega.__init__ 反向持有
    ad._emit_endpoint = None  # 走 inbox 分支
    ok = ad.emit_capability({"name": "m1"})
    assert any(e.get("type") == "capability_consumed" for e in published), "emit 成功必须 publish"
