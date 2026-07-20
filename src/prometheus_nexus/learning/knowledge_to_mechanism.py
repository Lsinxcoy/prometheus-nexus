"""KnowledgeToMechanism — 三级知识翻译器.

将 learn() 获取的外部知识翻译为系统可执行的变更。

三级翻译:
  Level A (参数级): 从知识中提取参数写入 _learned_config，自动应用，重启重置。
  Level B (策略级): 从知识中提取策略模式调整 dynamic_scaler，条件应用。
  Level C (能力级): 产出 skill/mechanism 建议，仅做记录不自动执行。

设计原则:
  - 所有方法 try/except 保护，不影响调用管道
  - 不作 LLM 推理，纯规则提取
  - Level A 变更写入内存（_learned_config），重启自动清除
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class KnowledgeToMechanism:
    """三级知识翻译器。

    兼容 life.py L1412-1418 的调用：
        mappings = self.knowledge_to_mechanism.analyze_knowledge(content, tags)
        for mapping in mappings:
            if self.knowledge_to_mechanism.apply_mapping(mapping, self):
                applied_changes.append(mapping)
    """

    def __init__(self):
        self._applied_hashes: set[int] = set()  # 内容哈希去重，防止重复应用
        # 三级信任标注追踪
        self._trust_refs: dict[str, dict] = {}  # node_id -> {ref_count, sources, application_count, level}

    def get_trust_level(self, node_id: str) -> str:
        """获取指定节点的信任等级。"""
        info = self._trust_refs.get(node_id, {})
        refs = info.get("ref_count", 0)  # 独立来源数
        apps = info.get("applications", 0)  # 有效应用数
        if apps >= 3:
            return "core"
        elif refs >= 2:
            return "validated"
        return "fact"

    def record_trust_reference(self, node_id: str, source: str = "unknown") -> dict:
        """记录一次来源引用，触发 trust 晋升。"""
        if node_id not in self._trust_refs:
            self._trust_refs[node_id] = {"ref_count": 0, "sources": set(), "applications": 0, "last_promote": time.time()}
        ref = self._trust_refs[node_id]
        if source not in ref["sources"]:
            ref["sources"].add(source)
            ref["ref_count"] = len(ref["sources"])
        old = self._trust_level_for_count(ref["ref_count"], ref["applications"])
        new = self.get_trust_level(node_id)
        if new != old:
            ref["last_promote"] = time.time()
            logger.info("Trust promoted: %s → %s (%s)", node_id[:8], new, old)
        return {"node_id": node_id, "level": new}

    def record_trust_application(self, node_id: str) -> dict:
        """记录一次有效应用，触发 trust 晋升。"""
        if node_id not in self._trust_refs:
            self._trust_refs[node_id] = {"ref_count": 0, "sources": set(), "applications": 0, "last_promote": time.time()}
        self._trust_refs[node_id]["applications"] += 1
        return self.record_trust_reference(node_id, "application")

    def _trust_level_for_count(self, refs: int, apps: int) -> str:
        if apps >= 3:
            return "core"
        elif refs >= 2:
            return "validated"
        return "fact"

    def get_trust_state(self) -> dict:
        """获取可信状态快照用于持久化。"""
        serializable = {}
        for nid, info in self._trust_refs.items():
            serializable[nid] = {
                "ref_count": info["ref_count"],
                "applications": info["applications"],
                "last_promote": info["last_promote"],
            }
        return serializable

    def set_trust_state(self, state: dict) -> None:
        """从持久化快照恢复可信状态。"""
        if not state:
            return
        for nid, info in state.items():
            self._trust_refs[nid] = {
                "ref_count": info.get("ref_count", 0),
                "sources": set(),
                "applications": info.get("applications", 0),
                "last_promote": info.get("last_promote", 0),
            }

    def analyze_knowledge(self, content: str, tags: list[str]) -> list[dict]:
        """分析知识内容，产出一组翻译映射。

        Args:
            content: 知识文本内容。
            tags: 知识标签列表（可空）。

        Returns:
            翻译映射列表，每个元素含 level/type/target/value/confidence。
        """
        mappings: list[dict] = []
        if not content:
            return mappings
        tags = tags or []

        # 文本归一化：去冗余空格、统一分隔符
        import re as _re
        content_lower = _re.sub(r'[_\-]+', ' ', content.lower())
        content_lower = _re.sub(r'\s+', ' ', content_lower).strip()

        # Level A: 参数级翻译
        param_changes = self._extract_parameters(content_lower, tags)
        for key, value in param_changes.items():
            mappings.append({
                "level": "A",
                "type": "parameter",
                "target": key,
                "value": value,
                "confidence": 0.7,
            })

        # Level B: 策略级翻译
        strategy_changes = self._extract_strategies(content_lower, tags)
        for key, value, conf in strategy_changes:
            mappings.append({
                "level": "B",
                "type": "strategy",
                "target": key,
                "value": value,
                "confidence": conf,
            })

        # Level C: 能力级建议
        capability = self._extract_capability(content, tags)
        if capability:
            mappings.append({
                "level": "C",
                "type": "capability_suggestion",
                "target": "skill_registry",
                "value": capability,
                "confidence": 0.3,
            })

        return mappings

    def apply_mapping(self, mapping: dict, omega: Any) -> bool:
        """应用单个翻译映射到系统。

        Args:
            mapping: analyze_knowledge 产出的映射。
            omega: Omega 实例（self）。

        Returns:
            True 如果应用成功。
        """
        try:
            level = mapping.get("level", "")
            target = mapping.get("target", "")
            value = mapping.get("value")

            if level == "A":
                # Level A: 写入 _learned_config
                if hasattr(omega, "_learned_config"):
                    omega._learned_config[target] = value
                    logger.info("Level A applied: %s = %s", target, value)
                    return True

            elif level == "B":
                # Level B: 通过 dynamic_scaler 调整
                if hasattr(omega, "dynamic_scaler"):
                    omega.dynamic_scaler.update(target, value)
                    logger.info("Level B applied: %s = %s", target, value)
                    return True

            elif level == "C":
                # Level C: 记录日志，不自动执行
                logger.info(
                    "Level C suggestion: %s - value=%s",
                    target, str(value)[:100],
                )
                return True  # 返回 True 表示"已处理"

        except Exception as e:
            logger.debug("apply_mapping failed: %s", e)

        return False

    def analyze_and_apply(self, context: str, tags: list[str], omega: Any) -> dict:
        """分析上下文并应用翻译。在 evolve 管道中调用。

        Args:
            context: 进化上下文（知识内容）。
            tags: 知识标签。
            omega: Omega 实例。

        Returns:
            {applied: int, summary: str, changes: dict}
        """
        if not context:
            return {"applied": 0, "summary": "no_context", "changes": {}}

        # 去重：相同内容只翻译一次
        content_hash = hash(context)
        if content_hash in self._applied_hashes:
            return {"applied": 0, "summary": "duplicate", "changes": {}}
        self._applied_hashes.add(content_hash)

        applied = []
        changes = {}

        # 生成映射
        mappings = self.analyze_knowledge(context, tags)

        # 应用每个映射
        for m in mappings:
            if self.apply_mapping(m, omega):
                level = m.get("level", "?")
                target = m.get("target", "?")
                value = m.get("value", "?")
                applied.append(f"{level}:{target}={value}")
                if level in ("A", "B"):
                    changes[target] = value

        return {
            "applied": len(applied),
            "summary": ", ".join(applied) if applied else "none",
            "changes": changes,
        }

    def scan_for_opportunities(self, store: Any, utility_threshold: float = 0.6) -> dict:
        """扫描 store 中未翻译的高 utility 知识。

        Args:
            store: MinervaStore 实例。
            utility_threshold: 最小 utility 值（可通过 _learned_config 外部调整）。

        Returns:
            {untranslated_count: int, sample: list}
        """
        try:
            nodes = store.get_active_nodes(limit=50)
            untranslated = []
            for n in nodes:
                util = getattr(n, "utility", 0.5)
                tags = getattr(n, "tags", []) or []
                if util >= utility_threshold and "translated" not in tags:
                    untranslated.append({
                        "id": n.id[:16],
                        "utility": util,
                        "content": getattr(n, "content", "")[:80],
                    })
            return {
                "untranslated_count": len(untranslated),
                "sample": untranslated[:3],
            }
        except Exception as e:
            logger.debug("scan_for_opportunities failed: %s", e)
            return {"untranslated_count": 0, "sample": []}

    # ── 私有提取方法 ──────────────────────────────────

    def _extract_parameters(self, content_lower: str, tags: list[str]) -> dict[str, Any]:
        """从知识中提取参数变更建议。"""
        changes: dict[str, Any] = {}

        # 衰减相关关键词
        if "decay" in content_lower:
            for token in content_lower.split():
                try:
                    v = float(token.strip(".,;()[]"))
                    changes["utility_decay_rate"] = v
                except ValueError:
                    continue

        # fitness 相关
        if "fitness" in content_lower:
            if "energy" in content_lower or "thermodynamic" in content_lower:
                changes["fitness_energy_weight"] = 0.15

        # curiosity 相关
        if "curiosity" in content_lower:
            if "decrease" in content_lower or "reduce" in content_lower:
                changes["curiosity_decay"] = 0.3

        return changes

    def _extract_strategies(
        self, content_lower: str, tags: list[str],
    ) -> list[tuple[str, Any, float]]:
        """从知识中提取策略变更建议。

        Returns:
            [(target, value, confidence)]
        """
        suggestions: list[tuple[str, Any, float]] = []

        # recall 策略
        if "recall" in content_lower and "graph" in content_lower:
            if "priority" in content_lower or "weight" in content_lower:
                suggestions.append(("recall_graph_weight", 1.3, 0.5))

        # learn 策略
        if "learn" in content_lower and "curiosity" in content_lower:
            suggestions.append(("learn_curiosity_boost", 0.2, 0.4))

        # consolidate 策略
        if "consolidat" in content_lower and "utility" in content_lower:
            suggestions.append(("dream_priority_tag", "high_utility", 0.5))

        return suggestions

    def _extract_capability(self, content: str, tags: list[str]) -> dict | None:
        """从知识中提取新能力描述。"""
        content_lower = content.lower()
        if "method" in content_lower or "approach" in content_lower:
            lines = content.split("\n")
            title = lines[0][:100] if lines else "unknown"
            return {
                "name": f"kta_{hash(content) & 0xFFFF}",
                "title": title,
                "content": content[:500],
                "tags": tags[:5],
            }
        return None
