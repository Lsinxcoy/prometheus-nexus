"""B9: Progressive MCGS + EntropyScheduler + RetrospectiveMemory + StrategyCodingDecouple + ATP + GearSafety.

Progressive MCGS — 渐进式蒙特卡洛图搜索，基于UCB1树展开和跨分支协同搜索。
EntropyScheduler — 基于熵的探索/利用调度，含温度退火和自适应相位切换。
RetrospectiveMemory — 冷热双存储记忆系统，支持领域知识初始化和动态键值检索。
StrategyCodingDecouple — 策略与代码解耦，基于历史成功率的适应/稳定模式选择。
ATPValidator — 对齐真实性验证器，检查步骤陈旧性、冲突、资源依赖和循环依赖。
GearSafety — 基于风险的5档变速安全齿轮（idle/cautious/normal/fast/autonomous）。
"""
from __future__ import annotations
import logging
import math
import time
from collections import defaultdict, deque
from typing import Any

logger = logging.getLogger(__name__)


class ProgressiveMCGS:
    """渐进式蒙特卡洛图搜索（Progressive Monte Carlo Graph Search）。

    核心算法：
    1. expand(): 在树上展开新分支，记录探索计数和引用
    2. search_across_branches(): 跨分支查询，支持关键词匹配和UCB1加权排序
    3. ucb1_select(): 基于UCB1公式选择最有潜力的未充分探索分支
    4. get_best_path(): 返回探索次数最多的分支路径
    """

    def __init__(self, exploration_weight: float = 1.414):
        self._trees: dict[int, dict] = {}
        self._branch_stats: dict[str, dict] = {}  # branch -> {visits, value, last_updated}
        self._exploration_weight = exploration_weight
        self._search_history: list[dict] = []

    def expand(self, tree: dict | None, branch: str,
               refs: list | None = None) -> dict:
        """在树上展开一个新分支。

        Args:
            tree: 目标树（为空则创建新树）。
            branch: 分支名称。
            refs: 分支引用数据。

        Returns:
            更新后的树。
        """
        tree = tree or {}
        if branch not in tree:
            tree[branch] = {
                "explored": 0,
                "refs": refs or [],
                "created_at": time.time(),
            }
            self._branch_stats[branch] = {
                "visits": 0,
                "total_value": 0.0,
                "last_updated": time.time(),
            }
        self._trees[id(tree)] = tree
        return tree

    def search_across_branches(self, trees: list[dict] | None,
                               query: str, top_k: int = 5) -> list[dict]:
        """跨分支搜索匹配项。

        使用关键词解构查询，在分支名和数据中查找匹配。
        结果按UCB1分数降序排列。

        Args:
            trees: 树列表。
            query: 搜索关键词。

        Returns:
            匹配的分支列表，按UCB1排序。
        """
        query_lower = query.lower().strip()
        query_tokens = set(query_lower.split())
        candidates = []

        for t in trees or []:
            for branch, data in t.items():
                branch_lower = branch.lower()
                branch_tokens = set(branch_lower.replace("_", " ").split())
                # 关键词匹配（支持下划线分隔的复合词）
                if query_tokens & branch_tokens or query_lower in branch_lower:
                    # 精确匹配优先
                    stats = self._branch_stats.get(branch, {"visits": 0, "total_value": 0.0})
                    # UCB1评分
                    n = max(stats["visits"], 1)
                    total_visits = sum(s["visits"] for s in self._branch_stats.values()) or 1
                    q_value = stats["total_value"] / n if n > 0 else 0.0
                    ucb_score = q_value + self._exploration_weight * math.sqrt(
                        math.log(total_visits) / n
                    )
                    candidates.append({
                        "branch": branch,
                        "data": data,
                        "score": round(ucb_score, 4),
                        "visits": n,
                    })
                    # 更新访问计数
                    self._branch_stats[branch]["visits"] += 1

        candidates.sort(key=lambda x: x["score"], reverse=True)
        self._search_history.append({
            "query": query,
            "results": len(candidates),
            "timestamp": time.time(),
        })
        return candidates[:top_k] if top_k else candidates

    def ucb1_select(self, tree: dict, top_k: int = 3) -> list[dict]:
        """基于UCB1选择最有潜力的分支。

        Args:
            tree: 目标树。
            top_k: 返回top-K个分支。

        Returns:
            UCB1分数��高的分支列表。
        """
        if not tree:
            return []
        scored = []
        total_visits = sum(
            s["visits"] for s in self._branch_stats.values()
        ) or 1

        for branch, data in tree.items():
            stats = self._branch_stats.get(branch, {"visits": 1, "total_value": 0.0})
            n = max(stats["visits"], 1)
            q_value = stats["total_value"] / n
            ucb = q_value + self._exploration_weight * math.sqrt(
                math.log(total_visits) / n
            )
            scored.append({
                "branch": branch,
                "ucb_score": round(ucb, 4),
                "visits": n,
                "value": round(q_value, 4),
            })

        scored.sort(key=lambda x: x["ucb_score"], reverse=True)
        return scored[:top_k]

    def record_outcome(self, branch: str, value: float):
        """记录分支执行结果，更新UCB值。

        Args:
            branch: 分支名称。
            value: [0,1] 之间的执行得分。
        """
        value = max(0.0, min(1.0, value))
        if branch not in self._branch_stats:
            self._branch_stats[branch] = {"visits": 0, "total_value": 0.0, "last_updated": 0}
        self._branch_stats[branch]["visits"] += 1
        self._branch_stats[branch]["total_value"] += value
        self._branch_stats[branch]["last_updated"] = time.time()

    def get_best_path(self, tree: dict) -> dict | None:
        """返回探索次数最多的分支（最有信心的路径）。

        Args:
            tree: 目标树。

        Returns:
            最佳分支信息，或空。
        """
        if not tree:
            return None
        best_branch = None
        best_visits = -1
        for branch in tree:
            stats = self._branch_stats.get(branch, {"visits": 0})
            if stats["visits"] > best_visits:
                best_visits = stats["visits"]
                best_branch = branch
        if best_branch:
            return {
                "branch": best_branch,
                "visits": best_visits,
                "data": tree.get(best_branch),
            }
        return None

    def get_stats(self) -> dict:
        return {
            "trees": len(self._trees),
            "branches": len(self._branch_stats),
            "total_visits": sum(s["visits"] for s in self._branch_stats.values()),
            "avg_value": round(
                sum(s["total_value"] for s in self._branch_stats.values()) /
                max(sum(s["visits"] for s in self._branch_stats.values()), 1), 4
            ) if self._branch_stats else 0.0,
            "searches": len(self._search_history),
        }


class EntropyScheduler:
    """基于熵的探索/利用调度器。

    核心逻辑：
    1. schedule(): 根据当前熵值和探索进度计算相位和温度。
       - 高熵（>0.5）→ 探索阶段，温度与熵正相关
       - 低熵（≤0.5）→ 利用阶段，温度与熵负相关
    2. 温度退火：使用 exponential decay 使温度随调度次数递减。
    3. 自适应相位切换：连续低增益触发"重启"信号。
    """

    def __init__(self, initial_temp: float = 1.0, min_temp: float = 0.05,
                 decay_rate: float = 0.01):
        self._initial_temp = initial_temp
        self._min_temp = min_temp
        self._decay_rate = decay_rate
        self._steps: list[dict] = []
        self._step_count = 0
        self._low_gain_streak = 0

    def schedule(self, entropy: float, explored: float,
                 gain: float | None = None) -> dict:
        """根据熵值和探索进度计算调度结果。

        Args:
            entropy: [0,1] 当前系统熵值。
            explored: [0,1] 已探索比例。
            gain: 可选，上一轮的信息增益。

        Returns:
            调度结果：{phase, temperature, restart_signal, step}.
        """
        self._step_count += 1
        entropy = max(0.0, min(1.0, entropy))
        explored = max(0.0, min(1.0, explored))

        # 温度退火（指数衰减）
        temp = self._initial_temp * math.exp(-self._decay_rate * self._step_count)
        temp = max(self._min_temp, temp)

        # 相位决策：高熵探索，低熵利用
        if entropy > 0.5:
            # 探索阶段：温度随熵增加
            phase = "explore"
            temperature = temp * (entropy * 2.0)  # 0.5~2.0倍基础温度
        else:
            # 利用阶段：温度随探索进度衰减
            phase = "exploit"
            temperature = temp * (0.2 + 0.3 * (1.0 - explored))

        temperature = round(min(2.0, max(0.0, temperature)), 4)

        # 自适应重启检测
        restart = False
        if gain is not None:
            if gain < 0.05:
                self._low_gain_streak += 1
            else:
                self._low_gain_streak = 0
            if self._low_gain_streak >= 5:
                restart = True
                self._low_gain_streak = 0

        result = {
            "phase": phase,
            "temperature": temperature,
            "restart_signal": restart,
            "step": self._step_count,
            "entropy": entropy,
            "explored": explored,
        }
        self._steps.append(result)
        return result

    def get_stats(self) -> dict:
        if not self._steps:
            return {"steps": 0}
        phases = [s["phase"] for s in self._steps]
        return {
            "steps": self._step_count,
            "avg_temperature": round(
                sum(s["temperature"] for s in self._steps) / len(self._steps), 4
            ),
            "explore_ratio": round(phases.count("explore") / len(phases), 4),
            "exploit_ratio": round(phases.count("exploit") / len(phases), 4),
            "restarts": sum(1 for s in self._steps if s.get("restart_signal")),
            "last_phase": self._steps[-1]["phase"] if self._steps else "N/A",
        }


class RetrospectiveMemory:
    """回顾性记忆（冷热双存储）。

    热存储（_dynamic）：快速读写，用于会话内临时数据。
    冷存储（_cold）：结构化领域知识库，初始化后只读。

    ���索策略：
    1. 先在热存储中精确查找
    2. 再在冷存储中按领域前缀模糊匹配
    3. 支持跨域查询（query包含多个领域名时)
    """

    def __init__(self):
        self._cold: dict[str, Any] = {}
        self._dynamic: dict[str, Any] = {}
        self._access_log: deque = deque(maxlen=1000)

    def init_knowledge_base(self, domain: str, knowledge: Any):
        """初始化领域知识库（冷存储，只读）。"""
        self._cold[domain] = knowledge
        self._access_log.append({
            "action": "init_kb", "domain": domain, "ts": time.time()
        })

    def store_global(self, key: str, value: Any):
        """存储动态数据（热存储，读写）。"""
        self._dynamic[key] = value
        self._access_log.append({
            "action": "store", "key": key, "ts": time.time()
        })

    def retrieve(self, query: str) -> Any | None:
        """检索知识。

        ���略：
        1. 热存储精确匹配
        2. 冷存储领域前缀匹配
        3. 冷存储跨域关键词匹配

        Args:
            query: 查询字符串。

        Returns:
            匹配��知识条目，或None。
        """
        query_lower = query.lower().strip()

        # 1. 热存储精确匹配
        if query in self._dynamic:
            self._access_log.append({
                "action": "retrieve_dynamic", "query": query, "ts": time.time()
            })
            return self._dynamic[query]

        # 2. 热存储模糊匹配（键包含查询）
        for key, value in self._dynamic.items():
            if query_lower in key.lower():
                self._access_log.append({
                    "action": "retrieve_dynamic_fuzzy", "query": query,
                    "matched": key, "ts": time.time()
                })
                return value

        # 3. 冷存储领域前缀匹配
        if query in self._cold:
            self._access_log.append({
                "action": "retrieve_cold", "query": query, "ts": time.time()
            })
            return self._cold[query]

        # 4. 冷存储跨域搜索
        for domain, knowledge in self._cold.items():
            if domain.lower() in query_lower or query_lower in domain.lower():
                self._access_log.append({
                    "action": "retrieve_cold_cross", "query": query,
                    "domain": domain, "ts": time.time()
                })
                return knowledge

        # 5. 关键词片段匹配
        query_tokens = set(query_lower.split())
        for domain, knowledge in self._cold.items():
            domain_tokens = set(domain.lower().split())
            if query_tokens & domain_tokens:
                self._access_log.append({
                    "action": "retrieve_cold_token", "query": query,
                    "domain": domain, "ts": time.time()
                })
                return knowledge

        self._access_log.append({
            "action": "miss", "query": query, "ts": time.time()
        })
        return None

    def get_stats(self) -> dict:
        cold_keys = list(self._cold.keys())
        access_types = defaultdict(int)
        for entry in self._access_log:
            access_types[entry["action"]] += 1
        return {
            "cold": len(self._cold),
            "dynamic": len(self._dynamic),
            "cold_domains": cold_keys[:5],
            "total_accesses": len(self._access_log),
            "hit_count": access_types.get("retrieve_dynamic", 0)
                        + access_types.get("retrieve_cold", 0)
                        + access_types.get("retrieve_cold_cross", 0)
                        + access_types.get("retrieve_cold_token", 0)
                        + access_types.get("retrieve_dynamic_fuzzy", 0),
            "miss_count": access_types.get("miss", 0),
            "access_types": dict(access_types),
        }


class StrategyCodingDecouple:
    """策略与代码解耦。

    核心功能：
    1. decouple(): 将任务描述拆分为"策略"和"代码"两部分。
       策略 = 高层方法描述，代码 = 具体实现步骤。
    2. select_mode(): 根据历史执行结果选择适应(adapt)或稳定(stable)模式。
       - 最近历史成功率高 → adapt（持续改进）
       - 最近历史成功率低 → stable（保守执行）
    """

    def __init__(self, history_window: int = 5,
                 success_threshold: float = 0.6):
        self._tasks: list[dict] = []
        self._history: deque = deque(maxlen=history_window)
        self._success_threshold = success_threshold

    def decouple(self, task: str) -> dict:
        """将任务拆分为策略和代码。

        Args:
            task: 任务描述字符串。

        Returns:
            {strategy, code, task_hash}.
        """
        task_hash = str(hash(task))[:8]

        # 策略提取：取前2句或前100字符作为策略描述
        sentences = task.replace("。", ".").replace("\n", ". ").split(".")
        strategy = ".".join(sentences[:2]).strip()[:200] or task[:200]

        # 代码提取：剩余部分作为实现细节
        if len(sentences) > 2:
            code = ".".join(sentences[2:]).strip()[:500]
        else:
            code = f"# Implement: {task[:100]}"

        result = {
            "strategy": strategy,
            "code": code,
            "task_hash": task_hash,
        }
        self._tasks.append(result)
        return result

    def select_mode(self, task: str, history: list[dict] | None = None) -> dict:
        """选择执行模式。

        Args:
            task: 当前任务。
            history: 历史执行记录列表，每条含 success 字段。

        Returns:
            {mode, reason, success_rate}.
        """
        history = history or list(self._history)
        recent = history[-self._history.maxlen:] if history else []
        if not recent:
            return {"mode": "stable", "reason": "No history available",
                    "success_rate": 0.5}

        success_rate = sum(
            1 for h in recent if h.get("success", False)
        ) / len(recent)

        if success_rate >= self._success_threshold:
            mode = "adapt"
            reason = f"High success rate ({success_rate:.0%}) — adapting strategy"
        else:
            mode = "stable"
            reason = f"Low success rate ({success_rate:.0%}) — stable execution"

        return {"mode": mode, "reason": reason,
                "success_rate": round(success_rate, 4)}

    def record_outcome(self, task_hash: str, success: bool):
        """记录任务执行结果到历史。

        Args:
            task_hash: 任务哈希（来自 decouple()）。
            success: 是否成功。
        """
        self._history.append({
            "task_hash": task_hash,
            "success": success,
            "ts": time.time(),
        })

    def get_stats(self) -> dict:
        return {
            "tasks": len(self._tasks),
            "history_size": len(self._history),
            "success_rate": round(
                sum(1 for h in self._history if h["success"]) /
                max(len(self._history), 1), 4
            ),
            "adapt_count": 0,  # 由外部调用 select_mode 时跟踪
        }


class ATPValidator:
    """对齐真实性验证器（Alignment Truthfulness Validator）。

    检查4类违规：
    1. 陈旧(stale): 有时间戳的步骤过期超过阈值
    2. 冲突(conflicting): 步骤依赖与当前状态矛盾
    3. 资源(resource): 步骤请求的资源已被占用
    4. 循环(cycle): 步骤间存在依赖循环

    验证结果含修复建议。
    """

    def __init__(self, stale_threshold: float = 3600.0):
        self._validations: list[dict] = []
        self._stale_threshold = stale_threshold

    def validate(self, plan: list[dict] | None,
                 state: dict | None = None) -> dict:
        """验证计划步骤的完整性和一致性。

        Args:
            plan: 步骤列表，每步可选含 id, type, deps, ts, resource。
            state: 当前状态字典，可选含 resources, completed_ids 等。

        Returns:
            {valid, violations, fixes}.
        """
        violations = []
        state = state or {}
        completed_ids = set(state.get("completed_ids", []) or [])
        resources = set(state.get("resources", []) or [])
        used_resources = set()
        step_ids = set()

        for step in (plan or []):
            step_id = step.get("id", "?")
            step_ids.add(step_id)

            # 1. 陈旧性检查
            if self._check_stale(step):
                violations.append({
                    "type": "stale",
                    "detail": f"Step {step_id} exceeded max age "
                              f"{self._stale_threshold}s",
                    "step_id": step_id,
                })

            # 2. 冲突检查（依赖已完成或不存在）
            if self._check_conflict(step, state):
                deps = set(step.get("deps", []) or [])
                missing = deps - completed_ids - {step_id}
                if missing:
                    violations.append({
                        "type": "conflicting",
                        "detail": f"Step {step_id} depends on uncompleted: "
                                  f"{missing}",
                        "step_id": step_id,
                        "missing_deps": list(missing),
                    })

            # 3. 资源争用
            step_resource = step.get("resource")
            if step_resource:
                if step_resource in used_resources:
                    violations.append({
                        "type": "resource",
                        "detail": f"Step {step_id} conflicts on resource: "
                                  f"{step_resource}",
                        "step_id": step_id,
                        "resource": step_resource,
                    })
                used_resources.add(step_resource)

            # 4. 循环依赖（简易检测：自引用）
            deps = set(step.get("deps", []) or [])
            if step_id in deps:
                violations.append({
                    "type": "cycle",
                    "detail": f"Step {step_id} depends on itself",
                    "step_id": step_id,
                })

        fixes = [v["detail"] for v in violations]
        result = {
            "valid": len(violations) == 0,
            "violations": violations,
            "fixes": fixes,
            "steps_checked": len(plan or []),
            "violation_count": len(violations),
        }
        self._validations.append(result)
        return result

    def _check_stale(self, step: dict) -> bool:
        """检查步骤是否过期。

        条件：步骤设置了时间戳且超过阈值。
        """
        ts = step.get("ts")
        if ts is None:
            return False
        return (time.time() - ts) > self._stale_threshold

    def _check_conflict(self, step: dict, state: dict) -> bool:
        """检查步骤与前序步骤或当前状态是否冲突。

        条件：步骤的依赖中有未完成的步骤。
        """
        deps = step.get("deps", []) or []
        if not deps:
            return False
        completed_ids = set(state.get("completed_ids", []) or [])
        step_id = step.get("id", "?")
        missing = [d for d in deps if d not in completed_ids and d != step_id]
        return len(missing) > 0

    def get_stats(self) -> dict:
        if not self._validations:
            return {"total": 0, "valid_rate": 1.0}
        valid_count = sum(1 for v in self._validations if v["valid"])
        total_violations = sum(
            v["violation_count"] for v in self._validations
        )
        violation_types = defaultdict(int)
        for v in self._validations:
            for vv in v.get("violations", []):
                violation_types[vv["type"]] += 1
        return {
            "total": len(self._validations),
            "valid_rate": round(
                valid_count / len(self._validations), 4
            ),
            "total_violations": total_violations,
            "avg_violations_per_check": round(
                total_violations / max(len(self._validations), 1), 4
            ),
            "violation_types": dict(violation_types),
        }


class GearSafety:
    """变速安全齿轮（Gear-Based Safety Gate）。

    5档位: idle → cautious → normal → fast → autonomous

    选择逻辑：
    - idle: 风险极高 >0.95 或 系统未初始化
    - cautious: 高风险 >0.8
    - normal: 中风险 >0.5
    - fast: 低风险 >0.2
    - autonomous: 无风险 ≤0.2

    门控逻辑：
    - autonomous: 允许所有动作
    - fast: 禁止 shutdown
    - normal: 禁止 shutdown, execute
    - cautious: 只允许 read, observe, plan
    - idle: 所有动作被阻止
    """

    GEARS = ["idle", "cautious", "normal", "fast", "autonomous"]

    # 每个档位允许的动作类型
    GEAR_ALLOWED_ACTIONS = {
        "autonomous": {"read", "write", "execute", "delete", "shutdown",
                       "observe", "plan", "communicate"},
        "fast": {"read", "write", "execute", "delete", "observe", "plan",
                 "communicate"},
        "normal": {"read", "write", "observe", "plan", "communicate"},
        "cautious": {"read", "observe", "plan"},
        "idle": set(),
    }

    def __init__(self):
        self._gear_log: list[dict] = []
        self._gate_log: list[dict] = []

    def select_gear(self, state: dict) -> dict:
        """根据系统风险状态选择档位。

        Args:
            state: 系统状态，含 risk [0,1]。

        Returns:
            {gear, reason, risk}.
        """
        risk = max(0.0, min(1.0, state.get("risk", 0.5)))

        # 额外因素：系统稳定性和资源使用率
        stability = max(0.0, min(1.0, state.get("stability", 0.5)))
        resource_usage = max(0.0, min(1.0, state.get("resource_usage", 0.5)))

        # 综合风险调整：低稳定性 + 高资源使用 → 上调风险
        adjusted_risk = risk + (1.0 - stability) * 0.1 + resource_usage * 0.1
        adjusted_risk = min(1.0, adjusted_risk)

        # 档位选择（使用 adjusted_risk）
        if adjusted_risk > 0.95:
            gear = "idle"
            reason = f"Extreme risk ({adjusted_risk:.2f}) — full lockout"
        elif adjusted_risk > 0.8:
            gear = "cautious"
            reason = f"High risk ({adjusted_risk:.2f}) — limited operations"
        elif adjusted_risk > 0.5:
            gear = "normal"
            reason = f"Moderate risk ({adjusted_risk:.2f}) — standard ops"
        elif adjusted_risk > 0.2:
            gear = "fast"
            reason = f"Low risk ({adjusted_risk:.2f}) — fast operations"
        else:
            gear = "autonomous"
            reason = f"Minimal risk ({adjusted_risk:.2f}) — full autonomy"

        result = {
            "gear": gear,
            "reason": reason,
            "risk": round(adjusted_risk, 4),
            "raw_risk": round(risk, 4),
            "stability": round(stability, 4),
        }
        self._gear_log.append(result)
        return result

    def gate_action(self, gear: str, action: dict) -> dict:
        """根据当前档位判断是否允许执行动作。

        Args:
            gear: 当前档位名称。
            action: 动作字典，含 type 字段。

        Returns:
            {allowed, reason}.
        """
        action_type = action.get("type", "")
        allowed_types = self.GEAR_ALLOWED_ACTIONS.get(gear, set())
        allowed = action_type in allowed_types

        if allowed:
            reason = f"{gear} allows {action_type}"
        else:
            reason = f"{gear} blocks {action_type} — " \
                     f"only {sorted(allowed_types) or 'none'} allowed"

        result = {"allowed": allowed, "reason": reason, "gear": gear}
        self._gate_log.append(result)
        return result

    def get_stats(self) -> dict:
        gear_counts = defaultdict(int)
        for entry in self._gear_log:
            gear_counts[entry["gear"]] += 1
        blocked = sum(1 for g in self._gate_log if not g["allowed"])
        return {
            "gear_changes": len(self._gear_log),
            "gate_checks": len(self._gate_log),
            "blocked_actions": blocked,
            "current_gear": self._gear_log[-1]["gear"] if self._gear_log else "idle",
            "gear_distribution": dict(gear_counts),
            "block_rate": round(
                blocked / max(len(self._gate_log), 1), 4
            ),
        }
