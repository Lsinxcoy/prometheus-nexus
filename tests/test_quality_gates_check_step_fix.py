"""周期14: EvolutionQualityGates.check_step 步数预算门禁从恒通过(no-op)修复为真门禁.

薄弱点 (代码级证据):
  src/prometheus_nexus/evolution/evolution_quality_gates.py:293-296
    def check_step(self, step="", step_number=0, max_steps=0):
        # 默认允许继续
        return True, "step allowed"
  该方法签名含 step_number / max_steps, 文档称"检查步骤是否允许继续",
  但函数体恒返回 (True, "step allowed"), 完全无视输入。

生产调用方 (真实门控):
  src/prometheus_nexus/life.py:2315-2319
    allowed, reason = self.evo_quality_gates.check_step("evolve", 1, max_steps=loop_config.max_steps)
    if not allowed:
        blocked = EvolutionOutcome(result=EvolutionResult.BLOCKED, details=reason)
        ...
        return blocked
  -> check_step 恒 True => 该 BLOCKED 分支永不被触发 => step-budget 门禁在生产路径被 100% 静默绕过。

修复: check_step 真正执行预算门禁 (step_number >= max_steps 时阻断并 logger.warning);
      max_steps<=0 视为不限制 (向后兼容旧调用方)。
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from prometheus_nexus.evolution.evolution_quality_gates import EvolutionQualityGates


def _gate(gates, step_number, max_steps, step="evolve"):
    """复刻 life.py:2315 的门控解包语义。"""
    allowed, reason = gates.check_step(step, step_number, max_steps=max_steps)
    return allowed, reason


def test_check_step_blocks_at_budget_limit():
    """步数达到预算上限(>=max_steps)必须阻断 (修复前恒返回 True)。"""
    g = EvolutionQualityGates()
    allowed, reason = _gate(g, step_number=5, max_steps=5)
    assert allowed is False
    assert "budget" in reason.lower()
    assert "5" in reason


def test_check_step_blocks_far_over_budget():
    """远超预算 (step 9 vs max 5) 必须阻断。"""
    g = EvolutionQualityGates()
    allowed, reason = _gate(g, step_number=9, max_steps=5)
    assert allowed is False
    assert "9" in reason and "5" in reason


def test_check_step_allows_within_budget():
    """预算内 (step 1 vs max 5) 仍允许, 且不误伤正常进化。"""
    g = EvolutionQualityGates()
    allowed, reason = _gate(g, step_number=1, max_steps=5)
    assert allowed is True
    assert reason == "step allowed"


def test_check_step_unlimited_when_max_steps_zero():
    """max_steps<=0 视为不限制 (向后兼容旧调用方无预算场景)。"""
    g = EvolutionQualityGates()
    allowed, reason = _gate(g, step_number=100, max_steps=0)
    assert allowed is True
    assert reason == "step allowed"


def test_check_step_default_args_no_budget_still_allowed():
    """无参数调用 (旧兼容路径) 仍允许, 不改变既有行为。"""
    g = EvolutionQualityGates()
    allowed, reason = g.check_step()
    assert allowed is True
    assert reason == "step allowed"


def test_check_step_blocks_emits_warning(caplog):
    """阻断时必须显式 logger.warning 暴露, 不再静默失败。"""
    import logging
    g = EvolutionQualityGates()
    with caplog.at_level(logging.WARNING, logger="prometheus_nexus.evolution.evolution_quality_gates"):
        allowed, reason = _gate(g, step_number=7, max_steps=5)
    assert allowed is False
    assert any("blocked step" in r.message for r in caplog.records)
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_check_step_integration_blocks_evolve_pipeline():
    """集成语义: 复刻 life.py 的 `if not allowed: BLOCKED` 分支, 验证越界确实阻断进化。"""
    g = EvolutionQualityGates()
    # 模拟已用尽预算的 evolve 调用
    allowed, reason = g.check_step("evolve", step_number=12, max_steps=10)
    blocked = None
    if not allowed:
        blocked = ("BLOCKED", reason)
    assert blocked is not None
    assert blocked[0] == "BLOCKED"
    assert "budget" in blocked[1].lower()
