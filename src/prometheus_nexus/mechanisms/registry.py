"""MechanismRegistry — 机制注册表.

基于:
- "Plugin Architecture with Dependency Resolution"
  - 注册机制: 名称+元数据+依赖声明
  - 依赖解析: DAG拓扑排序
  - 生命周期: register/enable/disable/invoke
  - 健康检查: 调用统计+依赖验证

算法:
    register(name, dependencies):
        1. 创建机制条目
        2. 验证依赖(DAG无环)
        3. 设置初始状态
    
    resolve_dependencies():
        1. 构建依赖图
        2. 拓扑排序
        3. 返回执行顺序

复杂度:
    register(): O(D) 其中D=依赖数
    resolve_dependencies(): O(V+E)
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

from collections import defaultdict

from prometheus_nexus.mechanisms.base_mechanism import BaseMechanism


class MechanismRegistry:
    """机制注册表.
    
    支持依赖解析和健康检查.
    """
    
    def __init__(self, path: str | None = None):
        """初始化.

        path: 机制持久化文件路径(JSON). 非空则启动时 _load() 恢复机制态
        (解"机制注册表纯内存、重启全丢"根因 — B1 消费率/D1 回流
        此前在空 registry 上跑). None 则纯内存(测试/临时).
        """
        self._mechanisms: dict[str, dict] = {}
        self._enabled: set[str] = set()
        self._history: list[dict] = []
        self._health_checks: list[dict] = []
        # P0a: 激活消费者回调表 — 机制激活后按 category 触发"接生产"动作.
        # 例: "compiled"(T4)->host.emit_capability; T3 机制->evolution_engine.inject_gene_specs
        # 解 B1(僵尸机制): 激活不再只是 status=active, 而是真接生产/回流宿主.
        self._consumers: dict[str, callable] = {}
        # P1-b (论文⑥ Superposition CoT 借力): 机制叠加态候选
        # 论文核心: latent CoT 能在单表示里叠加多个候选解(superposition), 提升表达力.
        # 映射到 ULTRA: 同一问题保留多个机制候选的叠加态(各带权重),
        #   运行时按上下文动态选最相关的(而非固定激活一个). 这是 P6 A-B 并行的升级.
        self._superposed: dict[str, dict] = {}  # super_name -> {candidates: [{name, weight, draft_code, ...}]}
        # 持久化路径
        self._path = path
        if path:
            try:
                self._load()
            except Exception as e:
                logger.warning("MechanismRegistry: load from %s failed: %s", path, e)

    # ── 持久化 (方案A: JSON 文件, 契合 archive/ 本地产出物哲学) ──
    def _load(self) -> None:
        """从 JSON 恢复 _mechanisms / _enabled. 失败静默(纯内存启动)."""
        import json
        import os
        if not self._path or not os.path.exists(self._path):
            return
        with open(self._path, "r", encoding="utf-8") as f:
            blob = json.load(f)
        self._mechanisms = {k: dict(v) for k, v in blob.get("mechanisms", {}).items()}
        self._enabled = set(blob.get("enabled", []))
        # _history / _superposed 不持久(运行期临时态)

    def _persist(self) -> None:
        """序列化 _mechanisms / _enabled 到 JSON. 失败记 WARNING 暴露(不阻断主流程)."""
        if not self._path:
            return
        import json
        import os
        import threading
        try:
            os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
            blob = {
                "mechanisms": self._mechanisms,
                "enabled": sorted(self._enabled),
            }
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(blob, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self._path)  # 原子替换, 避免半写
        except Exception as e:
            logger.warning("MechanismRegistry._persist failed (registry durability lost): %s", e)
    
    def register(self, name: str, data: dict | None = None,
                 dependencies: list[str] | None = None,
                 category: str = "general",
                 pending: bool = False) -> dict:
        """注册机制.

        Args:
            name: 机制名称
            data: 元数据
            dependencies: 依赖列表
            category: 分类
            pending: 若为 True, 机制以 "pending" 状态注册(待验证激活),
                     不进 _enabled 集合, 需经 verify_and_activate() 验证通过才激活。
                     这是 P6 激活闭环的核心: T3/T4 产物默认 pending, 不自动直替生产。

        Returns:
            dict: 注册结果
        """
        deps = dependencies or []

        # 验证依赖是否存在
        missing_deps = [d for d in deps if d not in self._mechanisms]
        if missing_deps:
            return {
                "registered": False,
                "error": "missing_dependencies",
                "missing": missing_deps,
            }

        status = "pending" if pending else "registered"
        entry = {
            "name": name,
            "data": data or {},
            "dependencies": deps,
            "category": category,
            "status": status,
            "invoke_count": 0,
            "error_count": 0,
            "last_invoked": None,
            "activated_at": None,
        }

        self._mechanisms[name] = entry
        if not pending:
            self._enabled.add(name)
        self._persist()
        self._history.append({"action": "register", "name": name, "deps": deps, "pending": pending})

        return {
            "registered": True,
            "name": name,
            "dependencies": deps,
            "category": category,
            "status": status,
        }
    
    def enable(self, name: str) -> bool:
        """启用机制.
        
        Args:
            name: 机制名称
        
        Returns:
            bool: 是否成功
        """
        if name not in self._mechanisms:
            return False
        
        self._mechanisms[name]["status"] = "enabled"
        self._enabled.add(name)
        self._persist()
        self._history.append({"action": "enable", "name": name})
        return True
    
    def deactivate(self, name: str) -> bool:
        """P0b: 熔断回滚 — 把已激活/启用的机制移出 _enabled (状态置 disabled).

        区别于手动 disable(): 语义上用于"激活后验证有害, 自动熔断回滚".
        解 B3: 坏机制激活后若拖垮 fitness, 自动回滚而非永久驻留.
        """
        if name not in self._mechanisms:
            return False
        self._mechanisms[name]["status"] = "disabled"
        self._enabled.discard(name)
        self._persist()
        self._history.append({"action": "deactivate", "name": name, "reason": "circuit_break"})
        return True

    def disable(self, name: str) -> bool:
        """禁用机制.
        
        Args:
            name: 机制名称
        
        Returns:
            bool: 是否成功
        """
        if name not in self._mechanisms:
            return False
        
        self._mechanisms[name]["status"] = "disabled"
        self._enabled.discard(name)
        self._persist()
        self._history.append({"action": "disable", "name": name})
        return True
    
    def invoke(self, name: str, context: dict | None = None) -> bool:
        """调用机制。

        若机制 data 中带可执行对象(callable / BaseMechanism 实例), 则真执行;
        否则仅记账(向后兼容旧元数据机制)。

        Returns:
            bool: 是否成功
        """
        if name not in self._enabled:
            return False

        entry = self._mechanisms[name]
        entry["invoke_count"] += 1
        import time
        entry["last_invoked"] = time.time()

        executable = entry.get("data", {}).get("executable")
        draft_code = entry.get("data", {}).get("draft_code", "")
        # D2 真能力: active 机制优先经沙箱编译执行 draft_code(真能力生效, 非空壳)
        if draft_code and entry.get("status") == "active":
            try:
                from prometheus_nexus.integration.mechanism_sandbox import MechanismSandbox
                from prometheus_nexus.mechanisms import base_mechanism
                sb = MechanismSandbox()
                result = sb.run(name, draft_code, base_mechanism, context=context)
                entry["data"]["last_result"] = result
                if not result.get("ok", False):
                    entry["error_count"] = entry.get("error_count", 0) + 1
                    logger.warning("MechanismRegistry: sandbox run %s: %s", name, result.get("note"))
                    return False
                entry["last_executed_at"] = time.time()
                return True
            except Exception as e:
                logger.warning("MechanismRegistry: sandbox invoke %s failed: %s", name, e)
                entry["error_count"] = entry.get("error_count", 0) + 1
                return False
        # 降级: 原 executable.run (草案类/无 draft_code 机制)
        if executable is not None:
            try:
                if isinstance(executable, BaseMechanism):
                    result = executable.run(context or {})
                    ok = bool(result.get("ok", True)) if isinstance(result, dict) else True
                    entry["data"]["last_result"] = result
                    entry["error_count"] = entry.get("error_count", 0)
                    if not ok:
                        entry["error_count"] += 1
                    return ok
                if callable(executable):
                    executable(context or {})
                    return True
            except Exception as e:  # 机制执行失败不影响主流程
                logger.warning("MechanismRegistry: invoke %s failed: %s", name, e)
                entry["error_count"] = entry.get("error_count", 0) + 1
                return False
        return True
    
    def resolve_dependencies(self) -> list[str]:
        """解析依赖顺序(拓扑排序).
        
        Returns:
            list: 执行顺序(字符串列表)
        """
        # 构建邻接表
        graph = defaultdict(list)
        in_degree = defaultdict(int)
        
        for name, mech in self._mechanisms.items():
            if name not in in_degree:
                in_degree[name] = 0
            for dep in mech["dependencies"]:
                graph[dep].append(name)
                in_degree[name] += 1
        
        # Kahn算法
        queue = [n for n in self._mechanisms if in_degree[n] == 0]
        order = []
        
        while queue:
            node = queue.pop(0)
            order.append(node)
            for neighbor in graph[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        
        # 检测环
        if len(order) != len(self._mechanisms):
            return []  # 有环,返回空

        return order

    def verify_and_activate(self, name: str, claim: str = "", hypothesis: str = "",
                            graph: dict | None = None) -> dict:
        """P6 激活闭环: 验证机制是否可安全激活, 通过后翻为 active。

        三道门(不自动直替生产):
          1. IronLaw.verify(claim)  — 不违反核心约束
          2. AntiEvo.check(hypothesis) — 不退化/不重复
          3. FGGM.verify(graph)   — 图结构有效(若有图)

        全部通过 → activate(): status="active" + 进 _enabled。
        任一道门失败 → 保持 pending, 返回失败原因。

        Args:
            name: 机制名
            claim: IronLaw 验证声明(如机制描述)
            hypothesis: AntiEvo 假设(如机制名+来源)
            graph: FGGM 验证图(可选, 机制依赖图)

        Returns:
            dict: {activated: bool, gates: {...}, reason: str}
        """
        if name not in self._mechanisms:
            return {"activated": False, "reason": "not_found"}
        entry = self._mechanisms[name]
        if entry["status"] == "active":
            return {"activated": True, "reason": "already_active", "gates": {}}

        gates = {}
        # 门1: IronLaw
        try:
            from prometheus_nexus.evolution.iron_law import VerificationIronLaw
            iron = VerificationIronLaw(strict_fuzzy_rejection=True)
            r1 = iron.verify(claim or name)
            gates["iron_law"] = {"passed": bool(getattr(r1, "passed", False)),
                                 "confidence": getattr(r1, "confidence", 0.0)}
        except Exception as e:
            logger.debug("IronLaw verify failed: %s", e)
            # 失败关闭(fail-closed): 安全门执行异常 = 未能验证 = 不得当作通过
            logger.warning("MechanismRegistry: IronLaw gate errored, blocking activation: %s", e)
            gates["iron_law"] = {"passed": False, "confidence": 0.0,
                                 "error": str(e), "note": "gate_error"}

        # 门2: AntiEvo
        try:
            from prometheus_nexus.evolution.anti_evolution_gate import AntiEvolutionGate
            anti = AntiEvolutionGate()
            r2 = anti.check(hypothesis or name)
            gates["anti_evo"] = {"passed": bool(getattr(r2, "passed", False)),
                                 "verdict": getattr(r2, "verdict", "SAFE")}
        except Exception as e:
            logger.debug("AntiEvo check failed: %s", e)
            # 失败关闭(fail-closed): AntiEvo 门异常 = 未验证 = 不得激活
            logger.warning("MechanismRegistry: AntiEvo gate errored, blocking activation: %s", e)
            gates["anti_evo"] = {"passed": False, "verdict": "UNKNOWN",
                                 "error": str(e), "note": "gate_error"}

        # 门3: FGGM(仅当提供图时)
        if graph is not None:
            try:
                from prometheus_nexus.evolution.fggm import FGGVerifier
                fggm = FGGVerifier()
                r3 = fggm.verify(graph)
                gates["fggm"] = {"passed": bool(r3.get("valid", True)),
                                 "node_count": r3.get("node_count", 0)}
            except Exception as e:
                logger.debug("FGGM verify failed: %s", e)
                # 失败关闭(fail-closed): FGGM 门异常 = 未验证 = 不得激活
                logger.warning("MechanismRegistry: FGGM gate errored, blocking activation: %s", e)
                gates["fggm"] = {"passed": False, "error": str(e), "note": "gate_error"}

        # 全部通过才激活
        failed = [g for g, v in gates.items() if not v.get("passed", True)]
        if failed:
            entry["status"] = "blocked"
            self._history.append({"action": "blocked", "name": name, "gates": gates})
            return {"activated": False, "reason": f"gates_failed: {failed}", "gates": gates}

        entry["status"] = "active"
        entry["activated_at"] = __import__("time").time()
        self._enabled.add(name)
        self._history.append({"action": "activate", "name": name, "gates": gates})
        # P0a: 激活后触发消费者回调(接生产) — 解 B1 僵尸机制
        # T4(category=compiled)->host.emit_capability; T3->inject_gene_specs 等
        self._consume_active(name, entry)
        return {"activated": True, "reason": "verified", "gates": gates}

    def register_consumer(self, category: str, consumer: callable) -> None:
        """P0a: 注册某 category 的激活消费者.

        consumer(entry: dict) -> None  在机制激活后被调用, 负责把机制接进生产
        (如 T4 编译机制 -> 经 HostAgentAdapter 导出给宿主; T3 提取机制 -> 注入 gene_specs).
        这是 P6'不自动直替'原则的精确落地: 激活=通知消费者生成"建议/补丁",
        由消费者决定是否/如何接生产(通常走 A-B 并行或宿主确认, 非直接覆盖).
        """
        self._consumers[category] = consumer

    def _consume_active(self, name: str, entry: dict) -> None:
        """P0a: 按 category 派发激活事件给已注册消费者."""
        category = entry.get("category", "")
        consumer = self._consumers.get(category)
        if consumer is None:
            logger.debug("Registry: no consumer for category=%s (mechanism stays registered)", category)
            return
        try:
            result = consumer(entry)
            entry["consumed_at"] = __import__("time").time()
            # consumer 可返回 bool 表示宿主是否接受(emit 成功). 用于熔断精准化 [P1 C3]
            if isinstance(result, bool):
                entry["emit_accepted"] = result
            self._history.append({"action": "consume", "name": name, "category": category})
        except Exception as e:
            logger.warning("Registry: consumer for %s failed: %s", name, e)
            entry["consume_error"] = str(e)
    
    def get_enabled(self) -> list[str]:
        """返回当前已启用(含已激活)机制名列表. 公开接口供监控/熔断使用."""
        return list(self._enabled)

    def mark_host_used(self, name: str, effect: float = 0.0) -> None:
        """P1 C4: 宿主侧反馈机制实际被使用/效果. 用于有效性追踪.

        Ultra emit 机制给宿主后, 宿主若真用且有效, 应回调此方法记录(避免'emit 了但没用'盲区).
        effect>0 表示有益, <0 表示有害.
        """
        if name not in self._mechanisms:
            return
        e = self._mechanisms[name]
        e["host_used_count"] = e.get("host_used_count", 0) + 1
        e["last_host_effect"] = effect
        e["last_host_used_at"] = __import__("time").time()

    def health_check(self) -> dict:
        """健康检查.
        
        Returns:
            dict: 健康报告
        """
        issues = []
        
        # 检查孤立机制(未被依赖且从未调用)
        depended_on = set()
        for name, mech in self._mechanisms.items():
            for dep in mech["dependencies"]:
                depended_on.add(dep)
        
        for name in self._enabled:
            if self._mechanisms[name]["invoke_count"] == 0 and name not in depended_on:
                issues.append({"type": "unused", "mechanism": name})

        # P1 C4: 僵尸 emit — 激活且 emit 被宿主接受, 但宿主从未 mark_host_used(机制没真被用)
        for name in self._enabled:
            e = self._mechanisms[name]
            if e.get("category") in ("compiled", "extracted") and e.get("emit_accepted") is True:
                if e.get("host_used_count", 0) == 0:
                    issues.append({"type": "zombie_emit", "mechanism": name,
                                    "note": "emitted_to_host_but_never_used"})
        
        # 检查环依赖
        order = self.resolve_dependencies()
        if len(order) < len(self._mechanisms):
            issues.append({"type": "circular_dependency", "total": len(self._mechanisms), "resolved": len(order)})
        
        report = {
            "healthy": len(issues) == 0,
            "issues": issues,
            "total_mechanisms": len(self._mechanisms),
            "enabled": len(self._enabled),
            "total_invocations": sum(m["invoke_count"] for m in self._mechanisms.values()),
        }
        
        self._health_checks.append(report)
        return report
    
    def get_stats(self) -> dict:
        """获取统计."""
        categories = {}
        for mech in self._mechanisms.values():
            cat = mech["category"]
            categories[cat] = categories.get(cat, 0) + 1

        return {
            "registered": len(self._mechanisms),
            "enabled": len(self._enabled),
            "categories": categories,
            "history_size": len(self._history),
            "total_invocations": sum(m["invoke_count"] for m in self._mechanisms.values()),
        }

    # ============================================================
    # P0-a (论文③ Grad Token Pruning 借力): 机制级效用追踪 + 主动剪枝
    # 论文核心: 干扰pattern(伪相关)误导注意力 -> 梯度引导剪枝.
    # 映射到 ULTRA: 机制若反复负效用(伪相关/对宿主无价值), 主动剪枝,
    #   不等 fitness 连续下降才 C3 回滚(那是事后补救, 这是事前主动).
    # ============================================================
    def record_mechanism_effect(self, name: str, effect: float) -> None:
        """记录机制被宿主/系统使用后的效用反馈. effect∈[-1,1], 正=有益, 负=有害.

        这是论文③"梯度引导"的等效: 负反馈机制权重下降, 正反馈上升.
        """
        if name not in self._mechanisms:
            return
        e = self._mechanisms[name]
        hist = e.setdefault("effect_history", [])
        hist.append(effect)
        if len(hist) > 50:
            hist[:] = hist[-30:]
        # 滚动均值作为当前效用估计(梯度方向)
        e["effect_mean"] = sum(hist) / len(hist)

    def get_prune_candidates(self, threshold: float = -0.3) -> list[str]:
        """返回效用均值低于阈值的机制名(应被剪枝的'干扰pattern')."""
        out = []
        for name, e in self._mechanisms.items():
            mean = e.get("effect_mean")
            if mean is not None and mean < threshold and name in self._enabled:
                out.append(name)
        return out

    def prune_harmful(self, threshold: float = -0.3) -> int:
        """主动剪枝负效用机制 [P0-a]. 返回实际剪枝数.

        与 C3 熔断门区别: C3 是 fitness 下降后回滚(事后); 此处是机制效用
        持续为负即主动剪枝(事前梯度引导), 不等到拖垮系统. 对应论文③的
        '移除干扰pattern提升推理'.
        """
        rolled = 0
        for name in self.get_prune_candidates(threshold):
            if self.deactivate(name):
                rolled += 1
                logger.warning("Registry: pruned harmful mechanism %s (effect_mean=%.3f)",
                               name, self._mechanisms[name].get("effect_mean", 0.0))
        return rolled

    # ============================================================
    # P1-b (论文⑥ Superposition CoT 借力): 机制叠加态候选
    # 同一 super 机制存多个候选(各带 weight), 运行时按上下文动态选择最相关者.
    # ============================================================
    def register_superposed(self, super_name: str, candidates: list[dict]) -> None:
        """注册叠加态机制: 一组候选(各含 name/weight/draft_code/category).

        candidates: [{name, weight, draft_code, category, ...}]
        权重应归一化(0..1 之和≈1). 运行时 select_by_context 按上下文选最相关候选.
        """
        if not candidates:
            return
        # 归一化权重
        total = sum(max(0.0, c.get("weight", 1.0)) for c in candidates) or 1.0
        for c in candidates:
            c["weight"] = max(0.0, c.get("weight", 1.0)) / total
        self._superposed[super_name] = {"candidates": candidates}

    def select_by_context(self, super_name: str, context: str = "") -> dict | None:
        """从叠加态候选中选最相关者 [P1-b superposition].

        选择策略: 上下文与候选 claim/name 的 token 重叠度 × weight.
        返回选中的候选 dict(含 name/draft_code/weight), 或 None(无候选).
        """
        sp = self._superposed.get(super_name)
        if not sp:
            return None
        cands = sp["candidates"]
        if not cands:
            return None
        ctx_tokens = set(context.lower().split())
        best, best_score = None, -1.0
        for c in cands:
            claim = (c.get("claim") or c.get("name") or "").lower()
            overlap = len(ctx_tokens & set(claim.split())) if ctx_tokens else 0
            score = overlap + c.get("weight", 0.0)
            if score > best_score:
                best, best_score = c, score
        return best

    def get_superposed_names(self) -> list[str]:
        return list(self._superposed.keys())
