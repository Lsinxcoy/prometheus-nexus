"""Cycle25 — CrashRecovery 崩溃安全深化 (复用 cycle22 crash_restore 同构模式).

根因: CrashRecovery 名为"崩溃恢复", 但 create_checkpoint 仅把检查点存于
内存 self._checkpoints, 从不落盘; recover() 读内存列表, 进程崩溃/重启后
列表清空 -> 永远返回 no_checkpoint. 真实路径上 (life.py:3849-3850 每轮
maintain 调用) 这是一个隐藏的 no-op 崩溃恢复. 本测试断言修复后:
  1. create_checkpoint 真实落盘 (文件存在且内容/哈希可校验)
  2. 模拟重启 (同目录新建实例) 后 recover() 返回真实检查点 (非 no_checkpoint)
  3. 编号基于磁盘最大 id+1, 跨重启连续不碰撞/不覆盖
  4. 原子写不留 .tmp 残留
  5. 损坏检查点文件被跳过且不污染恢复链
  6. 全新目录仍返回 no_checkpoint (首跑良性)
"""
import os
import json
import tempfile

import pytest

from prometheus_nexus.harness.crash_recovery import CrashRecovery


def _tmp_dir():
    return tempfile.mkdtemp(prefix="cr_cycle25_")


def test_checkpoint_persisted_to_disk():
    d = _tmp_dir()
    cr = CrashRecovery(checkpoint_dir=d)
    cp = cr.create_checkpoint({"x": 1})

    assert os.path.exists(cp["file_path"])
    content = open(cp["file_path"], encoding="utf-8").read()
    assert json.loads(content) == {"x": 1}
    # 写后校验: 磁盘内容哈希 == 记录哈希
    import hashlib
    assert hashlib.sha256(content.encode()).hexdigest()[:16] == cp["state_hash"]


def test_recover_after_restart_returns_real_checkpoint():
    d = _tmp_dir()
    cr = CrashRecovery(checkpoint_dir=d)
    cr.create_checkpoint({"state": "A"})

    # 模拟进程崩溃/重启: 同目录新建实例
    cr2 = CrashRecovery(checkpoint_dir=d)
    rec = cr2.recover({"status": "maintain"})

    assert rec["recovered"] is True
    assert rec["status"] != "no_checkpoint"
    assert rec["from_checkpoint"] is not None


def test_id_monotonic_across_restart_no_collision():
    d = _tmp_dir()
    cr = CrashRecovery(checkpoint_dir=d, max_checkpoints=100)
    id1 = cr.create_checkpoint({})["id"]
    # 模拟重启
    cr2 = CrashRecovery(checkpoint_dir=d, max_checkpoints=100)
    id2 = cr2.create_checkpoint({})["id"]

    assert id2 == id1 + 1
    files = sorted(os.listdir(d))
    # 两个检查点文件均存在, 未被覆盖
    assert len(files) == 2
    assert any(f.startswith("checkpoint_1.") for f in files)
    assert any(f.startswith("checkpoint_2.") for f in files)


def test_atomic_write_no_tmp_leftover():
    d = _tmp_dir()
    cr = CrashRecovery(checkpoint_dir=d)
    cr.create_checkpoint({"k": "v"})
    leftovers = [f for f in os.listdir(d) if f.endswith(".tmp")]
    assert leftovers == []


def test_corrupt_checkpoint_skipped_not_loaded():
    d = _tmp_dir()
    cr = CrashRecovery(checkpoint_dir=d)
    cr.create_checkpoint({"good": 1})

    # 注入一个损坏检查点文件 (高 id, 若被误加载会污染恢复链)
    bad = os.path.join(d, "checkpoint_999.json")
    open(bad, "w", encoding="utf-8").write("{not valid json")

    cr2 = CrashRecovery(checkpoint_dir=d)
    # 损坏文件应被跳过 (仅加载完好检查点)
    assert len(cr2._checkpoints) == 1
    # 恢复仍可用
    rec = cr2.recover()
    assert rec["recovered"] is True
    assert rec["from_checkpoint"] is not None


def test_no_checkpoint_when_fresh_dir():
    d = _tmp_dir()
    cr = CrashRecovery(checkpoint_dir=d)
    rec = cr.recover()
    assert rec["recovered"] is False
    assert rec["status"] == "no_checkpoint"


def test_get_stats_exposes_checkpoint_dir():
    d = _tmp_dir()
    cr = CrashRecovery(checkpoint_dir=d)
    cr.create_checkpoint({})
    stats = cr.get_stats()
    assert stats["checkpoints"] >= 1
    assert "checkpoint_dir" in stats
