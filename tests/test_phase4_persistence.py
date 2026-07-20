"""Phase 4 测试: Nexus 持久化 SelectionGate 决策 + 全轨道集成冒烟.

验证: (1) Nexus._persist 写入 selection_gate, _load 恢复; (2) mount_dynamic
默认 candidate(pending) 不直替; (3) evaluate_candidate 按 effect 历史决策.
"""
from __future__ import annotations

import sys
import os
import json
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from prometheus_nexus.cns.nexus import Nexus


def _make_nexus(tmpdir):
    path = os.path.join(tmpdir, "nexus_state.json")
    return Nexus(path=path, store=None)


def test_selection_gate_persist_roundtrip():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        nx = _make_nexus(d)
        # 模拟决策历史
        for _ in range(5):
            nx.selection_gate.observe("cand_a", 0.6, 0.1)
        assert nx.selection_gate.decision_for("cand_a") == "promote"
        nx._persist()
        # 重新加载
        nx2 = _make_nexus(d)
        nx2._load()
        assert nx2.selection_gate.decision_for("cand_a") == "promote"


def test_mount_dynamic_default_candidate_pending():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        nx = _make_nexus(d)

        class FakeMech:
            pass

        res = nx.mount_dynamic("t4_mech", FakeMech(), category="compiled")
        assert res["status"] == "pending", res  # 默认 candidate, 不直替
        assert "t4_mech" not in nx._enabled


def test_mount_dynamic_explicit_activate():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        nx = _make_nexus(d)

        class FakeMech:
            pass

        res = nx.mount_dynamic("t4_mech2", FakeMech(), category="compiled", candidate=False)
        assert res["status"] == "active"  # Nexus 层: 非 candidate 即 active 启用
        assert "t4_mech2" in nx._enabled


def test_evaluate_candidate_promotes_on_superior():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        nx = _make_nexus(d)

        class FakeMech:
            pass

        # 注册 candidate
        nx.mount_dynamic("cand_x", FakeMech(), category="compiled")
        # 模拟 effect 历史: candidate 持续优于 base
        for _ in range(nx.selection_gate.min_samples):
            nx.record_effect("cand_x", 0.7)
            nx.record_effect("base_y", 0.1)
        # 声明 cand_x 接管 base_y
        nx._route_override["base_y"] = "cand_x"
        dec = nx.evaluate_candidate("cand_x", base_name="base_y")
        assert dec == "promote"
        assert nx._mechanisms["cand_x"]["status"] == "active"


def test_evaluate_candidate_prunes_on_inferior():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        nx = _make_nexus(d)

        class FakeMech:
            pass

        nx.mount_dynamic("cand_z", FakeMech(), category="compiled")
        for _ in range(nx.selection_gate.min_samples):
            nx.record_effect("cand_z", -0.3)
            nx.record_effect("base_w", 0.2)
        nx._route_override["base_w"] = "cand_z"
        dec = nx.evaluate_candidate("cand_z", base_name="base_w")
        assert dec == "prune"
        assert nx._mechanisms["cand_z"]["status"] == "disabled"
