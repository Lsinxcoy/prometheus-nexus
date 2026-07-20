# 实现计划：借鉴 Agentic Proposing + SEED 强化 ULTRA 的技能合成与自进化

分支：`feat/nexus-cns` ｜ 基于：监控改造完成后的状态（commit `1d883d5`）
论文：
- P1 Agentic Proposing (arxiv 2602.03279) — 组合式技能合成 + 多粒度策略优化
- P2 SEED (arxiv 2607.14777) — 后见之明技能蒸馏（on-policy 轨迹 → hindsight skills → 稠密自监督信号）

## 0. 现状事实（已读真实代码，非推测）

| 现有符号 | 位置 | 现状 |
|---------|------|------|
| `SkillClaw` | `src/prometheus_nexus/skills/skill_claw.py` | 技能仅 `name/description/tags/score` 元数据，无可执行体、无组合 DAG |
| `Playbook` / `PlaybookStep` | `src/prometheus_nexus/evolution/playbook_inheritance.py:19,31` | `PlaybookStep(step_id,name,operation,params,depends_on,condition,default_timeout)` 结构完整，但 `learn` 在 `life.py:3536` 注册的 playbook **只有 name/desc/tags，无 steps（空壳）** |
| `Omega._compute_fitness()` | `life.py:927,933,2697` 等 | 结果级 fitness，进化用 `fitness_before/after`（稀疏，无决策级信号） |
| `Omega.llm` | `life.py:673` LLMBridge | 可用 LLM 接口，提炼技能时调用 |
| `Omega.event_bus.get_recent(limit)` | `event_bus.py:260` | 已有轨迹日志，未被提炼成技能 |
| `self_observation` / `diagnostics` | learn/evolve 内 | 每次管道跑完有结构化诊断，未被提炼 |
| `Omega.cot` | `life.py:494` CoTPrompter | 可复用做 Proposer 的推理 |

**核心缺口**：轨迹日志存在，但从不被提炼成"带内容的技能/playbook"；进化只有结果级 fitness，无稠密自监督。

## 1. 目标与约束

- **零机制损失**：不改动现有 7 管道 / Nexus CNS / 消费层，只新增"提炼层" + 给进化目标加一项。
- **真实数据驱动**：所有技能提炼来自真实运行轨迹，不伪造。
- **渐进交付**：先 B（后见蒸馏，低成本高收益），再 A（组合引擎），最后 C（闭环）。

---

## 2. Phase B（先做，最高杠杆）：后见之明技能蒸馏

### B1. 新增模块 `src/prometheus_nexus/evolution/hindsight_skill.py`
职责：从一次管道运行的轨迹提炼 3 类 hindsight 技能，并写成真实 `PlaybookStep`。

```python
class HindsightSkillMiner:
    def __init__(self, omega: "Omega"): ...
    def mine(self, pipeline: str, trajectory: dict) -> list[HindsightSkill]:
        """trajectory = {events, diagnostics, self_observation, outcome, errors}"""
    def _to_playbook_steps(self, skills: list[HindsightSkill]) -> list[PlaybookStep]:
        """3 类技能映射为 PlaybookStep:
           - workflow   -> operation='workflow', params={'steps':[...]}
           - observation-> operation='observe', params={'signal':..., 'action':...}
           - avoid      -> operation='avoid',  params={'trigger':..., 'instead':...}
        """
    def register(self, pipeline: str, steps: list[PlaybookStep]):
        """写真实 steps 进 PlaybookInheritance（修空壳 bug）"""
```

**提炼规则（确定性 + LLM 辅助，二选一或混合）**：
- 确定性提取（必做，零成本）：从 `trajectory['errors']` + `Omega._issues` 提取 **avoid 类**（如 "T4 compile 返回 None → 记 issue 不挂"）；从 `diagnostics` 里的重复模式提取 **observation 类**（如 "consumption_rate<0.2 → prune 候选"）。
- LLM 提取（可选，用 `Omega.llm`）：把 `events`+`diagnostics` 喂给 prompt，要求输出 workflow/observation/avoid 三类自然语言技能。失败则降级到确定性提取。

### B2. 接入点：4 个管道末尾调用 miner
在 `learn` / `evolve` / `dream_cycle` / `reflect` 的 return 前（已有 `record_production` 处附近），加：
```python
self._hindsight_miner.mine(pipeline="learn", trajectory={...})
```
`trajectory` 组装：从 `event_bus.get_recent()` + 本管道 `diagnostics` + `Omega._issues`（近窗口）+ `outcome`。
- 改动文件：`life.py`（4 处小插入，每处 ≤5 行）
- 风险：低（try/except 包裹，失败只 warning）

### B3. 修 playbook 空壳 bug（B 的副作用）
`life.py:3536` 当前 `Playbook(name=..., description=..., tags=...)` 无 steps。改为：
```python
pb = Playbook(playbook_id=..., name=..., description=..., tags=[...])
for step in self._hindsight_miner.steps_for("rumination"):
    pb.steps.append(step)
self.playbook_inheritance.register_playbook(pb)
```

### B4. 稠密蒸馏信号并入进化目标（SEED 核心）
- 新增 `_distill_bonus(trajectory)`：对同一决策，在「普通上下文」vs「技能增强上下文（注入提炼出的 skills）」下用 `Omega.llm` 重打分，得 `Δ = log p(a|skill) − log p(a|base)`。
- 改 `evolve` 的 fitness 计算（`life.py:2697` 附近）：
  ```python
  fitness_before = self._compute_fitness()
  distill = self._distill_bonus(recent_trajectories)   # 新增
  fitness_before = fitness_before + ALPHA * distill      # 联合优化
  ```
- `ALPHA` 默认 0.1，可配。
- **降级**：若 `Omega.llm.available == False`（无 LLM 配置），`distill=0`，进化退化为原行为，不报错。

---

## 3. Phase A：技能组合引擎（借鉴 P1）

### A1. 给 `SkillClaw` 加技能体 + 组合 DAG
`skill_claw.py` 的 `register_skill` 增加：
```python
def register_skill(self, ..., body: str | None = None, composes: list[str] | None = None):
    # body: prompt 模板或可调用步骤；composes: 依赖的子技能 id 列表
```
- 新增 `compose(query) -> list[skill_id]`：按 query 选+排序子技能成 workflow（用 `Omega.cot` 做 Proposer 推理，或基于 tags/usage 的启发式）。

### A2. 新增 `Proposer` 角色
`src/prometheus_nexus/skills/proposer.py`：
```python
class Proposer:
    def propose(self, problem: str) -> ComposedWorkflow:
        # 1. 分解子目标  2. 从 SkillClaw 选技能  3. 组合成 DAG
        # 多粒度优化类比: 任务级(整体成功率) + 步骤级(单技能贡献) 用 utility_tracker 记录
```

### A3. 接入 learn 的 "知识缺口" 链路
`learn` 已有 `signal_fusion.get_chain_context()`（缺口检测）。把 Proposer 合成的 workflow 注入 learn 的查询计划（不替代现有扫描，只增强排序/路由）。

---

## 4. Phase C：闭环（B+A 的自然结果）
- B 提炼的 hindsight skills → `SkillClaw.register_skill(body=...)` → A 的 Proposer 组合进新任务 → 新轨迹再被 B 提炼。
- 这就是 SEED 的 "policy updates improve subsequent decision making and skill analysis together"。
- 无需单独写代码，是 B+A 接通后的涌现行为；验证即可。

---

## 5. 文件改动清单（预估）

| 文件 | 改动 | Phase |
|------|------|-------|
| `src/prometheus_nexus/evolution/hindsight_skill.py` | 新增（~180 行） | B |
| `src/prometheus_nexus/life.py` | 4 处 mine() 调用 + playbook 空壳修复 + fitness 加 distill | B |
| `src/prometheus_nexus/skills/skill_claw.py` | register_skill 加 body/composes + compose() | A |
| `src/prometheus_nexus/skills/proposer.py` | 新增（~120 行） | A |
| `scripts/ultra_monitor_fine.py` | 报告加【技能提炼】块（本周期提炼 N 条 hindsight skills） | B(可观测) |

---

## 6. 验证（每 Phase 独立）

**B 验证**：
1. 单元测试：`HindsightSkillMiner.mine(fake_trajectory)` → 断言产出 3 类 step 且 `Playbook.steps` 非空。
2. 集成：触发 learn（arxiv 拉论文走 T4）→ 查 `playbook_inheritance.get_playbook(...).steps` 应有内容（修空壳）。
3. 蒸馏：构造同一决策的 skill/base 上下文，`_distill_bonus` 返回 float ∈ [-1,1]，无 LLM 时返回 0。
4. 监控报告出现【技能提炼】块，计数真实。

**A 验证**：
1. 单测：`compose("拉论文并编译机制")` 返回含 learn/T4 依赖的 DAG。
2. Proposer 对已知问题输出 workflow，且子技能来自 SkillClaw 真实注册项。

**C 验证**：
1. 跑 2 轮 learn+evolve，断言第 2 轮提炼的 skills 能被 Proposer 命中（闭环成立）。

---

## 7. 风险与降级
- LLM 不可用 → B4 distill=0，B1 降级确定性提取，系统不退化为损坏。
- 提炼噪音 → 加去重（同 (type,signal) 聚合，参考监控去重逻辑）+ 最小置信阈值。
- 性能 → mine() 异步/低频（管道末尾调用，非热路径），不阻塞主流程。

## 8. 交付顺序建议
1. 先实现 **B1+B2+B3**（提炼 + 修空壳 + 接入 4 管道）→ 跑通验证
2. 再 **B4**（蒸馏信号并入 fitness）→ 验证进化目标变化
3. 然后 **A1+A2+A3**（组合引擎）
4. 最后 **C** 验证闭环
