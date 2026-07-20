"""针对 CrashStateRestore.save_checkpoint 崩溃安全薄弱点的回归测试。

修复前薄弱点 (cycle 22):
  1. checkpoint_id = len(self._checkpoints) + 1 依赖内存列表, 进程重启后
     _checkpoints 清空 -> 从 1 重新编号 -> 覆盖上一会话的 checkpoint_1.json,
     且旧会话高编号文件 (orphan) 永不清理。
  2. file_path.write_text(...) 非原子写, 崩溃中途留半截文件, 且无写后校验,
     损坏检查点被静默写入。

修复后: 编号基于磁盘已有文件 (重启不碰撞/不覆盖); 原子写 (tmp+fsync+replace);
写后哈希校验 fail-loud; 损坏文件跳过加载但保留其编号不被复用。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from prometheus_nexus.harness.crash_restore import CrashStateRestore


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---- 核心回归: 重启后保留旧检查点 + 编号续接, 不覆盖 ----

def test_restart_preserves_prior_checkpoint_and_continues_id(tmp_path):
    # 模拟"上一次会话"写了一个检查点
    cr1 = CrashStateRestore(checkpoint_dir=str(tmp_path))
    cp1 = cr1.save_checkpoint({"session": "A", "n": 1})
    assert cp1.checkpoint_id == 1
    f1 = tmp_path / "checkpoint_1.json"
    assert f1.exists()
    assert _read_json(f1)["session"] == "A"

    # 模拟"进程重启": 全新实例, 同一目录
    cr2 = CrashStateRestore(checkpoint_dir=str(tmp_path))
    cp2 = cr2.save_checkpoint({"session": "B", "n": 2})
    assert cp2.checkpoint_id == 2, "重启后应从磁盘编号续接, 而非覆盖 checkpoint_1"

    f2 = tmp_path / "checkpoint_2.json"
    assert f2.exists()
    # 关键: 旧会话的 checkpoint_1.json 必须仍然完好 (未被覆盖/丢失)
    assert f1.exists(), "重启后旧检查点文件不应被覆盖"
    assert _read_json(f1)["session"] == "A"
    assert _read_json(f2)["session"] == "B"

    # restore_latest 应返回最新 (B)
    restored = cr2.restore_latest()
    assert restored is not None
    assert restored["session"] == "B"


# ---- 往返保真 ----

def test_roundtrip_restore_returns_saved_state(tmp_path):
    cr = CrashStateRestore(checkpoint_dir=str(tmp_path))
    state = {"maintain_cycle": 123.0, "nodes": 42}
    cr.save_checkpoint(state)
    out = cr.restore_latest()
    assert out == state


def test_restore_latest_on_empty_dir_is_none(tmp_path):
    cr = CrashStateRestore(checkpoint_dir=str(tmp_path))
    assert cr.restore_latest() is None


# ---- 原子写: 无残留 .tmp, 最终文件有效 ----

def test_atomic_write_leaves_no_tmp_and_valid_final(tmp_path):
    cr = CrashStateRestore(checkpoint_dir=str(tmp_path))
    cr.save_checkpoint({"k": "v"})
    tmps = list(tmp_path.glob("checkpoint_*.json.tmp"))
    assert tmps == [], "原子写不应残留临时文件"
    finals = list(tmp_path.glob("checkpoint_*.json"))
    assert len(finals) == 1
    # 最终文件必须是合法 JSON
    _read_json(finals[0])


def test_atomic_write_cleans_tmp_on_replace_failure(tmp_path, monkeypatch):
    cr = CrashStateRestore(checkpoint_dir=str(tmp_path))

    def boom(*a, **k):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        cr.save_checkpoint({"k": "v"})
    # 异常路径必须清理半截临时文件
    tmps = list(tmp_path.glob("checkpoint_*.json.tmp"))
    assert tmps == [], "replace 失败后必须清理临时文件"
    # 写入未完成: 不应留下最终文件
    assert list(tmp_path.glob("checkpoint_*.json")) == []


# ---- 写后校验 fail-loud: 读回与写入不一致即抛错, 杜绝静默损坏 ----

def test_write_verification_fails_loud_on_corruption(tmp_path, monkeypatch):
    cr = CrashStateRestore(checkpoint_dir=str(tmp_path))
    # 模拟"写后读回内容被篡改" (磁盘位翻转 / 读路径损坏)
    orig = Path.read_text

    def fake_read_text(self, *a, **k):
        return "TAMPERED_CONTENT_NOT_JSON"

    monkeypatch.setattr(Path, "read_text", fake_read_text)
    with pytest.raises(IOError):
        cr.save_checkpoint({"k": "v"})


# ---- 损坏检查点文件: 跳过加载, 但保留其编号不被复用 (不覆盖) ----

def test_corrupt_checkpoint_skipped_but_id_reserved(tmp_path):
    # 预置一个合法 checkpoint_1 与一个损坏 checkpoint_3
    (tmp_path / "checkpoint_1.json").write_text(
        json.dumps({"session": "A"}), encoding="utf-8"
    )
    (tmp_path / "checkpoint_3.json").write_text("{not valid json", encoding="utf-8")

    cr = CrashStateRestore(checkpoint_dir=str(tmp_path))
    # 只加载了合法的 checkpoint_1, checkpoint_3 被跳过 (记 warning)
    loaded_ids = [c.checkpoint_id for c in cr._checkpoints]
    assert loaded_ids == [1]

    # 下一个编号应为 4 (基于磁盘最大文件名, 不复用损坏文件的 id=3)
    cp = cr.save_checkpoint({"session": "B"})
    assert cp.checkpoint_id == 4
    assert (tmp_path / "checkpoint_1.json").exists()
    assert (tmp_path / "checkpoint_3.json").exists(), "损坏文件不应被静默覆盖"
    # 合法旧检查点仍可恢复
    restored = cr.restore_latest()
    assert restored is not None
    assert restored["session"] == "B"


# ---- 多次保存受 _max 限制, 不无限增长 ----

def test_checkpoint_count_bounded_by_max(tmp_path):
    cr = CrashStateRestore(checkpoint_dir=str(tmp_path), max_checkpoints=3)
    for i in range(10):
        cr.save_checkpoint({"i": i})
    # 磁盘文件数应收敛到 max_checkpoints
    files = list(tmp_path.glob("checkpoint_*.json"))
    assert len(files) == 3, f"检查点文件应受 max 限制, 实际 {len(files)}"
    # restore_latest 应为最后一次 (i=9)
    assert cr.restore_latest()["i"] == 9
