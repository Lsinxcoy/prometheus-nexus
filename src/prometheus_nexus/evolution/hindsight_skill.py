"""HindsightSkillMiner — 后见之明技能蒸馏 (借鉴 SEED: 2607.14777).

把已完成的 on-policy 轨迹 (管道运行日志) 提炼成 3 类可复用 hindsight 技能:
  - workflow   : 可复用工作流 (步骤序列)
  - observation: 关键观察 -> 触发动作的信号
  - avoid      : 避错规则 (触发条件 -> 替代动作)

提炼出的技能既写入 PlaybookInheritance (带真实 steps, 修空壳 bug),
也注册进 SkillClaw (供 Phase A 的 Proposer 组合复用).

设计约束:
  - 零 LLM 依赖: 确定性提取始终可用; LLM 仅作增强, 不可用则降级.
  - 零机制损失: 只新增提炼层, 不改动现有管道/CNS.
  - 去重: 同 (type, signal) 聚合, 避免刷屏.
"""
from __future__ import annotations

import logging
import time
import hashlib
from dataclasses import dataclass, field
from typing import Any

from prometheus_nexus.evolution.playbook_inheritance import (
    Playbook,
    PlaybookStep,
    PlaybookInheritance,
)
from prometheus_nexus.skills.skill_claw import SkillClaw

logger = logging.getLogger(__name__)

# 噪音过滤 (与监控 issues 噪音过滤一致)
_NOISE = (
    "owner_harm", "WAL LCRP rejected",
    "batch_update_utilities received booleans",
    "A2A delegate_task failed", "httpx", "urllib3",
)


@dataclass
class HindsightSkill:
    """一条后见之明技能."""
    skill_type: str          # workflow | observation | avoid
    signal: str              # 触发信号/上下文 (归一化 key)
    content: str             # 自然语言描述
    action: str = ""         # 建议动作 (workflow/avoid 用)
    confidence: float = 0.5
    source_pipeline: str = ""
    meta: dict = field(default_factory=dict)

    def to_playbook_step(self) -> PlaybookStep:
        if self.skill_type == "workflow":
            operation = "workflow"
            params = {"steps": self.meta.get("steps", [self.content])}
        elif self.skill_type == "observation":
            operation = "observe"
            params = {"signal": self.signal, "action": self.action or self.content}
        else:  # avoid
            operation = "avoid"
            params = {"trigger": self.signal, "instead": self.action or self.content}
        step_id = "hs_" + hashlib.md5(
            f"{self.skill_type}:{self.signal}".encode("utf-8")
        ).hexdigest()[:10]
        return PlaybookStep(
            step_id=step_id,
            name=f"{self.skill_type}:{self.signal[:40]}",
            operation=operation,
            params=params,
            depends_on=[],
            condition="",
            default_timeout=30.0,
        )

    def skill_body(self) -> str:
        """注册进 SkillClaw 的可执行体 (供 Proposer 组合)."""
        if self.skill_type == "avoid":
            return f"IF {self.signal} THEN {self.action or self.content}"
        if self.skill_type == "observation":
            return f"OBSERVE {self.signal} -> {self.action or self.content}"
        return self.content


class HindsightSkillMiner:
    def __init__(self, omega: Any = None, playbook: PlaybookInheritance | None = None,
                 skill_claw: SkillClaw | None = None, llm: Any = None):
        self.omega = omega
        self.playbook = playbook or (omega.playbook_inheritance if omega else None)
        self.skill_claw = skill_claw or (omega.skill_claw if omega else None)
        self.llm = llm or (getattr(omega, "llm", None))
        self._seen: set[str] = set()  # 去重 (type,signal)

    # ---------------------------------------------------------------- #
    def mine(self, pipeline: str, trajectory: dict) -> list[HindsightSkill]:
        """从一次管道运行轨迹提炼 hindsight 技能."""
        skills: list[HindsightSkill] = []
        errors = trajectory.get("errors", []) or []
        diagnostics = trajectory.get("diagnostics", {}) or {}
        outcome = trajectory.get("outcome", "")
        success = trajectory.get("success", True)

        # 1) 确定性: 从 errors/issues 提炼 avoid 类
        for e in errors:
            msg = (e.get("msg") if isinstance(e, dict) else str(e))
            src = (e.get("source") if isinstance(e, dict) else "")
            low = (msg or "").lower()
            if any(n.lower() in low for n in _NOISE):
                continue
            if not msg:
                continue
            key = f"avoid:{src}:{msg[:50]}"
            if key in self._seen:
                continue
            self._seen.add(key)
            instead = self._infer_avoid_action(msg)
            skills.append(HindsightSkill(
                skill_type="avoid",
                signal=f"{src}: {msg[:60]}",
                content=msg[:120],
                action=instead,
                confidence=0.7,
                source_pipeline=pipeline,
            ))

        # 2) 确定性: 从成功产出提炼 observation 类
        produced = trajectory.get("produced", 0) or 0
        if success and produced > 0:
            key = f"observation:{pipeline}:success"
            if key not in self._seen:
                self._seen.add(key)
                skills.append(HindsightSkill(
                    skill_type="observation",
                    signal=f"{pipeline} 产出 {produced} 项",
                    content=f"{pipeline} 在最近运行成功产出 {produced} 项",
                    action=f"优先路由 {pipeline}",
                    confidence=0.5,
                    source_pipeline=pipeline,
                ))

        # 3) LLM 增强: 提炼 workflow 类 (不可用则跳过)
        llm_skills = self._llm_workflow(pipeline, trajectory)
        skills.extend(llm_skills)

        return skills[:10]

    # ---------------------------------------------------------------- #
    def _infer_avoid_action(self, msg: str) -> str:
        m = msg.lower()
        if "compile" in m and "none" in m:
            return "编译返回 None 时记录 issue 并跳过挂载, 不中断管道"
        if "mount failed" in m:
            return "挂载失败时记录 issue 并降级, 继续后续机制"
        if "extract" in m or "compile" in m:
            return "机制提取/编译失败时记录 issue, 回退到已有机制"
        if "404" in m:
            return "源 404 时尝试备用链接 (src 而非 e-print)"
        return "记录 issue 并安全降级, 不中断管道"

    def _llm_workflow(self, pipeline: str, trajectory: dict) -> list[HindsightSkill]:
        if self.llm is None or not getattr(self.llm, "available", False):
            return []
        try:
            events = trajectory.get("events", []) or []
            diag = trajectory.get("diagnostics", {}) or {}
            prompt = (
                f"你是 Prometheus Nexus 的后见之明技能提炼器。\n"
                f"管道 {pipeline} 刚完成运行。\n"
                f"事件样本: {str(events[:5])[:600]}\n"
                f"诊断键: {list(diag.keys())[:20]}\n"
                f"请提炼 0-2 条可复用 WORKFLOW 技能 (JSON 数组, 每项含 content 字段, "
                f"描述该管道可复用的工作流步骤)。只输出 JSON。"
            )
            resp = self.llm.generate(prompt)
            import json
            txt = resp if isinstance(resp, str) else str(resp)
            start = txt.find("[")
            end = txt.rfind("]")
            if start < 0 or end < 0:
                return []
            arr = json.loads(txt[start:end + 1])
            out = []
            for it in arr[:2]:
                c = (it.get("content") or "").strip()
                if not c:
                    continue
                key = f"workflow:{c[:50]}"
                if key in self._seen:
                    continue
                self._seen.add(key)
                out.append(HindsightSkill(
                    skill_type="workflow",
                    signal=f"{pipeline} workflow",
                    content=c[:200],
                    confidence=0.6,
                    source_pipeline=pipeline,
                    meta={"steps": [c]},
                ))
            return out
        except Exception as e:
            logger.debug("HindsightSkillMiner LLM workflow failed: %s", e)
            return []

    # ---------------------------------------------------------------- #
    def register(self, pipeline: str, skills: list[HindsightSkill]) -> int:
        """把技能写真实 steps 进 Playbook + 注册进 SkillClaw. 返回写入数."""
        if not skills:
            return 0
        written = 0
        steps = [s.to_playbook_step() for s in skills]
        if self.playbook is not None:
            try:
                pb = Playbook(
                    playbook_id=f"pb_hindsight_{pipeline}_{int(time.time())}",
                    name=f"hindsight_{pipeline}",
                    description=f"后见之明技能 (来自 {pipeline} 运行轨迹)",
                    steps=steps,
                    tags=["hindsight", pipeline],
                )
                self.playbook.register_playbook(pb)
                written += len(steps)
            except Exception as e:
                logger.warning("HindsightSkillMiner playbook register failed: %s", str(e)[:50])
        if self.skill_claw is not None:
            for s in skills:
                try:
                    self.skill_claw.register_skill(
                        skill_id=f"hs_{s.skill_type}_{abs(hash(s.signal)) % 100000}",
                        name=f"{s.skill_type}:{s.signal[:30]}",
                        description=s.content[:120],
                        tags=["hindsight", s.skill_type, s.source_pipeline],
                        body=s.skill_body(),
                    )
                except Exception:
                    pass
        logger.info("HindsightSkillMiner: %s 提炼 %d 条技能 -> Playbook steps=%d",
                    pipeline, len(skills), len(steps))
        return written
