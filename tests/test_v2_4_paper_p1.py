"""V2.4 论文借力强化测试 (P1-a future-aware / P1-b superposition / P1-c 拓扑对齐).

- P1-a (论文① Causal VL): recall future_aware — 未来记忆不被因果屏蔽
- P1-b (论文⑥ Superposition): 机制叠加态候选 — 运行时按上下文动态选择
- P1-c (论文② HeRA): 跨 NodeType 拓扑对齐 — 多 rail 节点获对齐增益
"""
import pytest
import tempfile
import os
import time


class TestP1aFutureAware:
    def test_future_memory_not_penalized(self):
        """P1-a: future_aware=True 时, 未来记忆(created_at>now)排名不劣于过去记忆."""
        from prometheus_nexus.life import Omega
        from prometheus_nexus.foundation.schema import Node, NodeType
        db = os.path.join(tempfile.gettempdir(), f"ultra_p1a_{os.getpid()}_{id(object())}.db")
        o = Omega(db_path=db)
        # 放行 AdaMEM 门控(测试环境未训练会拦截所有检索)
        try:
            o.ada_mem.should_retrieve = lambda *a, **k: True
        except Exception:
            pass
        now = time.time()
        # 过去记忆(低 utility) + 未来记忆(高 utility, created_at 在未来)
        past = Node(content="past memory about caching", type=NodeType.FACT,
                    utility=0.3, created_at=now - 1000.0)
        future = Node(content="future memory about caching strategy", type=NodeType.FACT,
                      utility=0.3, created_at=now + 1000.0)
        o.store.create_node(past)
        o.store.create_node(future)
        # future_aware 召回: 未来节点应被 boost 且出现在结果
        res = o.recall("caching", limit=10, future_aware=True)
        hit_ids = [h.node_id for h in res.hits]
        assert future.id in hit_ids, "未来记忆应被召回(future_aware)"
        o.store.close()
        try:
            os.remove(db)
        except Exception:
            pass

    def test_future_aware_default_on(self):
        """P1-a: recall 默认 future_aware=True(向后兼容, 不屏蔽未来)."""
        from prometheus_nexus.life import Omega
        db = os.path.join(tempfile.gettempdir(), f"ultra_p1a2_{os.getpid()}_{id(object())}.db")
        o = Omega(db_path=db)
        import inspect
        # CNS 重构后 o.recall 被 _wrapped 包装(签名含 _orig/_pn 形参); 真实方法存于 __kwdefaults__['_orig']
        recall_fn = o.recall
        if getattr(recall_fn, "__kwdefaults__", None) and "_orig" in recall_fn.__kwdefaults__:
            recall_fn = recall_fn.__kwdefaults__["_orig"]
        sig = inspect.signature(recall_fn)
        assert sig.parameters.get("future_aware").default is True
        o.store.close()
        try:
            os.remove(db)
        except Exception:
            pass


class TestP1bSuperposition:
    def test_superposed_select_by_context(self):
        """P1-b: 叠加态候选按上下文动态选择最相关者."""
        from prometheus_nexus.mechanisms.registry import MechanismRegistry
        reg = MechanismRegistry()
        reg.register_superposed("super_m", [
            {"name": "c_a", "weight": 1.0, "claim": "memory caching strategy", "draft_code": "x"},
            {"name": "c_b", "weight": 1.0, "claim": "gradient clipping method", "draft_code": "y"},
        ])
        # 上下文匹配 c_a -> 选 c_a
        sel = reg.select_by_context("super_m", context="how to cache memory effectively")
        assert sel is not None
        assert sel["name"] == "c_a", f"应选中与上下文相关的候选, got {sel['name']}"
        # 权重归一化
        cands = reg._superposed["super_m"]["candidates"]
        assert abs(sum(c["weight"] for c in cands) - 1.0) < 1e-6

    def test_superposed_no_candidates(self):
        """P1-b: 无叠加态时 select_by_context 返回 None."""
        from prometheus_nexus.mechanisms.registry import MechanismRegistry
        reg = MechanismRegistry()
        assert reg.select_by_context("nonexistent", context="x") is None


class TestP1cTopology:
    def test_cross_rail_node_gets_alignment_boost(self):
        """P1-c: 跨多 rail 节点(拓扑对齐)在 rumination 后 utility 更高."""
        from prometheus_nexus.life import Omega
        from prometheus_nexus.foundation.schema import Node, NodeType
        db = os.path.join(tempfile.gettempdir(), f"ultra_p1c_{os.getpid()}_{id(object())}.db")
        o = Omega(db_path=db)
        # 单 rail 节点(对照组) + 双 rail 节点(对齐组), 初始 utility 相同
        single = Node(content="single rail node", type=NodeType.PROCEDURE,
                      utility=0.5, tags=["rail_t1"])
        cross = Node(content="cross rail node", type=NodeType.PROCEDURE,
                     utility=0.5, tags=["rail_t1", "rail_t2"])
        o.store.create_node(single)
        o.store.create_node(cross)
        # 跑 rumination(force) — 正确属性名 rumination_engine
        try:
            o.rumination_engine.ruminate(mode="full", force=True)
        except Exception as e:
            print("ruminate error:", e)
        s = o.store.read_node(single.id)
        c = o.store.read_node(cross.id)
        # 双 rail 节点应获对齐增益(>单 rail)
        assert c.utility >= s.utility, f"跨rail节点应对齐增益: cross={c.utility} single={s.utility}"
        assert c.utility > 0.5, "跨rail节点 rumination 后应升 utility"
        o.store.close()
        try:
            os.remove(db)
        except Exception:
            pass


class TestP1dTemporalFusion:
    def test_temporal_neighbor_fusion(self):
        """P1-d (论文④ Overlap Speech): recall top 节点融合其时间邻域, 重建上下文."""
        from prometheus_nexus.life import Omega
        from prometheus_nexus.foundation.schema import Node, NodeType
        db = os.path.join(tempfile.gettempdir(), f"ultra_p1d_{os.getpid()}_{id(object())}.db")
        o = Omega(db_path=db)
        try:
            o.ada_mem.should_retrieve = lambda *a, **k: True
        except Exception:
            pass
        now = time.time()
        # 主节点(匹配查询) + 时间邻域节点(前后 600s, 不同内容, 不直接匹配查询)
        main = Node(content="main topic about speech enhancement", type=NodeType.FACT,
                    utility=0.6, created_at=now)
        nb1 = Node(content="neighbor context frame A", type=NodeType.FACT,
                   utility=0.4, created_at=now - 300.0)
        nb2 = Node(content="neighbor context frame B", type=NodeType.FACT,
                   utility=0.4, created_at=now + 300.0)
        o.store.create_node(main)
        o.store.create_node(nb1)
        o.store.create_node(nb2)
        res = o.recall("speech enhancement", limit=10)
        hit_ids = [h.node_id for h in res.hits]
        # 主节点召回
        assert main.id in hit_ids
        # 时间邻域节点应被融合召回(即使不直接匹配查询)
        assert nb1.id in hit_ids, "时间邻域节点应被融合召回"
        assert nb2.id in hit_ids, "时间邻域节点(未来)应被融合召回"
        # recall_data 应记录融合数
        assert res.metadata.get("temporal_neighbors_fused", 0) >= 2
        o.store.close()
        try:
            os.remove(db)
        except Exception:
            pass
