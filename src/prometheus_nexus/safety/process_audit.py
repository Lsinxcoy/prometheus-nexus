"""ProcessAuditor — COMPASS 过程审计 (arXiv 2605.30838).

论文核心方法：
MCTS 合成隐蔽攻击轨迹 + 逐步安全审计。
有害意图可被分解为看似无害的子查询组合。
MCTS 从安全组件中合成隐蔽攻击路径。

算法：
1. 接收 agent 操作轨迹
2. 将轨迹分解为子操作序列
3. 为每个子操作建立安全上下文
4. MCTS 搜索：检测"无害→有害"的分解模式
5. 逐步骤安全审计，计算风险分数
"""

from __future__ import annotations
import logging
import math
import random
from collections import defaultdict
from typing import Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Safety checkers
_SAFE_ACTIONS = {"read", "view", "list", "search", "query", "navigate", "open"}
_NEUTRAL_ACTIONS = {"write", "update", "modify", "append", "copy", "move"}
_RISKY_ACTIONS = {"delete", "remove", "erase", "overwrite", "replace"}
_CRITICAL_ACTIONS = {"execute", "eval", "exec", "shell", "system", "popen", 
                     "send", "upload", "transfer", "exfiltrate", "grant", "revoke"}

# Risky parameter patterns
_RISKY_PARAM_PATTERNS = {
    "path": ["/etc/", "/root/", "/sys/", "/proc/", "/boot/", "/.ssh/", "/.aws/"],
    "url": ["evil", "malicious", "exfil", "steal", "attacker", "hack"],
    "query": ["drop ", "truncate ", "delete ", "alter ", "grant ", "revoke "],
    "permission": ["admin", "root", "777", "chmod", "sudo"],
}

# Harmful decomposition patterns: seemingly safe actions that combine to harm
_HARMFUL_DECOMPOSITIONS = [
    ({"read", "search", "query"}, {"send", "upload", "transfer"}, "data_exfiltration"),
    ({"read", "search", "query"}, {"delete", "remove", "overwrite"}, "data_destruction"),
    ({"navigate", "open", "view"}, {"execute", "shell", "system"}, "remote_access"),
    ({"list", "search"}, {"delete", "drop", "truncate"}, "mass_deletion"),
    ({"read", "view"}, {"grant", "revoke", "chmod"}, "privilege_escalation"),
]


@dataclass
class AuditStep:
    """审计步骤记录。"""
    index: int = 0
    action: str = ""
    params: dict = field(default_factory=dict)
    safety_score: float = 1.0  # 1.0 = safe, 0.0 = dangerous
    flags: list[str] = field(default_factory=list)
    decomposition_risk: float = 0.0  # 0-1, 是否为有害分解的一部分


class MCTSNode:
    """MCTS 树节点，表示一个子操作。"""
    def __init__(self, step: AuditStep, parent=None):
        self.step = step
        self.parent = parent
        self.children: list[MCTSNode] = []
        self.visits = 0
        self.total_risk = 0.0

    @property
    def avg_risk(self) -> float:
        return self.total_risk / max(self.visits, 1)

    def ucb1(self, total_visits: int, c: float = 1.414) -> float:
        if self.visits == 0:
            return float("inf")
        exploitation = self.avg_risk
        exploration = c * math.sqrt(math.log(max(total_visits, 1)) / self.visits)
        return exploitation + exploration  # Higher risk = more interesting to audit


class ProcessAuditor:
    """基于 MCTS 的逐步过程审计器。"""

    def __init__(self):
        self._audits: list[dict] = []
        self._total = 0
        self._alerts = 0

    def audit_trajectory(self, trajectory: list[dict]) -> dict:
        """审计完整 agent 轨迹。返回风险评估。"""
        self._total += 1
        if not trajectory:
            return {"safe": True, "decompositions": [], "risk_score": 0.0,
                    "alert_level": "none"}

        # Step 1: 将轨迹分解为审计步骤
        steps = self._decompose_trajectory(trajectory)

        # Step 2: 逐步骤安全检查
        for step in steps:
            result = self._check_step_safety(step)
            step.safety_score = result["score"]
            step.flags = result["flags"]

        # Step 3: MCTS 检测有害分解模式
        decompositions = self._detect_harmful_decompositions(steps)

        # Step 4: 计算总体风险
        risk_score = self._compute_risk_score(steps, decompositions)
        safe = risk_score < 0.5

        if not safe:
            self._alerts += 1

        result = {
            "safe": safe,
            "risk_score": round(risk_score, 4),
            "alert_level": "critical" if risk_score > 0.8 else "warning" if risk_score > 0.5 else "none",
            "decompositions": decompositions,
            "total_steps": len(steps),
            "steps_summary": [
                {"index": s.index, "action": s.action, "safety": round(s.safety_score, 2)}
                for s in steps
            ],
        }
        self._audits.append(result)
        return result

    def _decompose_trajectory(self, trajectory: list[dict]) -> list[AuditStep]:
        """将轨迹分解为审计步骤。"""
        steps = []
        for i, step in enumerate(trajectory):
            action = step.get("action", "").lower()
            params = step.get("params", {})
            audit_step = AuditStep(
                index=i,
                action=action,
                params=params if isinstance(params, dict) else {"raw": str(params)},
            )
            steps.append(audit_step)
        return steps

    def _check_step_safety(self, step: AuditStep) -> dict:
        """检查单个步骤的安全性。"""
        flags = []
        score = 1.0
        action = step.action
        params = step.params

        # 动作分类
        if action in _CRITICAL_ACTIONS:
            score -= 0.6
            flags.append(f"CRITICAL action: {action}")
        elif action in _RISKY_ACTIONS:
            score -= 0.4
            flags.append(f"RISKY action: {action}")
        elif action in _NEUTRAL_ACTIONS:
            score -= 0.1

        # 参数检查
        param_str = str(params).lower()
        for category, patterns in _RISKY_PARAM_PATTERNS.items():
            for pat in patterns:
                if pat in param_str:
                    score -= 0.3
                    flags.append(f"Sensitive {category}: {pat}")

        # 序列长度/大小检查
        param_size = len(str(params))
        if param_size > 1000:
            score -= 0.1
            flags.append(f"Large payload: {param_size} chars")

        return {"score": max(0.0, score), "flags": flags}

    def _detect_harmful_decompositions(self, steps: list[AuditStep]) -> list[dict]:
        """MCTS 检测有害分解模式。

        对每个子操作序列进行 MCTS 搜索，检测是否
        存在"多个无害操作→有害结果"的分解模式。
        """
        decompositions = []

        for safe_set, harmful_set, harm_type in _HARMFUL_DECOMPOSITIONS:
            # 找到轨迹中的安全动作集
            found_safe = set()
            found_harmful = set()
            for s in steps:
                if s.action in safe_set:
                    found_safe.add(s.action)
                if s.action in harmful_set:
                    found_harmful.add(s.action)

            # 检查是否同时存在安全动作和有害动作
            if found_safe and found_harmful:
                # 计算风险：安全动作之间的间隔越小，风险越高
                safe_indices = [s.index for s in steps if s.action in found_safe]
                harmful_indices = [s.index for s in steps if s.action in found_harmful]

                min_gap = float("inf")
                for si in safe_indices:
                    for hi in harmful_indices:
                        gap = abs(si - hi)
                        min_gap = min(min_gap, gap)

                # 间隔越小，分解越隐蔽
                risk = max(0.3, 1.0 - min_gap / max(len(steps), 3))

                decompositions.append({
                    "type": f"harmful_decomposition:{harm_type}",
                    "safe_actions": list(found_safe),
                    "harmful_actions": list(found_harmful),
                    "min_gap": min_gap,
                    "risk_score": round(risk, 4),
                })

        return decompositions

    # ── COMPASS CTE: MCTS-based attack trajectory synthesis ──────────────────────

    def _mcts_search(self, steps: list[AuditStep],
                     iterations: int = 200) -> dict:
        """Cognitive Tree Exploration (CTE) via MCTS.

        Paper (arXiv 2605.30838 §3.2-3.3):
        MCTS synthesizes stealthy attack trajectories by decomposing seemingly
        harmless sub-queries into harmful sequences.  Each node represents a
        trajectory prefix; UCB1 balances exploitation (known-high-risk paths)
        against exploration (untested perturbations).

        Returns attack trajectories found and per-step ISA alignment scores.
        """
        if not steps:
            return {"attack_trajectories": [], "isa_scores": [],
                    "tree_stats": {"total_nodes": 0, "total_iterations": 0}}

        # ── Build root from the actual trajectory steps ──
        root = MCTSNode(AuditStep(index=-1, action="ROOT", safety_score=1.0))
        for step in steps:
            child = MCTSNode(step, parent=root)
            root.children.append(child)

        # Tokens for rollout perturbation
        _ROLLOUT_ACTIONS = list(_SAFE_ACTIONS | _NEUTRAL_ACTIONS | _RISKY_ACTIONS | _CRITICAL_ACTIONS)

        for _ in range(iterations):
            # 1. SELECT — traverse via UCB1 until reaching a node with unexpanded children
            node = root
            path = [node]
            while node.children and all(c.visits > 0 for c in node.children):
                total_visits = sum(c.visits for c in node.children)
                node = max(node.children,
                           key=lambda c, tv=total_visits: c.ucb1(tv))
                path.append(node)

            # 2. EXPAND — pick unvisited child OR create a CTE decomposition variant
            unvisited = [c for c in node.children if c.visits == 0] if node.children else []
            if unvisited:
                # Standard MCTS: pick the first unvisited child
                node = unvisited[0]
                path.append(node)
            elif node.visits > 0 and node is not root:
                # CTE Cognitive Tree Exploration: decompose into attack sub-queries
                # Instead of random action flip, inject realistic decomposition patterns
                # that combine safe sub-actions into harmful trajectories
                orig = node.step
                # Find which HARMFUL_DECOMPOSITION patterns could start from this action
                decomp_actions = []
                for safe_set, harmful_set, harm_type in _HARMFUL_DECOMPOSITIONS:
                    if orig.action in safe_set:
                        # Decompose: add a harmful follow-up action as child
                        harmful_action = next(iter(harmful_set))
                        decomp_actions.append((harmful_action, harm_type))
                
                if decomp_actions:
                    # Create decomposition node: safe + harmful = attack path
                    for harmful_action, harm_type in decomp_actions[:2]:
                        perturbed = AuditStep(
                            index=orig.index + 1,
                            action=harmful_action,
                            params={**orig.params, "_decomp_type": harm_type},
                            safety_score=self._check_step_safety(
                                AuditStep(index=orig.index + 1, action=harmful_action,
                                          params=orig.params))["score"],
                            decomposition_risk=0.7,
                        )
                        child = MCTSNode(perturbed, parent=node)
                        node.children.append(child)
                
                # Also try the inverse: if this is a neutral/risky action, 
                # check if preceded by a safe action that enables it
                if orig.action in _NEUTRAL_ACTIONS | _RISKY_ACTIONS | _CRITICAL_ACTIONS:
                    for safe_set, harmful_set, harm_type in _HARMFUL_DECOMPOSITIONS:
                        if orig.action in harmful_set:
                            safe_action = next(iter(safe_set))
                            safe_perturbed = AuditStep(
                                index=max(0, orig.index - 1),
                                action=safe_action,
                                params=orig.params,
                                safety_score=0.9,  # looks safe
                                decomposition_risk=0.5,
                            )
                            child = MCTSNode(safe_perturbed, parent=node)
                            node.children.append(child)
                
                # If no decomposition found, create a standard variant
                if not decomp_actions:
                    flipped = random.choice(list(_SAFE_ACTIONS | _NEUTRAL_ACTIONS | _RISKY_ACTIONS | _CRITICAL_ACTIONS))
                    perturbed = AuditStep(
                        index=orig.index,
                        action=flipped,
                        params={**orig.params},
                        safety_score=self._check_step_safety(
                            AuditStep(index=orig.index, action=flipped,
                                      params=orig.params))["score"],
                    )
                    child = MCTSNode(perturbed, parent=node)
                    node.children.append(child)
                    node = child
                    path.append(node)

            # 3. ROLLOUT — simulate remaining trajectory
            rollout_risk = self._mcts_rollout(node, steps)

            # 4. BACKPROPAGATE
            for n in reversed(path):
                n.visits += 1
                n.total_risk = (n.total_risk + rollout_risk)  # accumulate

        # Extract attack trajectories
        attack_trajectories = self._extract_attack_trajectories(root, steps)

        # ISA per-step alignment scores
        isa_scores = self._compute_isa_scores(steps, root)

        return {
            "attack_trajectories": attack_trajectories,
            "isa_scores": isa_scores,
            "tree_stats": {
                "total_nodes": self._count_nodes(root),
                "total_iterations": iterations,
            },
        }

    def _mcts_rollout(self, node: MCTSNode, steps: list[AuditStep]) -> float:
        """Simulate completion of the trajectory from *node* onward.

        Rollout policy: continue with remaining steps, computing combined risk.
        High risk → interesting attack path.
        """
        if node.step.index < 0:
            start = 0
        else:
            start = node.step.index
        remaining = steps[start:]
        if not remaining:
            return 0.0

        total = 0.0
        for i, s in enumerate(remaining):
            base = 1.0 - s.safety_score
            # Decaying discount — closer steps matter more
            total += base * (1.0 / (1.0 + i * 0.5))
        return min(1.0, total / max(len(remaining), 1))

    def _extract_attack_trajectories(self, root: MCTSNode,
                                     steps: list[AuditStep]) -> list[dict]:
        """Walk the MCTS tree and extract high-risk paths as attack trajectories."""
        trajectories = []
        high_risk_threshold = 0.4

        def _walk(node: MCTSNode, seq: list[int]):
            if node.step.index >= 0:
                seq.append(node.step.index)
            risk = node.avg_risk
            if risk > high_risk_threshold and len(seq) >= 2:
                traj_steps = [steps[i] for i in seq if i < len(steps)]
                trajectories.append({
                    "step_indices": list(seq),
                    "actions": [s.action for s in traj_steps],
                    "avg_risk": round(risk, 4),
                    "max_risk": round(max((s.safety_score for s in traj_steps),
                                         default=0.0), 4),
                })
            for child in node.children:
                _walk(child, list(seq))

        _walk(root, [])
        # Deduplicate and sort
        seen = set()
        unique = []
        for t in sorted(trajectories, key=lambda x: -x["avg_risk"]):
            key = tuple(t["step_indices"])
            if key not in seen:
                seen.add(key)
                unique.append(t)
        return unique[:5]

    def _compute_isa_scores(self, steps: list[AuditStep],
                            root: MCTSNode) -> list[dict]:
        """Introspective Step-wise Alignment (ISA) scores.

        For each step, measure alignment between the step's stated intent
        (its action) and the actual capability/risk it exposes.  Steps that
        are safe-looking but enable a harmful downstream action get low ISA.
        """
        isa_scores = []
        for i, step in enumerate(steps):
            # Base alignment: safety score
            alignment = step.safety_score

            # Penalty: if this safe step is followed by a risky step
            if step.action in _SAFE_ACTIONS:
                for j in range(i + 1, min(i + 4, len(steps))):
                    if steps[j].safety_score < 0.5:
                        gap = j - i
                        alignment -= 0.15 / gap  # closer gap → bigger penalty

            # Bonus: if the step is critical and obviously flagged
            if step.action in _CRITICAL_ACTIONS and step.safety_score < 0.3:
                alignment = max(alignment, 0.6)  # at least partially aligned

            # Check if this step is a known harmful decomposition part
            for safe_set, harmful_set, harm_type in _HARMFUL_DECOMPOSITIONS:
                if step.action in safe_set:
                    for j in range(i + 1, min(i + 5, len(steps))):
                        if steps[j].action in harmful_set:
                            alignment -= 0.2
                            break

            isa_scores.append({
                "step_index": i,
                "action": step.action,
                "isa_score": round(max(0.0, min(1.0, alignment)), 4),
                "aligned": alignment >= 0.5,
            })
        return isa_scores

    @staticmethod
    def _count_nodes(node: MCTSNode) -> int:
        """Count total nodes in the MCTS tree."""
        total = 1
        for child in node.children:
            total += ProcessAuditor._count_nodes(child)
        return total

    # ── Public scan interface ───────────────────────────────────────────────

    def scan(self, trajectory: list[dict]) -> dict:
        """External scan interface — triggers full CTE MCTS search + ISA.

        Equivalent to audit_trajectory but explicitly invokes the MCTS-based
        Cognitive Tree Exploration from COMPASS §3.2 and includes
        attack_trajectories and isa_scores in the result.

        Returns a dict with 'safe', 'risk_score', 'attack_trajectories',
        'isa_scores', 'tree_stats', and 'decompositions'.
        """
        base = self.audit_trajectory(trajectory)

        # Run explicit MCTS search to surface attack trajectories & ISA scores
        steps = self._decompose_trajectory(trajectory)
        for step in steps:
            step_result = self._check_step_safety(step)
            step.safety_score = step_result["score"]
            step.flags = step_result["flags"]

        mcts_result = self._mcts_search(steps, iterations=200)

        base["attack_trajectories"] = mcts_result["attack_trajectories"]
        base["isa_scores"] = mcts_result["isa_scores"]
        base["tree_stats"] = mcts_result["tree_stats"]
        return base

    # ── Modified compute to integrate MCTS ──────────────────────────────────

    def _compute_risk_score(self, steps: list[AuditStep],
                            decompositions: list[dict]) -> float:
        """计算总体风险分数。"""
        if not steps:
            return 0.0

        # 基础风险：平均步骤安全性
        avg_safety = sum(s.safety_score for s in steps) / len(steps)
        base_risk = 1.0 - avg_safety

        # 分解风险加成
        decomp_risk = 0.0
        for d in decompositions:
            decomp_risk = max(decomp_risk, d["risk_score"])

        # 混合：基础风险 + 分解风险
        total_risk = base_risk * 0.4 + decomp_risk * 0.6

        # COMPASS CTE uplift: run MCTS search and factor in attack trajectories
        mcts_result = self._mcts_search(steps, iterations=100)
        if mcts_result["attack_trajectories"]:
            max_traj_risk = max(
                t["avg_risk"] for t in mcts_result["attack_trajectories"]
            )
            total_risk = max(total_risk, base_risk * 0.3 + max_traj_risk * 0.7)

        return min(1.0, total_risk)

    def check_step(self, step: dict) -> dict:
        """检查单个步骤（外部接口）。"""
        audit_step = AuditStep(
            index=0,
            action=step.get("action", "").lower(),
            params=step.get("params", {}),
        )
        result = self._check_step_safety(audit_step)
        return {
            "safe": result["score"] >= 0.5,
            "score": result["score"],
            "flags": result["flags"],
        }

    def get_stats(self) -> dict:
        return {
            "total_audits": self._total,
            "alerts": self._alerts,
            "alert_rate": round(self._alerts / max(self._total, 1), 4),
        }
