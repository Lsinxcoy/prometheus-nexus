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


# 机制运行阶段(对应 Omega/Nexus 主循环 remember/recall/evolve/learn/reflect/dream...)
class Phase:
    INGEST = "ingest"          # 写入 / 采集
    RETRIEVE = "retrieve"      # 检索 / 读取
    REASON = "reason"          # 推理 / 规划
    EVOLVE = "evolve"          # 进化 / 自改
    LEARN = "learn"            # 外部学习
    REFLECT = "reflect"        # 反思 / 评估
    DREAM = "dream"            # 巩固 / 离线
    GOVERN = "govern"          # 安全 / 治理
    ANY = "any"                # 不限定阶段


class BaseMechanism(abc.ABC):
    """所有四轨机制产物的基类。

    扩展(2026-07-23, 架构优化 P1): 接入点声明。
    - phase: 机制应在主循环的哪个阶段被调度
    - hooks_into: 挂到宿主哪个方法/事件之后(可选, 细粒度介入)
    - auto_wire: 是否允许 Orchestrator 自动从注册表收集并接入(默认 False,
      保持向后兼容 — 既有硬编码调度不受影响)

    设计意图: 让新增机制 / 复活机制(如文档点名的 LOCA/CARA/CAMP)能
    *声明式*接入主循环, 而非人肉改 life.py 的 5333 行硬编码调度。
    这是根治 _remaining.py 堆砌与死代码盲区的方式。
    """

    # 子类覆盖
    name: str = "unnamed"
    description: str = ""
    dependencies: list[str] = []
    category: str = "general"  # extracted(third-rail) | compiled(fourth-rail) | internal

    # 接入点声明(架构优化 P1, 默认不自动接入)
    phase: str = Phase.ANY
    hooks_into: str | None = None      # 例如 "after_store" / "post_evolve"
    auto_wire: bool = False            # 默认 False: 不自动接入, 兼容现有硬编码调度

    def __init__(self):
        self.fitness: float = 0.0
        self.invoke_count: int = 0
        # 机制级运行时指标 (架构优化 P2: 遥测地基)
        # 由 wiring.run_phase 自动填充, 机制作者无需手改
        self._metrics: dict = {
            "total_latency_ms": 0.0,   # 累计运行延迟
            "call_count": 0,           # 被调度次数(含经 wiring)
            "error_count": 0,          # 运行异常次数
            "last_latency_ms": 0.0,    # 最近一次延迟
            "last_error": None,        # 最近一次异常信息
        }

    def record_latency(self, ms: float) -> None:
        """记录一次运行延迟 (由 wiring.run_phase 自动调用)."""
        self._metrics["total_latency_ms"] += ms
        self._metrics["last_latency_ms"] = ms
        self._metrics["call_count"] += 1

    def record_error(self, exc: Exception) -> None:
        """记录一次运行异常."""
        self._metrics["error_count"] += 1
        self._metrics["last_error"] = str(exc)

    @property
    def avg_latency_ms(self) -> float:
        """平均延迟. 无调用返回 0."""
        c = self._metrics["call_count"]
        return self._metrics["total_latency_ms"] / c if c else 0.0

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
            "phase": self.phase,
            "hooks_into": self.hooks_into,
            "auto_wire": self.auto_wire,
            "metrics": {
                "total_latency_ms": round(self._metrics["total_latency_ms"], 3),
                "call_count": self._metrics["call_count"],
                "error_count": self._metrics["error_count"],
                "avg_latency_ms": round(self.avg_latency_ms, 3),
                "last_latency_ms": round(self._metrics["last_latency_ms"], 3),
                "last_error": self._metrics["last_error"],
            },
        }
