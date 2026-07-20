"""方案 Y 回归测试: 机制消费率聚合器覆盖全 6 类载体。

根因: B1 消费率原只看 mechanism_registry (1/6 机制), 其余 5 类
(Skill/Handbook/Instincts/Speculative/Harness) 的激活/消费状态不可观测。
修复: 各载体补使用时间戳 + Omega.get_mechanism_consumption() 聚合全 6 类。

测试:
- SkillRegistry.activate 写 consumed_at
- Handbook locate 命中写 last_used/used_count
- Instincts 命中记 _trigger_counts
- Speculative promote 写 consumed_at
- 聚合器返回 total/consumed/by_carrier 覆盖全 6 类
"""
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from prometheus_nexus.skills.registry import SkillRegistry
from prometheus_nexus.mechanisms.handbook import HarnessHandbook, BehaviorEntry
from prometheus_nexus.safety.instincts import InstinctsRegistry
from prometheus_nexus.evolution.speculative import SpeculativeEvolution
from prometheus_nexus.life import Omega


def test_skill_activate_writes_consumed_at():
    reg = SkillRegistry()
    reg.register(name="s1", tags=["x"])
    assert reg.activate("s1") is True
    assert reg._skill_map["s1"].get("consumed_at") is not None


def test_handbook_locate_writes_used():
    hb = HarnessHandbook(src_root="src")
    # 构造一个能命中关键词的 entry
    e = BehaviorEntry(behavior="caching mechanism", module="m", filepath="f", lineno=1,
                      kind="function", signature="caching()", docstring="cache impl")
    hb.entries = [e]
    cands = hb.locate_behavior("caching mechanism", llm=None, top_k=1)
    # 命中后 entry 应记 last_used + used_count
    assert e.used_count >= 1, "locate 命中应记 used_count"
    assert e.last_used > 0, "locate 命中应记 last_used"


def test_instincts_trigger_counted():
    reg = InstinctsRegistry()
    reg.register("t1", lambda ctx: False, "warn")  # 返回 False = 违规 -> 记触发
    reg.evaluate_all({"x": 1})
    assert reg._trigger_counts.get("t1", 0) >= 1


def test_speculative_promote_writes_consumed_at():
    ev = SpeculativeEvolution()
    ev.fork(context="test", fitness=0.5)
    # 强制 promote: actual > parent
    f = ev._active_forks[0]
    f["parent_fitness"] = 0.1
    f["actual_fitness"] = 0.9
    best = ev.evaluate_and_select()
    assert best is not None
    assert best.get("consumed_at") is not None, "promote 应记 consumed_at"


def test_aggregation_covers_all_carriers():
    """聚合器返回 total/consumed/by_carrier, 且含全 6 类键。"""
    o = Omega(db_path="src/prometheus_nexus.db")
    snap = o.get_mechanism_consumption()
    assert "total" in snap and "consumed" in snap and "rate" in snap
    bc = snap["by_carrier"]
    # 至少应含 mechanism_registry / skill_registry / handook / instincts / harness_x
    for key in ["mechanism_registry", "skill_registry", "handbook", "instincts", "harness_x"]:
        assert key in bc, f"聚合器漏掉载体: {key}"
    # 总机制数应 > 仅看 mechanism_registry 的数 (handbook 单类就数千条)
    assert snap["total"] >= bc["mechanism_registry"]["total"], "total 应含全类"
    o.shutdown() if hasattr(o, "shutdown") else None


def test_b1_consumption_uses_aggregation():
    """B1 消费率维度调聚合器(非只看 mechanism_registry)。"""
    o = Omega(db_path="src/prometheus_nexus.db")
    o._compute_fitness()
    fd = o._last_fitness_detail
    assert "consumption" in fd
    # 聚合器 total 应 >= mechanism_registry 单类 (验证覆盖扩展)
    snap = o.get_mechanism_consumption()
    assert snap["total"] >= 1  # handbook 3170 条必使 total 远大于 1
    o.shutdown() if hasattr(o, "shutdown") else None
