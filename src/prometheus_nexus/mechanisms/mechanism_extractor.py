"""MechanismExtractor — T3 第三轨: 从成熟 GitHub 项目提取优势机制。

设计初衷(用户): 基于 learn 管道抓取的 GitHub 项目, 提取高价值机制(含学习 + 编译双步).

Phase 2 升级:
- Step1 学习: AST 解析 repo 源码真实参数/类(非脆弱正则), LLM 总结机制意图
- Step2 编译: 理解的机制 -> MechanismCompiler 编译成 BaseMechanism 子类(复用 T4 管线)
- 高价值过滤: 仅提取与系统相关/有可调参数的 repo
- 强类型产出: gene_specs (param:(lo,hi)) 或 mechanism_draft, 不再混文本

安全: 仅提取描述/契约/编译, 不执行外部代码; 激活由验证门 + S7 调度决定。
"""
from __future__ import annotations

import ast
import logging
import re

from prometheus_nexus.mechanisms.base_mechanism import BaseMechanism
from prometheus_nexus.mechanisms.source_fetcher import fetch_repo_overview, fetch_repo_source

logger = logging.getLogger(__name__)


class ExtractedMechanism(BaseMechanism):
    """T3 提取出的机制(来自外部 repo), 作为候选进入 registry。

    Phase 2: 强类型字段, 不再把文本当 gene_specs 注入(修 'items' bug)。
    """

    def __init__(self, name: str, description: str, repo: str,
                 contract: str = "", gene_specs: dict | None = None,
                 mechanism_summary: str = ""):
        super().__init__()
        self.name = name
        self.description = description
        self.repo = repo
        self.contract = contract
        self.gene_specs = gene_specs or {}
        self.mechanism_summary = mechanism_summary
        self.category = "extracted"

    def run(self, context: dict | None = None) -> dict:
        """提取机制默认不直接执行外部代码, 仅返回提取的契约/描述。

        真正的执行需经适配层(x/y_adapter范式)对齐 BaseMechanism 后由 S7 调度。
        """
        return {
            "ok": True,
            "mechanism": self.name,
            "source_repo": self.repo,
            "contract": self.contract,
            "gene_specs": self.gene_specs,
            "note": "extracted mechanism (candidate, not auto-activated)",
        }


def extract_gene_specs_from_source(source: str) -> dict[str, tuple[float, float]]:
    """AST 提取源码中可调参数的真实值域(替代脆弱正则).

    从模块级常量赋值 / 类属性默认值中抽取数值配置, 派生 (lo, hi) 搜索区间。
    """
    specs: dict[str, tuple[float, float]] = {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return specs
    for node in ast.walk(tree):
        # 模块级 / 类属性: NAME = <数值>
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and isinstance(node.value, ast.Constant) \
                        and isinstance(node.value.value, (int, float)):
                    v = float(node.value.value)
                    specs[f"ext_{t.id}"] = (round(max(0.0, v * 0.5), 4),
                                            round(max(v * 1.5, 0.01), 4))
        # 函数默认参数: def f(x: float = 0.3)
        # Python 3.11: 默认值在 node.args.defaults (位置参数) / kw_defaults (关键字),
        # 与 args 列表尾部对齐, 无默认值的参数对应 None 占位.
        if isinstance(node, ast.FunctionDef):
            pos_args = node.args.args
            defaults = list(node.args.defaults)
            # 对齐: defaults 对应 pos_args 末尾 len(defaults) 个
            offset = len(pos_args) - len(defaults)
            for i, a in enumerate(pos_args):
                if a.arg in ("self", "cls"):
                    continue
                di = i - offset
                if di >= 0 and isinstance(defaults[di], ast.Constant) \
                        and isinstance(defaults[di].value, (int, float)):
                    v = float(defaults[di].value)
                    specs[f"ext_{a.arg}"] = (round(max(0.0, v * 0.5), 4),
                                             round(max(v * 1.5, 0.01), 4))
    return specs


class MechanismExtractor:
    """从 GitHub repo 提取机制(学习 + 编译双步)."""

    # 与系统语义相关的高价值关键词(用于价值过滤)
    RELEVANCE_KEYWORDS = (
        "agent", "memory", "evolution", "mechanism", "reasoning", "policy",
        "optimizer", "attention", "retrieval", "embedding", "rl", "llm",
        "neural", "plasticity", "meta-learning", "self-impro",
    )

    def __init__(self, llm=None, store=None, compiler=None):
        self.llm = llm
        self._store = store
        self._compiler = compiler  # 复用 T4 的 MechanismCompiler(可选, 延迟构造)

    def extract(self, repo_full_name: str) -> ExtractedMechanism | None:
        overview = fetch_repo_overview(repo_full_name)
        if not overview:
            logger.debug("MechanismExtractor: cannot fetch %s", repo_full_name)
            return None

        mechanism_name = repo_full_name.split("/")[-1]
        description = ""
        contract = ""
        gene_specs: dict[str, tuple[float, float]] = {}

        # ---- Step1 学习: 取源码做 AST 提取真实参数 ----
        files = self._parse_file_list(overview)
        py_files = [f for f in files if f.endswith(".py")][:8]
        if py_files:
            source = fetch_repo_source(repo_full_name, py_files)
            if source:
                gene_specs = extract_gene_specs_from_source(source)

        # ---- Step1 学习: LLM 总结机制意图(语义理解, 不产结构) ----
        if self.llm is not None and self.llm.available:
            prompt = (
                f"从以下开源项目概览中提取其'核心机制/算法'(而非功能列表):\n"
                f"{overview[:6000]}\n\n"
                f"输出格式:\nMECHANISM: <机制名>\n"
                f"WHAT: <一句话说明它做什么>\n"
                f"CONTRACT: <输入/输出/依赖接口>\n"
                f"RELEVANCE: <与 AI Agent/记忆/进化系统的相关度 0-1>"
            )
            out = self.llm.complete(prompt, system="你是机制提取器, 只输出机制签名")
            if out:
                description = out
                contract = out
        else:
            classes = re.findall(r"class\s+(\w+)", overview)
            defs = re.findall(r"def\s+(\w+)", overview)
            description = f"从 {repo_full_name} 提取: 类={classes[:5]}, 函数={defs[:8]}"
            contract = f"classes={classes[:5]}"

        return ExtractedMechanism(
            name=f"ext_{mechanism_name}",
            description=description,
            repo=repo_full_name,
            contract=contract,
            gene_specs=gene_specs,
        )

    @staticmethod
    def _parse_file_list(overview: str) -> list[str]:
        """从 overview 末尾 '## Top-level files' 行解析文件名列表."""
        m = re.search(r"## Top-level files\s*\n(.+)", overview)
        if not m:
            return []
        return [f.strip() for f in m.group(1).split(",") if f.strip()]

    def is_high_value(self, mech: ExtractedMechanism) -> tuple[bool, float]:
        """高价值过滤: 有可调参数 或 与系统语义相关. 返回 (是否值得提取, 评分)."""
        score = 0.0
        if mech.gene_specs:
            score += 0.5
        # 语义相关度: 描述/contract 命中关键词
        text = (mech.description + " " + mech.contract).lower()
        hits = sum(1 for kw in self.RELEVANCE_KEYWORDS if kw in text)
        score += min(0.5, hits * 0.1)
        return score >= 0.3, round(score, 2)

    def compile_to_mechanism(self, mech: ExtractedMechanism, paper_context: str = "") -> str | None:
        """Step2 编译: 把理解的机制经 MechanismCompiler 编译成 BaseMechanism 子类.

        复用 T4 管线(共享底座, 不重复造轮). 返回编译通过的 draft_code 或 None.
        """
        if self._compiler is None:
            from prometheus_nexus.mechanisms.mechanism_compiler import MechanismCompiler
            self._compiler = MechanismCompiler(llm=self.llm, store=self._store)
        draft = self._compiler._compile_draft_with_fix(
            mech.mechanism_summary or mech.description,
            mech.name, system="你是机制编译器(从 GitHub 项目编译)",
            paper_context=paper_context or mech.description,
        )
        return draft

    def extract_from_node(self, node) -> ExtractedMechanism | None:
        """P3: 从 learn 已吸收的 rail_t3 节点取 url, 提取机制(不重拉源)。

        消费 store 中 NodeType.PROJECT / rail_t3 节点(learn 已吸收 github 项目),
        直接取 node.url 拉代码, 而非自己重新扫描 github。消除源重复。
        """
        if node is None:
            return None
        url = getattr(node, "url", "") or ""
        if not url:
            logger.debug("MechanismExtractor: node %s has no url", getattr(node, "id", "?"))
            return None
        # url 形如 https://github.com/owner/repo -> owner/repo
        repo = url.replace("https://github.com/", "").strip("/")
        if not repo or "/" not in repo:
            logger.debug("MechanismExtractor: invalid github url %s", url)
            return None
        return self.extract(repo)

    def register_from_node(self, node, registry) -> dict:
        """从节点提取并注册进机制表(不激活)。

        P4: 同时写 store 的 PATTERN 节点(统一存储, 消除 registry/store 三分裂),
        并建立 PROVENANCE_DERIVED_FROM 边连回源节点。
        """
        mech = self.extract_from_node(node)
        if mech is None:
            return {"registered": False, "reason": "fetch_failed"}
        result = registry.register(
            mech.name,
            data={"executable": mech, "repo": mech.repo, "contract": mech.contract},
            dependencies=[],
            category="extracted",
            pending=True,  # P6: T3 产物默认 pending, 待验证激活(不自动直替生产)
        )
        # P4: 写 store 节点(统一知识底座)
        try:
            store = getattr(registry, "store", None) or getattr(self, "_store", None)
            if store is not None:
                from prometheus_nexus.foundation.schema import Node, NodeType, Edge, EdgeType
                store.create_node(Node(
                    content=f"[T3 extracted] {(mech.description or '')[:300]}",
                    type=NodeType.PATTERN, tags=["mechanism", "extracted", mech.name],
                    utility=0.6, url=getattr(node, "url", ""),
                ))
                # 衍生边: 机制 <- 源项目(源节点有 id 时才连)
                nid = getattr(node, "id", None)
                if nid:
                    try:
                        store.create_edge(Edge(source_id=nid, target_id=mech.name,
                                               type=EdgeType.PROVENANCE_DERIVED_FROM, weight=1.0))
                    except Exception:
                        pass
        except Exception as e:
            logger.debug("MechanismExtractor: store write failed: %s", e)

        # P6: 激活闭环 — 注册为 pending 后立刻走三道门验证, 通过则 activate
        # (不自动直替生产: 仅验证通过的机制才 active, 并回写 evolve)
        try:
            act = registry.verify_and_activate(
                mech.name,
                claim=(mech.description or mech.name),
                hypothesis=f"T3:{mech.name} from {mech.repo}",
            )
            result["activated"] = act.get("activated", False)
            result["activation"] = act
            # 回写 store 的 PATTERN 节点(标记 active / blocked)
            store = getattr(registry, "store", None) or getattr(self, "_store", None)
            if store is not None and act.get("activated"):
                try:
                    pats = store.get_nodes_by_type(NodeType.PATTERN, limit=1000)
                    for p in pats:
                        if mech.name in (p.tags or []):
                            p.tags = list(p.tags or []) + ["active"]
                            store.update_node(p)
                            break
                except Exception:
                    pass
        except Exception as e:
            logger.debug("MechanismExtractor: activation failed: %s", e)
        return result

    def register(self, repo_full_name: str, registry) -> dict:
        """向后兼容: 旧接口(直接传 repo 名提取+注册)。新代码请用 register_from_node。"""
        mech = self.extract(repo_full_name)
        if mech is None:
            return {"registered": False, "reason": "fetch_failed"}
        return registry.register(
            mech.name,
            data={"executable": mech, "repo": mech.repo, "contract": mech.contract},
            dependencies=[],
            category="extracted",
        )
