"""Harness Handbook — P7 行为定位层 (Behavior Localization).

源自论文 Harness Handbook (arXiv:2607.13285, Tencent Hunyuan 2026):
    "Agent 的演进瓶颈不是生成 edit, 而是确定 edit 该落在哪 (behavior localization)."

本模块把该方法论移植进 ULTRA 的四轨进化:
- build_handbook(): 对 ULTRA 源码跑 AST 静态分析, 生成 behavior->source_location 映射
- locate_behavior(): 给定"机制应改进什么行为", 用 LLM 从 handbook 找最匹配代码位置
- bgpd_locate(): Behavior-Guided Progressive Disclosure 三级渐进披露
    Level1 高层行为 -> Level2 相关模块 -> Level3 具体函数 + 对照当前源码验证候选位置
    论文证明 BGPD 用更少 planner token 达到更好定位.

设计原则(对齐 ULTRA 现有惯例):
- 静态分析用 stdlib ast (无重依赖)
- LLM 不可用时降级为关键词/路径规则定位(不静默丢功能)
- 产物是"位置建议"而非自动直替(对齐 P6 不自动直替原则, 交 A-B 验证)
"""
from __future__ import annotations

import ast
import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class BehaviorEntry:
    """一个行为条目: 描述 + 源码位置。"""
    behavior: str = ""           # 行为语义描述(来自 docstring/函数名)
    module: str = ""             # 模块路径 (prometheus_nexus.xxx)
    filepath: str = ""           # 绝对/相对文件路径
    lineno: int = 0              # 定义行号
    kind: str = "function"       # function / class / method
    signature: str = ""          # 函数签名摘要
    docstring: str = ""          # 文档字符串(行为语义主来源)
    callees: list = field(default_factory=list)  # 调用的本地符号(用于跨模块/分散行为推断)
    # 方案Y: 使用追踪(被 locate_behavior 查中时记时间戳, 供 B1 消费率观测)
    last_used: float = 0.0
    used_count: int = 0


@dataclass
class LocationCandidate:
    """BGPD 定位结果: 候选代码位置 + 置信度 + 验证状态。"""
    module: str = ""
    filepath: str = ""
    lineno: int = 0
    symbol: str = ""
    confidence: float = 0.0
    level: int = 0               # 1=高层行为 2=模块 3=具体函数
    verified: bool = False       # 是否对照当前源码验证候选位置存在
    rationale: str = ""


class HarnessHandbook:
    """行为定位手册: 从代码库静态分析生成, 支持 LLM 辅助定位。"""

    def __init__(self, src_root: str | None = None):
        self.src_root = src_root or self._default_src_root()
        self.entries: list[BehaviorEntry] = []
        self._by_module: dict[str, list[BehaviorEntry]] = {}

    @staticmethod
    def _default_src_root() -> str:
        # src/prometheus_nexus 相对本文件两级
        here = os.path.dirname(os.path.abspath(__file__))
        return os.path.normpath(os.path.join(here, "..", ".."))

    def build(self, src_root: str | None = None) -> list[BehaviorEntry]:
        """AST 静态分析源码树, 提取所有函数/类为 BehaviorEntry。

        行为语义来自 docstring + 函数名(论文: static analysis + LLM-assisted structuring)。
        这里做 static 部分; LLM 结构化在 locate/bgpd 里做。
        """
        root = src_root or self.src_root
        entries: list[BehaviorEntry] = []
        for dirpath, _, files in os.walk(root):
            # 跳过非源码/私有
            if any(seg.startswith(".") for seg in dirpath.split(os.sep)):
                continue
            if "__pycache__" in dirpath or "archive" in dirpath:
                continue
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                fpath = os.path.join(dirpath, fn)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        src = f.read()
                    tree = ast.parse(src)
                except Exception as e:
                    logger.debug("Handbook: parse failed %s: %s", fpath, e)
                    continue
                module = self._path_to_module(fpath, root)
                entries.extend(self._extract_from_tree(tree, module, fpath))
        self.entries = entries
        self._by_module = {}
        for e in entries:
            self._by_module.setdefault(e.module, []).append(e)
        logger.info("Handbook built: %d behavior entries from %s", len(entries), root)
        return entries

    def _path_to_module(self, fpath: str, root: str) -> str:
        rel = os.path.relpath(fpath, root)
        mod = rel.replace(os.sep, ".").removesuffix(".py")
        if mod.endswith(".__init__"):
            mod = mod[: -len(".__init__")]
        return mod

    def _extract_from_tree(self, tree: ast.AST, module: str, fpath: str) -> list[BehaviorEntry]:
        out: list[BehaviorEntry] = []

        def visit(node: ast.AST, cls: str | None = None):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    doc = ast.get_docstring(child) or ""
                    sig = self._signature(child)
                    callees = self._local_callees(child)
                    out.append(BehaviorEntry(
                        behavior=(doc.strip().split("\n")[0] if doc else child.name),
                        module=module, filepath=fpath, lineno=child.lineno,
                        kind="method" if cls else "function",
                        signature=sig, docstring=doc, callees=callees,
                    ))
                elif isinstance(child, ast.ClassDef):
                    doc = ast.get_docstring(child) or ""
                    out.append(BehaviorEntry(
                        behavior=(doc.strip().split("\n")[0] if doc else child.name),
                        module=module, filepath=fpath, lineno=child.lineno,
                        kind="class", signature=child.name, docstring=doc,
                    ))
                    visit(child, cls=child.name)  # 进入类内提取方法
            # 顶层函数也需 visit(node) 初始调用
        visit(tree)
        return out

    @staticmethod
    def _signature(fn: ast.FunctionDef) -> str:
        args = fn.args
        parts = [a.arg for a in args.args if a.arg != "self"]
        if args.vararg:
            parts.append("*" + args.vararg.arg)
        return f"{fn.name}({', '.join(parts)})"

    @staticmethod
    def _local_callees(fn: ast.FunctionDef) -> list[str]:
        called = []
        for n in ast.walk(fn):
            if isinstance(n, ast.Call):
                f = n.func
                if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "self":
                    called.append(f.attr)
                elif isinstance(f, ast.Name):
                    called.append(f.id)
        return called

    # ------------------------------------------------------------------
    # 定位 (方向1: behavior -> source location)
    # ------------------------------------------------------------------
    def locate_behavior(self, query: str, llm=None, top_k: int = 3) -> list[LocationCandidate]:
        """给定机制描述 query, 返回最匹配的代码位置候选。

        LLM 可用时: 让 LLM 在 handbook 条目里挑最相关行为(语义匹配)。
        LLM 不可用时: 关键词重叠降级(论文: 无离线 fallback 时静默失效, 此处补 fallback)。
        """
        if llm is not None and getattr(llm, "available", False):
            return self._llm_locate(query, llm, top_k)
        return self._rule_locate(query, top_k)

    def _rule_locate(self, query: str, top_k: int) -> list[LocationCandidate]:
        """关键词重叠降级定位(无 LLM 时仍可给出位置建议)。"""
        q_tokens = set(self._tokenize(query))
        scored = []
        for e in self.entries:
            text = f"{e.behavior} {e.docstring} {e.signature}".lower()
            overlap = len(q_tokens & set(self._tokenize(text)))
            if overlap == 0:
                continue
            e.last_used = __import__("time").time()  # 方案Y: 被查中记时间戳
            e.used_count += 1
            scored.append((overlap, e))
        scored.sort(key=lambda x: -x[0])
        cands = []
        for ov, e in scored[:top_k]:
            cands.append(LocationCandidate(
                module=e.module, filepath=e.filepath, lineno=e.lineno,
                symbol=e.signature, confidence=min(1.0, ov / 5.0),
                level=3, verified=True, rationale=f"关键词重叠 {ov}",
            ))
        return cands

    def _llm_locate(self, query: str, llm, top_k: int) -> list[LocationCandidate]:
        """LLM 辅助定位: 把 handbook 摘要喂给 LLM, 让它挑行为位置。"""
        # 构造 handbook 摘要(仅行为描述+位置, 控制 token)
        summary = "\n".join(
            f"- [{e.module}:{e.lineno}] {e.behavior}" for e in self.entries[:200]
        )
        prompt = (
            f"你是代码定位器。给定要实现的机制描述, 从以下行为手册挑出最相关的代码位置(最多{top_k}个)。\n"
            f"机制描述: {query}\n\n行为手册:\n{summary}\n\n"
            f"输出每行: MODULE|LINENO|SYMBOL|CONFIDENCE|RATIONALE"
        )
        try:
            out = llm.complete(prompt, system="代码行为定位器")
        except Exception as e:
            logger.debug("Handbook LLM locate failed: %s", e)
            return self._rule_locate(query, top_k)
        return self._parse_llm_locations(out, top_k)

    def _parse_llm_locations(self, text: str, top_k: int) -> list[LocationCandidate]:
        cands = []
        for line in (text or "").splitlines():
            if "|" not in line:
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 4:
                continue
            module, lineno, symbol, conf = parts[0], parts[1], parts[2], parts[3]
            rationale = parts[4] if len(parts) > 4 else ""
            # 验证候选位置是否真实存在(对照 handbook)
            verified = any(e.module == module and str(e.lineno) == lineno
                           for e in self.entries)
            try:
                cands.append(LocationCandidate(
                    module=module, lineno=int(lineno), symbol=symbol,
                    confidence=float(conf), level=3, verified=verified,
                    rationale=rationale,
                ))
            except ValueError:
                continue
            if len(cands) >= top_k:
                break
        return cands

    # ------------------------------------------------------------------
    # BGPD (方向2: 三级渐进披露, 省 token)
    # ------------------------------------------------------------------
    def bgpd_locate(self, query: str, llm=None, top_k: int = 1) -> list[LocationCandidate]:
        """Behavior-Guided Progressive Disclosure: 从高层行为渐进到实现细节。

        Level1: 高层行为(匹配 handbook 里的模块级/类级行为)
        Level2: 相关模块(该行为所在模块)
        Level3: 具体函数 + 对照当前源码验证候选位置

        返回 Level3 候选(已验证位置存在)。
        """
        # Level1+2: 先粗定位模块(用关键词/LLM 挑模块)
        module_hits = self._module_hits(query, llm)
        if not module_hits:
            #  fallback 到全量定位
            return self.locate_behavior(query, llm, top_k)
        # Level3: 在命中模块内精确定位具体函数
        q_tokens = set(self._tokenize(query))
        cands = []
        for mod in module_hits:
            for e in self._by_module.get(mod, []):
                text = f"{e.behavior} {e.docstring} {e.signature}".lower()
                overlap = len(q_tokens & set(self._tokenize(text)))
                if overlap == 0:
                    continue
                e.last_used = __import__("time").time()  # 方案Y: 被查中记时间戳
                e.used_count += 1
                cands.append(LocationCandidate(
                    module=e.module, filepath=e.filepath, lineno=e.lineno,
                    symbol=e.signature, confidence=min(1.0, overlap / 5.0),
                    level=3, verified=True, rationale=f"BGPD L3 模块{mod}内匹配",
                ))
        cands.sort(key=lambda c: -c.confidence)
        return cands[:top_k]

    def _module_hits(self, query: str, llm) -> list[str]:
        """BGPD Level1/2: 挑相关模块(关键词或 LLM)。"""
        q_tokens = set(self._tokenize(query))
        mod_scores: dict[str, int] = {}
        for e in self.entries:
            text = f"{e.module} {e.behavior}".lower()
            ov = len(q_tokens & set(self._tokenize(text)))
            if ov:
                mod_scores[e.module] = mod_scores.get(e.module, 0) + ov
        if not mod_scores:
            return []
        # 取 top 2 模块
        ranked = sorted(mod_scores.items(), key=lambda x: -x[1])[:2]
        return [m for m, _ in ranked]

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """分词: 英文按词, 中文按字(bigram 重叠)以兼容中英文混合行为描述。

        论文 handbook 的行为语义多为中文 docstring; 原英文正则会丢中文,
        导致中英文 query/描述 overlap=0 无法定位。中文按字符切(长度>=2)即可
        让 "参数进化" 与 "执行进化循环" 共享 "进化" 字符 -> 命中。
        """
        import re
        tokens: list[str] = []
        # 英文/数字词
        tokens.extend(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]+", text.lower()))
        # 中文: 按字符(去除标点空白), 单字也保留(便于子串重叠)
        cjk = re.findall(r"[一-鿿]", text)
        tokens.extend(cjk)
        return [t for t in tokens if len(t) >= 1]


# 模块级便捷函数(供 T4 调用)
_default_handbook: HarnessHandbook | None = None


def get_handbook(rebuild: bool = False) -> HarnessHandbook:
    """获取(惰性构建)全局 handbook 单例。"""
    global _default_handbook
    if _default_handbook is None or rebuild:
        _default_handbook = HarnessHandbook()
        _default_handbook.build()
    return _default_handbook
