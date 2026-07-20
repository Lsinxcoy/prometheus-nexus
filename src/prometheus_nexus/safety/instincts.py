"""InstinctsRegistry — instinct-based safety evaluation.

Based on: Biological instinct metaphor for zero-latency safety checks.
"""
from __future__ import annotations



import logging

logger = logging.getLogger(__name__)

class InstinctsRegistry:
    def __init__(self):
        self._instincts: list[dict] = []
        self._trigger_counts: dict[str, int] = {}
        self._recent_triggers: list[dict] = []
        self.nexus = None  # 反向引用: Nexus 统一调用图(旁路记账, 零延迟保留)

    def register(self, name: str, check_fn, action: str = "warn"):
        self._instincts.append({"name": name, "check": check_fn, "action": action})

    def evaluate_all(self, context: dict) -> list[dict]:
        results = []
        for inst in self._instincts:
            try:
                passed = inst["check"](context)
                # 旁路记账进 Nexus 统一调用图(零延迟: 仅计数, 不转发)
                if self.nexus is not None:
                    self.nexus.mark_invoked(inst["name"])
                if not passed:
                    self._trigger_counts[inst["name"]] = self._trigger_counts.get(inst["name"], 0) + 1
                    self._recent_triggers.append({"name": inst["name"], "action": inst["action"]})
                    if len(self._recent_triggers) > 100:
                        self._recent_triggers = self._recent_triggers[-50:]
                    results.append({"instinct": inst["name"], "result": {"action": inst["action"]}})
            except Exception as e:
                logger.warning("Instinct check failed for %s: %s", inst.get("name", "unknown"), e)
        return results

    def get_stats(self) -> dict:
        return {
            "instincts": len(self._instincts),
            "trigger_counts": dict(self._trigger_counts),
            "recent_triggers": len(self._recent_triggers),
        }


def register_default_instincts(registry: InstinctsRegistry):
    registry.register("utility_floor", lambda ctx: ctx.get("utility", 0.5) >= 0.1, "block")
    registry.register("surprise_clamp", lambda ctx: 0.0 <= ctx.get("surprise", 0.0) <= 1.0, "block")
    registry.register("content_required", lambda ctx: len(ctx.get("content", "").strip()) > 0, "block")
    registry.register("content_length_max", lambda ctx: len(ctx.get("content", "")) < 50000, "block")
    registry.register("tag_format", lambda ctx: isinstance(ctx.get("tags", []), list), "warn")
    registry.register("no_empty_tags", lambda ctx: len(ctx.get("tags", [])) > 0, "warn")
