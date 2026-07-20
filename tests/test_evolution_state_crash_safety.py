"""cycle17 — EvolutionState 崩溃安全 + 失败可见性 测试。

针对 evolution_state.py 的薄弱点修复:
  * save() 原 open(path,'w') 非原子写 -> 崩溃中途写即截断唯一状态文件, 重启丢失进化进度;
    现改临时文件 + fsync + os.replace 原子写, 覆盖前备分上一版完好状态为 .bak。
  * save()/load() 原失败仅 logger.debug(生产默认级别下不可见) -> 进化进度静默丢失;
    现一律 logger.warning 暴露。
  * load() 原损坏即静默返 False -> 现损坏回退 .bak 并 WARNING。

反向验证: 旧代码在 save 失败时记 DEBUG(非 WARNING), 故本文件所有
'失败必须 WARNING' 断言在旧代码下必失败 —— 证明非假绿。
"""
from __future__ import annotations

import builtins
import json
import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from prometheus_nexus.evolution.evolution_state import EvolutionState

LOGGER = "prometheus_nexus.evolution.evolution_state"


class _FakeEngine:
    def __init__(self, specs=None, gen=0):
        self._gene_specs = specs or {}
        self._generation = gen


def test_save_writes_valid_atomic_file(tmp_path):
    p = str(tmp_path / "evo_state.json")
    st = EvolutionState(path=p)
    eng = _FakeEngine({"g1": ("a", "b")}, 3)
    assert st.save(eng) is True
    assert os.path.exists(p)
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    assert data["generation"] == 3
    assert data["gene_specs"]["g1"] == ["a", "b"]
    # 原子写: 无残留 .tmp
    assert not os.path.exists(p + ".tmp")


def test_save_rotates_bak_of_previous_good_state(tmp_path):
    p = str(tmp_path / "evo_state.json")
    st = EvolutionState(path=p)
    assert st.save(_FakeEngine({"g1": ("a",)}, 1)) is True
    # 再次 save 前, .bak 应为上一次完整写(gen=1)
    assert st.save(_FakeEngine({"g2": ("b",)}, 2)) is True
    assert os.path.exists(p + ".bak")
    with open(p + ".bak", encoding="utf-8") as f:
        bak = json.load(f)
    assert bak["generation"] == 1
    assert "g1" in bak["gene_specs"]


def test_save_failure_logs_warning_not_debug(tmp_path, caplog):
    p = str(tmp_path / "evo_state.json")
    st = EvolutionState(path=p)
    real_open = builtins.open
    builtins.open = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
    try:
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            ok = st.save(_FakeEngine())
    finally:
        builtins.open = real_open
    assert ok is False
    # 关键: 失败必须以 WARNING 暴露; 旧代码用 DEBUG -> 此断言在旧代码失败(非假绿)
    warns = [r for r in caplog.records
             if r.levelno == logging.WARNING and "EvolutionState.save" in r.getMessage()]
    assert warns, "save 失败必须以 WARNING 暴露, 旧代码记 DEBUG 会静默丢失进度"
    # 且不应有半截 .tmp 残留
    assert not os.path.exists(p + ".tmp")


def test_load_corrupt_main_falls_back_to_bak_with_warning(tmp_path, caplog):
    p = str(tmp_path / "evo_state.json")
    st = EvolutionState(path=p)
    # 两次 save 后 .bak 持有第一次的完整写(gen=5); 主文件=gen=7
    assert st.save(_FakeEngine({"g1": ("a",)}, 5)) is True
    assert st.save(_FakeEngine({"g2": ("b",)}, 7)) is True
    with open(p, "w", encoding="utf-8") as f:
        f.write("{ this is not json")
    eng = _FakeEngine()
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        ok = st.load(eng)
    assert ok is True
    # 从 .bak 恢复的是第一次写(gen=5, g1)
    assert eng._gene_specs.get("g1") == ("a",)
    assert eng._generation == 5
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warns


def test_load_no_file_is_benign_first_run(tmp_path, caplog):
    p = str(tmp_path / "evo_state_nofile.json")
    st = EvolutionState(path=p)
    eng = _FakeEngine()
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        ok = st.load(eng)
    assert ok is False
    # 首跑(无文件)不是故障, 不应 WARNING
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert not warns


def test_load_both_corrupt_logs_warning_and_returns_false(tmp_path, caplog):
    p = str(tmp_path / "evo_state.json")
    st = EvolutionState(path=p)
    with open(p, "w", encoding="utf-8") as f:
        f.write("garbage")
    with open(p + ".bak", "w", encoding="utf-8") as f:
        f.write("garbage")
    eng = _FakeEngine()
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        ok = st.load(eng)
    assert ok is False
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warns
