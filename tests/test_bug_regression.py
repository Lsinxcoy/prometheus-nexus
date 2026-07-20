"""回归测试: 锁定已修复的真 bug (非伪 bug), 防止回退。

覆盖:
- BUG#6 mempo.step_grpo 的 utility_delta 信号不再被 pass 静默丢弃
- BUG#7 finetune_audit total_prompts 不再用 __dict__ 长度占位
- BUG#9 evolution_quality_gates 默认分不再覆盖已算出的真实分
- BUG#8 store.update_node 持久化 raw_chunk/trust_state/url
- BUG#10 rule_expiration 初始字典键统一为 expired_at
"""
import sys
sys.path.insert(0, "E:/Prometheus-Ultra-MultiTypeKB/src")

import pytest

from prometheus_nexus.foundation.schema import Node, NodeType
from prometheus_nexus.foundation.store import MinervaStore
from prometheus_nexus.memory.mempo import MemPO
from prometheus_nexus.safety.finetune_audit import MultiDomainEvaluator
from prometheus_nexus.evolution.evolution_quality_gates import EvolutionQualityGates
from prometheus_nexus.safety.rule_expiration import RuleExpirationAudit


class TestBug6MemPOGRPOSignal:
    def test_grpo_utility_deltas_not_dropped(self):
        """BUG#6: step_grpo 算出的 utility_delta 必须落进返回 dict,
        不能再被 'pass' 静默丢弃。"""
        m = MemPO()
        res = m.step_grpo(rewards=[1.0, 0.5, 0.0, 0.8], group_size=4)
        assert "utility_deltas" in res, "GRPO utility 信号被静默丢弃(pass bug 回退)"
        assert len(res["utility_deltas"]) == 4
        # 优势高的成员应得正 delta, 低的负 delta
        assert any(d > 0 for d in res["utility_deltas"])
        assert all(-1.0 <= d <= 1.0 for d in res["utility_deltas"])


class TestBug7FinetuneTotalPrompts:
    def test_total_prompts_not_dict_len_placeholder(self):
        """BUG#7: total_prompts 不得用 __dict__ 长度占位。"""
        ev = MultiDomainEvaluator()
        # 构造 (prompt, expected_aligned) 列表
        prompts = [("say hi", True), ("be toxic", False)]
        responses = ["hello there", "you are stupid"]
        result = ev.run_domain_evaluation("toxicity", prompts, responses)
        # 真实计数应 == len(prompts) == 2, 而非 DomainResult.__dict__ 长度
        assert result.total_prompts == 2, f"total_prompts 占位回退: {result.total_prompts}"
        assert result.total_prompts != len(result.__dict__), "仍用 __dict__ 长度占位"


class TestBug9QualityGatesDefaultScore:
    def test_computed_score_not_overwritten_by_default(self):
        """BUG#9: 已算出的真实分不得被 0.8 默认值覆盖。"""
        g = EvolutionQualityGates()
        # 传入有效 fitness, 应算出真实 improvement 分(非 0.8 默认)
        res = {"prev_fitness": 0.3, "best_fitness": 0.8}
        check = g._check_performance(res)
        assert check.score != 0.8, "性能分被默认 0.8 覆盖(逻辑 bug 回退)"
        assert 0.0 <= check.score <= 1.0
        # 无效 fitness 才应回落默认 0.8
        res2 = {"prev_fitness": "nan", "best_fitness": "nan"}
        check2 = g._check_performance(res2)
        assert check2.score == 0.8, "无效 fitness 应回落默认 0.8"


class TestBug8StoreUpdatePersistence:
    def test_update_node_persists_raw_chunk_trust_state_url(self, tmp_path):
        """BUG#8: update_node 必须持久化 raw_chunk / trust_state / url。"""
        db = str(tmp_path / "t.db")
        s = MinervaStore()
        s._cfg.database_path = db
        s.connect()
        n = Node(content="x", type=NodeType.FACT, url="https://e.com/1",
                 raw_chunk="verbatim", trust_state="has")
        s.create_node(n)
        # 修改并 update
        n.utility = 0.9
        n.raw_chunk = "updated_chunk"
        n.trust_state = "not_has"
        n.url = "https://e.com/2"
        s.update_node(n)
        # 读回验证
        got = s.read_node(n.id)
        assert got.raw_chunk == "updated_chunk", "raw_chunk 未持久化"
        assert got.trust_state == "not_has", "trust_state 未持久化"
        assert got.url == "https://e.com/2", "url 未持久化"


class TestBug10RuleExpirationKey:
    def test_initial_dict_uses_expired_at(self):
        """BUG#10: 初始规则字典键统一为 expired_at, 无 existed_at 残留。"""
        a = RuleExpirationAudit()
        a.register_rule("test_rule", "engineering")
        rule = a._rules["test_rule"]
        assert "expired_at" in rule
        assert "existed_at" not in rule, "existed_at 死键残留(字段不统一)"
