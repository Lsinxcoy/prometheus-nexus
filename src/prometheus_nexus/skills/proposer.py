"""Proposer — 组合式技能合成代理 (借鉴 Agentic Proposing: 2602.03279).

给定目标, 动态选择并组合模块化推理技能, 生成可执行的 workflow。
这是 MGPO (多粒度策略优化) 在 Nexus 中的体现: 任务级 (整条 workflow) + 步骤级
(单个子技能贡献) 同时优化。

设计约束:
  - 零 LLM 依赖: 无 LLM 时退化到 SkillClaw.compose 的相关性排序。
  - 零机制损失: 只新增提议层, 不改动现有技能/CNS。
"""
from __future__ import annotations

import logging
from typing import Any

from prometheus_nexus.skills.skill_claw import SkillClaw

logger = logging.getLogger(__name__)


class Proposer:
    """目标驱动的技能组合代理."""

    def __init__(self, skill_claw: SkillClaw, llm: Any = None):
        self.skill_claw = skill_claw
        self.llm = llm

    def propose(self, goal: str, max_steps: int = 5) -> dict:
        """为给定目标生成技能组合 workflow.

        返回: {
            "goal": str,
            "workflow": [{"skill": name, "body": str}, ...],  # 有序
            "source": "llm" | "heuristic",
        }
        """
        # 1) LLM 增强: 让 Proposer 用 CoT 选+组合技能
        if self.llm is not None and getattr(self.llm, "available", False):
            wf = self._llm_propose(goal, max_steps)
            if wf:
                return {"goal": goal, "workflow": wf, "source": "llm"}

        # 2) 确定性降级: SkillClaw.compose 的相关性+依赖展开
        chain = self.skill_claw.compose(goal, max_depth=3)
        workflow = [{"skill": s["name"], "body": s.get("body", "")} for s in chain[:max_steps]]
        return {"goal": goal, "workflow": workflow, "source": "heuristic"}

    def _llm_propose(self, goal: str, max_steps: int) -> list[dict] | None:
        try:
            # 取候选技能供给 LLM 选择
            cands = self.skill_claw.search(goal, k=10)
            if not cands:
                return None
            catalog = "\n".join(
                f"- {c['id']}: {c['name']} :: {c.get('description','')[:60]}"
                for c in cands
            )
            prompt = (
                f"你是 Prometheus Nexus 的技能组合 Proposer (借鉴 Agentic Proposing)。\n"
                f"目标: {goal}\n"
                f"可用技能:\n{catalog}\n"
                f"请选择最多 {max_steps} 个技能组成有序 workflow, 输出 JSON 数组, "
                f"每项含 skill_id 字段。只输出 JSON。"
            )
            resp = self.llm.generate(prompt)
            import json
            txt = resp if isinstance(resp, str) else str(resp)
            s, e = txt.find("["), txt.rfind("]")
            if s < 0 or e < 0:
                return None
            arr = json.loads(txt[s:e + 1])
            out = []
            for it in arr[:max_steps]:
                sid = it.get("skill_id")
                sk = self.skill_claw._skills.get(sid)
                if sk:
                    out.append({"skill": sk["name"], "body": sk.get("body", "")})
            return out or None
        except Exception as e:
            logger.debug("Proposer LLM propose failed: %s", e)
            return None
