"""Phase 3 测试: T2 语义→参数映射器(SemanticToParam).

验证: learn 语义聚类 -> 系统可调维度强化提案; 偶发主题不强化;
提案经 T1 inject_gene_specs 而非绕过验证.
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from prometheus_nexus.evolution.semantic_to_param import SemanticToParam


class _Node:
    def __init__(self, tags, content, utility=0.5):
        self.tags = tags
        self.content = content
        self.utility = utility
        self.id = "n"


def _make_nodes():
    nodes = [_Node(["sparse"], "sparse attention mechanism", 0.6) for _ in range(4)]
    nodes += [_Node(["decay"], "memory decay and forgetting curve", 0.4) for _ in range(3)]
    nodes += [_Node(["random"], "unrelated cooking recipe", 0.2) for _ in range(1)]
    return nodes


def test_derive_proposals_maps_theme_to_param():
    m = SemanticToParam(freq_threshold=3)
    props = m.derive_proposals(_make_nodes())
    params = {p["param"] for p in props}
    assert "attention_sparsity" in params
    assert "memory_decay" in params


def test_derive_proposals_skips_rare_theme():
    m = SemanticToParam(freq_threshold=3)
    props = m.derive_proposals(_make_nodes())
    themes = {p["theme"] for p in props}
    assert "random" not in themes  # 偶发主题不强化


def test_proposal_interval_derived_from_default():
    m = SemanticToParam(freq_threshold=3)
    props = m.derive_proposals(_make_nodes())
    sp = next(p for p in props if p["param"] == "attention_sparsity")
    # default=0.1 -> (0.05, 0.15)
    assert sp["lo"] == 0.05
    assert sp["hi"] == 0.15


def test_proposal_confidence_scales_with_freq():
    m = SemanticToParam(freq_threshold=3)
    props = m.derive_proposals(_make_nodes())
    sp = next(p for p in props if p["param"] == "attention_sparsity")
    assert 0.0 < sp["confidence"] <= 1.0
    assert sp["freq"] >= 3


def test_proposals_to_specs_format():
    m = SemanticToParam(freq_threshold=3)
    props = m.derive_proposals(_make_nodes())
    specs = m.proposals_to_specs(props)
    assert all(isinstance(v, tuple) and len(v) == 2 for v in specs.values())
    assert "attention_sparsity" in specs


def test_no_matching_theme_yields_empty():
    m = SemanticToParam(freq_threshold=1)
    nodes = [_Node(["x"], "totally unrelated text", 0.1)]
    props = m.derive_proposals(nodes)
    assert props == []
