"""
KnowledgeRuminationEngine — 学习管道中的"温故知新"环节

设计定位（2026-07-15 重新设计）：
    反刍不是旁路垃圾回收，而是 learn 管道内的一个周期触发分支。
    它定期把存量知识"重新学习"一遍：
        温故 -> 从 store 取出存量节点（基于 learn_feedback 的访问/命中信号选优先）
        知新 -> 对节点重新跑 SemanticLearner（抽概念/关系）、重新跑 KnowledgeToMechanism
               （翻参数/策略/Level C 能力），把沉睡知识重新提炼成系统能力。

复用资产（不重复造轮子）：
    - Omega.semantic_learner  : SemanticLearner.learn(content, tags)
    - Omega.knowledge_to_mechanism : analyze_knowledge(content, tags) / apply_mapping(m, omega)
    - Omega.learn_feedback    : 提供"哪些知识被用过/没用过"的信号
    - Omega.skill_registry    : 高频模式注册回可执行技能
    - store.get_active_nodes / get_branch_nodes / update_node : 合法遍历与写回（不再裸 SQL）

反刍产出（温故知新的"新"）：
    1. 重新抽取的概念/关系 -> 写回节点的 tags / 关联（通过 update_node）
    2. 重新翻译的机制映射 -> apply_mapping 落 _learned_config / skill_registry
    3. utility 重评估 -> 被 SemanticLearner 抽到关系 / 被 KTM 翻译成功的节点升 utility
    4. 低频沉睡节点 -> 降 utility（但仍保留，除非 utility 跌破底线才清理）
"""
from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from typing import Any
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class RuminationResult:
    """反刍一轮的结果摘要"""
    total_scanned: int = 0
    relearned: int = 0              # 真正重新学习（跑过 SemanticLearner+KTM）的节点数
    concepts_extracted: int = 0
    relations_extracted: int = 0
    mappings_applied: int = 0       # 通过 KnowledgeToMechanism 落地的机制数
    skills_promoted: int = 0        # 注册/晋升到 skill_registry 的数量
    routed_nodes: int = 0           # 分类路由补全 NodeType/rail 的节点数(层2)
    utility_raised: int = 0
    utility_lowered: int = 0
    deleted_nodes: int = 0
    details: dict[str, Any] = field(default_factory=dict)


class KnowledgeRuminationEngine:
    """学习管道中的温故知新引擎。

    通过 Omega 注入的依赖工作，自身不持有 store 直连 SQL。
    """

    def __init__(
        self,
        omega,
        stale_threshold_days: float = 30.0,
        low_utility_threshold: float = 0.15,
        high_access_threshold: int = 5,
        full_interval_seconds: float = 21600.0,   # 默认 6h 全量
        incremental_interval_seconds: float = 1800.0,  # 默认 30min 增量
        state_path: str | None = None,  # 调度状态持久化路径(跨重启保留反刍周期)
    ):
        self.omega = omega
        self.store = getattr(omega, "store", None)
        self.semantic_learner = getattr(omega, "semantic_learner", None)
        self.ktm = getattr(omega, "knowledge_to_mechanism", None)
        self.learn_feedback = getattr(omega, "learn_feedback", None)
        self.skill_registry = getattr(omega, "skill_registry", None)

        # 配置
        self.stale_threshold_days = stale_threshold_days
        self.low_utility_threshold = low_utility_threshold
        self.high_access_threshold = high_access_threshold
        self.full_interval_seconds = full_interval_seconds
        self.incremental_interval_seconds = incremental_interval_seconds

        # 调度状态 — 默认内存态, 若 state_path 给定则加载持久化值
        self.state_path = state_path
        self.last_full_rumination: float = 0.0
        self.last_incremental_rumination: float = 0.0
        self.history: list = []
        if state_path:
            self._load()

    # ------------------------------------------------------------------
    # 依赖同步：修正初始化顺序 bug
    # Omega 在实例化本引擎（life.py:449）之后才创建 knowledge_to_mechanism
    # (life.py:616) 与 skill_registry (life.py:555)，构造期缓存会拿到 None，
    # 导致"知新→翻机制"与"高频模式晋升 skill"两半形同虚设。
    # 每次 ruminate 时重新绑定，消除时序耦合。
    # ------------------------------------------------------------------
    def _sync_omega_deps(self) -> None:
        self.store = getattr(self.omega, "store", None)
        self.semantic_learner = getattr(self.omega, "semantic_learner", None)
        self.ktm = getattr(self.omega, "knowledge_to_mechanism", None)
        self.learn_feedback = getattr(self.omega, "learn_feedback", None)
        self.skill_registry = getattr(self.omega, "skill_registry", None)

    # ------------------------------------------------------------------
    # 公开入口：learn 管道调用
    # ------------------------------------------------------------------
    def ruminate(self, mode: str = "auto", limit: int | None = None,
                 force: bool = False) -> RuminationResult:
        self._sync_omega_deps()  # 修正初始化顺序 bug：Omega 后期才建 ktm/skill_registry
        """执行一轮反刍（温故知新）。

        Args:
            mode: "auto" | "full" | "incremental"
                - auto: 按时间间隔自动选 full/incremental
                - full: 扫描全部存量节点
                - incremental: 只扫近期低价值/未充分利用的节点
            limit: 限制本轮扫描节点数（调试/防爆）
            force: 忽略时间间隔强制执行
        """
        now = time.time()
        mode = self._resolve_mode(mode, now, force)

        nodes = self._select_nodes(mode, limit)
        result = RuminationResult(total_scanned=len(nodes))

        if not nodes:
            logger.info("[Rumination] 无候选节点，跳过")
        else:
            logger.info("[Rumination:%s] 温故 %d 个存量节点", mode, len(nodes))

            for node in nodes:
                self._relearn_node(node, result)

            # 高频模式 -> 晋升 skill（知新的系统级产出）
            self._promote_frequent_patterns(result)

            # 层3: 燃料供给 — 统计 rail 标签分布, 通知神经系统调度四轨
            self._supply_fuel(result)

        # 更新调度时间戳
        if mode == "full":
            self.last_full_rumination = now
        else:
            self.last_incremental_rumination = now

        self.history.append(result)
        if len(self.history) > 10:
            self.history = self.history[-10:]

        # 持久化调度状态(跨重启保留反刍周期, 避免 cron 高频重启清零导致永远不触发)
        self._persist()

        logger.info("[Rumination:%s] 完成 relearned=%d mappings=%d skills=%d",
                    mode, result.relearned, result.mappings_applied, result.skills_promoted)

        # 发布 rumination_completed 事件，供 Telemetry 采集（修复神经系统对反刍失明）
        # 注意: CIPEventBus.publish(event_dict) 会把整个 dict 包进 event["data"]，
        #   因此真实字段必须放在顶层(与 remember/evolve 等管道一致)，不能嵌套二级 data。
        try:
            bus = getattr(self.omega, "event_bus", None)
            if bus is not None and hasattr(bus, "publish"):
                bus.publish({
                    "type": "rumination_completed",
                    "total_scanned": result.total_scanned,
                    "relearned": result.relearned,
                    "concepts_extracted": result.concepts_extracted,
                    "relations_extracted": result.relations_extracted,
                    "mappings_applied": result.mappings_applied,
                    "skills_promoted": result.skills_promoted,
                    "routed_nodes": result.routed_nodes,
                    "utility_raised": result.utility_raised,
                    "deleted_nodes": result.deleted_nodes,
                    "pending_t3": result.details.get("pending_t3", 0),
                    "pending_t4": result.details.get("pending_t4", 0),
                    "fuel_supplied": result.details.get("fuel_supplied", False),
                })
        except Exception as e:
            logger.warning("KnowledgeRuminationEngine: publish rumination_completed failed: %s", e)

        return result

    # ------------------------------------------------------------------
    # 温故：选节点
    # ------------------------------------------------------------------
    def _resolve_mode(self, mode: str, now: float, force: bool) -> str:
        if mode != "auto":
            return mode
        if force:
            return "full"
        since_full = now - self.last_full_rumination
        if since_full >= self.full_interval_seconds:
            return "full"
        since_inc = now - self.last_incremental_rumination
        if since_inc >= self.incremental_interval_seconds:
            return "incremental"
        return "skip"

    def _select_nodes(self, mode: str, limit: int | None) -> list:
        """从 store 取出存量节点。

        full: 全量遍历（用 get_branch_nodes，避免只取 top-N 漏掉沉睡节点）
        incremental: 优先选"沉睡"节点（低 access_count / 低 utility），用 get_active_nodes 后排序
        """
        if self.store is None:
            return []

        try:
            if mode == "full":
                # 全量遍历所有分支活跃节点
                # 当有限额时，优先反刍"沉睡"节点（低 access / 低 utility），
                # 符合温故知新要照顾被遗忘知识的初衷
                nodes = self.store.get_branch_nodes("main")
                if limit:
                    nodes = sorted(
                        nodes,
                        key=lambda n: (n.access_count, n.utility, -n.created_at),
                    )
                    nodes = nodes[:limit]
            else:
                # 增量：取活跃节点后按"沉睡度"排序，优先反刍被遗忘的
                nodes = self.store.get_active_nodes(limit=limit or 200)
                nodes = sorted(
                    nodes,
                    key=lambda n: (n.access_count, n.utility, -n.created_at),
                )
                nodes = nodes[: (limit or 80)]
            return nodes
        except Exception as e:
            logger.error("[Rumination] 取节点失败: %s", e)
            return []

    # ------------------------------------------------------------------
    # 知新：重新学习单个节点
    # ------------------------------------------------------------------
    def _relearn_node(self, node, result: RuminationResult) -> None:
        """对一个存量节点执行温故知新。"""
        content = getattr(node, "content", "") or ""
        tags = list(getattr(node, "tags", []) or [])
        if not content:
            return

        new_concepts = 0
        new_relations = 0
        mappings_applied = 0

        # --- 知新 Step 1: 重新语义学习（抽概念/关系）---
        if self.semantic_learner is not None:
            try:
                r = self.semantic_learner.learn(content, tags)
                new_concepts += r.get("concepts_found", 0)
                new_relations += r.get("relations_found", 0) + r.get("inferred_relations", 0)
            except Exception as e:
                logger.debug("[Rumination] SemanticLearner 失败 node=%s: %s", node.id[:8], e)

        # --- 知新 Step 2: 重新机制翻译（翻参数/策略/能力）---
        if self.ktm is not None:
            try:
                mappings = self.ktm.analyze_knowledge(content, tags)
                for m in mappings:
                    if self.ktm.apply_mapping(m, self.omega):
                        mappings_applied += 1
            except Exception as e:
                logger.debug("[Rumination] KTM 失败 node=%s: %s", node.id[:8], e)

        result.relearned += 1
        result.concepts_extracted += new_concepts
        result.relations_extracted += new_relations
        result.mappings_applied += mappings_applied

        # --- 知新 Step 3: utility 重评估（写回 store，不再裸 SQL）---
        self._reevaluate_utility(node, new_concepts, new_relations, mappings_applied, result)

        # --- 知新 Step 4: 分类路由(层2) — 补全/修正 NodeType + rail 标签 ---
        # learn 写入时已打基础标签, 此处基于重学产出(KTM映射/概念)补全轨道归属
        self._route_node_type(node, concepts=new_concepts, mappings=mappings_applied, result=result)

    def _reevaluate_utility(self, node, concepts: int, relations: int,
                            mappings: int, result: RuminationResult) -> None:
        """根据重新学习的产出调整 utility，并写回 store。"""
        if self.store is None:
            return

        try:
            old_util = float(getattr(node, "utility", 0.5))
            # 被重新抽出结构 / 翻出机制的节点 -> 升 utility
            gain = 0.0
            if concepts > 0:
                gain += 0.03
            if relations > 0:
                gain += 0.04
            if mappings > 0:
                gain += 0.05 * min(mappings, 3)

            # 沉睡但未产生新知识 -> 轻微降 utility（仍保留，除非跌破底线）
            access = getattr(node, "access_count", 0)
            if access == 0 and concepts == 0 and relations == 0 and mappings == 0:
                gain -= 0.02

            # P1-c (论文② HeRA 借力): 跨 NodeType 拓扑对齐 (MKNN 局部邻域保持)
            # 论文核心: 跨模态表示对齐到细粒度(head级), 保持拓扑邻域关系.
            # 映射到 ULTRA: 一个节点若跨越多个轨道(rail_t1~t4 共存), 说明它
            # 在类型拓扑里连接多类知识(模态对齐), 应获对齐增益(而非孤立降级).
            tags_l = [t for t in (getattr(node, "tags", []) or [])]
            rails = [t for t in tags_l if t.startswith("rail_t")]
            if len(rails) >= 2:
                gain += 0.04  # 跨模态对齐增益(拓扑邻域保持)

            new_util = max(0.0, min(1.0, old_util + gain))

            if new_util > old_util + 1e-6:
                result.utility_raised += 1
            elif new_util < old_util - 1e-6:
                result.utility_lowered += 1

            # 跌破底线才清理（默认极保守，0.15）
            if new_util < self.low_utility_threshold and access == 0:
                wr = self.store.delete_node(node.id)
                if getattr(wr, "success", False):
                    result.deleted_nodes += 1
                return

            # 写回：复用 store.update_node（合法 API，不裸 SQL）
            node.utility = new_util
            self.store.update_node(node)
        except Exception as e:
            logger.debug("[Rumination] 写回 utility 失败 node=%s: %s", node.id[:8], e)

    def _route_node_type(self, node, concepts: int, mappings: int, result: RuminationResult) -> None:
        """分类路由(层2): 基于重学产出补全节点的 NodeType + rail 标签。

        温故知新不只是重估 utility —— 重学时 SemanticLearner/KTM 可能发现
        节点新的结构(参数映射/概念关系), 应据此补全轨道归属, 让下游四轨
        能正确消费该知识(不重拉源)。
        """
        if self.store is None:
            return
        if node is None:
            return
        try:
            from prometheus_nexus.foundation.schema import NodeType
            tags = list(getattr(node, "tags", []) or [])
            changed = False

            # KTM 翻出参数/策略映射 -> 确保 rail_t1(促参数进化)
            if mappings > 0 and "rail_t1" not in tags:
                tags.append("rail_t1")
                changed = True
            # 抽出概念关系 -> 确保 rail_t2(促语义进化)
            if concepts > 0 and "rail_t2" not in tags and "rail_t4" not in tags:
                tags.append("rail_t2")
                changed = True

            # 补全 NodeType: 若 learn 时未设(仍为 FACT)但有明确轨道信号
            ntype = getattr(node, "type", NodeType.FACT)
            if ntype == NodeType.FACT:
                if "rail_t1" in tags:
                    ntype = NodeType.PROCEDURE
                    changed = True
                elif "rail_t2" in tags and "rail_t4" not in tags:
                    ntype = NodeType.CONCEPT
                    changed = True

            if changed:
                node.tags = tags
                node.type = ntype
                self.store.update_node(node)
                result.routed_nodes = getattr(result, "routed_nodes", 0) + 1
        except Exception as e:
            logger.debug("[Rumination] 路由失败 node=%s: %s", node.id[:8], e)

    def _supply_fuel(self, result: RuminationResult) -> None:
        """燃料供给(层3): 盘点 rail 标签分布, 通知神经系统调度四轨。

        温故知新不止于重学 —— 若反刍发现某类轨道知识堆积(已被 learn 吸收
        但未进入对应进化轨道), 应通知 autonomic_regulator 优先触发 T3/T4
        去消化, 形成 '反刍发现缺口 -> 四轨知新' 闭环。
        """
        if self.store is None or self.omega is None:
            return
        try:
            ar = getattr(self.omega, "autonomic_regulator", None)
            if ar is None:
                return
            # 统计 store 中待处理的 rail_t3/rail_t4 节点数(知识已吸收, 机制未提取/编译)
            # 注意: 遍历全量(而非 limit=500), 避免种子数据淹没真实 rail 节点
            pending_t3 = pending_t4 = 0
            for n in self.store.get_active_nodes(limit=100000):
                tags = getattr(n, "tags", []) or []
                if "rail_t3" in tags:
                    pending_t3 += 1
                elif "rail_t4" in tags:
                    pending_t4 += 1
            result.details["pending_t3"] = pending_t3
            result.details["pending_t4"] = pending_t4
            # 堆积超阈值 -> 通知神经系统触发外部进化
            if pending_t3 >= 3 or pending_t4 >= 3:
                try:
                    ar._trigger_external_evolution(self.omega._compute_fitness() if hasattr(self.omega, "_compute_fitness") else 0.5)
                    result.details["fuel_supplied"] = True
                except Exception as e:
                    logger.debug("[Rumination] 供给燃料失败: %s", e)
        except Exception as e:
            logger.debug("[Rumination] _supply_fuel 失败: %s", e)

    # ------------------------------------------------------------------
    # 知新：系统级产出（高频模式晋升 skill）
    # ------------------------------------------------------------------
    def _promote_frequent_patterns(self, result: RuminationResult) -> None:
        """把本轮高频共现的 tag 模式注册/晋升为技能。

        这是"温故知新"的系统级落点：反复出现的知识主题
        应当成为系统可主动调用的技能，而非沉睡在 store。
        """
        if self.skill_registry is None or self.learn_feedback is None:
            return

        # 从 learn_feedback 提取高频 query 主题
        try:
            qstats = getattr(self.learn_feedback, "_query_stats", {})
            freq: dict[str, int] = defaultdict(int)
            for (src, q), st in qstats.items():
                if st.get("registered", 0) >= 3:
                    freq[q] += st["registered"]
            for q, cnt in freq.items():
                if cnt >= 3:
                    skill_name = f"rumination_pattern_{abs(hash(q)) % 100000}"
                    try:
                        self.skill_registry.register(
                            type("Skill", (), {"name": skill_name, "topic": q, "origin": "rumination"})()
                        )
                        result.skills_promoted += 1
                    except Exception as e:
                        logger.warning(
                            "[Rumination] 技能晋升注册失败 skill=%s: %s", skill_name, e
                        )
        except Exception as e:
            logger.warning("[Rumination] 模式晋升失败: %s", e)

    # ------------------------------------------------------------------
    # 调度状态持久化 (跨重启保留反刍周期)
    # ------------------------------------------------------------------
    def _persist(self) -> None:
        """原子写调度状态到 state_path (JSON). 失败告警(不阻塞反刍, 但生产须可见)."""
        state_path = getattr(self, "state_path", None)
        if not state_path:
            return
        try:
            import os, json
            os.makedirs(os.path.dirname(state_path) or ".", exist_ok=True)
            tmp = state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({
                    "last_full_rumination": getattr(self, "last_full_rumination", 0.0),
                    "last_incremental_rumination": getattr(self, "last_incremental_rumination", 0.0),
                    "history_len": len(getattr(self, "history", []) or []),
                    "updated_at": time.time(),
                }, f, ensure_ascii=False, indent=2)
            os.replace(tmp, state_path)
        except Exception as e:
            logger.warning("[Rumination] persist failed: %s", e)

    def _load(self) -> None:
        """从 state_path 加载调度状态. 损坏/缺失则保持默认(0.0)."""
        import json
        state_path = getattr(self, "state_path", None)
        if not state_path:
            return
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                d = json.load(f)
            self.last_full_rumination = float(d.get("last_full_rumination", 0.0) or 0.0)
            self.last_incremental_rumination = float(d.get("last_incremental_rumination", 0.0) or 0.0)
            self.history = [None] * int(d.get("history_len", 0) or 0)
            logger.info("[Rumination] loaded state: full=%s inc=%s",
                        self.last_full_rumination, self.last_incremental_rumination)
        except FileNotFoundError:
            pass  # 首次运行, 保持默认
        except Exception as e:
            logger.warning("[Rumination] load failed (using defaults): %s", e)

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------
    def next_rumination_due(self, now: float | None = None) -> dict:
        """返回下次反刍调度信息（供心跳/监控使用）"""
        now = now or time.time()
        since_full = now - self.last_full_rumination
        since_inc = now - self.last_incremental_rumination
        return {
            "mode": "full" if since_full >= self.full_interval_seconds else (
                "incremental" if since_inc >= self.incremental_interval_seconds else "skip"),
            "seconds_to_full": max(0, self.full_interval_seconds - since_full),
            "seconds_to_incremental": max(0, self.incremental_interval_seconds - since_inc),
        }

    def get_stats(self) -> dict:
        return {
            "last_full": self.last_full_rumination,
            "last_incremental": self.last_incremental_rumination,
            "history_len": len(self.history),
            "semantic_learner_ready": self.semantic_learner is not None,
            "ktm_ready": self.ktm is not None,
            "store_ready": self.store is not None,
        }
