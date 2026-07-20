"""ModelRouter — Model selection based on query complexity and tool load.

基于:
- "Tool Overload: Small Model Performance with Many Tools" (2024) + Berkeley FC Leaderboard
  - 复杂度估计: 长度(40%)+技术词(40%)+问号(20%)
  - 工具惩罚: tool_count>10时线性惩罚
  - 路由评分: (max_tokens/cost) × (0.5+complexity×0.5) × (1-tool_penalty)
  - 约束过滤: cost/latency/capabilities/tool_count

算法:
    route(query, constraints):
        1. 估计查询复杂度(0-1)
        2. 对每个模型: 检查约束→计算工具惩罚→评分
        3. 选择评分最高的模型

来源: Omega系统 router 模型路由模块 + Berkeley Function-Calling Leaderboard
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


from dataclasses import dataclass, field


@dataclass
class ModelConfig:
    name: str = "default"
    cost_per_1k_tokens: float = 0.01
    max_tokens: int = 4096
    avg_latency_ms: float = 100.0
    capabilities: list[str] | None = None
    max_tools: int = 50
    tool_penalty_per_10: float = 0.05


class ModelRouter:
    """Model selection with tool load awareness.

    Based on Tool Overload paper + Berkeley FC Leaderboard.

    Usage:
        router = ModelRouter({
            "small": ModelConfig(name="small", max_tools=20),
            "large": ModelConfig(name="large", max_tools=100),
        })
        model = router.route("complex task", constraints={"tool_count": 25})
    """

    def __init__(self, models: dict | None = None):
        self._models = models or {"default": ModelConfig()}
        self._routes: list[dict] = []
        self._model_usage: dict[str, int] = {}

    def route(self, query: str, constraints: dict | None = None) -> str:
        constraints = constraints or {}
        max_cost = constraints.get("max_cost", float("inf"))
        max_latency = constraints.get("max_latency_ms", float("inf"))
        required_caps = set(constraints.get("capabilities", []))
        tool_count = constraints.get("tool_count", 0)

        complexity = self._estimate_complexity(query)
        best_model, best_score = None, -1

        for name, model in self._models.items():
            model_caps = set(model.capabilities or [])
            if required_caps and not required_caps.issubset(model_caps):
                continue

            estimated_tokens = len(query.split()) * 2
            estimated_cost = model.cost_per_1k_tokens * estimated_tokens / 1000
            if estimated_cost > max_cost or model.avg_latency_ms > max_latency:
                continue

            if tool_count > model.max_tools:
                continue

            tool_penalty = 0
            if tool_count > 10:
                tool_penalty = (tool_count - 10) / 10 * model.tool_penalty_per_10

            score = (model.max_tokens / max(model.cost_per_1k_tokens, 0.001) *
                    (0.5 + complexity * 0.5) * (1.0 - tool_penalty))

            if score > best_score:
                best_score = score
                best_model = name

        selected = best_model or "default"
        self._routes.append({
            "query": query[:50], "model": selected,
            "complexity": complexity, "tool_count": tool_count,
        })
        self._model_usage[selected] = self._model_usage.get(selected, 0) + 1
        return selected

    def _estimate_complexity(self, query: str) -> float:
        words = query.split()
        length_score = min(1.0, len(words) / 50)
        tech_words = {"algorithm", "implementation", "architecture", "distributed", "optimization"}
        tech_score = min(1.0, sum(1 for w in words if w.lower() in tech_words) * 0.3)
        return min(1.0, length_score * 0.4 + tech_score * 0.4 + (0.3 if "?" in query else 0) * 0.2)

    def suggest_model_for_tools(self, tool_count: int) -> str | None:
        candidates = []
        for name, model in self._models.items():
            if tool_count <= model.max_tools:
                headroom = model.max_tools - tool_count
                candidates.append((name, headroom))
        if not candidates:
            return None
        candidates.sort(key=lambda x: -x[1])
        return candidates[0][0]

    def get_stats(self) -> dict:
        return {
            "routes": len(self._routes),
            "models": len(self._models),
            "model_usage": dict(self._model_usage),
        }
