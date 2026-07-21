# 架构升级：外部知识单一获取入口（learn 管道归一）

> 起因：用户质疑"按照架构设计，外部知识学习只应该在 learn 管道存在，为什么 T3/T4 也要去获取相关外部知识"。
> 经代码核查确认：**T3/T4 当前确实绕过 learn 自己重新打外部源**，且根因是 learn 只存了摘要/元数据，
> 下游编译/提取需要全文必须重拉。本方案治本：让 learn 成为唯一外部获取入口，T3/T4 纯消费 store。

---

## 一、现状事实核查（代码级，非印象）

### 1.1 learn 管道存进 store 节点的内容

`learn`（life.py:3252）调 `knowledge_scanner.scan()` 拿 ScanResult，第 3384 行 `remember(content=f"{r.title}: {r.content}", url=...)`。
`remember`（life.py:1352-1354）创建节点时 `raw_chunk=content`——即 raw_chunk 与 content 同值。

scanner 各源返回的 `content` 实际内容：

| 源 | scanner 返回 content | 是否全文 | 代码位置 |
|---|---|---|---|
| arxiv | `summary[:500]`（API 摘要截断 500 字） | ❌ 非全文 | scanner.py:230 |
| github | `Language: {lang}. Stars: {n}. Forks: {n}. {description}`（纯元数据） | ❌ 无 README/源码 | scanner.py:303 |
| wiki | snippet（搜索摘要） | ❌ | scanner.py:335 |
| web | snippet | ❌ | scanner.py:335 |
| rss | `summary[:500]` | ❌ | scanner.py:440 |
| academic | `(p.get("content") or "")[:500]` | ❌ | scanner.py:565 |

**结论：learn 只存了外部知识的"摘要/元数据片段"进 store，没有存全文/README/源码。**

### 1.2 T3/T4 的重复抓取点（违反单一入口原则）

**T4 `compile_from_node`**（mechanism_compiler.py:307-322）：
- 注释声称"消费 learn 已吸收的论文节点…**而非自己重新扫描 arxiv**。消除源重复"。
- **实现第 322 行 `return self.compile(arxiv_id, title)` → `compile` 第 66 行 `fulltext = fetch_arxiv_fulltext(arxiv_id)`** → 自己重新拉 arxiv 全文。
- **注释与实现矛盾**：说好不重拉，实际又拉了。

**T3 `extract_from_node`**（mechanism_extractor.py:111-130）：
- `extract_from_node` → `extract` → `fetch_repo_overview(repo)` + `fetch_repo_source(repo, files)` → 自己重新拉 GitHub README + 源码。
- learn 已抓 GitHub 项目进 store，T3 却绕过 store 直接打 GitHub API。

### 1.3 两层违规

1. **第一层（用户质疑的）**：T3/T4 绕过 learn 直接打外部源——违反"外部知识只经 learn 管道获取"。
2. **第二层（根因）**：learn 只存了摘要没存全文——T3/T4 要全文必须重拉。**第一层违规是第二层的被迫后果**。

learn 第 3324 行注释"供四轨下游消费, 不重拉源"是**设计意图，但实现没兑现**——因为 scanner 只存 500 字摘要，下游无法只凭摘要编译机制。

---

## 二、目标架构（单一获取入口）

```
        外部源(arxiv/github/wiki/web)
                    │
                    ▼  ★ 唯一的外部获取入口
            ┌───────────────┐
            │  learn 管道    │  scanner 扫描 + 高价值源拉全文/README/源码
            │  (life.learn)  │  存进 store 节点(content=摘要, raw_chunk=全文/README)
            └───────┬───────┘
                    │
                    ▼
            ┌───────────────┐
            │   store 节点   │  content=摘要(检索/展示) | raw_chunk=全文/README(供编译)
            │  (带 url +     │  url=源地址(溯源, 不再用于重拉)
            │   rail 标签)   │
            └───────┬───────┘
                    │ 纯消费(无外部 I/O)
        ┌───────────┼───────────┐
        ▼           ▼           ▼
    ┌───────┐   ┌───────┐   ┌───────┐
    │  T3   │   │  T4   │   │  T2   │
    │extract│   │compile│   │semantic│
    │从node │   │从node │   │从node │
    │content│   │raw_   │   │content│
    │/源码  │   │chunk  │   │/tags  │
    └───────┘   └───────┘   └───────┘
```

**核心原则**：
- learn 是唯一打外部源的地方（scanner 扫描 + 命中高价值源时拉全文/README/源码）。
- store 节点 content=摘要（供检索/展示/dopamine 评分），raw_chunk=全文/README/源码（供 T3/T4 编译/提取）。
- T3/T4 只从 store 节点取数据，**删掉自己的 fetch_arxiv_fulltext / fetch_repo_overview 调用**。
- url 字段保留作溯源（provenance），但不再用于重拉。

---

## 三、实施计划（分阶段，每阶段独立可验证）

### Phase A：ScanResult 增 fulltext 字段 + scanner 高价值源拉全文

**改动文件**：`learning/scanner.py`

1. `ScanResult` dataclass 新增 `fulltext: str = ""` 字段（全文/README/源码，默认空）。
2. `_scan_arxiv`：对每个命中的 entry，调 `fetch_arxiv_fulltext(arxiv_id)` 拉全文存入 `result.fulltext`（失败静默，fulltext 保持空，content 仍存摘要）。
   - 限制：单次 learn 最多拉 `min(max_results, 3)` 篇全文（避免 quota 爆炸/超时）。
3. `_scan_github`：对每个命中的 repo，调 `fetch_repo_overview(repo_full_name)` 拉 README + 文件树存入 `result.fulltext`（失败静默）。
   - 限制：最多拉 `min(max_results, 3)` 个 repo 的 README。
4. 其他源（wiki/web/rss/academic）：fulltext 留空（这些源 T2/T3/T4 不需要全文）。

**验收**：scanner 命中 arxiv/github 时 ScanResult.fulltext 非空且含全文/README；网络失败时 fulltext 空但 content 仍有摘要（降级不崩）。

### Phase B：learn 把 fulltext 存进节点 raw_chunk

**改动文件**：`life.py`（learn 方法）

1. learn 第 3384 行 `remember(content=..., url=...)` 之后，若 `getattr(r, "fulltext", "")` 非空，更新节点的 raw_chunk：
   ```python
   if getattr(r, "fulltext", ""):
       node = self.store.read_node(node_id)
       if node:
           node.raw_chunk = r.fulltext
           self.store.update_node(node)
   ```
2. 或更优：`remember` 增 `raw_chunk` 参数（默认空），learn 传入 `raw_chunk=getattr(r,"fulltext","")`，remember 创建节点时若 raw_chunk 非空则用它，否则用 content（保持原行为）。

**验收**：learn 命中 arxiv 后，store 节点的 raw_chunk 含论文全文（非 500 字摘要）；命中 github 后 raw_chunk 含 README+文件树。

### Phase C：T4 改为只从节点 raw_chunk 消费（删自己的 fetch）

**改动文件**：`mechanisms/mechanism_compiler.py`

1. `compile_from_node`：从 `node.raw_chunk`（全文）编译，**删掉第 322 行 `return self.compile(arxiv_id, title)`**（不再重新 fetch_arxiv_fulltext）。
2. `compile` 方法：新增 `compile_from_text(fulltext, title)` 内部方法，接收全文直接走 LLM 编译；`compile(arxiv_id)` 保留但标记为"独立扫描入口"（非 learn 链路用）。
3. `compile_from_node` 调 `compile_from_text(node.raw_chunk, node.content[:80])`；若 raw_chunk 空，降级用 content 摘要 + 记 warning（不再重拉）。

**验收**：T4 compile_from_node 不触发任何外部 HTTP；raw_chunk 非空时正常编译，raw_chunk 空时降级用摘要（不崩）。

### Phase D：T3 改为只从节点 raw_chunk 消费（删自己的 fetch）

**改动文件**：`mechanisms/mechanism_extractor.py`

1. `extract_from_node`：从 `node.raw_chunk`（README+源码概要）提取，**删掉第 113-127 行的 `fetch_repo_overview` / `fetch_repo_source` 调用**。
2. `extract` 拆分：新增 `extract_from_overview(overview_text, repo_full_name)` 内部方法，接收已有文本直接走 AST + LLM；`extract(repo)` 保留作独立扫描入口。
3. `extract_from_node` 调 `extract_from_overview(node.raw_chunk, repo)`；若 raw_chunk 空，降级用 content 元数据（不崩，不重拉）。
4. AST 提取的源码：若 learn 时 scanner 把源码也存进了 raw_chunk（Phase A 的 fetch_repo_source 结果），T3 直接 AST 解析 raw_chunk 中的 `# === {fn} ===` 段；否则 T3 无源码可 AST，降级为纯 LLM 提取（记 warning）。

**验收**：T3 extract_from_node 不触发任何外部 HTTP；raw_chunk 非空时正常 AST+LLM 提取，raw_chunk 空时降级（不崩）。

### Phase E：回归验证 + 清理

1. 重跑 Phase 4 eval harness：T3 系统级回归应能跑通（不再因网络依赖失败，因为从 store 节点取）。
2. 跑 test_phase1/2（T3/T4 单测）确认从节点消费不破坏逻辑。
3. 全量 pytest 聚焦模块回归。
4. doc 更新：标注 fetch_arxiv_fulltext/fetch_repo_overview 仅 learn 链路调用，T3/T4 不再直接调。

**验收**：T3 系统级 eval t3_specs > 0（不再因网络受限为 0）；T4 仍 5/5 非空壳；无新增回归。

---

## 四、取舍与风险

### 4.1 为什么不让 scanner 对所有源都拉全文
- arxiv/github 是 T3/T4 编译所需的高价值源，值得拉全文。
- wiki/web/rss 摘要已够 T2 语义分析，拉全文是 quota 浪费。
- 限制每次 learn 最多拉 3 篇/repo 全文，避免单次 learn 超时。

### 4.2 raw_chunk 已被 Verbatim Chunks 机制使用，冲突吗
- 不冲突。raw_chunk 当前 = content（remember 第 1354 行），本方案改为 = fulltext（高价值源）或 = content（其他源，保持原行为）。
- Verbatim Chunks 的检索逻辑（life.py:2426-2434）读 raw_chunk 作 chunk——全文存入后 chunk 更丰富，是增益非破坏。

### 4.3 网络失败时的降级策略
- scanner 拉 fulltext 失败 → fulltext 空 → learn 存节点 raw_chunk=content（摘要）→ T3/T4 降级用摘要编译/提取（质量降但不崩）。
- 不引入重试/阻塞——learn 是探索性管道，失败即跳过，下轮再来。

### 4.4 T3/T4 保留独立扫描入口吗
- 保留 `compile(arxiv_id)` / `extract(repo)` 作独立入口（非 learn 链路，如手动调试/一次性编译）。
- 但 learn 链路（`compile_from_node` / `extract_from_node`）严格只从 store 消费，不重拉。

---

## 五、验收清单（全局，已落地）

- [x] scanner ScanResult 增 fulltext 字段；arxiv/github 命中时 fulltext 含全文/README ✅
- [x] learn 把 fulltext 存进节点 raw_chunk（非仅 content 摘要）✅
- [x] T4 compile_from_node 从 node.raw_chunk 编译，无 fetch_arxiv_fulltext 调用 ✅
- [x] T3 extract_from_node 从 node.raw_chunk 提取，无 fetch_repo_overview 调用 ✅
- [x] T3/T4 raw_chunk 空时降级用 content 摘要（不崩，不重拉）✅
- [x] Phase 4 eval 重跑：T3 t3_specs = 4（系统级跑通，不再因网络受限为 0）✅
- [x] 现有 test_phase1/2 单测仍全绿（47 passed 含 bug_regression）✅
- [x] fetch_arxiv_fulltext / fetch_repo_overview 仅被 learn 链路(scanner) + 独立入口调用（grep 确认 T3/T4 from_node 路径无直接引用）✅

### Phase 4 eval 最终结果（三轨全跑通）
- fitness: 0.0306 → 0.7233（delta +0.69，稳定上升后趋稳）
- T2: 2 个强化提案（attention_sparsity + memory_decay）✅
- T3: 4 个 AST gene_specs（从 store 节点 raw_chunk 消费，不再打外部源）✅
- T4: 5/5 编译机制 run() 非空壳 ✅

---

## 六、与既有升级的关系

本方案是 T2-T4 升级（见 `T2_T4_EVOLUTION_UPGRADE.md`）的**架构纠偏前置项**：
- T2-T4 升级解决了"轨道后半环（执行->评估->选择）"缺失。
- 本方案解决"轨道前半环（外部知识获取）"的单一入口违规。
- 两者正交：本方案改 learn/T3/T4 的数据来源，不改进化/选择逻辑。
- 建议本方案优先合入，再做 T2-T4 的 Phase 5（验证锚共享已落地，无依赖冲突）。
