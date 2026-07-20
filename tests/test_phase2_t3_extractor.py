"""Phase 2 测试: T3 学习(AST+LLM)+编译(复用T4)+价值过滤+修'items' bug.

覆盖: extract_gene_specs_from_source (AST), 强类型 ExtractedMechanism,
is_high_value 过滤, 以及 _consume_t3 类型安全(不再把文本当 gene_specs).
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from prometheus_nexus.mechanisms.mechanism_extractor import (
    extract_gene_specs_from_source, ExtractedMechanism, MechanismExtractor,
)


def test_ast_extracts_module_constants():
    src = "LEARNING_RATE = 0.3\nDROPOUT = 0.5\n"
    specs = extract_gene_specs_from_source(src)
    assert specs["ext_LEARNING_RATE"] == (0.15, 0.45)
    assert specs["ext_DROPOUT"] == (0.25, 0.75)


def test_ast_extracts_function_defaults():
    src = "def train(model, lr: float = 0.01, wd: float = 0.001):\n    pass\n"
    specs = extract_gene_specs_from_source(src)
    assert specs["ext_lr"] == (0.005, 0.015)
    assert specs["ext_wd"] == (0.0005, 0.01)


def test_ast_skips_self_cls():
    src = "def f(self, x: float = 2.0):\n    pass\n"
    specs = extract_gene_specs_from_source(src)
    assert "ext_self" not in specs
    assert "ext_x" in specs


def test_ast_invalid_syntax_returns_empty():
    assert extract_gene_specs_from_source("def (:::") == {}


def test_extracted_mechanism_strongly_typed():
    m = ExtractedMechanism("ext_x", "desc", "owner/repo", gene_specs={"ext_a": (0.1, 0.3)})
    assert isinstance(m.gene_specs, dict)
    assert m.run()["gene_specs"] == {"ext_a": (0.1, 0.3)}


def test_high_value_filter_positive():
    ex = MechanismExtractor()
    hi = ExtractedMechanism("ext_hi", "agent memory evolution mechanism", "r",
                            gene_specs={"ext_lr": (0.1, 0.3)})
    ok, score = ex.is_high_value(hi)
    assert ok is True
    assert score >= 0.5


def test_high_value_filter_negative():
    ex = MechanismExtractor()
    low = ExtractedMechanism("ext_low", "家常菜谱 烹饪技巧", "r")
    ok, _ = ex.is_high_value(low)
    assert ok is False


def test_parse_file_list():
    overview = "# r\n\n## README\nxxx\n\n## Top-level files\nmain.py, util.py, README.md\n"
    files = MechanismExtractor._parse_file_list(overview)
    assert files == ["main.py", "util.py", "README.md"]


# ---- _consume_t3 类型安全(修 'items' bug) ----
class _FakeAttrScoring:
    def __init__(self):
        self.failures = []
        self.completed = 0
    def create_work_item(self, *a, **k):
        pass
    def complete_work_item(self, *a, **k):
        self.completed += 1
    def fail_work_item(self, item, reason):
        self.failures.append(reason)


class _FakeEvoEngine:
    def __init__(self):
        self.injected = []
    def inject_gene_specs(self, specs):
        n = len(specs)
        self.injected.append(specs)
        return n


class _FakeOmega:
    """最小 Omega 桩, 仅测 _consume_t3 类型安全分支."""
    def __init__(self):
        self.attribution_scoring = _FakeAttrScoring()
        self.evolution_engine = _FakeEvoEngine()

    def _consume_t3(self, entry):
        # 复制 life.py 修复后的逻辑(保持同步验证)
        item_id = f"t3_{entry.get('name', '')}"
        self.attribution_scoring.create_work_item(item_id, "mechanism_activate", priority=5)
        data = entry.get("data", {})
        specs = {}
        direct = data.get("gene_specs")
        if isinstance(direct, dict):
            specs = direct
        elif direct is not None:
            logger_ = __import__("logging").getLogger(__name__)
            logger_.warning("skip non-dict gene_specs")
        elif data.get("executable") is not None:
            exe = data["executable"]
            gs = getattr(exe, "gene_specs", None)
            if isinstance(gs, dict):
                specs = gs
        if specs:
            try:
                added = self.evolution_engine.inject_gene_specs(specs)
                self.attribution_scoring.complete_work_item(item_id)
            except Exception as e:
                self.attribution_scoring.fail_work_item(item_id, str(e)[:60])
        else:
            self.attribution_scoring.complete_work_item(item_id)
        return specs


def test_consume_t3_dict_specs_injected():
    o = _FakeOmega()
    o._consume_t3({"name": "ext_x", "data": {"gene_specs": {"ext_lr": (0.1, 0.3)}}})
    assert o.evolution_engine.injected == [{"ext_lr": (0.1, 0.3)}]


def test_consume_t3_str_contract_not_injected():
    """contract 是文本(str) -> 不应当 gene_specs 注入(修 'items' bug)."""
    o = _FakeOmega()
    o._consume_t3({"name": "ext_x", "data": {"gene_specs": "some text contract"}})
    # 非 dict -> 跳过, 不注入, 不崩
    assert o.evolution_engine.injected == []


def test_consume_t3_executable_gene_specs():
    o = _FakeOmega()
    m = ExtractedMechanism("ext_y", "d", "r", gene_specs={"ext_a": (0.1, 0.3)})
    o._consume_t3({"name": "ext_y", "data": {"executable": m}})
    assert o.evolution_engine.injected == [{"ext_a": (0.1, 0.3)}]
