# Cross-Pipeline Data Flow Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** 让 evolve/dream/maintain 三个管道读取链上下文（chain context），不再闭门造车。上游的 score/fitness/patterns 数据要传递到下游管道内部。

**Architecture:** 在 life.py 的 evolve()/dream_cycle()/maintain() 开头分别调用 `self.signal_fusion.get_chain_context()`，将上游信号注入到管道内部逻辑中。

**Tech Stack:** Python 3.11, Prometheus Ultra

## Global Constraints

- 只修改 life.py，不修改 CNSOrchestrator 或 CerebralCortex
- 保持所有现有功能不变
- 链上下文读取失败时静默 fallback（现有 try/except 模式）
- 每个改动不超过 15 行

---

### Task 1: evolve() 读取链上下文注入 score/drift

**Files:**
- Modify: `life.py:1031-1036`

**Interfaces:**
- Consumes: `self.signal_fusion.get_chain_context()` → `{"trigger_pipe": "reflect", "trigger_signals": {"raw_score": float, "raw_drift": int}}`
- Produces: evolve 的 brainstorm 和 PlanWriter 接收 enriched context 字符串

- [ ] **Step 1: 在 evolve() 开头添加链上下文读取**

在 evolve() 的 `brainstorm_result = self.brainstorming.brainstorm(...)` 之前，添加链上下文读取：

```python
# 链上下文：读取触发管的信号
try:
    ctx = self.signal_fusion.get_chain_context()
    if ctx:
        trigger_pipe = ctx.get("trigger_pipe", "")
        sigs = ctx.get("trigger_signals", {})
        if trigger_pipe == "reflect":
            raw_score = sigs.get("raw_score", 0.5)
            raw_drift = sigs.get("raw_drift", 0)
            context += f" | Triggered by reflect: score={raw_score:.3f}, drift={raw_drift}"
            self.cerebral_cortex.add_merge_reason(
                "evolve", f"reflect_driven:score={raw_score:.3f}")
except Exception:
    pass
```

插入位置：第 1035 行（`brainstorm_result = ...`）之前。

- [ ] **Step 2: 验证 syntax**

Run: `python -c "import ast; ast.parse(open('E:/Prometheus-Ultra/src/prometheus_nexus/life.py').read()); print('OK')"`
Expected: OK

---

### Task 2: dream_cycle() 读取链上下文注入触发源信息

**Files:**
- Modify: `life.py:1877-1883`

**Interfaces:**
- Consumes: `self.signal_fusion.get_chain_context()`
- Produces: dream_data 中包含上游信息

- [ ] **Step 1: 在 dream_cycle() 开头添加链上下文读取**

在 `dream_result = self.dream.run_cycle(branch=branch)` 之前，添加链上下文读取：

```python
# 链上下文：读取触发管的信号
try:
    ctx = self.signal_fusion.get_chain_context()
    if ctx:
        trigger_pipe = ctx.get("trigger_pipe", "")
        sigs = ctx.get("trigger_signals", {})
        dream_data["trigger_pipe"] = trigger_pipe
        if trigger_pipe == "reflect":
            raw_score = sigs.get("raw_score", 0.5)
            dream_data["trigger_score"] = raw_score
            logger.info("Dream triggered by reflect (score=%.3f)", raw_score)
        elif trigger_pipe == "evolve":
            raw_delta = sigs.get("raw_delta", 0)
            dream_data["evolve_delta"] = raw_delta
            logger.info("Dream triggered by evolve (delta=%.4f)", raw_delta)
except Exception:
    pass
```

插入位置：第 1882-1886 行之间（`dream_data = {}` 之后，`dream_result = self.dream.run_cycle(...)` 之前）。

- [ ] **Step 2: 验证 syntax**

Run: `python -c "import ast; ast.parse(open('E:/Prometheus-Ultra/src/prometheus_nexus/life.py').read()); print('OK')"`
Expected: OK

---

### Task 3: maintain() 读取链上下文注入 dream patterns

**Files:**
- Modify: `life.py:1984-1990`

**Interfaces:**
- Consumes: `self.signal_fusion.get_chain_context()`
- Produces: maintain_data 中包含上游 patterns 信息

- [ ] **Step 1: 在 maintain() 开头添加链上下文读取**

在 maintain() 的 `self.bank.run_migration()` 之前，添加链上下文读取：

```python
# 链上下文：读取触发管的信号
try:
    ctx = self.signal_fusion.get_chain_context()
    if ctx:
        trigger_pipe = ctx.get("trigger_pipe", "")
        sigs = ctx.get("trigger_signals", {})
        maintain_data["trigger_pipe"] = trigger_pipe
        if trigger_pipe == "dream":
            patterns = sigs.get("patterns_found", 0)
            maintain_data["upstream_patterns"] = patterns
            logger.info("Maintain triggered by dream (%d patterns)", patterns)
except Exception:
    pass
```

插入位置：第 1986 行（`maintain_data = {}` 之后，`self.bank.run_migration()` 之前）。

- [ ] **Step 2: 验证 syntax**

Run: `python -c "import ast; ast.parse(open('E:/Prometheus-Ultra/src/prometheus_nexus/life.py').read()); print('OK')"`
Expected: OK

---

### Task 4: CNS evolve→dream 传递 raw_delta（修补 set_chain_context 缺失的字段）

**Files:**
- Modify: `cns_orchestrator.py:364-370`（evolve→dream 的 set_chain_context 调用）

**Interfaces:**
- Consumes: `evolve` 事件的 fitness_before/fitness_after
- Produces: 链上下文包含 `raw_delta` 字段供 dream 读取

- [ ] **Step 1: 在 evolve 的 dream 触发处添加 `raw_delta`**

cns_orchestrator.py:368 行的 `sigs["raw_after"] = after` 之后添加：

```python
                    sigs["raw_delta"] = delta
```

- [ ] **Step 2: 验证 syntax**

Run: `python -c "import ast; ast.parse(open('E:/Prometheus-Ultra/src/prometheus_nexus/lifecycle/cns_orchestrator.py').read()); print('OK')"
Expected: OK

---

### Task 5: 验证服务器重启和 7 管道

- [ ] **Step 1: 杀掉旧进程重启**

```bash
kill $(lsof -ti:9200) 2>/dev/null; sleep 1
cd /e/Prometheus-Ultra && PYTHONPATH=E:/Prometheus-Ultra/src python -m prometheus_nexus.services.api_server --port 9200 &
sleep 3
```

- [ ] **Step 2: 测试所有 7 管道**

```bash
# learn
curl -s -X POST http://localhost:9200/learn -H 'Content-Type: application/json' -d '{"source":"web","query":"test","max_results":1}' | head -c 200
# recall
curl -s -X POST http://localhost:9200/recall -H 'Content-Type: application/json' -d '{"query":"test","limit":3}' | head -c 200
# evolve
curl -s -X POST http://localhost:9200/evolve -H 'Content-Type: application/json' -d '{"context":"test"}' | head -c 200
# reflect
curl -s -X POST http://localhost:9200/reflect -H 'Content-Type: application/json' -d '{}' | head -c 200
# dream
curl -s -X POST http://localhost:9200/dream -H 'Content-Type: application/json' -d '{}' | head -c 200
# maintain
curl -s -X POST http://localhost:9200/maintain -H 'Content-Type: application/json' -d '{}' | head -c 200
```

Expected: 所有管道返回包含 `success: true` 或类似成功信号。

- [ ] **Step 3: 检查日志确认链上下文被读取**

启动时观察日志中是否出现 "Dream triggered by", "Maintain triggered by" 等新日志行。
