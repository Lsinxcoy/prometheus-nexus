"""PlaybookInheritance — Playbook继承机制

借鉴OpenOPC的Playbook Inheritance概念：
- 基础Playbook定义通用操作流程
- 派生Playbook继承并扩展基础功能
- 支持模板化配置和参数化执行
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from copy import deepcopy

logger = logging.getLogger(__name__)


@dataclass
class PlaybookStep:
    """Playbook步骤"""
    step_id: str
    name: str
    operation: str
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    condition: str = ""  # 条件表达式（可选）
    default_timeout: float = 30.0


@dataclass
class Playbook:
    """Playbook - 可复用的操作手册"""
    playbook_id: str
    name: str
    description: str = ""
    version: str = "1.0"
    steps: list[PlaybookStep] = field(default_factory=list)
    variables: dict[str, Any] = field(default_factory=dict)
    parent_playbook_id: str | None = None  # 父Playbook ID
    parent_resolver: Callable[[str], "Playbook | None"] | None = None  # 父 Playbook 查找器 (由 PlaybookInheritance 注入)
    tags: list[str] = field(default_factory=list)

    def get_step(self, step_id: str) -> PlaybookStep | None:
        """获取指定步骤"""
        for step in self.steps:
            if step.step_id == step_id:
                return step
        return None

    def resolve_variable(self, var_name: str) -> Any:
        """解析变量值，优先使用本地变量，其次沿继承链向上查找父 Playbook 变量。"""
        if var_name in self.variables:
            return self.variables[var_name]
        # 沿继承链向上解析父 Playbook 变量 (修复: 原 TODO 未实现, 直接返回 None 导致继承变量静默丢失)
        if self.parent_playbook_id and self.parent_resolver is not None:
            parent = self.parent_resolver(self.parent_playbook_id)
            if parent is not None:
                return parent.resolve_variable(var_name)
        return None


class PlaybookInheritance:
    """Playbook继承系统

    支持基础Playbook派生出专用Playbook，实现操作流程的复用和扩展。
    """

    def __init__(self):
        self._playbooks: dict[str, Playbook] = {}
        self._inheritance_map: dict[str, str] = {}  # child_id -> parent_id

    def register_playbook(self, playbook: Playbook) -> bool:
        """注册Playbook"""
        if playbook.playbook_id in self._playbooks:
            logger.warning("Playbook %s already registered", playbook.playbook_id)
            return False

        # 注入父 Playbook 查找器, 使 resolve_variable 能沿继承链解析变量
        playbook.parent_resolver = lambda pid: self._playbooks.get(pid)

        self._playbooks[playbook.playbook_id] = playbook

        # 记录继承关系
        if playbook.parent_playbook_id:
            self._inheritance_map[playbook.playbook_id] = playbook.parent_playbook_id

        logger.info("Registered playbook: %s (v%s)", playbook.name, playbook.version)
        return True

    def create_derived_playbook(
        self,
        parent_id: str,
        derived_id: str,
        name: str,
        additional_steps: list[PlaybookStep] | None = None,
        override_variables: dict[str, Any] | None = None,
    ) -> Playbook | None:
        """创建派生Playbook

        Args:
            parent_id: 父Playbook ID
            derived_id: 派生Playbook ID
            name: 派生Playbook名称
            additional_steps: 额外添加的步骤
            override_variables: 覆盖的变量

        Returns:
            新创建的Playbook或None
        """
        if parent_id not in self._playbooks:
            logger.error("Parent playbook %s not found", parent_id)
            return None

        parent = self._playbooks[parent_id]

        # 深拷贝父Playbook的步骤
        derived_steps = deepcopy(parent.steps)

        # 添加额外步骤
        if additional_steps:
            derived_steps.extend(additional_steps)

        # 合并变量
        derived_variables = deepcopy(parent.variables)
        if override_variables:
            derived_variables.update(override_variables)

        # 创建派生Playbook
        derived = Playbook(
            playbook_id=derived_id,
            name=name,
            description=f"Derived from {parent.name}",
            version="1.0",
            steps=derived_steps,
            variables=derived_variables,
            parent_playbook_id=parent_id,
            tags=parent.tags + ["derived"],
        )

        # 注册
        self.register_playbook(derived)
        logger.info("Created derived playbook %s from %s", derived_id, parent_id)
        return derived

    def get_playbook(self, playbook_id: str) -> Playbook | None:
        """获取Playbook"""
        return self._playbooks.get(playbook_id)

    def get_inheritance_chain(self, playbook_id: str) -> list[str]:
        """获取继承链（从当前到根）"""
        chain = []
        current = playbook_id
        while current:
            chain.append(current)
            current = self._inheritance_map.get(current)
        return chain

    def execute_playbook(self, playbook_id: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """执行Playbook

        按照依赖顺序执行所有步骤。
        """
        playbook = self.get_playbook(playbook_id)
        if not playbook:
            return {"status": "error", "message": f"Playbook {playbook_id} not found"}

        context = context or {}
        results: dict[str, Any] = {}
        executed_steps: set[str] = set()

        # 按依赖顺序执行步骤
        for step in playbook.steps:
            # 检查依赖是否已执行
            if not all(dep in executed_steps for dep in step.depends_on):
                logger.warning("Skipping step %s due to missing dependencies", step.step_id)
                continue

            # 执行步骤
            try:
                result = self._execute_step(step, context)
                results[step.step_id] = {
                    "status": "success",
                    "result": result,
                    "duration_ms": result.get("duration_ms", 0),
                }
                executed_steps.add(step.step_id)
            except Exception as e:
                results[step.step_id] = {
                    "status": "failed",
                    "error": str(e),
                }
                logger.error("Step %s failed: %s", step.step_id, e)

        return {
            "playbook_id": playbook_id,
            "status": "completed",
            "results": results,
            "executed_steps": len(executed_steps),
            "total_steps": len(playbook.steps),
        }

    def _execute_step(self, step: PlaybookStep, context: dict[str, Any]) -> dict[str, Any]:
        """执行单个步骤"""
        start_time = time.time()

        # 这里可以集成实际的操作执行逻辑
        # 目前返回模拟结果
        result = {
            "operation": step.operation,
            "params": step.params,
            "context": context,
        }

        duration_ms = (time.time() - start_time) * 1000
        result["duration_ms"] = duration_ms

        return result
