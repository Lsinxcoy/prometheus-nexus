"""V2.1 宿主闭环补全测试 (C1-C5).

覆盖 V2 之后发现的薄弱点修复:
- C1: emit_capability 真落 inbox(不射入虚空) + apply_capability 落地
- C2: pull_experience 真拉取宿主经验 -> store 节点
- C3: 熔断精准化(只回滚 harmful: consume_error/emit拒绝/未消费)
- C4: 有效性追踪(mark_host_used + health_check zombie_emit)
- C5: 多宿主隔离(branch 按 host_id 分区)
"""
import sys
sys.path.insert(0, "E:/Prometheus-Ultra-MultiTypeKB/src")

import pytest
import tempfile
import os

from prometheus_nexus.integration.host_agent import HostAgentAdapter
from prometheus_nexus.integration.capability_inbox import CapabilityInbox


class FakeHost(HostAgentAdapter):
    def __init__(self, emit_accept=True, host_id="fake"):
        self.emitted = []
        self.ingested = []
        self.pulled = []
        self.host_id = host_id
        self._emit_accept = emit_accept
    def llm_complete(self, prompt, system=""):
        return None
    def get_runtime_context(self):
        return {"tools": ["x"], "context_window": 100, "current_task": "t", "host": self.host_id}
    def emit_capability(self, spec):
        self.emitted.append(spec)
        return self._emit_accept
    def ingest_experience(self, log):
        self.ingested.append(log)
    def pull_experience(self, limit=10):
        return self.pulled
    def apply_capability(self, name, host_id="fake"):
        return CapabilityInbox().apply_capability(name, host_id=host_id).applied


@pytest.fixture
def omega():
    from prometheus_nexus.life import Omega
    db = os.path.join(tempfile.gettempdir(), f"ultra_v21_{os.getpid()}_{id(object())}.db")
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


class TestC1Inbox:
    def test_emit_called_on_activate(self, omega, monkeypatch):
        """C1: T4 激活后 emit_capability 被调用(机制不再躺 registry 不出去)."""
        host = FakeHost(emit_accept=True)
        monkeypatch.setattr(omega, "host", host)
        omega.mechanism_registry.register_consumer("compiled", lambda e: omega._consume_t4(e))
        omega.mechanism_registry.register(
            "c1_mech", data={"paper": "x", "draft_code": "y", "target_location": {"module": "m"}},
            category="compiled", pending=True,
        )
        omega.mechanism_registry.verify_and_activate(
            "c1_mech", claim="A mechanism that improves parameter evolution via adaptive scheduling",
            hypothesis="c1_mech from paper X")
        assert len(host.emitted) == 1
        assert host.emitted[0]["name"] == "c1_mech"

    def test_apply_capability_lands_file(self, tmp_path):
        """C1: apply_capability 生成 applied 描述文件(真落地)."""
        inbox = CapabilityInbox(path=str(tmp_path / "inbox.jsonl"))
        inbox.receive({"name": "m1", "target_location": {"module": "m"}, "draft_code": "x"})
        r = inbox.apply_capability("m1", host_id="h1")
        assert r.applied is True
        assert os.path.exists(os.path.join(str(tmp_path), "applied", "m1.applied.json"))


class TestC2Pull:
    def test_pull_experience_to_store(self, omega, monkeypatch):
        """C2: pull_experience 真拉取宿主经验 -> store 节点(非空壳)."""
        host = FakeHost()
        host.pulled = [
            {"content": "agent failed on tool X 3 times", "utility": 0.7},
            {"content": "user preferred concise answers", "utility": 0.6},
        ]
        monkeypatch.setattr(omega, "host", host)
        res = omega.learn(source="host_experience", query="")
        assert res["new_nodes"] == 2, "应拉取 2 条宿主经验写入 store"
        assert res["source"] == "host_experience"


class TestC3PreciseBreak:
    def test_only_harmful_rolled_back(self, omega, monkeypatch):
        """C3: 熔断只回滚 harmful 机制(emit 被拒), 好机制(T3 inject)保留."""
        # 好机制 T3: emit 用 FakeHost(accept=True) 不会触发回滚
        good = FakeHost(emit_accept=True)
        monkeypatch.setattr(omega, "host", good)
        omega.mechanism_registry.register_consumer("extracted", lambda e: omega._consume_t3(e))
        omega.mechanism_registry.register(
            "good_t3", data={"gene_specs": {"g1": (0, 1)}}, category="extracted", pending=True)
        omega.mechanism_registry.verify_and_activate(
            "good_t3", claim="Extract GitHub mechanism: gradient clipping", hypothesis="good_t3")
        # 坏机制 T4: emit 拒绝 -> harmful
        bad = FakeHost(emit_accept=False)
        monkeypatch.setattr(omega, "host", bad)
        omega.mechanism_registry.register_consumer("compiled", lambda e: omega._consume_t4(e))
        omega.mechanism_registry.register(
            "bad_t4", data={"draft_code": "x", "target_location": {}}, category="compiled", pending=True)
        omega.mechanism_registry.verify_and_activate(
            "bad_t4", claim="A compiled mechanism improving memory via attention", hypothesis="bad_t4")
        # 触发熔断
        from prometheus_nexus.lifecycle.autonomic_regulator import AutonomicRegulator
        ar = AutonomicRegulator(omega)
        for f in [0.9, 0.7, 0.5, 0.4]:
            ar._fitness_log.append((f, 0.0, "evolve"))
        ar._on_evolve({"data": {"fitness_before": 0.4, "fitness_after": 0.3, "strategy": "x"}})
        enabled = omega.mechanism_registry.get_enabled()
        assert "bad_t4" not in enabled, "坏机制(emit 被拒)应被回滚"
        assert "good_t3" in enabled, "好机制(T3)不应被误伤"


class TestC4Effectiveness:
    def test_zombie_emit_detected(self, omega, monkeypatch):
        """C4: emit 被接受但宿主从未用 -> health_check 报 zombie_emit."""
        host = FakeHost(emit_accept=True)
        monkeypatch.setattr(omega, "host", host)
        omega.mechanism_registry.register_consumer("compiled", lambda e: omega._consume_t4(e))
        omega.mechanism_registry.register(
            "z_mech", data={"draft_code": "x", "target_location": {}}, category="compiled", pending=True)
        omega.mechanism_registry.verify_and_activate(
            "z_mech", claim="A compiled mechanism for faster inference", hypothesis="z_mech")
        hc = omega.mechanism_registry.health_check()
        assert any(i["type"] == "zombie_emit" for i in hc["issues"]), "应检测僵尸 emit"
        # 宿主标记使用后, 不再 zombie
        omega.mechanism_registry.mark_host_used("z_mech", effect=0.5)
        hc2 = omega.mechanism_registry.health_check()
        assert not any(i["type"] == "zombie_emit" and i["mechanism"] == "z_mech" for i in hc2["issues"])


class TestC5MultiHost:
    def test_experience_isolated_by_host_id(self, omega, monkeypatch):
        """C5: 不同 host_id 的经验按 branch 隔离(不混)."""
        # host A 拉经验
        hostA = FakeHost(host_id="agent_a")
        hostA.pulled = [{"content": "A-specific failure", "utility": 0.8}]
        monkeypatch.setattr(omega, "host", hostA)
        omega.learn(source="host_experience", query="")
        # host B 拉经验
        hostB = FakeHost(host_id="agent_b")
        hostB.pulled = [{"content": "B-specific preference", "utility": 0.6}]
        monkeypatch.setattr(omega, "host", hostB)
        omega.learn(source="host_experience", query="")
        # 查 branch 隔离: agent_a 的节点不应出现在 agent_b 的 recall
        a_nodes = omega.store.get_nodes_by_type(__import__("prometheus_nexus.foundation.schema", fromlist=["NodeType"]).NodeType.PROCEDURE, branch="agent_a")
        b_nodes = omega.store.get_nodes_by_type(__import__("prometheus_nexus.foundation.schema", fromlist=["NodeType"]).NodeType.PROCEDURE, branch="agent_b")
        assert any("A-specific" in (n.content if hasattr(n, "content") else "") for n in a_nodes)
        assert any("B-specific" in (n.content if hasattr(n, "content") else "") for n in b_nodes)
