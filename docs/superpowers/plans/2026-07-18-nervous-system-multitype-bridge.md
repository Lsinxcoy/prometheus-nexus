# 神经系统 × MultiTypeKB 接入强化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把"基于旧版 Ultra 设计的神经系统"(CNS/CC/AR/SFL/Telemetry) 与当前 MultiTypeKB 架构的真实能力(反刍知新、多类型 KB、机制消费闭环) 接上，消除 A/B/C/D 四级断裂，使自主进化引擎不再为旧版指标优化、对最贵的反刍动作不再失明。

**Architecture:** 神经系统依赖 `event_bus` + `Telemetry` 信号总线。本计划只做"补信号源 + 补评估维度"，不重写神经三层内部逻辑：(A1) rumination 完成时 publish `rumination_completed` 并被 CNS/CC/AR/Telemetry 消费；(B1) `_compute_fitness` 增加"多类型覆盖度 / 机制消费率 / 反刍产出率"维度，AR 自动继承；(C1) Telemetry `evolve` schema 扩展 camp/speculative/consensus 诊断字段，CNS `evolve_to_dream` 叠加质量门；(D1) `emit/apply_capability` 成功时 publish `capability_consumed`，AR 订阅纳入 fitness 趋势。

**Tech Stack:** Python 3.11, Prometheus-Ultra-MultiTypeKB 现有事件总线(`event_bus.publish`/`subscribe`)、TelemetryPipeline、`Omega._compute_fitness`、CapabilityInbox。无新依赖。

## Global Constraints

- Python >= 3.11（项目强制，所有 .py 用 `E:\Prometheus-Ultra-MultiTypeKB\.venv\Scripts\python.exe` 跑 pytest）
- 不破坏独立运行模式（NullHostAdapter 下所有新增事件 publish 需 `if self._omega` 守卫，不得抛异常）
- 不修改 CNS/CC/AR 的触发链逻辑本身，只补订阅/信号/评估维度（遵循"神经系统是旧版设计遗产，只接新架构不重写"原则）
- 所有新增事件发布必须用 try/except 包裹，logger.debug 降级，不影响主流程
- 遵循现有代码惯例：`event_bus.publish({"type": "...", ...})`；订阅用 `bus.subscribe("topic", handler, priority=...)`
- 100% 测试覆盖新增逻辑（按用户铁律），每个任务配 pytest
- API 向后兼容：dashboard summary 字段只增不删
- 每次改动在 git 上独立 commit（频繁提交）

---

## 已完成的事实核验（写计划前的根因证据）

- **A 级断裂属实**：`knowledge_rumination.ruminate()` 结束时不 publish 任何事件；CNS/CC/AR/Telemetry 的 `_PIPE_SCHEMAS` 均无 rumination；`grep rumination` 在生命周期事件里零 publish。
- **B 级失真属实**：`_compute_fitness`(life.py:4324) 7 维度只含 记忆/多样性/进化活动/健康/HarnessX/效用/热力学，不感知 多类型 node type 覆盖度、机制消费率(`consumed_at`/`emit_accepted`)、反刍产出率。
- **C 级盲区属实**：Telemetry `evolve` schema(telemetry_pipeline.py:65-73) 只提 `fitness_before/after/delta/result_code/best_strategy/gate_block_count`；实测 `last_chain.metadata` 含 `camp_vote/camp_panel/multi_agent_consensus/speculative` 等新诊断未被提取。
- **D 级缺失属实**：`host_agent.py` 的 `emit_capability`/`apply_capability` 不 publish 任何事件；AR 熔断只看 Ultra 内部 fitness。adapter 可经 `self._omega.event_bus` 发事件（`Omega(host=adapter)` 反向持有）。
- **E1 已证伪（不做）**：`SignalFusion.apply_threshold_adjustments`(signal_fusion.py:508-547) 已实现并调用 `cns.update_threshold` 写回 CNS，且 CC 每3次 reflect 触发。自适应闭环通畅，E1 删除。
- **summary 谎报已证伪（不做）**：api_server:761 用 `get_nodes_by_type(nt, limit=100000)` 真实统计 type_distribution，实测 CONCEPT 482/FACT 92/PROCEDURE 51 正确。无需修。

---

## File Structure（本计划涉及文件）

- Modify: `src/prometheus_nexus/learning/knowledge_rumination.py` — A1(rumination_completed publish + Telemetry schema 数据源)
- Modify: `src/prometheus_nexus/lifecycle/telemetry_pipeline.py` — A1(rumination schema)、C1(evolve 新诊断字段)
- Modify: `src/prometheus_nexus/lifecycle/cns_orchestrator.py` — A1(rumination→maintain 链)、C1(evolve_to_dream 质量门)
- Modify: `src/prometheus_nexus/lifecycle/cerebral_cortex.py` — A1(rumination 缺口监听，可选)
- Modify: `src/prometheus_nexus/lifecycle/autonomic_regulator.py` — A1(rumination 订阅)、B1(fitness 维度已在 _compute_fitness)、D1(capability_consumed 订阅)
- Modify: `src/prometheus_nexus/life.py` — B1(`_compute_fitness` 增维度)、D1(emit/apply 处 publish)
- Modify: `src/prometheus_nexus/integration/host_agent.py` — D1(adapter 内 publish capability_consumed)
- Test: `tests/test_nervous_system_multitype.py` — 本计划全部新增逻辑测试
- Test: 复用 `tests/test_v3_*.py` 中既有 Omega 实例化 fixture

---

## Task 1: A1 — rumination 完成事件发布 + Telemetry 采集

**Files:**
- Modify: `src/prometheus_nexus/learning/knowledge_rumination.py` (ruminate 末尾 publish)
- Modify: `src/prometheus_nexus/lifecycle/telemetry_pipeline.py` (_PIPE_SCHEMAS 增 rumination + _resolve 解析)
- Test: `tests/test_nervous_system_multitype.py`

**Interfaces:**
- Consumes: `RuminationResult` 字段 (total_scanned/relearned/concepts_extracted/relations_extracted/mappings_applied/skills_promoted/routed_nodes/utility_raised/deleted_nodes/details{pending_t3,pending_t4,fuel_supplied})
- Produces: event `{"type":"rumination_completed","data":{...RuminationResult字段...}}` 供 CNS/CC/AR/Telemetry 订阅

- [ ] **Step 1: 写失败测试**

```python
# tests/test_nervous_system_multitype.py
import pytest
from prometheus_nexus.learning.knowledge_rumination import KnowledgeRuminationEngine, RuminationResult

def test_rumination_publishes_event():
    # 用最小 stub omega 捕获 event_bus.publish
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
    # 造一个空候选(无节点)的快速返回分支
    eng._select_nodes = lambda mode, limit: []
    res = eng.ruminate(mode="full", force=True)
    assert any(e.get("type") == "rumination_completed" for e in published), "rumination 必须 publish rumination_completed"
    ev = [e for e in published if e.get("type")=="rumination_completed"][0]
    assert "data" in ev and "total_scanned" in ev["data"]
```

- [ ] **Step 2: 运行测试确认失败**
Run: `cd /e/Prometheus-Ultra-MultiTypeKB && .venv/Scripts/python.exe -m pytest tests/test_nervous_system_multitype.py::test_rumination_publishes_event -v`
Expected: FAIL（publish 未实现）

- [ ] **Step 3: 在 ruminate() 末尾加 publish（knowledge_rumination.py:142 之后）**

```python
        # 发布反刍完成事件 — 让神经系统(CNS/CC/AR/Telemetry)感知知新产出
        try:
            bus = getattr(self.omega, "event_bus", None)
            if bus is not None:
                bus.publish({
                    "type": "rumination_completed",
                    "data": {
                        "total_scanned": result.total_scanned,
                        "relearned": result.relearned,
                        "concepts_extracted": result.concepts_extracted,
                        "relations_extracted": result.relations_extracted,
                        "mappings_applied": result.mappings_applied,
                        "skills_promoted": result.skills_promoted,
                        "routed_nodes": result.routed_nodes,
                        "utility_raised": result.utility_raised,
                        "deleted_nodes": result.deleted_nodes,
                        "pending_t3": result.details.get("pending_t3", 0),
                        "pending_t4": result.details.get("pending_t4", 0),
                        "fuel_supplied": result.details.get("fuel_supplied", False),
                    },
                })
        except Exception as e:
            logger.debug("[Rumination] publish rumination_completed failed: %s", e)
        return result
```

- [ ] **Step 4: Telemetry 增 rumination schema（telemetry_pipeline.py:53 _PIPE_SCHEMAS 内追加）**

```python
        "rumination": {
            "total_scanned": ("event.data.total_scanned", "n"),
            "relearned": ("event.data.relearned", "n"),
            "mappings_applied": ("event.data.mappings_applied", "n"),
            "skills_promoted": ("event.data.skills_promoted", "n"),
            "routed_nodes": ("event.data.routed_nodes", "n"),
            "utility_raised": ("event.data.utility_raised", "n"),
            "pending_t3": ("event.data.pending_t3", "n"),
            "pending_t4": ("event.data.pending_t4", "n"),
        },
```

并在 `subscribe`(109行) 的 for 循环里 rumination 已被 `_PIPE_SCHEMAS` 覆盖，无需额外改动（循环遍历 `_PIPE_SCHEMAS` keys）。同时 `signal_fusion.subscribe`(72行) 与 CNS/CC/AR subscribe 列表需显式加 `rumination_completed`——见 Task 2/3/4。

- [ ] **Step 5: 运行测试确认通过**
Run: `cd /e/Prometheus-Ultra-MultiTypeKB && .venv/Scripts/python.exe -m pytest tests/test_nervous_system_multitype.py::test_rumination_publishes_event -v`
Expected: PASS

- [ ] **Step 6: Commit**
```bash
cd /e/Prometheus-Ultra-MultiTypeKB && git add src/prometheus_nexus/learning/knowledge_rumination.py src/prometheus_nexus/lifecycle/telemetry_pipeline.py tests/test_nervous_system_multitype.py && git commit -m "feat(A1): rumination publishes rumination_completed + Telemetry schema"
```

---

## Task 2: A1 — 神经三层订阅 rumination_completed

**Files:**
- Modify: `src/prometheus_nexus/lifecycle/signal_fusion.py` (subscribe 列表加 rumination_completed)
- Modify: `src/prometheus_nexus/lifecycle/cns_orchestrator.py` (subscribe + rumination→maintain 触发链)
- Modify: `src/prometheus_nexus/lifecycle/autonomic_regulator.py` (subscribe + rumination 统计)
- Modify: `src/prometheus_nexus/lifecycle/cerebral_cortex.py` (subscribe 可选，本任务加以支持完整性)
- Test: `tests/test_nervous_system_multitype.py`

**Interfaces:**
- Consumes: `rumination_completed` 事件（Task 1 产出）
- Produces: CNS 在 rumination 高产出(skills_promoted>0 或 routed_nodes>0)后触发 maintain；AR 记录 rumination 趋势

- [ ] **Step 1: 写失败测试（CNS 订阅后能响应 rumination）**

```python
def test_cns_subscribes_rumination():
    from prometheus_nexus.lifecycle.cns_orchestrator import CNSOrchestrator
    subs = []
    class StubBus:
        def subscribe(self, topic, handler, priority=0.5):
            subs.append(topic)
    cns = CNSOrchestrator.__new__(CNSOrchestrator)
    cns.subscribe(StubBus())
    assert "rumination_completed" in subs, "CNS 必须订阅 rumination_completed"
```

- [ ] **Step 2: 运行确认失败**
Run: `cd /e/Prometheus-Ultra-MultiTypeKB && .venv/Scripts/python.exe -m pytest tests/test_nervous_system_multitype.py::test_cns_subscribes_rumination -v`
Expected: FAIL

- [ ] **Step 3: SignalFusion.subscribe 加 rumination_completed（signal_fusion.py:72 循环列表追加）**

原列表 `[...7个...]` 改为包含 `"rumination"`：
```python
        for suffix in [\"remember\", \"recall\", \"evolve\", \"learn\",
                        \"reflect\", \"dream\", \"maintain\", \"rumination\"]:
            bus.subscribe(f\"{suffix}_completed\", self._on_pipe_event, priority=0.85)
```

- [ ] **Step 4: CNS.subscribe + 触发链（cns_orchestrator.py:93 subscribe 方法）**

在 subscribe 内现有 7 管道订阅后追加：
```python
        if hasattr(bus, "subscribe"):
            bus.subscribe("rumination_completed", self._on_rumination, priority=0.7)
```
并新增处理方法（放在 `_can_trigger` 附近）：
```python
    def _on_rumination(self, event: dict) -> None:
        \"\"\"反刍知新产出 → 触发 maintain 巩固 (仅当确有系统级产出)。\"\"\"
        try:
            data = event.get("data", {})
            skills = data.get("skills_promoted", 0) or 0
            routed = data.get("routed_nodes", 0) or 0
            mappings = data.get("mappings_applied", 0) or 0
            if skills > 0 or routed > 0 or mappings > 0:
                if self._can_trigger("maintain"):
                    logger.info("CNS: rumination produced knowledge (skills=%d routed=%d), triggering maintain", skills, routed)
                    try:
                        self._omega.maintain()
                    except Exception as e:
                        logger.warning("CNS: rumination->maintain failed: %s", e)
        except Exception as e:
            logger.warning("CNS._on_rumination: %s", e)
```

- [ ] **Step 5: AR.subscribe + 统计（autonomic_regulator.py:44 subscribe 方法）**

在 subscribe 内追加：
```python
            bus.subscribe("rumination_completed", self._on_rumination, priority=0.6)
```
新增（放在 `_on_remember` 之后）：
```python
    def _on_rumination(self, event: dict) -> None:
        \"\"\"反刍完成 → 记录知新产出到 fitness 趋势，供熔断/降级判断。\"\"\"
        try:
            d = event.get("data", {})
            promoted = d.get("skills_promoted", 0) or 0
            routed = d.get("routed_nodes", 0) or 0
            relearned = d.get("relearned", 0) or 0
            # 反刍产出视为正向 fitness 信号（系统把存量知识转化为能力）
            if promoted > 0 or routed > 0:
                self._fitness_log.append((max(0.1, 0.5 + 0.01 * promoted), time.time(), "rumination"))
        except Exception as e:
            logger.warning("AutonomicRegulator._on_rumination: %s", e)
```

- [ ] **Step 6: CC.subscribe（cerebral_cortex.py:100 subscribe 方法）**

在 subscribe 内 for 循环后追加：
```python
        bus.subscribe("rumination_completed", self._on_rumination, priority=0.7)
```
新增（放在 `_on_outcome` 附近）：
```python
    def _on_rumination(self, event: dict) -> None:
        \"\"\"反刍产出 → 记录到 outcome（与 evolve/learn 同口径参与自适应/熔断）。\"\"\"
        try:
            d = event.get("data", {})
            promoted = d.get("skills_promoted", 0) or 0
            routed = d.get("routed_nodes", 0) or 0
            outcome = min(1.0, (promoted + routed) / 10.0)
            fitness = self._omega._compute_fitness() if hasattr(self._omega, "_compute_fitness") else 0.5
            self._record_outcome("rumination", fitness, outcome)
        except Exception as e:
            logger.warning("CerebralCortex._on_rumination: %s", e)
```

- [ ] **Step 7: 运行测试确认通过**
Run: `cd /e/Prometheus-Ultra-MultiTypeKB && .venv/Scripts/python.exe -m pytest tests/test_nervous_system_multitype.py::test_cns_subscribes_rumination -v`
Expected: PASS

- [ ] **Step 8: Commit**
```bash
cd /e/Prometheus-Ultra-MultiTypeKB && git add src/prometheus_nexus/lifecycle/signal_fusion.py src/prometheus_nexus/lifecycle/cns_orchestrator.py src/prometheus_nexus/lifecycle/autonomic_regulator.py src/prometheus_nexus/lifecycle/cerebral_cortex.py tests/test_nervous_system_multitype.py && git commit -m "feat(A1): CNS/CC/AR/SFL subscribe rumination_completed"
```

---

## Task 3: B1 — `_compute_fitness` 增三维（多类型覆盖 / 机制消费率 / 反刍产出率）

**Files:**
- Modify: `src/prometheus_nexus/life.py` (`_compute_fitness` 4324 增三个维度)
- Test: `tests/test_nervous_system_multitype.py`

**Interfaces:**
- Consumes: `store.get_nodes_by_type`(多类型计数)、`mechanism_registry`(consumed_at/emit_accepted 统计)、`knowledge_rumination` 最近产出(`history[-1]`)
- Produces: `_compute_fitness` 返回值提升对"类型健康/机制被用/反刍产出"的敏感度；AR 自动继承（已调 `_compute_fitness`）

- [ ] **Step 1: 写失败测试**

```python
def test_fitness_includes_multitype_and_consumption():
    from prometheus_nexus.core.omega import Omega  # 或实际导入路径
    # 用 fixture 构建最小 Omega；断言 _compute_fitness 内部调用了多类型与消费率统计
    # 简化：monkeypatch store.get_nodes_by_type 返回差异化计数，验证 fitness 变化
    ...
```
(具体测试在 Step 5 用 stub 验证三个新维度函数被调用且影响总分)

- [ ] **Step 2: 运行确认失败**
Run: `cd /e/Prometheus-Ultra-MultiTypeKB && .venv/Scripts/python.exe -m pytest tests/test_nervous_system_multitype.py -k fitness -v`
Expected: FAIL

- [ ] **Step 3: 在 `_compute_fitness` (life.py:4358 之前) 增三维**

```python
        # Dimension 8: 多类型覆盖度 (0-0.1) — 类型越多样越健康
        try:
            type_counts = {}
            for nt in [NodeType.FACT, NodeType.CONCEPT, NodeType.PROCEDURE,
                       NodeType.PAPER, NodeType.PROJECT, NodeType.SKILL,
                       NodeType.PATTERN]:
                c = self.store.get_nodes_by_type(nt, limit=100000)
                if isinstance(c, (list, tuple)):
                    type_counts[nt.value] = len(c)
                elif isinstance(c, int):
                    type_counts[nt.value] = c
            non_empty = sum(1 for v in type_counts.values() if v > 0)
            multitype_score = min(0.1, non_empty * 0.02)
        except Exception:
            multitype_score = 0.0

        # Dimension 9: 机制消费率 (0-0.1) — 进化的机制真被宿主用上才算数
        try:
            reg = self.mechanism_registry
            all_mech = reg.get_all() if hasattr(reg, "get_all") else {}
            consumed = sum(1 for m in all_mech.values()
                           if getattr(m, "consumed_at", None) is not None
                           or getattr(m, "emit_accepted", None) is True)
            total_mech = max(1, len(all_mech))
            consumption_score = min(0.1, consumed / total_mech * 0.1)
        except Exception:
            consumption_score = 0.0

        # Dimension 10: 反刍产出率 (0-0.1) — 知新能力(近期 skills_promoted)
        try:
            hist = getattr(self.knowledge_rumination, "history", [])
            recent = hist[-1] if hist else None
            rumination_score = 0.0
            if recent is not None:
                promoted = getattr(recent, "skills_promoted", 0) or 0
                routed = getattr(recent, "routed_nodes", 0) or 0
                rumination_score = min(0.1, (promoted + routed) / 20.0)
        except Exception:
            rumination_score = 0.0
```

并把 `total = ...` 改为累加这三维：
```python
        total = (memory_score + diversity_score + evo_score + health_score
                 + harness_score + util_score + energy_score
                 + multitype_score + consumption_score + rumination_score)
```

- [ ] **Step 4: 确认不影响既有上限** — 各维 `min(...,0.1)` 封顶，总分仍 `min(1.0, ...)`，旧测试不因总分变化而误判（旧测试若断言精确值需同步；先 grep 确认无精确值断言）

- [ ] **Step 5: 运行测试确认通过**
Run: `cd /e/Prometheus-Ultra-MultiTypeKB && .venv/Scripts/python.exe -m pytest tests/test_nervous_system_multitype.py -k fitness -v`
Expected: PASS

- [ ] **Step 6: Commit**
```bash
cd /e/Prometheus-Ultra-MultiTypeKB && git add src/prometheus_nexus/life.py tests/test_nervous_system_multitype.py && git commit -m "feat(B1): _compute_fitness adds multitype/consumption/rumination dimensions"
```

> **⚠️ 执行修正（父会话核验发现）**：`MechanismRegistry` 无 `get_all()` 方法（实测只有 register/deactivate/get_enabled）。机制以 dict 存于 `reg._mechanisms`（entry 为 dict，含 `consumed_at`/`emit_accepted` 字段，autonomic_regulator.py:260 已用 `reg._mechanisms.get(name, {})` 验证）。Task 3 Step 3 的 Dimension 9 代码必须改为：
> ```python
> reg = self.mechanism_registry
> all_mech = getattr(reg, "_mechanisms", {}) or {}
> consumed = sum(1 for m in all_mech.values()
>                if isinstance(m, dict) and (m.get("consumed_at") is not None
>                or m.get("emit_accepted") is True))
> total_mech = max(1, len(all_mech))
> consumption_score = min(0.1, consumed / total_mech * 0.1)
> ```
> 测试中也不得调用 `reg.get_all()`。

---

## Task 4: C1 — Telemetry evolve 扩展新诊断信号 + CNS 质量门

**Files:**
- Modify: `src/prometheus_nexus/lifecycle/telemetry_pipeline.py` (`_PIPE_SCHEMAS["evolve"]` 增 camp/speculative/consensus 字段 + `_resolve` 解析)
- Modify: `src/prometheus_nexus/lifecycle/cns_orchestrator.py` (`_on_evolve` 或 `evolve_to_dream` 触发条件叠加质量门)
- Test: `tests/test_nervous_system_multitype.py`

**Interfaces:**
- Consumes: `evolve` 返回 `metadata` 含 `camp_vote`/`camp_panel`/`multi_agent_consensus`/`speculative`(实测 last_chain.metadata 字段)
- Produces: Telemetry `evolve` 信号含 `consensus_rate`/`speculative_flag`；CNS `evolve_to_dream` 仅在 consensus 通过时触发

- [ ] **Step 1: 写失败测试**

```python
def test_telemetry_evolve_captures_consensus():
    from prometheus_nexus.lifecycle.telemetry_pipeline import TelemetryPipeline
    tp = TelemetryPipeline.__new__(TelemetryPipeline)
    tp._history = {p: [] for p in ["remember","recall","evolve","learn","reflect","dream","maintain","rumination"]}
    tp._max_window = 50
    # 构造带 metadata 的 evolve 返回值 stub
    class Meta:
        camp_vote = 3
        camp_panel = 5
        multi_agent_consensus = True
        speculative = False
    class Ret:
        fitness_before = 0.5
        fitness_after = 0.55
        result = "SUCCESS"
        metadata = Meta()
    class Omega:
        _telemetry = {"evolve": Ret()}
    tp._omega = Omega()
    snap = tp._on_event({"data": {"type": "evolve_completed"}})
    s = tp.query("evolve")
    assert s.signals.get("consensus_rate") is not None
```

- [ ] **Step 2: 运行确认失败**
Run: `cd /e/Prometheus-Ultra-MultiTypeKB && .venv/Scripts/python.exe -m pytest tests/test_nervous_system_multitype.py::test_telemetry_evolve_captures_consensus -v`
Expected: FAIL

- [ ] **Step 3: Telemetry evolve schema 扩展（telemetry_pipeline.py:65-73）**

```python
        "evolve": {
            "fitness_before": ("return.fitness_before", "n"),
            "fitness_after": ("return.fitness_after", "n"),
            "delta": ("return", "delta"),
            "result_code": ("return.result", "categorical"),
            "duration_ms": ("return.duration_ms", "n"),
            "best_strategy": ("return.metadata", "best_strategy"),
            "gate_block_count": ("return.metadata", "gate_block_count"),
            # C1 新增: 多智能体审议质量信号
            "consensus_rate": ("return.metadata", "consensus_rate"),
            "speculative_flag": ("return.metadata", "speculative_flag"),
        },
```

并在 `_resolve` 的 `if path == "return.metadata":` 分支内追加：
```python
            if name == "consensus_rate" and isinstance(meta, dict):
                diag = meta.get("diagnostics", {}) or {}
                cv = diag.get("camp_vote", 0)
                cp = diag.get("camp_panel", 0)
                if cp and cv is not None:
                    return round(cv / max(cp, 1), 3)
                return None
            if name == "speculative_flag" and isinstance(meta, dict):
                diag = meta.get("diagnostics", {}) or {}
                return bool(diag.get("speculative_result") or diag.get("speculative_fork_merge"))
```

- [ ] **Step 4: CNS evolve_to_dream 质量门（cns_orchestrator.py 触发 evolve→dream 处）**

在现有 `if delta >= evolve_to_dream_min_delta:` 条件叠加 consensus 检查：
```python
            consensus = self._omega.signal_fusion.signal("evolve", "consensus_rate")
            speculative = self._omega.signal_fusion.signal("evolve", "speculative_flag")
            if delta >= min_delta and (consensus is None or consensus >= 0.5) and not speculative:
                # 仅当审议通过且非投机时才 dream 巩固
                ...
```

- [ ] **Step 5: 运行测试确认通过**
Run: `cd /e/Prometheus-Ultra-MultiTypeKB && .venv/Scripts/python.exe -m pytest tests/test_nervous_system_multitype.py::test_telemetry_evolve_captures_consensus -v`
Expected: PASS

- [ ] **Step 6: Commit**
```bash
cd /e/Prometheus-Ultra-MultiTypeKB && git add src/prometheus_nexus/lifecycle/telemetry_pipeline.py src/prometheus_nexus/lifecycle/cns_orchestrator.py tests/test_nervous_system_multitype.py && git commit -m "feat(C1): Telemetry evolve consensus/speculative + CNS quality gate"
```

---

## Task 5: D1 — 宿主侧机制消费回流神经系统

**Files:**
- Modify: `src/prometheus_nexus/integration/host_agent.py` (`emit_capability`/`apply_capability` 成功时 publish `capability_consumed`)
- Modify: `src/prometheus_nexus/life.py` (T4 激活 emit 成功后亦可由 adapter 内 publish，无需重复)
- Modify: `src/prometheus_nexus/lifecycle/autonomic_regulator.py` (AR 订阅 `capability_consumed` 纳入 fitness 趋势)
- Test: `tests/test_nervous_system_multitype.py`

**Interfaces:**
- Consumes: `emit_capability` 返回 True / `apply_capability` 返回 accepted；`self._omega.event_bus`
- Produces: event `{"type":"capability_consumed","data":{"name","action":"emit|apply","accepted":bool}}`；AR 把它当正/负 fitness 信号

> **⚠️ 执行修正（父会话核验发现，Task 5 必须）**：`Omega(host=adapter)` 后**从未**把 `self` 回指给 `adapter._omega`（实测 life.py 的 `self.host = ...` 处无 `host._omega = self`）。因此 adapter 内部**拿不到 `self._omega`**，原 Step 3 的 `getattr(self, "_omega", None)` 会恒为 None，publish 永不触发。
> **修正方案（推荐 α）**：在 `Omega.__init__` 中 `self.host = ...` 之后加 `self.host._omega = self`（反向持有），adapter 即可 `self._omega.event_bus.publish(...)`。同时 Step 5 AR 的测试需构造带 `_omega.event_bus` 的 stub adapter。
> 子代理执行 Task 5 时**必须在 life.py 加反向持有一行** + host_agent.py 两个 adapter 的 emit/apply 成功分支 publish + AR 订阅。

- [ ] **Step 1: 写失败测试**

```python
def test_adapter_publishes_capability_consumed():
    from prometheus_nexus.integration.host_agent import GenericAgentAdapter
    published = []
    class StubBus:
        def publish(self, ev): published.append(ev)
        def subscribe(self, *a, **k): pass
    class StubOmega:
        event_bus = StubBus()
    ad = GenericAgentAdapter(host_id="test", endpoint="http://x")
    ad._omega = StubOmega()
    # 让 emit 走 inbox 分支(无 endpoint) 返回 True
    ad._emit_endpoint = None
    ok = ad.emit_capability({"name": "m1"})
    assert any(e.get("type")=="capability_consumed" for e in published), "emit 成功必须 publish"
```

- [ ] **Step 2: 运行确认失败**
Run: `cd /e/Prometheus-Ultra-MultiTypeKB && .venv/Scripts/python.exe -m pytest tests/test_nervous_system_multitype.py::test_adapter_publishes_capability_consumed -v`
Expected: FAIL

- [ ] **Step 3: host_agent.py emit_capability 末尾 publish（两个 adapter 类均加）**

在 `GenericAgentAdapter.emit_capability` 与 `NullHostAdapter.emit_capability` 返回前（无论 HTTP 还是 inbox 成功）追加：
```python
            try:
                bus = getattr(self, "_omega", None)
                if bus is not None and hasattr(bus, "event_bus"):
                    bus.event_bus.publish({
                        "type": "capability_consumed",
                        "data": {"name": name, "action": "emit", "accepted": True},
                    })
            except Exception:
                pass
```
`apply_capability` 同理（`action": "apply"`）。

- [ ] **Step 4: AR 订阅 capability_consumed（autonomic_regulator.py subscribe + 新 handler）**

```python
            bus.subscribe("capability_consumed", self._on_capability, priority=0.6)
```
```python
    def _on_capability(self, event: dict) -> None:
        \"\"\"机制被宿主消费(emit/apply) → 正 fitness 信号；被拒 → 负信号。\"\"\"
        try:
            d = event.get("data", {})
            accepted = d.get("accepted", False)
            fit = 0.5 + (0.05 if accepted else -0.05)
            self._fitness_log.append((max(0.05, fit), time.time(), "capability"))
        except Exception as e:
            logger.warning("AutonomicRegulator._on_capability: %s", e)
```

- [ ] **Step 5: 运行测试确认通过**
Run: `cd /e/Prometheus-Ultra-MultiTypeKB && .venv/Scripts/python.exe -m pytest tests/test_nervous_system_multitype.py -v`
Expected: PASS（全文件）

- [ ] **Step 6: Commit**
```bash
cd /e/Prometheus-Ultra-MultiTypeKB && git add src/prometheus_nexus/integration/host_agent.py src/prometheus_nexus/lifecycle/autonomic_regulator.py tests/test_nervous_system_multitype.py && git commit -m "feat(D1): capability consumption flows back to nervous system"
```

---

## 收尾验证（所有 Task 完成后）

- [ ] **全量测试**：`cd /e/Prometheus-Ultra-MultiTypeKB && .venv/Scripts/python.exe -m pytest tests/ -q` 0 failed
- [ ] **实跑验证神经系统接住反刍**：手动 `omega.knowledge_rumination.ruminate(force=True)` 后查 `omega.telemetry.query("rumination")` 非空、`omega.autonomic_regulator.get_stats()` 含 rumination 记录
- [ ] **监控脚本不改**（A/B/C/D 是内部神经系统，不影响 ultra_monitor_2h.py；但 B1 后 fitness 值会变，报告"进化引擎"区若展示 fitness 需注意口径一致）
- [ ] **推送**：`git push` (经 127.0.0.1:7890 代理) 到 origin/main

## 风险与回滚

- B1 改 `_compute_fitness` 影响 AR 全部决策与进化引擎目标函数——若全量测试出现"进化停滞/误熔断"，回滚 Task 3 即可（其余 A/C/D 独立）。
- 所有 publish 均 try/except 包裹，NullHost 下不抛异常，独立运行模式不受影响。
- 无 API 破坏性变更；dashboard summary 字段未改。
