"""MechanismCompiler — T4 第四轨: 将论文编译为新机制草案。

与前三轨本质区别: 创造系统原本不存在的机制(超前探索), 而非调参/重组/搬已知。

流程:
1. SourceFetcher 拉论文全文(arxiv e-print)
2. LLM(复用 Hermes 对话模型)把核心机制编译为 draft module:
   - 机制描述 + 接口契约(input/output/依赖) + Python 骨架(继承 BaseMechanism)
   无 LLM 时降级为规则提取(识别 'we propose'/'algorithm'/'method' 段)
3. draft 存 archive/compiled/{name}.py + 注册进 registry(status='compiled', 不直启)
4. 激活由验证门 + S7 神经系统决定(A-B 并行, 不自动直替)

安全: 编译产物默认不执行, 仅存草稿待验证。
"""
from __future__ import annotations

import logging
import os
import re
import types
import ast

from prometheus_nexus.mechanisms.base_mechanism import BaseMechanism
from prometheus_nexus.mechanisms.source_fetcher import fetch_arxiv_fulltext

logger = logging.getLogger(__name__)


class CompiledMechanism(BaseMechanism):
    """T4 编译出的机制草案(来自论文), 作为候选进入 registry。"""

    def __init__(self, name: str, description: str, paper: str, draft_code: str = "",
                 target_location: dict | None = None):
        super().__init__()
        self.name = name
        self.description = description
        self.paper = paper
        self.draft_code = draft_code
        self.category = "compiled"
        # P7: 行为定位(behavior localization) — 机制应改进/插入的 ULTRA 代码位置
        # 来自 Harness Handbook (arXiv:2607.13285). 是"位置建议"而非自动直替.
        self.target_location = target_location or {}

    def run(self, context: dict | None = None) -> dict:
        """编译草案默认不执行(待验证), 仅返回草案信息。"""
        return {
            "ok": True,
            "mechanism": self.name,
            "source_paper": self.paper,
            "draft_code_len": len(self.draft_code),
            "target_location": self.target_location,
            "note": "compiled draft (candidate, not auto-activated)",
        }


class MechanismCompiler:
    """将论文编译为机制草案。"""

    def __init__(self, llm=None, store=None, compiled_dir: str = "archive/compiled"):
        self.llm = llm
        self._store = store
        self.compiled_dir = compiled_dir
        os.makedirs(self.compiled_dir, exist_ok=True)

    def compile(self, arxiv_id: str, paper_title: str = "") -> CompiledMechanism | None:
        """独立扫描入口(非 learn 链路): 自己拉 arxiv 全文再编译.

        learn 链路应走 compile_from_node(从 store 节点 raw_chunk 取全文, 不重拉).
        """
        fulltext = fetch_arxiv_fulltext(arxiv_id)
        if not fulltext:
            logger.debug("MechanismCompiler: no fulltext for %s", arxiv_id)
            return None
        return self.compile_from_text(fulltext, arxiv_id, paper_title)

    def compile_from_text(self, fulltext: str, arxiv_id: str,
                          paper_title: str = "") -> CompiledMechanism | None:
        """从已有全文编译机制(单一获取入口: 全文由 learn 存入, 不在此重拉).

        Args:
            fulltext: 论文全文(来自 store 节点 raw_chunk, 由 learn 时 scanner 拉取)
            arxiv_id: 论文 ID(用于命名/溯源)
            paper_title: 论文标题
        """
        if not fulltext or not fulltext.strip():
            logger.debug("MechanismCompiler: empty fulltext for %s", arxiv_id)
            return None

        mechanism_name = f"paper_{arxiv_id.split('/')[-1].replace('.', '_')}"
        description = ""
        draft_code = ""

        if self.llm is not None and self.llm.available:
            # P7 方向2: BGPD 三级渐进披露 - 先高层行为, 再模块, 最后具体函数
            prompt = (
                f"从论文提取核心机制, 分三级输出(Behavior-Guided Progressive Disclosure):\n"
                f"L1_BEHAVIOR: <该机制对应 agent 的哪类高层行为, 如'参数进化'/'语义记忆'/'工具调用'>\n"
                f"L2_MODULE: <ULTRA 中相关模块, 如 evolution / memory / mechanisms>\n"
                f"L3_MECHANISM: <机制名 + 一句话 + 接口契约(input/output/依赖)>\n"
                f"论文: {paper_title}\n\n{fulltext[:8000]}\n"
            )
            out = self.llm.complete(prompt, system="你是机制编译器(三级渐进)")
            if out:
                description = out
                # 编译校验 + LLM 自修正循环
                draft_code = self._compile_draft_with_fix(
                    out, mechanism_name, system="你是机制编译器(三级渐进)",
                    paper_context=f"论文: {paper_title}\n{fulltext[:4000]}",
                )
                if not draft_code:
                    logger.warning("MechanismCompiler: LLM draft 无法编译通过, 丢弃 %s", mechanism_name)
                    return None
        else:
            # 降级(P2a): 无 LLM 时规则提取
            proposals = re.findall(r"(?:we propose|our method|algorithm \d+|our approach)[^\n.]{0,120}", fulltext, re.I)
            description = f"从 {arxiv_id} 提取: " + " | ".join(proposals[:3])
            tl = self._locate_target(description, paper_title)
            tl_repr = repr(tl) if tl else "{}"
            draft_code = (
                f"# DRAFT (rule-extracted, no LLM - requires human review)\n"
                f"# paper: {arxiv_id} {paper_title}\n"
                f"# target_location: {tl_repr}\n"
                f"# apply: 经 P7 行为定位确认位置后, 由宿主/A-B 验证落地, 非自动直替\n"
                f"# mechanism_summary: {description[:200]}\n"
                f"from prometheus_nexus.mechanisms.base_mechanism import BaseMechanism\n\n"
                f"class {mechanism_name}(BaseMechanism):\n"
                f"    name = '{mechanism_name}'\n"
                f"    category = 'compiled'\n"
                f"    target_location = {tl_repr}\n\n"
                f"    def run(self, context=None):\n"
                f"        # TODO: 实现论文机制 (LLM 缺失时仅占位, 待人工补全)\n"
                f"        return {{'ok': False, 'note': 'rule-extracted draft, awaiting LLM/human implementation'}}\n"
            )

        # P7 方向1: 行为定位
        target_location = self._locate_target(description, paper_title)

        # 存草稿文件
        try:
            fname = os.path.join(self.compiled_dir, f"{mechanism_name}.py")
            with open(fname, "w", encoding="utf-8") as f:
                f.write(f'"""{mechanism_name} (from {arxiv_id}: {paper_title})"""\n')
                if target_location:
                    f.write(f"# TARGET_LOCATION: {target_location.get('module')}:"
                             f"{target_location.get('lineno')} {target_location.get('symbol')}\n")
                    f.write(f"# TARGET_RATIONALE: {target_location.get('rationale', '')}\n")
                f.write("\nfrom prometheus_nexus.mechanisms.base_mechanism import BaseMechanism\n\n")
                f.write(f"class {mechanism_name}(BaseMechanism):\n")
                f.write(f"    name = '{mechanism_name}'\n")
                f.write(f"    description = '''{description[:300]}''')\n")
                f.write(f"    category = 'compiled'\n")
                f.write(f"    target_location = {target_location!r}\n\n")
                f.write("    def run(self, context=None):\n")
                f.write("        return {'ok': True, 'note': 'compiled draft, awaiting verification'}\n")
        except Exception as e:
            logger.debug("MechanismCompiler: save draft failed: %s", e)

        return CompiledMechanism(
            name=mechanism_name, description=description, paper=arxiv_id,
            draft_code=draft_code, target_location=target_location,
        )

    # 自修正循环上限: LLM 生成的草案编译不过时, 最多重生成次数
    MAX_DRAFT_FIX = 2

    def _validate_draft(self, draft_code: str, mechanism_name: str) -> str | None:
        """编译 draft_code 并校验是合法 BaseMechanism 子类.

        返回通过编译且含合法子类的 draft_code; 否则返回 None(劣质草案)。
        仅做 compile + 类检查, 不执行(安全边界同 MechanismSandbox)。
        """
        if not draft_code or not draft_code.strip():
            return None
        try:
            mod = types.ModuleType(f"_mech_chk_{mechanism_name}")
            mod.__dict__["BaseMechanism"] = BaseMechanism
            code = compile(draft_code, f"<mech_{mechanism_name}>", "exec")
            exec(code, mod.__dict__)  # noqa: S102 — 仅编译/类检查, 不运行
        except Exception as e:
            logger.debug("MechanismCompiler: draft 校验失败 %s: %s", mechanism_name, e)
            return None
        # 必须含 BaseMechanism 子类(非 BaseMechanism 本身)
        cls = None
        for v in mod.__dict__.values():
            if (isinstance(v, type) and issubclass(v, BaseMechanism)
                    and v is not BaseMechanism):
                cls = v
                break
        if cls is None:
            logger.debug("MechanismCompiler: draft 无 BaseMechanism 子类 %s", mechanism_name)
            return None
        # Phase 1: run() 必须非空壳 — 引用 context 且返回非纯占位
        if not self._run_is_non_trivial(draft_code):
            logger.debug("MechanismCompiler: draft run() 为空壳/未用 context %s", mechanism_name)
            return None
        return draft_code

    @staticmethod
    def _run_is_non_trivial(draft_code: str) -> bool:
        """静态检查 run() 方法: 必须引用 context 参数, 且返回非纯 ok 占位.

        劣质草案(如 `def run(self, ctx): return {"ok": True}`)不挂载 — 对系统无帮助.
        这是对 '编译通过但语义空壳' 的守门升级(契合用户立场: 劣质草案无帮助).
        """
        try:
            tree = ast.parse(draft_code)
        except SyntaxError:
            return False
        run_func = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "run":
                run_func = node
                break
        if run_func is None:
            return False
        # 必须引用 context 形参(否则机制对输入无感知, 无意义)
        args = [a.arg for a in run_func.args.args]
        if "context" not in args and "ctx" not in args:
            return False
        # 禁止纯占位返回: return {"ok": True} / return {"ok": True, "note": "..."}
        for ret in ast.walk(run_func):
            if isinstance(ret, ast.Return) and isinstance(ret.value, ast.Dict):
                keys = [k.value for k in ret.value.keys if isinstance(k, ast.Constant)]
                if keys == ["ok"] or (keys == ["ok", "note"]) or (keys == ["note", "ok"]):
                    return False
        return True

    def _compile_draft_with_fix(self, first_draft: str, mechanism_name: str,
                                system: str | None = None,
                                paper_context: str = "") -> str | None:
        """LLM 草案编译校验 + 自修正循环.

        首稿编译/类检查不过, 把具体 SyntaxError 反馈给 LLM 修正重生成,
        直到通过或达到 MAX_DRAFT_FIX 上限. 全部失败返回 None(调用方丢弃,
        不挂载劣质/占位草案)。
        """
        draft = first_draft
        last_err = ""
        for _ in range(self.MAX_DRAFT_FIX + 1):
            ok = self._validate_draft(draft, mechanism_name)
            if ok is not None:
                return ok
            if self.llm is None or not self.llm.available:
                return None
            # 构造修正 prompt: 反馈上次错误, 要求只输出纯 Python
            fix_prompt = (
                f"你上一版机制代码无法通过 Python 编译, 错误: {last_err or '未通过编译/非 BaseMechanism 子类'}.\n"
                f"请修正并**只输出**一个继承 BaseMechanism 的 Python 类定义(无解释/无 Markdown 代码块标记/无全角标点):\n"
                f"- 必须 `from prometheus_nexus.mechanisms.base_mechanism import BaseMechanism`\n"
                f"- class 内实现 `def run(self, context=None) -> dict:`\n"
                f"- 仅用半角标点, 不要用中文全角逗号/冒号/括号\n\n"
                f"原始论文上下文:\n{paper_context[:3000]}\n\n"
                f"上一版代码:\n{draft[:2000]}\n"
            )
            try:
                fixed = self.llm.complete(fix_prompt, system=system, temperature=0.2)
            except Exception as e:
                logger.warning("MechanismCompiler: draft 修正调用 LLM 失败 %s: %s", mechanism_name, e)
                return None
            if not fixed:
                return None
            # 剥离可能的 Markdown 代码块包裹
            draft = self._strip_code_fence(fixed)
            last_err = self._last_compile_error(draft, mechanism_name)
        return None

    @staticmethod
    def _strip_code_fence(text: str) -> str:
        """去掉 LLM 输出常见的 ```python ... ``` 包裹, 提取纯代码。"""
        if "```" in text:
            parts = text.split("```")
            for seg in parts:
                seg = seg.strip()
                if seg.startswith("python") or seg.startswith("py"):
                    seg = seg.split("\n", 1)[1] if "\n" in seg else seg
                if "class " in seg and "BaseMechanism" in seg:
                    return seg
            return "\n".join(l for l in text.splitlines() if not l.strip().startswith("```"))
        return text.strip()

    def _last_compile_error(self, draft_code: str, mechanism_name: str) -> str:
        try:
            compile(draft_code, f"<mech_{mechanism_name}>", "exec")
            return ""
        except SyntaxError as e:
            return f"SyntaxError: {e.msg} (line {e.lineno})"
        except Exception as e:  # noqa: BLE001 — 只为生成反馈文本
            return f"{type(e).__name__}: {e}"

    def _locate_target(self, description: str, paper_title: str) -> dict:
        """P7: 用 Harness Handbook 定位编译机制应改进/插入的 ULTRA 代码位置。

        返回 LocationCandidate 的 dict 形式(模块/行号/符号/置信度/验证状态)。
        无 LLM 时降级为关键词规则定位(论文原方案无离线 fallback, 此处补上)。
        """
        try:
            from prometheus_nexus.mechanisms.handbook import get_handbook
            hb = get_handbook()
            query = f"{paper_title} {description}"
            # 优先 BGPD 三级渐进(更省 token, 定位更准); 退化为普通 locate
            cands = hb.bgpd_locate(query, self.llm, top_k=1)
            if not cands:
                cands = hb.locate_behavior(query, self.llm, top_k=1)
            if cands:
                c = cands[0]
                return {
                    "module": c.module, "filepath": c.filepath, "lineno": c.lineno,
                    "symbol": c.symbol, "confidence": c.confidence,
                    "verified": c.verified, "rationale": c.rationale,
                    "level": c.level,
                }
        except Exception as e:
            logger.debug("MechanismCompiler: target location failed: %s", e)
        return {}

    def compile_from_node(self, node) -> CompiledMechanism | None:
        """从 learn 已吸收的 rail_t4 节点编译机制(单一获取入口: 只消费 store, 不重拉源).

        消费 store 中 NodeType.PAPER / rail_t4 节点(learn 已吸收论文),
        从 node.raw_chunk 取全文(learn 时 scanner 已拉取存入), 调 compile_from_text.
        raw_chunk 空时降级用 content 摘要(不崩, 不重拉外部源).
        """
        if node is None:
            return None
        url = getattr(node, "url", "") or ""
        arxiv_id = ""
        if url:
            # url 形如 https://arxiv.org/abs/2401.12345 -> 2401.12345
            arxiv_id = url.replace("https://arxiv.org/abs/", "").strip("/")
        if not arxiv_id or "." not in arxiv_id:
            logger.debug("MechanismCompiler: invalid arxiv url %s, fallback to node id", url)
            arxiv_id = getattr(node, "id", "unknown")
        title = getattr(node, "content", "")[:80]
        # 单一获取入口: 优先 raw_chunk(全文), 降级 content(摘要)
        fulltext = getattr(node, "raw_chunk", "") or ""
        if not fulltext:
            fulltext = getattr(node, "content", "") or ""
            logger.debug("MechanismCompiler: node %s raw_chunk 空, 降级用 content 摘要", arxiv_id)
        return self.compile_from_text(fulltext, arxiv_id, title)

    def register_from_node(self, node, registry, paper_title: str = "") -> dict:
        """从节点编译并注册进机制表(status=compiled, 不激活)。

        P4: 同时写 store 的 PATTERN 节点(统一存储), 并建立
        PROVENANCE_DERIVED_FROM 边连回源论文节点。
        """
        mech = self.compile_from_node(node)
        if mech is None:
            return {"registered": False, "reason": "fetch_failed"}
        result = registry.register(
            mech.name,
            data={"executable": mech, "paper": mech.paper, "draft_code": mech.draft_code,
                  "target_location": mech.target_location},
            dependencies=[],
            category="compiled",
            pending=True,  # P6: T4 产物默认 pending, 待验证激活(不自动直替生产)
        )
        # P4: 写 store 节点(统一知识底座)
        try:
            store = getattr(registry, "store", None) or getattr(self, "_store", None)
            if store is not None:
                from prometheus_nexus.foundation.schema import Node, NodeType, Edge, EdgeType
                store.create_node(Node(
                    content=f"[T4 compiled] {(mech.description or '')[:300]}",
                    type=NodeType.PATTERN, tags=["mechanism", "compiled", mech.name],
                    utility=0.6, url=getattr(node, "url", ""),
                ))
                nid = getattr(node, "id", None)
                if nid:
                    try:
                        store.create_edge(Edge(source_id=nid, target_id=mech.name,
                                               type=EdgeType.PROVENANCE_DERIVED_FROM, weight=1.0))
                    except Exception:
                        pass
        except Exception as e:
            logger.debug("MechanismCompiler: store write failed: %s", e)

        # P6: 激活闭环 — 注册为 pending 后立刻走三道门验证, 通过则 activate
        try:
            act = registry.verify_and_activate(
                mech.name,
                claim=(mech.description or mech.name),
                hypothesis=f"T4:{mech.name} from {mech.paper}",
            )
            result["activated"] = act.get("activated", False)
            result["activation"] = act
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
            logger.debug("MechanismCompiler: activation failed: %s", e)
        return result

    def register(self, arxiv_id: str, registry, paper_title: str = "") -> dict:
        """向后兼容: 旧接口(直接传 arxiv_id 编译+注册)。新代码请用 register_from_node。"""
        mech = self.compile(arxiv_id, paper_title)
        if mech is None:
            return {"registered": False, "reason": "fetch_failed"}
        return registry.register(
            mech.name,
            data={"executable": mech, "paper": mech.paper, "draft_code": mech.draft_code},
            dependencies=[],
            category="compiled",
        )
