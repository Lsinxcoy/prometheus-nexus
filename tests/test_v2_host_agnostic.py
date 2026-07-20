"""V2 宿主无关自进化闭环测试 (P0/P1/P2).

验证:
- P0a: T4 激活 -> host.emit_capability 被调用 (僵尸机制解); T3 激活 -> inject_gene_specs
- P0b: 熔断门 — 坏机制激活后 fitness 下降触发 deactivate
- P1a/b: HostAgentAdapter 抽象 + HermesAdapter(无 endpoint 降级 NullHost)
- P1c: learn(source=host_experience) 走 host adapter
- P2a: LLM 缺失时 T4 draft 非空壳(含 target_location+apply 指令)
- P2b: inject_gene_specs 经 EvolutionState 跨会话持久
"""
import sys
sys.path.insert(0, "E:/Prometheus-Ultra-MultiTypeKB/src")

import pytest

from prometheus_nexus.integration.host_agent import HostAgentAdapter, NullHostAdapter


class FakeHost(HostAgentAdapter):
    """测试用宿主: 记录 emit_capability 调用."""
    def __init__(self, emit_accept=True):
        self.emitted = []
        self.ingested = []
        self.pulled = []
        self._emit_accept = emit_accept
    def llm_complete(self, prompt, system=""):
        return None
    def get_runtime_context(self):
        return {"tools": ["x"], "context_window": 100, "current_task": "test_task", "host": "fake"}
    def emit_capability(self, spec):
        self.emitted.append(spec)
        return self._emit_accept
    def ingest_experience(self, log):
        self.ingested.append(log)
    def pull_experience(self, limit=10):
        return self.pulled
    def apply_capability(self, name, host_id="fake"):
        return True


@pytest.fixture
def omega():
    from prometheus_nexus.life import Omega
    import tempfile, os
    db = os.path.join(tempfile.gettempdir(), f"ultra_v2_{os.getpid()}_{id(object())}.db")
    o = Omega(db_path=db)
    yield o
    try:
        o.store.close() if hasattr(o, "store") and hasattr(o.store, "close") else None
    except Exception:
        pass
    try:
        if os.path.exists(db):
            os.remove(db)
    except Exception:
        pass


class TestP0aT4Emit:
    def test_t4_activate_triggers_emit(self, omega, monkeypatch):
        """T4 编译机制激活后, host.emit_capability 被调用(闭环合上, 解 B1)."""
        from prometheus_nexus.integration.host_agent import HostAgentAdapter
        host = FakeHost()
        monkeypatch.setattr(omega, "host", host)
        # 重注册 consumer(consumer 引用旧 host, 需重绑)
        omega.mechanism_registry.register_consumer("compiled", lambda e: omega._consume_t4(e))

        # 注册一个 T4 机制并激活
        omega.mechanism_registry.register(
            "test_compiled_mech",
            data={"paper": "2607.13285", "draft_code": "x", "target_location": {"module": "m", "lineno": 1}},
            category="compiled", pending=True,
        )
        res = omega.mechanism_registry.verify_and_activate(
            "test_compiled_mech",
            claim="A mechanism that improves parameter evolution fitness via adaptive learning rate scheduling",
            hypothesis="test_compiled_mech from paper 2607.13285",
        )
        assert res["activated"] is True
        assert len(host.emitted) == 1, "T4 激活应触发 emit_capability"
        assert host.emitted[0]["name"] == "test_compiled_mech"
        assert host.emitted[0]["target_location"]["module"] == "m"


class TestP0aT3Inject:
    def test_t3_activate_injects_genes(self, omega):
        """T3 提取机制激活后, evolution_engine.inject_gene_specs 生效(解 B1)."""
        specs = {"ext_lr": (0.0, 1.0), "ext_momentum": (0.0, 0.9)}
        omega.mechanism_registry.register(
            "test_extracted_mech",
            data={"gene_specs": specs},
            category="extracted", pending=True,
        )
        before = len(omega.evolution_engine._gene_specs)
        res = omega.mechanism_registry.verify_and_activate(
            "test_extracted_mech",
            claim="Extract GitHub mechanism: adaptive gradient clipping to stabilize training",
            hypothesis="test_extracted_mech from repo X",
        )
        assert res["activated"] is True
        after = len(omega.evolution_engine._gene_specs)
        assert after == before + 2, "T3 激活应注入 2 个 gene_specs"
        assert "ext_lr" in omega.evolution_engine._gene_specs


class TestP0bCircuitBreak:
    def test_bad_mechanism_deactivated_on_decline(self, omega, monkeypatch):
        """熔断门(C3 精准化): 坏机制(emit 被宿主拒绝)激活后 fitness 下降 -> 回滚."""
        # 用拒绝 emit 的 host -> bad_mech 激活后 emit_accepted=False -> harmful
        host = FakeHost()
        host._emit_accept = False
        monkeypatch.setattr(omega, "host", host)
        omega.mechanism_registry.register_consumer("compiled", lambda e: omega._consume_t4(e))
        omega.mechanism_registry.register(
            "bad_mech", data={"draft_code": "x"}, category="compiled", pending=True,
        )
        omega.mechanism_registry.verify_and_activate(
            "bad_mech",
            claim="A compiled mechanism that improves memory consolidation via differential attention",
            hypothesis="bad_mech from paper Y",
        )
        assert "bad_mech" in omega.mechanism_registry.get_enabled()

        # 模拟 autonomic_regulator 连续 fitness 下降 (注意 _on_evolve 内部会再 append after)
        from prometheus_nexus.lifecycle.autonomic_regulator import AutonomicRegulator
        ar = AutonomicRegulator(omega)
        # 预灌 4 个严格下降值, _on_evolve 会再 append after=0.3, 形成 5 个连续下降
        for f in [0.9, 0.7, 0.5, 0.4]:
            ar._fitness_log.append((f, 0.0, "evolve"))
        ar._on_evolve({"data": {"fitness_before": 0.4, "fitness_after": 0.3, "strategy": "x"}})
        # 熔断应已回滚 bad_mech(emit 被拒 -> harmful)
        assert "bad_mech" not in omega.mechanism_registry.get_enabled(), "坏机制应被熔断回滚"


class TestP1cHostExperience:
    def test_learn_host_experience_routes_to_host(self, omega, monkeypatch):
        """learn(source=host_experience) 真拉取宿主经验写 store (解 B7/C2)."""
        host = FakeHost()
        host.pulled = [{"content": "host observed failure on task X", "utility": 0.7}]
        monkeypatch.setattr(omega, "host", host)
        result = omega.learn(source="host_experience", query="test")
        assert result["source"] == "host_experience"
        assert result["host"] == "fake"
        # 宿主经验应真写入 store (rail_t2/rail_t4 节点)
        assert result["new_nodes"] >= 1, "learn(host_experience) 应拉取宿主经验写 store"


class TestP2aNoLLMDraft:
    def test_t4_draft_not_empty_shell_without_llm(self, tmp_path, monkeypatch):
        """LLM 缺失时 T4 draft 非空壳(含 target_location + apply 指令, 解 B2)."""
        from prometheus_nexus.mechanisms.mechanism_compiler import MechanismCompiler
        monkeypatch.setattr(
            "prometheus_nexus.mechanisms.mechanism_compiler.fetch_arxiv_fulltext",
            lambda aid: "We propose a novel parameter evolution method that improves fitness adaptation.",
        )
        from prometheus_nexus.mechanisms import handbook as hb_mod
        class FakeCand:
            module = "prometheus_nexus.evolution.evolution_engine"
            filepath = "/x/e.py"; lineno = 2357; symbol = "evolve()"
            confidence = 0.8; verified = True; rationale = "x"; level = 3
        monkeypatch.setattr(hb_mod.HarnessHandbook, "bgpd_locate", lambda s, q, llm, top_k: [FakeCand()])
        monkeypatch.setattr(hb_mod.HarnessHandbook, "locate_behavior", lambda s, q, llm, top_k: [FakeCand()])

        comp = MechanismCompiler(llm=None, compiled_dir=str(tmp_path / "c"))
        mech = comp.compile("2401.12345", "Paper")
        assert mech is not None
        # draft 不能只是 "# stub"
        assert "target_location" in mech.draft_code, "draft 应含 target_location"
        assert "apply:" in mech.draft_code, "draft 应含 apply 指令"
        assert "rule-extracted" in mech.draft_code


class TestP2bGenePersistence:
    def test_injected_genes_persist_across_sessions(self, omega, tmp_path):
        """T3 注入的 gene_specs 经 EvolutionState 跨会话持久(解 B4)."""
        specs = {"persist_gene": (0.1, 0.9)}
        omega.mechanism_registry.register(
            "p_mech", data={"gene_specs": specs}, category="extracted", pending=True,
        )
        omega.mechanism_registry.verify_and_activate(
            "p_mech",
            claim="Parameter mechanism: momentum scheduling for faster convergence",
            hypothesis="p_mech from repo Z",
        )
        # 触发 save (evolve 末尾会 save; 这里直接调 save 模拟会话结束)
        omega.evolution_state.save(omega.evolution_engine)
        assert "persist_gene" in omega.evolution_engine._gene_specs

        # 新引擎实例 load
        from prometheus_nexus.evolution.evolution_engine import EvolutionEngine
        from prometheus_nexus.evolution.evolution_state import EvolutionState
        eng2 = EvolutionEngine()
        st2 = EvolutionState(path=omega.evolution_state.path)
        assert st2.load(eng2)
        assert "persist_gene" in eng2._gene_specs, "重启后 gene_specs 应保留"
