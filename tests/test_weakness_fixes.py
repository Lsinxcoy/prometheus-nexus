"""薄弱点修复回归测试。

覆盖:
- host_agent._mark_consumed: 机制消费后沉淀 consumed_at 进 registry (B1 消费率维度从死变活)
- life._compute_fitness: 三维(multitype/consumption/rumination) 正确计入总分
"""
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from prometheus_nexus.integration.host_agent import GenericAgentAdapter, HostAgentAdapter
from prometheus_nexus.life import Omega
from prometheus_nexus.foundation.schema import NodeType
from prometheus_nexus.loop.info_gain import InfoGainCalculator


def test_mark_consumed_writes_registry():
    """_mark_consumed 把 consumed_at 写进 registry._mechanisms[name]。"""
    reg = type("R", (), {"_mechanisms": {"m1": {"status": "active"}}})()
    omega = type("O", (), {"mechanism_registry": reg})()
    ad = GenericAgentAdapter(host_id="test")
    ad._omega = omega

    ad._mark_consumed("m1")

    assert reg._mechanisms["m1"].get("consumed_at") is not None
    # 不存在的 name 不崩
    ad._mark_consumed("nonexistent")


def test_mark_consumed_no_omega_is_safe():
    """无 _omega 反向持有时静默跳过, 不崩。"""
    ad = GenericAgentAdapter(host_id="test")
    ad._mark_consumed("m1")  # 无 _omega -> 静默


def test_compute_fitness_includes_new_dimensions():
    """_compute_fitness 返回 [0,1] 且 _last_fitness_detail 含三维。"""
    o = Omega(db_path="src/prometheus_nexus.db")
    total = o._compute_fitness()
    assert isinstance(total, float)
    assert 0.0 <= total <= 1.0
    detail = getattr(o, "_last_fitness_detail", {})
    assert "multitype" in detail
    assert "consumption" in detail
    assert "rumination" in detail
    # 三维各自封顶 0.1
    for k in ("multitype", "consumption", "rumination"):
        assert 0.0 <= detail[k] <= 0.1, f"{k}={detail[k]} 超范围"


def test_read_entries_surfaces_malformed_inbox_line(caplog, tmp_path):
    """cycle3: inbox 中腐蚀 JSON 行不再静默丢失, 而是告警(此前 except:pass 无声吞掉)。"""
    import json
    import logging

    from prometheus_nexus.integration.capability_inbox import CapabilityInbox

    inbox_path = tmp_path / "inbox.jsonl"
    with open(inbox_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"event": "received", "name": "good_mech"}) + "\n")
        f.write("{ 这一行是损坏的 JSON \n")  # 非法 JSON

    caplog.set_level(logging.WARNING,
                     logger="prometheus_nexus.integration.capability_inbox")
    inbox = CapabilityInbox(path=str(inbox_path))

    entries = inbox._read_entries()
    # 合法行仍正常解析
    assert len(entries) == 1
    assert entries[0]["name"] == "good_mech"
    # 损坏行触发告警 —— 证明不再静默吞掉(修复前此处零日志)
    assert any("损坏的 inbox 行" in r.message for r in caplog.records), \
        "腐蚀 inbox 行应触发告警, 但无任何日志(静默丢失未修复)"


def test_load_applied_surfaces_malformed_record(caplog, tmp_path):
    """cycle3: 腐蚀的 applied 记录不再静默跳过, 而是告警(防 pending() 重复报已应用机制)。"""
    import json
    import logging
    import os

    from prometheus_nexus.integration.capability_inbox import CapabilityInbox

    inbox_path = tmp_path / "inbox.jsonl"
    inbox_path.write_text("", encoding="utf-8")
    inbox = CapabilityInbox(path=str(inbox_path))  # 启动时 applied/ 不存在, 安全

    applied_dir = os.path.join(os.path.dirname(str(inbox_path)), "applied")
    os.makedirs(applied_dir, exist_ok=True)
    # 腐蚀的 applied 记录
    with open(os.path.join(applied_dir, "bad.applied.json"), "w", encoding="utf-8") as f:
        f.write("{ corrupted json")
    # 合法 applied 记录
    good = {"name": "good_mech", "host_id": "default", "applied_at": 1.0}
    with open(os.path.join(applied_dir, "good_mech.applied.json"), "w", encoding="utf-8") as f:
        json.dump(good, f)

    caplog.set_level(logging.WARNING,
                     logger="prometheus_nexus.integration.capability_inbox")
    inbox._load_applied()

    # 合法记录仍加载
    assert "good_mech" in inbox._applied
    # 腐蚀记录触发告警且不崩(修复前 except:pass 无声吞掉 -> 重启后 pending 重报机制)
    assert any("损坏的 applied 记录" in r.message for r in caplog.records), \
        "腐蚀 applied 记录应触发告警, 但无任何日志(静默丢失未修复)"


# ===== cycle4: InfoGainCalculator.record_gain / diminishing_returns 未实现方法修复 =====
def test_record_gain_stores_history():
    """record_gain 真实落地: 累积历史(此前是 return float(value) 的 no-op, 历史永不增长)。"""
    ig = InfoGainCalculator()
    assert ig._gains == []
    ret = ig.record_gain("reflect", 0.42)
    assert ret == 0.42            # 兼容别名: 原样返回
    ig.record_gain("reflect", 0.3)
    assert len(ig._gains) == 2
    assert ig._gains == [0.42, 0.3]


def test_diminishing_returns_false_without_history():
    """样本不足时仍返回 False(保留安全默认, 不崩、不误报)。"""
    ig = InfoGainCalculator()
    assert ig.diminishing_returns() is False


def test_diminishing_returns_detects_clear_diminishing():
    """增益明显边际递减时返回 True(此前恒返回 False, 永远检测不到)。"""
    ig = InfoGainCalculator()
    for v in [1.0, 0.9, 0.8, 0.1, 0.05, 0.02]:
        ig.record_gain("reflect", v)
    assert ig.diminishing_returns() is True


def test_diminishing_returns_false_when_increasing():
    """增益持续上升时不误报递减(近期均值 > 前期均值)。"""
    ig = InfoGainCalculator()
    for v in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]:
        ig.record_gain("reflect", v)
    assert ig.diminishing_returns() is False


def test_diminishing_returns_no_args_callable_like_life():
    """life.py 以无参方式调用 diminishing_returns(), 签名须保持兼容且平稳时返回 False。"""
    ig = InfoGainCalculator()
    for v in [0.5, 0.5, 0.5, 0.5, 0.5, 0.5]:
        ig.record_gain("reflect", v)
    assert ig.diminishing_returns() is False


# ===== cycle5: DAGScheduler.checkpoint 持久化断点容错修复 =====
# 根因: save_checkpoint 非原子写(中途崩溃留半截JSON); load_checkpoint 对
# checkpoint 数据无条件信任 —— TaskStatus[tdata["status"]] 遇非法状态直接抛
# KeyError, json.load 遇损坏文件抛 JSONDecodeError, 二者均无兜底, 导致整个
# 断点续跑(崩溃恢复)在恰好需要它的崩溃场景下失效并丢失全部进度。
from prometheus_nexus.evolution.dag_scheduler import DAGScheduler, TaskStatus


def test_save_checkpoint_atomic_no_temp_leftover(tmp_path):
    """save_checkpoint 原子写: 目标存在且.rsplit无残留 .tmp(中途崩溃不致损坏)。"""
    sch = DAGScheduler()
    sch.add_task("a")
    sch.add_task("b", dependencies=["a"])
    p = str(tmp_path / "ckpt.json")
    sch.save_checkpoint(p)
    assert os.path.exists(p)
    assert not os.path.exists(p + ".tmp"), "原子写应已 rename, 不应残留 .tmp 临时文件"


def test_load_checkpoint_roundtrip_preserves_state(tmp_path):
    """save->load 往返: 任务数/依赖/并发度完整保留(修复不破坏正常路径)。"""
    sch = DAGScheduler(max_concurrent=3)
    sch.add_task("a")
    sch.add_task("b", dependencies=["a"])
    p = str(tmp_path / "ckpt.json")
    sch.save_checkpoint(p)

    sch2 = DAGScheduler()
    n = sch2.load_checkpoint(p)
    assert n == 2
    assert sch2._max_concurrent == 3
    assert "b" in sch2._tasks
    assert sch2._tasks["b"].dependencies == {"a"}


def test_load_checkpoint_resilient_to_unknown_status(tmp_path):
    """断点续跑: 单任务状态非法时不抛 KeyError 中止全部, 降级 PENDING 继续。"""
    sch = DAGScheduler()
    sch.add_task("a")
    sch.add_task("b", dependencies=["a"])
    p = str(tmp_path / "ckpt.json")
    sch.save_checkpoint(p)

    # 篡改 checkpoint: 把任务 a 的状态改成非法枚举名
    import json
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    tids = list(data["tasks"].keys())
    data["tasks"][tids[0]]["status"] = "NOT_A_REAL_STATUS"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f)

    # 修复前此处直接 KeyError -> 整个续跑失败; 修复后返回恢复数且坏任务降级
    restored = sch.load_checkpoint(p)
    assert restored == 2
    assert sch._tasks[tids[0]].status == TaskStatus.PENDING


def test_load_checkpoint_skips_malformed_record(tmp_path, caplog):
    """断点续跑: 单条损坏(非 dict / 缺字段)任务记录被跳过并告警, 其余正常恢复。"""
    import json
    import logging

    sch = DAGScheduler()
    sch.add_task("a")
    sch.add_task("b", dependencies=["a"])
    p = str(tmp_path / "ckpt.json")
    sch.save_checkpoint(p)

    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["tasks"]["broken"] = "this is not a dict"  # 损坏记录
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f)

    caplog.set_level(logging.WARNING,
                     logger="prometheus_nexus.evolution.dag_scheduler")
    restored = sch.load_checkpoint(p)
    assert restored == 2                      # 仅合法两条恢复
    assert "broken" not in sch._tasks         # 损坏记录被跳过
    assert any("跳过损坏的任务记录" in r.message for r in caplog.records), \
        "损坏任务记录应触发告警, 但无日志"


def test_load_checkpoint_corrupt_file_raises_clear_error(tmp_path):
    """断点续跑: 文件级损坏(截断 JSON)抛出清晰 ValueError(非静默裸异常)。"""
    import pytest

    sch = DAGScheduler()
    p = str(tmp_path / "ckpt.json")
    with open(p, "w", encoding="utf-8") as f:
        f.write('{ "version": 1, "tasks": { "a": ')  # 截断的 JSON
    with pytest.raises(ValueError):
        sch.load_checkpoint(p)


# ---- 周期9: EvolutionQualityGates._check_reliability 可靠性评分越界(负数) ----
# 根因: evolution_quality_gates.py:182 原式 check.score = 1.0 - abs(mutation_rate - 0.1)
# 未夹到 [0,1]; 当 mutation_rate 偏离 0.1 过大(>1.1 或 <-0.9, 来自未校验的
# evolution result) 会产出负数, 污染 QualityReport.avg_score 与 get_stats() 聚合。
# 其 sibling 门 (functional/performance/diversity) 全部 clamp 到 [0,1]。
from prometheus_nexus.evolution.evolution_quality_gates import (
    EvolutionQualityGates, GateResult,
)


def _reliability_check(report):
    return next(c for c in report.checks if c.name == "reliability")


def test_reliability_gate_score_clamped_high_mutation():
    """mutation_rate=2.0 -> 原式 1.0-1.9=-0.9, 必须夹紧到 0.0; WARN 决策不变。"""
    gates = EvolutionQualityGates()
    rep = gates.check({"mutation_rate": 2.0, "best_fitness": 0.8})
    rel = _reliability_check(rep)
    assert 0.0 <= rel.score <= 1.0
    assert rel.score == 0.0
    assert rel.result == GateResult.WARN


def test_reliability_gate_score_clamped_extreme():
    """mutation_rate=5.0 -> 原式 -3.9, 必须夹紧到 0.0。"""
    gates = EvolutionQualityGates()
    rep = gates.check({"mutation_rate": 5.0})
    assert _reliability_check(rep).score == 0.0


def test_reliability_gate_score_clamped_negative_input():
    """mutation_rate=-1.0 -> 原式 -0.1, 必须夹紧到 0.0。"""
    gates = EvolutionQualityGates()
    rep = gates.check({"mutation_rate": -1.0})
    assert _reliability_check(rep).score == 0.0


def test_reliability_gate_score_ideal_is_one():
    """mutation_rate=0.1 (理想) -> 评分 1.0, 决策 PASS。"""
    gates = EvolutionQualityGates()
    rep = gates.check({"mutation_rate": 0.1})
    rel = _reliability_check(rep)
    assert rel.score == 1.0
    assert rel.result == GateResult.PASS


def test_quality_report_avg_score_stays_in_range_pathological():
    """即便出现异常的 mutation_rate, 聚合 avg_score 不得越出 [0,1] / 变负。"""
    gates = EvolutionQualityGates()
    for mr in [0.1, 0.3, 2.0, 5.0, -1.0]:
        gates.check({"mutation_rate": mr, "best_fitness": 0.8})
    stats = gates.get_stats()
    assert 0.0 <= stats["avg_score"] <= 1.0
