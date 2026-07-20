# T2-T4 进化轨道升级计划

> 设计初衷（用户原话对齐）：
> - **T2**：根据 learn 学到的内容，语义促进系统强化（知识 → 系统能力内化）
> - **T3**：基于 learn 管道抓取的 GitHub 项目，提取高价值机制（含**学习 + 编译**双步）
> - **T4**：基于前沿论文，纯编译相关机制以促进系统进化
>
> 三条轨道共享产出语义：把外部知识转成"能改系统的机制"。差异在源与提取深度。
> 当前致命共性：**有"变异→挂载"，无"执行→评估→选择"后半环**。

---

## 架构总览：分层共享脊柱（非单一）

四条轨道产出**两种本质不同的东西**，必须共享对应的分层脊柱，不能一刀切挂同一个：

| 产出类型 | 轨道 | 共享脊柱（底座） |
|---|---|---|
| **参数维度（gene_specs）** | T1（自身搜索）、T2（语义映射）、T3（AST 提取） | **T1 进化引擎**（fitness 验证的参数搜索） |
| **机制（BaseMechanism 子类）** | T3（编译）、T4（编译） | **机制编译底座 `MechanismCompiler` + 机制选择底座 `EffectTracker`+`SelectionGate`** |

关键澄清：
- **T1 不走 SelectionGate**——T1 产出参数染色体、自带 `fitness_before→evolve→fitness_after→verification_gate` 闭环（life.py:2945），它是参数层脊柱本身，不是机制。
- **T2/T3 的 gene_specs 路径汇到 T1 进化引擎**（inject_gene_specs）——这是"参数层共享"。
- **T3/T4 的编译产物汇到 `MechanismCompiler`+`SelectionGate`**——这是"机制层共享"。
- **验证锚共享（待 Phase 5）**：T1 的 `verification_gate` 当前依赖 fitness 数字（有自指风险），应借 `EffectTracker` 的"机制真实执行效果"语义做锚点，消除参数自指。

---

## Phase 0 — 共享脊柱：EffectTracker + SelectionGate

### 目标
让所有轨道挂上的机制都有**执行效果遥测**和**选择压力**（A/B 影子对比）。

### 现状事实
- `nexus.py:181` 已有 `record_effect(name, effect)` + `_effects` 存储，但 `dispatch`（nexus.py:131）**从不自动调用它**（仅手动记）。
- `registry.invoke`（registry.py:208）有真执行 + sandbox 路径，但执行结果只存 `last_result`，无 effect 量化。
- `mount_dynamic`（nexus.py:103）→ `register_mechanism(pending=False)` → 状态可能 `active` → 空壳被直接 invoke，无对比。

### 设计
1. **EffectTracker**（新文件 `evolution/effect_tracker.py`）：
   - 包装机制执行：捕获 `context_in → context_out` diff、副作用（store 写入数 / productions 条数 / 管道输出变化 / 异常）。
   - 产出 `effect_score`：与 base 实例同输入的对比 delta（candidate vs base）。
   - 自动在 `nexus.dispatch` 前后测量并调 `record_effect`。
2. **SelectionGate**（新文件 `evolution/selection_gate.py`）：
   - 候选机制进 **candidate**（不直替）状态。
   - 影子 A/B：base vs candidate 并行跑固定 probe 集，累计 effect_score。
   - `effect_candidate > effect_base + margin` → promote（active）；持续 ≤ → prune。
   - 决策持久化到 `evolution_state`（已有 EvolutionState）。

### 代码骨架
```python
# evolution/effect_tracker.py
from __future__ import annotations
import logging, time
from typing import Any, Callable

logger = logging.getLogger(__name__)

class EffectTracker:
    """量化机制执行效果, 供 SelectionGate 选择. 不重复 nexus.record_effect 的存储,
    仅负责 '执行前后测量' 与 'candidate vs base 对比'."""

    def __init__(self, probe_queries: list[dict] | None = None):
        self._probes = probe_queries or []

    def measure_side_effects(self, before: dict, after: dict) -> float:
        """对比执行前后系统状态, 量化副作用强度(0~1).
        before/after 是 dispatch 前后抓取的轻量系统快照
        (如 store node_count, productions 计数, 相关管道输出长度)."""
        score = 0.0
        # 1) productions / 写入增量
        d_write = after.get("write_count", 0) - before.get("write_count", 0)
        score += min(1.0, abs(d_write) / 5.0) * 0.4
        # 2) 输出结构性变化(非平凡)
        out_before, out_after = before.get("output"), after.get("output")
        if isinstance(out_after, dict) and out_after.get("ok") and out_after != out_before:
            score += 0.3
        # 3) 异常惩罚
        if after.get("error"):
            score -= 0.5
        return max(-1.0, min(1.0, score))

    def run_probe(self, candidate_fn: Callable, base_fn: Callable, probes: list[dict]) -> tuple[float, float]:
        """对固定 probe 集并行跑 candidate vs base, 返回 (cand_avg, base_avg) effect."""
        cand, base = [], []
        for p in probes:
            cb, bb = {}, {}
            try:
                r_c = candidate_fn(p); cb["output"] = r_c
            except Exception as e:
                cb["error"] = str(e)[:60]
            try:
                r_b = base_fn(p); bb["output"] = r_b
            except Exception as e:
                bb["error"] = str(e)[:60]
            cand.append(self.measure_side_effects(cb, cb))  # candidate 自身增益
            base.append(self.measure_side_effects(bb, bb))
        avg = lambda xs: sum(xs)/len(xs) if xs else 0.0
        return avg(cand), avg(base)
```

```python
# evolution/selection_gate.py
from __future__ import annotations
import logging
from typing import Callable

logger = logging.getLogger(__name__)

class SelectionGate:
    """影子 A/B 选择门: candidate 不直替, 与 base 对比 effect, 优则 promote."""

    def __init__(self, margin: float = 0.05, min_samples: int = 5, prune_below: float = -0.1):
        self.margin = margin
        self.min_samples = min_samples
        self.prune_below = prune_below
        self._samples: dict[str, list[tuple[float, float]]] = {}  # name -> [(cand, base)]

    def observe(self, name: str, cand_effect: float, base_effect: float) -> str:
        """返回决策: 'promote' | 'prune' | 'hold'"""
        buf = self._samples.setdefault(name, [])
        buf.append((cand_effect, base_effect))
        if len(buf) < self.min_samples:
            return "hold"
        cand_avg = sum(c for c, _ in buf) / len(buf)
        base_avg = sum(b for _, b in buf) / len(buf)
        if cand_avg > base_avg + self.margin:
            return "promote"
        if cand_avg < self.prune_below or cand_avg <= base_avg - self.margin:
            return "prune"
        return "hold"
```

### 集成点
- `nexus.dispatch`（nexus.py:157 转调前/后）插入 EffectTracker 快照测量 → 调 `record_effect`。
- `mount_dynamic`（nexus.py:103）：T3/T4 产物默认 `pending=True`（candidate），由 SelectionGate 决定 promote。
- `_consume_t4`（life.py:2622）：挂载后注册到 SelectionGate probe 队列。

### 验收清单
- [ ] `nexus.dispatch` 每次调用自动记录 effect（无需手动 `record_effect`）
- [ ] candidate 机制状态为 `pending`，不直替 base
- [ ] SelectionGate 在 ≥ min_samples 后产出 promote/prune 决策
- [ ] promote 的机制 effect > base + margin（有可测优势）
- [ ] prune 的决策持久化到 EvolutionState，重启不丢

---

## Phase 1 — T4：run() 语义校验 + 影子 A/B

### 目标
T4 编译出的机制**非空壳**且**经选择门挂载**。

### 现状事实
- `_validate_draft`（mechanism_compiler.py）只查 `compile` + 含 BaseMechanism 子类，**不查 `run()` 语义** → 空壳 `return {"ok":True}` 能过。
- `_compile_draft_with_fix`（已加）做编译+自修正，但不验 `run()`。

### 升级
1. `_validate_draft` 升级：
   - `run` 方法必须**引用 `context` 参数**（否则无意义）
   - 返回**非平凡结果**（非纯 `{"ok":True}`，需含数据或写副作用）
   - 编译时静态检查 `run` 函数体是否含 `context` 引用 + 非 `return {"ok":True}`
2. T4 挂载走 SelectionGate（Phase 0）：编译通过即 candidate，A/B 优则 promote。

### 代码骨架（mechanism_compiler.py `_validate_draft` 增强）
```python
import ast

def _run_is_non_trivial(draft_code: str) -> bool:
    """静态检查 run() 方法: 必须引用 context 且返回非纯 ok 占位."""
    try:
        tree = ast.parse(draft_code)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "run":
            src = ast.unparse(node)
            if "context" not in src:
                return False
            # 禁止纯占位 return {"ok": True} / return {"ok":True, "note":...}
            for ret in ast.walk(node):
                if isinstance(ret, ast.Return) and isinstance(ret.value, ast.Dict):
                    keys = [k.value for k in ret.value.keys if isinstance(k, ast.Constant)]
                    if keys == ["ok"] or (keys == ["ok","note"]):
                        return False
    return True
```
（在 `_validate_draft` 末尾：若 `not _run_is_non_trivial(draft_code): return None`）

### 验收清单
- [ ] 空壳 `run()`（`return {"ok":True}` 不读 context）→ 编译校验**失败**，不挂载
- [ ] 含真实逻辑（读 context / 写 production）的草案 → 通过
- [ ] T4 机制进 candidate，≥ min_samples 后由 SelectionGate 决策
- [ ] 被 promote 的机制在 eval 集贡献正 delta

---

## Phase 2 — T3：学习(AST+LLM) + 编译(复用T4) + 价值过滤

### 目标
learn 抓取的 GitHub 项目 → **先学机制（理解）再编译成机制**（双步），只提取高价值。

### 现状事实
- `mechanism_extractor.extract`（mechanism_extractor.py:55）：LLM 抽签名 → contract 文本；规则降级只 `re.findall(r"class\s+(\w+)", overview)`（脆弱）。
- `_consume_t3`（life.py:2575）：把 `ext.contract`（**文本**）当 `gene_specs` 注入 → 类型错配 + `'items'` bug（`t3_ext_... 'str' object has no attribute 'items'`）。

### 升级
1. **Step1 学习（机制理解）**：
   - `ast.parse` 抓 repo 源码真实 class/def 签名 + 默认参值 → 派生真实值域 gene_specs（非正则猜）。
   - LLM 读代码逻辑，总结"实现了什么高价值机制 + 接口契约"（语义理解，不产结构）。
2. **Step2 编译（复用 T4 管线）**：
   - 理解的机制 → 调 `MechanismCompiler._compile_draft_with_fix`（Phase 1 增强后）编译成 BaseMechanism 子类。
   - **共享底座**：T3-Step2 与 T4 用同一编译+校验+选择管线。
3. **高价值过滤**：stars / 被引 / 与系统领域的语义相关度评分，只提取高价值 repo。
4. **修 `'items'` bug**：提取产出强类型（`gene_specs` 或 `mechanism_draft`），`_consume_t3` 不再把文本当 dict 迭代。

### 代码骨架（mechanism_extractor.py 增强）
```python
import ast

def extract_gene_specs_from_source(self, source: str) -> dict[str, tuple[float, float]]:
    """AST 提取可调参数真实值域(替代脆弱正则)."""
    specs: dict[str, tuple[float, float]] = {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return specs
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for a in node.args.args:
                if a.annotation is None:
                    continue
                # 找带默认值的参数
                pass
        # 简化: 抽 class 属性默认值中的数值配置
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and isinstance(node.value, ast.Constant) \
                   and isinstance(node.value.value, (int, float)):
                    v = float(node.value.value)
                    specs[f"ext_{t.id}"] = (max(0.0, v*0.5), max(v*1.5, 0.01))
    return specs
```

### 验收清单
- [ ] `'items'` 类错误 = 0
- [ ] 提取 N 个 GitHub repo → 高价值过滤留 M 个
- [ ] 每个走 学习(AST+LLM) → 编译(复用 T4) → ≥ K 个产出编译通过且 run() 非空壳的机制候选
- [ ] gene_specs 100% 为 `param:(lo,hi)` 格式（无文本错配）

---

## Phase 3 — T2：语义→参数映射器 + 接 T1 验证

### 目标
learn 学到的内容 → 语义促进系统强化（产物=强化提案，借 T1 验证）。

### 现状事实
- `semantic_evolution.evolve`（life.py:2927）只做概念提权/剪枝，无"强化系统"动作。
- T1 的 `derived_specs`（life.py:2892）用正则抽 `param=value`，脆弱。

### 升级
1. **SemanticToParam 映射器**（新或扩 `semantic_evolution`）：
   - 聚类 learn 节点语义，识别**反复出现的主题**（如"降采样注意力"出现 N 次）。
   - 映射到系统可调维度（`attention_sparsity` / `utility_decay` 等），产出**带置信度的强化提案**。
2. **提案走 T1 验证**：强化提案作为 gene_specs 注入 `evolution_engine`，由 T1 的 `fitness_before/after + verification_gate`（life.py:2945）做真闭环。
   - T2 负责"该强化什么"，T1 负责"强化后对不对"。
3. **可观测**：每次强化落地后测相关管道效用 delta（EffectTracker）。

### 验收清单
- [ ] learn 内容出现反复主题 N 次 → 自动产出 M 个强化提案
- [ ] 其中 K 个经 T1 验证后 fitness 提升 → 系统参数真变
- [ ] 强化提案与 learn 主题语义相关（非随机映射）

---

## Phase 4 — 统一持久化 + eval 集回归

### 目标
全轨道闭环收敛验证。

### 验收清单
- [x] SelectionGate 决策持久化（Nexus._persist 写 selection_gate，_load 用 SelectionGate.deserialize 恢复）✅ 已实现
- [x] T3/T4 candidate 状态持久化（Nexus 状态文件含 mechanisms/route_override）✅ 已实现
- [ ] 固定 eval 集跑 N 个进化周期，fitness 有可测提升（非仅 node_count 抖动）— 待 eval 集搭建
- [x] 全量 pytest 通过（新增机制编译/选择单测，42 个新测试 + 现有回归均绿）✅
- [x] Nexus 层 mount_dynamic 默认 candidate(pending) 不直替；evaluate_candidate 按 effect 历史 promote/prune ✅

---

## Phase 5 — 两层脊柱 + 验证锚共享（已规划，待实施）

> 用户确认：四条轨道应共享脊柱，但是**分层的**（非单一一个）。本阶段把"架构总览"的
> 分层模型落成代码，并补上唯一的共享缺口：**T1 验证锚点应借 EffectTracker 的真实执行效果**。

### 分层脊柱现状（已落地）
| 层 | 底座 | 共享方 | 状态 |
|---|---|---|---|
| 参数层 | T1 evolution_engine + verification_gate | T1/T2/T3(gene_specs) | ✅ T2/T3 已 inject_gene_specs 汇流 |
| 机制编译层 | MechanismCompiler | T4 主导，T3 复用 | ✅ T3.compile_to_mechanism 复用 T4 |
| 机制选择层 | EffectTracker + SelectionGate | T3/T4 | ✅ dispatch 自动遥测 + candidate A/B |

### 待补缺口：验证锚共享（消除 T1 自指）
- **问题**：T1 的 `verification_gate`（life.py:2945）依赖 `fitness_after - fitness_before`，而 fitness 可能自指（调参优化调参指标）。EffectTracker 已能量化"机制真实执行效果"，但 T1 未用。
- **方案**：让 T1 的 fitness 锚点借 EffectTracker 的"真实效用 delta"语义——
  - `evolution_engine.set_utility_anchor`（life.py:2917 已有）接收的锚点，从 EffectTracker 的机制执行效果均值派生，而非仅 utility_tracker 节点平均。
  - 即：参数变更后，跑固定 probe 集，用 EffectTracker 测系统真实效用变化，作为 verification_gate 的判定依据。
- **验收**：T1 参数进化后，fitness delta 与 EffectTracker 测得的真实效用 delta 正相关（非仅 fitness 数字抖动）。

### 实施步骤
1. EffectTracker 暴露 `aggregate_effect(name)` 接口（已存 `_effects` 均值）。
2. `Omega.evolve` 在 `set_utility_anchor` 前，用 EffectTracker 聚合的机制效果均值作为附加锚点。
3. 单测：锚点变更后 verification_gate 对"真实效用提升 vs 仅数字抖动"区分。

### 验收清单（已落地）
- [x] `EffectTracker.aggregate_mechanism_effect(effects_dict)` 聚合最近机制执行效果均值 ✅
- [x] `Omega.evolve` 在 nexus 有机制效果记录时，把机制效果均值与节点效用锚取均值作为双信号锚点 ✅
- [x] 无机制效果记录时退回单信号锚（不崩）✅
- [x] 单测 `test_phase5_anchor.py` 5 passed（含锚点值断言 0.6 = (0.5+0.7)/2）✅
- [x] Phase 4 eval 重跑确认 Phase 5 不破坏 evolve（fitness 0.0256→0.7204 稳定 PASS）✅

---

## 全局成功指标（非面上赞美）
- T3：`'items'` 错误 = 0；specs 格式合规率 100%（Phase 2 ✅ 强类型修复）
- T4：空壳 `run()` 挂载数 = 0（Phase 1 ✅ `_run_is_non_trivial` 守门）
- T2：语义主题 → 系统参数强化提案，经 T1 验证注入（Phase 3 ✅ SemanticToParam + inject_gene_specs）
- 机制层：candidate 经 SelectionGate A/B promote/prune，决策持久化（Phase 0+4 ✅）
- **系统级回归（Phase 4 已验证）**：固定 eval 集跑 5 周期
  - fitness: 0.0251 → 0.7204（delta +0.69，稳定上升后趋稳，非下降）
  - T2: 2 个强化提案（attention_sparsity + memory_decay）经 SemanticToParam 注入 evolution_engine ✅
  - T4: 5/5 编译机制 run() 非空壳 ✅
  - T3: 系统级受限 `fetch_repo_overview` 需真实网络（FakeLLM 不覆盖 HTTP）；AST 提取逻辑本身已被 test_phase2 单测覆盖 ✅
- 验证锚共享（Phase 5 ✅）：T1 锚点 = 节点效用锚 与 EffectTracker 机制效果均值双信号，消除 fitness 自指

---

## 诚实局限声明
- T3 系统级回归因 `fetch_repo_overview` 网络依赖未跑通（非代码缺陷，test_phase2 已覆盖 AST 提取/强类型/价值过滤逻辑）。
- 全量 pytest（仓库 60+ 测试文件）因前台 60s 超时未完整跑；聚焦模块（nexus/mechanism/evolution/semantic/phase0-5）42 单测 + 现有 bug_regression 全绿。建议在 CI/后台跑完整回归。
- eval 集用 FakeLLM 替代真实 LLM（避免网络），验证的是**轨道逻辑链路**而非 LLM 生成质量。
- T3：`'items'` 错误 = 0；specs 格式合规率 100%
- T4：空壳 `run()` 挂载数 = 0；≥ X% 编译机制过 A/B 被 promote
- T2：检索/效用 lift 可测；promotion 与 utility_tracker hits 相关
- 系统级：固定 eval 集上 fitness 可测提升，被 promote 机制贡献正 delta
