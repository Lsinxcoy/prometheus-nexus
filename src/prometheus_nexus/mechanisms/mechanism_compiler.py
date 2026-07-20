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
        fulltext = fetch_arxiv_fulltext(arxiv_id)
        if not fulltext:
            logger.debug("MechanismCompiler: no fulltext for %s", arxiv_id)
            return None

        mechanism_name = f"paper_{arxiv_id.split('/')[-1].replace('.', '_')}"
        description = ""
        draft_code = ""

        if self.llm is not None and self.llm.available:
            # P7 方向2: BGPD 三级渐进披露 — 先高层行为, 再模块, 最后具体函数
            # 论文证明用更少 token 达到更好定位. 这里把"机制提取"也分三级.
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
                draft_code = out
        else:
            # 降级(P2a): 无 LLM 时规则提取, 但 draft 不能是纯 stub 空壳 —
            # 至少含机制描述 + target_location(若已定位) + 人工 apply 指令, 让激活后仍有意义.
            proposals = re.findall(r"(?:we propose|our method|algorithm \d+|our approach)[^\n.]{0,120}", fulltext, re.I)
            description = f"从 {arxiv_id} 提取: " + " | ".join(proposals[:3])
            tl = self._locate_target(description, paper_title)
            tl_repr = repr(tl) if tl else "{}"
            draft_code = (
                f"# DRAFT (rule-extracted, no LLM — requires human review)\n"
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

        # P7 方向1: 行为定位 — 编译出机制后, 用 Harness Handbook 定位应改进/插入的代码位置
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
        """P3: 从 learn 已吸收的 rail_t4 节点取 url, 编译机制(不重拉源)。

        消费 store 中 NodeType.PAPER / rail_t4 节点(learn 已吸收论文),
        直接取 node.url 中的 arxiv_id 拉全文, 而非自己重新扫描 arxiv。消除源重复。
        """
        if node is None:
            return None
        url = getattr(node, "url", "") or ""
        if not url:
            logger.debug("MechanismCompiler: node %s has no url", getattr(node, "id", "?"))
            return None
        # url 形如 https://arxiv.org/abs/2401.12345 -> 2401.12345
        arxiv_id = url.replace("https://arxiv.org/abs/", "").strip("/")
        if not arxiv_id or "." not in arxiv_id:
            logger.debug("MechanismCompiler: invalid arxiv url %s", url)
            return None
        title = getattr(node, "content", "")[:80]
        return self.compile(arxiv_id, title)

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
