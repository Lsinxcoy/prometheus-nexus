"""BaseMechanism — 四轨进化产出的机制统一契约。

T3(机制提取) / T4(论文编译) 产出的机制都继承此类, 经 MechanismRegistry
注册 + 验证门后由神经系统调度。契约保证:
- 统一接口: run(context) -> result
- 元信息: name / description / dependencies / fitness
- 安全: 不直替生产机制, 先 A-B 并行验证
"""
from __future__ import annotations

import abc
import logging

logger = logging.getLogger(__name__)


class BaseMechanism(abc.ABC):
    """所有四轨机制产物的基类。"""

    # 子类覆盖
    name: str = "unnamed"
    description: str = ""
    dependencies: list[str] = []
    category: str = "general"  # extracted(third-rail) | compiled(fourth-rail) | internal

    def __init__(self):
        self.fitness: float = 0.0
        self.invoke_count: int = 0

    @abc.abstractmethod
    def run(self, context: dict | None = None) -> dict:
        """机制执行入口。返回 dict(含 'ok': bool 等)。"""
        raise NotImplementedError

    def health_check(self) -> bool:
        """机制健康自检(默认 True, 子类可重载)。"""
        return True

    def meta(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "dependencies": self.dependencies,
            "category": self.category,
            "fitness": self.fitness,
            "invoke_count": self.invoke_count,
        }
