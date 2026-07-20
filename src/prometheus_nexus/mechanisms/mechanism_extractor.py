"""MechanismExtractor — T3 第三轨: 从成熟 GitHub 项目提取优势机制。

流程:
1. SourceFetcher 拉 repo README + 文件树
2. LLM(复用 Hermes 对话模型, HTTP桥)抽机制签名: 做了什么/接口/依赖
   无 LLM 时降级为规则提取(识别 class/def/@decorator 模式)
3. 包装为 ExtractedMechanism(BaseMechanism) 实例
4. 注册进 MechanismRegistry(category='extracted') —— 存 registry + A-B 并行, 不自动直替

安全: 仅提取描述与契约, 不执行外部代码; 激活由验证门 + S7 调度决定。
"""
from __future__ import annotations

import logging
import re

from prometheus_nexus.mechanisms.base_mechanism import BaseMechanism
from prometheus_nexus.mechanisms.source_fetcher import fetch_repo_overview

logger = logging.getLogger(__name__)


class ExtractedMechanism(BaseMechanism):
    """T3 提取出的机制(来自外部 repo), 作为候选进入 registry。"""

    def __init__(self, name: str, description: str, repo: str, contract: str = ""):
        super().__init__()
        self.name = name
        self.description = description
        self.repo = repo
        self.contract = contract
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
            "note": "extracted mechanism (candidate, not auto-activated)",
        }


class MechanismExtractor:
    """从 GitHub repo 提取机制。"""

    def __init__(self, llm=None, store=None):
        self.llm = llm
        self._store = store

    def extract(self, repo_full_name: str) -> ExtractedMechanism | None:
        overview = fetch_repo_overview(repo_full_name)
        if not overview:
            logger.debug("MechanismExtractor: cannot fetch %s", repo_full_name)
            return None

        mechanism_name = repo_full_name.split("/")[-1]
        description = ""
        contract = ""

        # 优先 LLM 抽取
        if self.llm is not None and self.llm.available:
            prompt = (
                f"从以下开源项目概览中提取其'核心机制/算法'(而非功能列表):\n"
                f"{overview[:6000]}\n\n"
                f"输出格式:\nMECHANISM: <机制名>\n"
                f"WHAT: <一句话说明它做什么>\n"
                f"CONTRACT: <输入/输出/依赖接口>"
            )
            out = self.llm.complete(prompt, system="你是机制提取器, 只输出机制签名")
            if out:
                description = out
                contract = out

        # 降级: 规则提取(识别代码结构模式)
        if not description:
            classes = re.findall(r"class\s+(\w+)", overview)
            defs = re.findall(r"def\s+(\w+)", overview)
            description = (
                f"从 {repo_full_name} 提取: 类={classes[:5]}, 函数={defs[:8]}"
            )
            contract = f"classes={classes[:5]}"

        return ExtractedMechanism(
            name=f"ext_{mechanism_name}",
            description=description,
            repo=repo_full_name,
            contract=contract,
        )

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
