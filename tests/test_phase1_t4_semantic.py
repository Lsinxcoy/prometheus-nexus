"""Phase 1 测试: T4 run() 语义校验(劣质空壳草案不挂载).

验证 mechanism_compiler._validate_draft 在编译通过后, 仍拒绝 run() 空壳/未用 context.
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from prometheus_nexus.mechanisms.mechanism_compiler import (
    MechanismCompiler, BaseMechanism,
)


class _FakeLLM:
    def __init__(self, responses):
        self._r = list(responses)
        self.available = True
        self.calls = 0
    def complete(self, prompt, system=None, temperature=0.3, max_tokens=2048):
        self.calls += 1
        return self._r.pop(0) if self._r else None


def test_run_shell_no_context_rejected():
    assert MechanismCompiler._run_is_non_trivial(
        'class M(BaseMechanism):\n    def run(self, x):\n        return {"ok": True}\n'
    ) is False


def test_run_refs_context_but_pure_ok_rejected():
    assert MechanismCompiler._run_is_non_trivial(
        'class M(BaseMechanism):\n    def run(self, context):\n        return {"ok": True}\n'
    ) is False


def test_run_with_real_logic_accepted():
    assert MechanismCompiler._run_is_non_trivial(
        'class M(BaseMechanism):\n'
        '    def run(self, context):\n'
        '        v = context.get("x", 0)\n'
        '        return {"ok": True, "doubled": v * 2}\n'
    ) is True


def test_no_run_method_rejected():
    assert MechanismCompiler._run_is_non_trivial('class M(BaseMechanism):\n    pass\n') is False


def test_validate_draft_rejects_shell_after_compile_ok():
    """_validate_draft 应编译通过但 run() 空壳 -> 返回 None(不挂载)."""
    c = MechanismCompiler(llm=_FakeLLM([]))
    shell = ('class M(BaseMechanism):\n'
             '    def run(self, context):\n'
             '        return {"ok": True}\n')
    assert c._validate_draft(shell, "M") is None


def test_validate_draft_accepts_real_mechanism():
    c = MechanismCompiler(llm=_FakeLLM([]))
    good = ('class M(BaseMechanism):\n'
            '    def run(self, context):\n'
            '        v = context.get("x", 0)\n'
            '        return {"ok": True, "doubled": v * 2}\n')
    assert c._validate_draft(good, "M") == good


def test_compile_with_fix_discards_persistent_shell():
    """LLM 始终吐空壳 -> 自修正循环耗尽 -> 丢弃(None)."""
    shell = ('class M(BaseMechanism):\n'
             '    def run(self, context):\n'
             '        return {"ok": True}\n')
    c = MechanismCompiler(llm=_FakeLLM([shell, shell, shell]))
    result = c._compile_draft_with_fix(shell, "M", system="x", paper_context="p")
    assert result is None  # 劣质草案被丢弃, 不挂载
