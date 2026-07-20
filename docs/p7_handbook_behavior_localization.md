# P7: Harness Handbook 行为定位层 (Behavior Localization)

> 源自论文 **Harness Handbook: Making Evolving Agent Harnesses Readable, Navigable, and Editable**
> (arXiv:2607.13285, Tencent Hunyuan, 2026)
> 项目页: https://ruhan-wang.github.io/Harness-Handbook/
> 仓库: Ruhan-Wang/Harness-Handbook (注意: 仅为研究博客站, **无可用 import 库**, 方法需自实现)

## 1. 论文核心命题（代码级提炼）

论文唯一但锋利的论点:

> **Agent 的演进瓶颈不是"生成 edit", 而是"确定 edit 该落在哪" (behavior localization).**

证据链:
- 现代 agent 能力 = 基础模型 + **harness** (构建 prompt / 管理状态 / 调工具 / 协调执行)
- harness 必须随模型/API/环境/需求**持续修改**
- 但生产级 harness **庞大、紧耦合、行为分散**, 而修改请求描述"系统该做什么", 仓库按文件组织
  → **行为 ↔ 代码的映射需手工恢复** (核心瓶颈)
- 方案: **Harness Handbook** = 静态分析 + LLM 结构化, 自动合成"以行为为中心"的代码地图 (行为→源码)
- **BGPD (Behavior-Guided Progressive Disclosure)** = 从高层行为渐进披露到实现细节, 并**对照当前源码验证候选位置**
- 实验: Handbook-Assisted planning 改善行为定位 + 编辑计划质量, **用更少 planner token**; 在**分散站点/罕见路径/跨模块交互**上收益最大

## 2. ULTRA 现状缺口（为什么需要 P7）

ULTRA 四轨进化解决"**进化什么**" (T1 参数 / T2 语义 / T3 GitHub机制 / T4 论文机制),
但**没解决"进化落在哪"**:

| 组件 | 现状 | P7 命中的缺口 |
|---|---|---|
| T4 `mechanism_compiler.compile()` | 拉全文→LLM 编 draft→存 `archive/compiled/`→register(pending) | draft 是**孤立机制**, 无"该改 ULTRA 哪个函数/管道"的位置信息 |
| T4 激活 | `verify_and_activate()` 三关后 `status=active`, 不自动直替 | 即使激活, 机制**没绑定代码位置**, 无法指导"改哪里" |
| T2 `SemanticEvolutionEngine` | 产物是 `semantic_evolution` category registry 条目 | 同样**不绑定代码位置** |
| 反刍 rumination | 分类+打 rail 标签, 路由 T3/T4 | 只做"知识→轨道", **不做"机制→代码位置"路由** |

**P7 补的就是 behavior localization 层**: 把进化产物映射到具体代码行为位置。

## 3. 三方向实现（已落地）

### 方向3: 自映射 — `handbook.py` (新模块)
- `HarnessHandbook.build(src_root)`: 对 ULTRA `src/` 跑 `ast` 静态分析, 提取所有
  function/class/method 为 `BehaviorEntry` (行为语义来自 docstring + 函数名; 调用关系用于跨模块推断)
- 产物 = `behavior → source_location` 映射 (module / filepath / lineno / signature / docstring)
- 惰性单例 `get_handbook()`

### 方向1: 行为定位 — `locate_behavior(query, llm)`
- 给定机制描述 query, 返回最匹配代码位置 `LocationCandidate`
- LLM 可用: 把 handbook 摘要喂 LLM, 挑行为位置 (语义匹配)
- **LLM 不可用: 关键词/中文分词规则降级** (论文原方案无离线 fallback, 此处补上 — 避免静默失效)

### 方向2: BGPD 三级渐进 — `bgpd_locate(query, llm)`
- Level1 高层行为 → Level2 相关模块 → Level3 具体函数 + 对照当前源码验证
- 论文证明用更少 token 达到更好定位; 这里 LLM prompt 也改三级渐进 (L1_BEHAVIOR/L2_MODULE/L3_MECHANISM)

### T4 接线 (`mechanism_compiler.py`)
- `CompiledMechanism` 新增 `target_location` 字段 (dict: module/lineno/symbol/confidence/verified)
- `compile()` 编译出 draft 后调 `_locate_target()` → BGPD 定位 → 写入 draft 文件头注释 + registry data
- `register_from_node()` 的 `data` 透传 `target_location`
- **是"位置建议"而非自动直替** (对齐 P6 不自动直替原则, 交 A-B 验证/人工)

## 4. 实测验证

- `tests/test_p7_handbook.py`: 7 测试全过
  - 真实 src 建 handbook (>50 行为条目, 含 compile/evolve 等)
  - 临时源码树 AST 提取 (evolve/learn_external 命中)
  - 规则定位 (无 LLM, 中文分词匹配)
  - LLM 定位 (解析 MODULE|LINENO|SYMBOL|CONF|RATIONALE)
  - BGPD 三级定位 (Level3 已验证)
  - T4 compile 带 target_location (mock handbook)
  - handbook 空时优雅降级 (target_location={} 不崩)

## 5. 诚实风险（不忽悠）

1. **论文方法是通用方法论, 非现成包**. 项目仓库仅为博客站, 需自实现 (已完成 `handbook.py`).
2. **静态分析对动态语言有限**. "行为"是语义概念 (如"参数进化"跨 evolution_engine + life.evo()),
   需 LLM 辅助结构化 — 有不确定性; 规则降级仅关键词级.
3. **定位是"建议"非"保证"**. `target_location` 是候选, 仍需三关验证/人工确认才能落地 (对齐 P6).
4. **handbook 惰性构建会扫全 src** (首次 ~秒级). 生产环境可缓存 handbook.json 避免每次重建.

## 6. 后续 (可选 P8)
- handbook 序列化缓存 (`handbook.json`), 避免每次 AST 重建
- T2 语义进化也接 target_location (当前仅 T4)
- 激活闭环消费 target_location: 生成"进化补丁建议 diff" (不自动 apply, 交 A-B)
