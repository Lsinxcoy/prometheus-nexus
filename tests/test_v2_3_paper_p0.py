"""V2.3 论文借力强化测试 (P0-a 主动剪枝 / P0-b 链完整性).

- P0-a (论文③ Grad Token Pruning): 机制级效用追踪 + 负效用主动剪枝
- P0-b (论文⑤ Thought Leap Bridge): evolve 关键 stage 执行追踪, 暴露 chain_complete
"""
import pytest
import tempfile
import os


class TestP0aActivePruning:
    def test_record_effect_and_prune(self):
        """P0-a: 负效用机制持续反馈 -> 主动剪枝(梯度引导思想)."""
        from prometheus_nexus.mechanisms.registry import MechanismRegistry
        reg = MechanismRegistry()
        # 注册一个 active 机制
        reg._mechanisms["harmful_mech"] = {
            "name": "harmful_mech", "category": "compiled", "status": "active",
            "enabled": True, "dependencies": [], "data": {}, "invoke_count": 0,
        }
        reg._enabled.add("harmful_mech")
        # 连续负反馈(机制对宿主无价值, 伪相关)
        for _ in range(5):
            reg.record_mechanism_effect("harmful_mech", -0.8)
        # 应被标记为负效用
        assert reg._mechanisms["harmful_mech"]["effect_mean"] < -0.3
        # 主动剪枝
        pruned = reg.prune_harmful(threshold=-0.3)
        assert pruned == 1
        assert "harmful_mech" not in reg.get_enabled()

    def test_positive_effect_not_pruned(self):
        """P0-a: 正效用机制不被剪枝."""
        from prometheus_nexus.mechanisms.registry import MechanismRegistry
        reg = MechanismRegistry()
        reg._mechanisms["good_mech"] = {
            "name": "good_mech", "category": "compiled", "status": "active",
            "enabled": True, "dependencies": [], "data": {}, "invoke_count": 0,
        }
        reg._enabled.add("good_mech")
        for _ in range(5):
            reg.record_mechanism_effect("good_mech", 0.7)
        assert reg.prune_harmful() == 0
        assert "good_mech" in reg.get_enabled()

    def test_prune_candidates_threshold(self):
        """P0-a: get_prune_candidates 按阈值返回候选."""
        from prometheus_nexus.mechanisms.registry import MechanismRegistry
        reg = MechanismRegistry()
        reg._mechanisms["m1"] = {"name": "m1", "category": "compiled", "status": "active",
                                 "enabled": True, "dependencies": [], "data": {}, "invoke_count": 0}
        reg._enabled.add("m1")
        reg.record_mechanism_effect("m1", -0.5)
        cands = reg.get_prune_candidates(threshold=-0.3)
        assert "m1" in cands


class TestP0bChainCompleteness:
    def test_evolve_exposes_chain_complete(self):
        """P0-b: evolve 返回 chain_trace(关键 stage 执行追踪). 核心 stage 必执行."""
        from prometheus_nexus.life import Omega
        db = os.path.join(tempfile.gettempdir(), f"ultra_p0b_{os.getpid()}_{id(object())}.db")
        o = Omega(db_path=db)
        out = o.evolve(context="test chain completeness")
        # chain_trace 必须存在且记录关键 stage
        assert "chain_trace" in out.metadata
        ct = out.metadata["chain_trace"]
        # 核心 stage(主进化/状态持久化/验证门)必须执行 — 这些不依赖外部子系统
        assert ct.get("main_evolve") is True, "主进化引擎必须执行"
        assert ct.get("state_save") is True, "进化状态持久化必须执行"
        assert ct.get("verify") is True, "验证门必须执行"
        # brainstorm/plan 应在正常初始化下执行
        assert ct.get("brainstorm") is True
        assert ct.get("plan") is True
        # semantic 可能因测试环境子系统未完全初始化而 leap, 但必须被追踪(非静默)
        assert "semantic" in ct
        o.store.close()
        try:
            os.remove(db)
        except Exception:
            pass

    def test_chain_trace_records_leap(self):
        """P0-b: 若某关键 stage 抛异常被吞(leap), chain_complete=False 且暴露缺失."""
        from prometheus_nexus.life import Omega
        db = os.path.join(tempfile.gettempdir(), f"ultra_p0b2_{os.getpid()}_{id(object())}.db")
        o = Omega(db_path=db)
        # 强制 semantic_evolution 抛异常(模拟 leap)
        orig = o.semantic_evolution.evolve
        def boom(*a, **k):
            raise RuntimeError("simulated leap")
        o.semantic_evolution.evolve = boom
        out = o.evolve(context="test leap")
        # semantic stage 应标记未执行 -> chain_complete False
        assert out.metadata.get("chain_complete") is False
        assert "semantic" in out.metadata.get("chain_missing_stages", [])
        o.semantic_evolution.evolve = orig
        o.store.close()
        try:
            os.remove(db)
        except Exception:
            pass
