"""MultiAgentSystem — 多代理协调与任务分配.

基于:
- "Contract Net Protocol for Multi-Agent Task Allocation" (Davis, 1980)
  - 合同网协议: 任务招标+投标+分配
  - 能力匹配: 根据代理能力分配任务
  - 负载均衡: 避免过载
  - 共识机制: 投票/多数决策

CAMP Integration (arXiv 2604.00085):
  "CAMP: Case-Adaptive Multi-agent Panel"
  - Dynamic expert assembly: assemble panel per case, not static roles
  - Ternary voting: for / against / abstain (abstain more informative)
  - Multi-round deliberation with consensus tracking

Note: MultiAgentSystem is the PRIMARY multi-agent coordination class.
  CAMP-specific logic (_deliberate_assembly, _three_value_vote, deliberate)
  lives here. The camp_assembly.py module provides a lightweight wrapper/
  factory that delegates to this class — it is NOT a competing implementation.

算法:
    allocate_task(task, agents):
        1. 广播任务请求
        2. 收集投标(能力评分)
        3. 选择最佳投标者
        4. 确认分配
    
    consensus_vote(agents, options):
        1. 收集投票
        2. 加权计票
        3. 返回共识结果

    deliberate(task, agents, rounds):
        1. 动态组装专家团 (CAMP)
        2. 每轮三值投票 (支持/反对/弃权)
        3. 跟踪共识收敛度
        4. 返回最终共识和轮次历史

复杂度:
    allocate_task(): O(N) N=代理数
    consensus_vote(): O(N×M) M=选项数
    deliberate(): O(R×N×M) R=轮次
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import time
import random
import math
from collections import defaultdict


class MultiAgentSystem:
    """多代理协调系统 — 合同网协议+共识决策+CAMP专家组装.

    管理代理注册、任务分配和集体决策.
    This is the PRIMARY coordination class; see camp_assembly.py for
    factory/convenience wrappers.
    """

    # Expertise domains recognized by the system
    EXPERTISE_DOMAINS = [
        "general", "memory", "reasoning", "planning", "learning",
        "safety", "evolution", "communication", "perception", "control",
    ]

    def __init__(self, load_threshold: float = 0.8):
        """初始化.

        Args:
            load_threshold: 负载阈值,超过则不接受新任务
        """
        self._load_threshold = load_threshold
        self._agents: dict[str, dict] = {}
        self._allocations: list[dict] = []
        self._votes: list[dict] = []
        # CAMP deliberation history
        self._deliberations: list[dict] = []
        # Expertise profiles derived from capabilities
        self._expertise_domains: dict[str, set[str]] = {}

    def register_agent(self, agent_id: str, capabilities: list[str],
                       capacity: int = 10) -> dict:
        """注册代理.

        Args:
            agent_id: 代理ID
            capabilities: 能力列表
            capacity: 最大并发任务数

        Returns:
            dict: 代理信息
        """
        if not capabilities:
            capabilities = ["general"]

        agent = {
            "id": agent_id,
            "capabilities": set(capabilities),
            "capacity": capacity,
            "current_load": 0,
            "success_count": 0,
            "total_tasks": 0,
            "reputation": 1.0,
            "registered_at": time.time(),
            # CAMP-specific: experience profile
            "panel_participations": 0,
            "consensus_votes_cast": 0,
            "abstention_count": 0,
        }
        self._agents[agent_id] = agent

        # Build expertise domains from capabilities
        domains = set()
        for cap in capabilities:
            # Map capability to a recognized domain (or use raw cap)
            if cap in self.EXPERTISE_DOMAINS:
                domains.add(cap)
            else:
                # Try prefix-match against known domains
                matched = False
                for d in self.EXPERTISE_DOMAINS:
                    if d in cap or cap in d:
                        domains.add(d)
                        matched = True
                        break
                if not matched:
                    domains.add(cap)  # register raw capability as domain
        self._expertise_domains[agent_id] = domains

        return {
            "id": agent_id,
            "capabilities": list(capabilities),
            "capacity": capacity,
            "reputation": 1.0,
            "domains": list(domains),
        }

    # ============================================================
    # Expertise & Panel
    # ============================================================

    def get_expertise_profile(self, agent_id: str | None = None) -> dict:
        """Return which domains each agent (or a specific agent) specializes in.

        Args:
            agent_id: Optional specific agent. If None, returns all agents.

        Returns:
            dict mapping agent_id → list of domain strings,
            or a single dict for one agent.
        """
        if agent_id is not None:
            agent = self._agents.get(agent_id)
            if not agent:
                return {"error": "agent not found"}
            return {
                "agent_id": agent_id,
                "domains": sorted(self._expertise_domains.get(agent_id, set())),
                "reputation": agent["reputation"],
                "success_rate": round(
                    agent["success_count"] / max(agent["total_tasks"], 1), 4
                ),
                "current_load": agent["current_load"],
                "capacity": agent["capacity"],
                "total_tasks": agent["total_tasks"],
                "panel_participations": agent["panel_participations"],
            }

        # All agents
        result = {}
        for aid, agent in self._agents.items():
            result[aid] = {
                "domains": sorted(self._expertise_domains.get(aid, set())),
                "reputation": agent["reputation"],
                "success_rate": round(
                    agent["success_count"] / max(agent["total_tasks"], 1), 4
                ),
                "current_load": agent["current_load"],
                "capacity": agent["capacity"],
                "panel_participations": agent["panel_participations"],
            }
        return result

    def panel_composition(self) -> dict:
        """Return current panel membership — which agents are part of
        an active deliberation panel.

        Note: Panels are assembled per-deliberation. This returns the
        last assembled panel info plus a summary of all agents' participation.

        Returns:
            dict with 'last_panel' (agents in last CAMP assembly),
            'agent_participation' (counts per agent),
            'total_deliberations' (int).
        """
        last_panel_info = {}
        if self._deliberations:
            last_delib = self._deliberations[-1]
            last_panel_info = {
                "panel_size": len(last_delib.get("panel", [])),
                "panel_members": last_delib.get("panel", []),
                "rounds_completed": last_delib.get("rounds_completed", 0),
                "consensus_reached": last_delib.get("consensus_reached", False),
                "winner": last_delib.get("final_winner"),
                "timestamp": last_delib.get("ts", 0),
            }

        # Aggregate participation counts
        agent_participation = {}
        for aid, agent in self._agents.items():
            agent_participation[aid] = {
                "panel_participations": agent["panel_participations"],
                "consensus_votes_cast": agent["consensus_votes_cast"],
                "abstention_count": agent["abstention_count"],
                "domains": sorted(self._expertise_domains.get(aid, set())),
            }

        return {
            "last_panel": last_panel_info,
            "agent_participation": agent_participation,
            "total_agents": len(self._agents),
            "total_deliberations": len(self._deliberations),
        }

    # ============================================================
    # Task Allocation (Contract Net Protocol)
    # ============================================================

    def allocate_task(self, task: str | dict, required_cap: str | list[str] | None = None) -> dict:
        """分配任务(合同网协议).

        Args:
            task: 任务描述 (str 或 dict 含 'required_capabilities')
            required_cap: 所需能力 (str 或 list)

        Returns:
            dict: 分配结果
        """
        # 兼容 dict 输入
        if isinstance(task, dict):
            required_caps = task.get("required_capabilities", [])
            task_str = str(task.get("task", str(task)))
        else:
            required_caps = [required_cap] if required_cap else []
            task_str = task

        if not required_caps:
            required_caps = ["general"]
        candidates = []

        for agent_id, agent in self._agents.items():
            # 能力匹配
            if not any(rc in agent["capabilities"] for rc in required_caps):
                continue

            # 负载检查
            load_ratio = agent["current_load"] / max(agent["capacity"], 1)
            if load_ratio >= self._load_threshold:
                continue

            # 计算投标得分
            score = (
                agent["reputation"] * 0.4 +
                (1 - load_ratio) * 0.3 +
                min(agent["success_count"] / 10, 1.0) * 0.3
            )

            candidates.append({
                "agent_id": agent_id,
                "score": round(score, 4),
                "load_ratio": round(load_ratio, 4),
                "reputation": agent["reputation"],
            })

        if not candidates:
            return {
                "allocated": False,
                "reason": "no suitable agent available",
                "required_caps": required_caps,
            }

        # 选择最高分
        candidates.sort(key=lambda x: x["score"], reverse=True)
        winner = candidates[0]
        winner_id = winner["agent_id"]

        # 更新代理状态
        self._agents[winner_id]["current_load"] += 1
        self._agents[winner_id]["total_tasks"] += 1

        allocation = {
            "allocated": True,
            "agent_id": winner_id,
            "task": task_str[:100],
            "score": winner["score"],
            "candidates": len(candidates),
            "ts": time.time(),
        }

        self._allocations.append(allocation)
        if len(self._allocations) > 500:
            self._allocations = self._allocations[-250:]

        return allocation

    def complete_task(self, agent_id: str, success: bool = True) -> dict:
        """完成任务.

        Args:
            agent_id: 代理ID
            success: 是否成功

        Returns:
            dict: 更新结果
        """
        agent = self._agents.get(agent_id)
        if not agent:
            return {"error": "agent not found"}

        agent["current_load"] = max(0, agent["current_load"] - 1)

        if success:
            agent["success_count"] += 1
            agent["reputation"] = min(1.0, agent["reputation"] * 0.99 + 0.01)
        else:
            agent["reputation"] = max(0.0, agent["reputation"] * 0.95 - 0.03)

        return {
            "agent_id": agent_id,
            "current_load": agent["current_load"],
            "reputation": round(agent["reputation"], 4),
            "success_rate": round(
                agent["success_count"] / max(agent["total_tasks"], 1), 4
            ),
        }

    # ============================================================
    # Consensus Vote
    # ============================================================

    def consensus_vote(self, agent_ids: list[str], options: list[str],
                       weights: dict[str, float] | None = None) -> dict:
        """共识投票.

        Args:
            agent_ids: 投票代理ID列表
            options: 选项列表
            weights: 代理权重

        Returns:
            dict: 投票结果
        """
        scores: dict[str, float] = {opt: 0.0 for opt in options}
        votes = []

        for agent_id in agent_ids:
            agent = self._agents.get(agent_id)
            if not agent:
                continue

            # 模拟投票(基于声誉加权随机)
            weight = (weights or {}).get(agent_id, agent["reputation"])
            chosen = random.choices(options, weights=[1.0] * len(options), k=1)[0]
            scores[chosen] += weight

            votes.append({
                "agent_id": agent_id,
                "vote": chosen,
                "weight": round(weight, 4),
            })

        # 找出获胜者
        winner = max(scores, key=scores.get) if scores else None
        total_weight = sum(scores.values())

        result = {
            "winner": winner,
            "scores": {k: round(v, 4) for k, v in scores.items()},
            "total_participants": len(votes),
            "total_weight": round(total_weight, 4),
            "margin": round(
                (scores[winner] / max(total_weight, 1)) if winner and total_weight > 0 else 0, 4
            ),
            "ts": time.time(),
        }

        self._votes.append(result)
        if len(self._votes) > 200:
            self._votes = self._votes[-100:]

        return result

    # ============================================================
    # CAMP: Dynamic Expert Assembly (arXiv 2604.00085)
    # ============================================================

    def _deliberate_assembly(self, task_description: str,
                             available_agents: list[dict],
                             required_caps: list[str],
                             min_panel_size: int = 3) -> list[str]:
        """CAMP: 案例自适应动态专家组装 (arXiv 2604.00085).

        按案例需求动态组装专家团，不做静态角色划分。

        Args:
            task_description: 任务描述
            available_agents: 可用代理列表
            required_caps: 所需能力列表
            min_panel_size: 最小专家团大小

        Returns:
            选中的agent_id列表
        """
        if not available_agents:
            return []

        scored = []
        for agent in available_agents:
            caps = agent.get("capabilities", set())
            if isinstance(caps, list):
                caps = set(caps)

            # 能力匹配分数
            cap_score = sum(1 for rc in required_caps if rc in caps) / max(len(required_caps), 1)
            # 声誉分数
            rep_score = agent.get("reputation", 0.5)
            # 负载分数
            load = agent.get("current_load", 0)
            capacity = agent.get("capacity", 10)
            load_score = 1.0 - (load / max(capacity, 1))

            total = cap_score * 0.5 + rep_score * 0.3 + load_score * 0.2
            scored.append((total, agent["id"]))

        scored.sort(key=lambda x: -x[0])
        panel_size = max(min_panel_size, min(len(required_caps) * 2, len(scored)))
        selected = [sid for _, sid in scored[:panel_size]]
        return selected

    def _three_value_vote(self, options: list[str],
                           agents: list[dict]) -> dict:
        """CAMP: 三值投票（支持/反对/弃权），弃权比强制投票更有信息量。

        Args:
            options: 选项列表
            agents: 代理列表（含id, reputation）

        Returns:
            投票结果 dict
        """
        scores = {opt: {"for": 0.0, "against": 0.0, "abstain": 0.0}
                  for opt in options}

        for agent in agents:
            aid = agent["id"]
            rep = agent.get("reputation", 0.5)
            for opt in options:
                # 有rep一定概率弃权（低rep更可能弃权）
                abstain_prob = 1.0 - rep
                if random.random() < abstain_prob:
                    scores[opt]["abstain"] += rep
                elif random.random() < 0.7:  # 70%支持（匹配的）
                    scores[opt]["for"] += rep
                else:
                    scores[opt]["against"] += rep

        # 计算净得分
        net_scores = {}
        for opt, s in scores.items():
            net_scores[opt] = round(s["for"] - s["against"], 4)

        winner = max(net_scores, key=net_scores.get) if net_scores else None

        return {
            "winner": winner,
            "scores": scores,
            "net_scores": net_scores,
            "total_participants": len(agents),
        }

    def deliberate(self, task_description: str,
                   options: list[str],
                   required_caps: list[str] | None = None,
                   max_rounds: int = 3,
                   min_panel_size: int = 3,
                   consensus_threshold: float = 0.6) -> dict:
        """CAMP: Multi-round deliberation with consensus tracking.

        Assembles a case-adaptive expert panel, then runs up to max_rounds
        of ternary voting (for/against/abstain). Tracks convergence across
        rounds and returns when consensus is reached or rounds exhausted.

        Args:
            task_description: Description of the case/task.
            options: List of decision options to vote on.
            required_caps: Required capabilities for panel selection.
                If None, uses ["general"].
            max_rounds: Maximum number of deliberation rounds.
            min_panel_size: Minimum panel size.
            consensus_threshold: Net score ratio needed to declare consensus
                (e.g., 0.6 means winner must have 60% of max possible net).

        Returns:
            dict with deliberation history and final consensus state.
        """
        if required_caps is None:
            required_caps = ["general"]

        # --- Step 1: Assemble panel (CAMP dynamic assembly) ---
        available = []
        for aid, agent in self._agents.items():
            load_ratio = agent["current_load"] / max(agent["capacity"], 1)
            if load_ratio < self._load_threshold:
                panel_info = dict(agent)
                panel_info["id"] = aid
                available.append(dict(agent))

        panel = self._deliberate_assembly(
            task_description, available, required_caps, min_panel_size
        )
        panel_agents = [dict(self._agents[aid]) for aid in panel]
        # Fix up: panel_agents already have correct 'id' from copying dict
        # But dict(self._agents[aid]) uses 'id' key, so we rely on it

        # Track participation
        for aid in panel:
            self._agents[aid]["panel_participations"] += 1

        # --- Step 2: Multi-round deliberation ---
        rounds = []
        convergence_history = []
        prev_net_scores = None
        final_winner = None
        consensus_reached = False

        for round_idx in range(max_rounds):
            round_result = self._three_value_vote(options, panel_agents)

            # Compute convergence: cosine similarity between consecutive rounds
            net = round_result["net_scores"]
            convergence_score = 0.0
            if prev_net_scores is not None:
                # Normalized similarity between consecutive net score vectors
                keys = list(net.keys())
                vec_prev = [prev_net_scores[k] for k in keys]
                vec_cur = [net[k] for k in keys]
                mag_prev = math.sqrt(sum(v * v for v in vec_prev))
                mag_cur = math.sqrt(sum(v * v for v in vec_cur))
                if mag_prev > 0 and mag_cur > 0:
                    dot = sum(a * b for a, b in zip(vec_prev, vec_cur))
                    convergence_score = dot / (mag_prev * mag_cur)
            prev_net_scores = dict(net)

            # Track abstention per agent this round
            for entry in panel_agents:
                aid = entry["id"]
                # Approximate: each agent cast votes with some abstention probability
                rep = entry.get("reputation", 0.5)
                if random.random() < (1.0 - rep):
                    self._agents[aid]["abstention_count"] += 1
                self._agents[aid]["consensus_votes_cast"] += 1

            # Record round
            round_record = {
                "round": round_idx + 1,
                "net_scores": net,
                "winner": round_result["winner"],
                "scores_detail": round_result["scores"],
                "convergence": round(convergence_score, 4),
            }
            rounds.append(round_record)
            convergence_history.append(convergence_score)

            # Check consensus: does the winner have sufficient margin?
            if round_result["winner"] and round_result["net_scores"][round_result["winner"]] > 0:
                # Consensus threshold: winner's net proportion of max possible
                max_possible = len(panel_agents)  # each agent contributes at most 1.0
                winner_net = round_result["net_scores"][round_result["winner"]]
                consensus_ratio = winner_net / max(max_possible, 1)

                if consensus_ratio >= consensus_threshold and round_idx >= 1:
                    consensus_reached = True
                    final_winner = round_result["winner"]
                    break

        # If consensus not reached in rounds, final winner = last round winner
        if not consensus_reached and rounds:
            final_winner = rounds[-1]["winner"]

        # --- Step 3: Build deliberation record ---
        deliberation = {
            "ts": time.time(),
            "task": task_description[:200],
            "panel": panel,
            "panel_size": len(panel),
            "rounds_completed": len(rounds),
            "max_rounds": max_rounds,
            "consensus_reached": consensus_reached,
            "consensus_threshold": consensus_threshold,
            "final_winner": final_winner,
            "rounds": rounds,
            "convergence_trace": [round(c, 4) for c in convergence_history],
            "required_caps": required_caps,
        }

        self._deliberations.append(deliberation)
        if len(self._deliberations) > 100:
            self._deliberations = self._deliberations[-50:]

        return deliberation

    def reach_consensus(self, options: list[dict], agent_ids: list[str] | None = None) -> dict:
        """达成共识 (兼容别名)."""
        if not options:
            return {"winner": None, "scores": {}, "total_participants": 0}
        if agent_ids is None:
            agent_ids = list(self._agents.keys())
        if not agent_ids:
            return {"winner": None, "scores": {}, "total_participants": 0}
        opt_values = [o.get("value", str(o)) for o in options]
        return self.consensus_vote(agent_ids, opt_values)

    def get_stats(self) -> dict:
        """获取统计."""
        return {
            "agents": len(self._agents),
            "total_allocations": len(self._allocations),
            "total_votes": len(self._votes),
            "total_deliberations": len(self._deliberations),
            "avg_reputation": round(
                sum(a["reputation"] for a in self._agents.values()) / max(len(self._agents), 1), 4
            ),
            "total_load": sum(a["current_load"] for a in self._agents.values()),
            "panel_participations": sum(
                a["panel_participations"] for a in self._agents.values()
            ),
        }
