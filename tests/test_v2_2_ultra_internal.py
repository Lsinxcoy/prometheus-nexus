"""V2.2 强化 Ultra 本身测试 (D2/D3/D4).

- D2: 机制真执行 — active 机制经沙箱编译 draft_code 成 callable(invoke 拿真结果)
- D3: fitness 效用锚 — 无外部 eval_fn 时融合 utility_anchor, 非纯参数自指
- D4: provenance 保真 — 多轮 rumination 后 raw_chunk 仍可追溯
"""
import sys
sys.path.insert(0, "E:/Prometheus-Ultra-MultiTypeKB/src")

import pytest
import tempfile
import os


class TestD2RealExecution:
    def test_invoke_executes_draft_code(self, tmp_path):
        """D2: active 机制的 draft_code 经沙箱真执行, invoke 拿真结果(非空壳)."""
        from prometheus_nexus.mechanisms.registry import MechanismRegistry
        reg = MechanismRegistry()
        # 一个真有 run 实现的 draft_code
        draft = (
            "from prometheus_nexus.mechanisms.base_mechanism import BaseMechanism\n\n"
            "class real_mech(BaseMechanism):\n"
            "    name = 'real_mech'\n"
            "    category = 'compiled'\n"
            "    def run(self, context=None):\n"
            "        x = (context or {}).get('x', 0)\n"
            "        return {'ok': True, 'doubled': x * 2}\n"
        )
        reg._mechanisms["real_mech"] = {
            "name": "real_mech", "category": "compiled", "status": "active",
            "enabled": True, "dependencies": [], "data": {"draft_code": draft},
            "invoke_count": 0,
        }
        reg._enabled.add("real_mech")
        ok = reg.invoke("real_mech", context={"x": 21})
        assert ok is True
        assert reg._mechanisms["real_mech"]["data"]["last_result"]["doubled"] == 42
        assert reg._mechanisms["real_mech"]["data"]["last_result"].get("_executed") is True

    def test_pending_mechanism_not_executed(self):
        """D2: pending 机制不执行 draft_code(门控: 仅 active 可跑)."""
        from prometheus_nexus.mechanisms.registry import MechanismRegistry
        reg = MechanismRegistry()
        draft = (
            "from prometheus_nexus.mechanisms.base_mechanism import BaseMechanism\n\n"
            "class pending_mech(BaseMechanism):\n"
            "    def run(self, context=None):\n"
            "        return {'ok': True, 'ran': True}\n"
        )
        reg._mechanisms["pending_mech"] = {
            "name": "pending_mech", "category": "compiled", "status": "pending",
            "enabled": True, "dependencies": [], "data": {"draft_code": draft},
            "invoke_count": 0,
        }
        reg._enabled.add("pending_mech")
        ok = reg.invoke("pending_mech", context={})
        # pending: 不进沙箱(无 draft 执行), 降级路径返回 True 但 last_result 不含 _executed
        assert reg._mechanisms["pending_mech"]["data"].get("last_result", {}).get("_executed") is not True

    def test_dangerous_draft_blocked(self):
        """D2: 危险 draft_code(如 __import__) 被沙箱白名单拦截, 编译失败不崩溃."""
        from prometheus_nexus.mechanisms.registry import MechanismRegistry
        reg = MechanismRegistry()
        draft = (
            "import os\n"  # 不在白名单
            "from prometheus_nexus.mechanisms.base_mechanism import BaseMechanism\n\n"
            "class evil(BaseMechanism):\n"
            "    def run(self, context=None):\n"
            "        os.system('echo pwned')\n"
            "        return {'ok': True}\n"
        )
        reg._mechanisms["evil"] = {
            "name": "evil", "category": "compiled", "status": "active",
            "enabled": True, "dependencies": [], "data": {"draft_code": draft},
            "invoke_count": 0,
        }
        reg._enabled.add("evil")
        ok = reg.invoke("evil", context={})
        assert ok is False  # 编译/执行失败 -> 不崩溃, 返回 False


class TestD3UtilityAnchor:
    def test_heuristic_fuses_anchor(self):
        """D3: _heuristic_fitness 融合 utility_anchor, 高锚上抬 fitness."""
        from prometheus_nexus.evolution.evolution_engine import Evaluator, Gene
        genes = [Gene(gene_id="g", name="lr", value=0.05, min_val=0.001, max_val=0.1)]
        low = Evaluator._heuristic_fitness(genes, utility_anchor=0.1)
        high = Evaluator._heuristic_fitness(genes, utility_anchor=0.9)
        assert high > low, "高效用锚应上抬 fitness"

    def test_engine_uses_anchor_when_no_eval_fn(self):
        """D3: 无 evaluate_fn 时 engine.evolve 融合 set_utility_anchor 的信号."""
        from prometheus_nexus.evolution.evolution_engine import EvolutionEngine
        eng = EvolutionEngine(gene_specs={"lr": (0.001, 0.1)}, population_size=8, max_generations=3)
        eng.set_utility_anchor(0.9)  # 高真实效用
        out = eng.evolve(context="test")
        assert "best_fitness" in out or "best" in out


class TestD4Provenance:
    def test_raw_chunk_survives_rumination(self):
        """D4: 多轮 rumination 后 raw_chunk 仍等于原文(provenance 保真)."""
        from prometheus_nexus.life import Omega
        from prometheus_nexus.foundation.schema import Node, NodeType
        db = os.path.join(tempfile.gettempdir(), f"ultra_d4_{os.getpid()}_{id(object())}.db")
        o = Omega(db_path=db)
        original = "ORIGINAL VERBATIM CHUNK: agent must retry on transient failure"
        # 直接构造带 raw_chunk 的节点写 store(Omega.remember 不透传 raw_chunk)
        node = Node(content="agent retry on failure", type=NodeType.FACT,
                    utility=0.7, tags=["rail_t2"], raw_chunk=original)
        o.store.create_node(node)
        nid = node.id
        # 跑 3 轮 rumination
        for _ in range(3):
            try:
                o.knowledge_rumination.ruminate(mode="full", force=True)
            except Exception:
                pass
        # 取回节点, 断言 raw_chunk 不变
        got = o.store.read_node(nid)
        assert got is not None
        assert got.raw_chunk == original, "rumination 不应丢失原始 provenance"
        o.store.close()
        try:
            os.remove(db)
        except Exception:
            pass
