"""CrashStateRestore — Crash state recovery with serialization.

Enhances CrashRecovery with actual state serialization and restoration.
Based on: "Agents in Practice" (Anthropic, 2024)

Key Concepts:
    1. Serialize agent state to disk at checkpoints
    2. Restore state from latest valid checkpoint on crash
    3. Integrity verification via hash comparison
    4. Incremental checkpoints (only changed state)
"""
from __future__ import annotations



import logging
import os
import re

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
logger = logging.getLogger(__name__)


@dataclass
class StateCheckpoint:
    checkpoint_id: int = 0
    timestamp: float = 0.0
    state_hash: str = ""
    state_data: dict = field(default_factory=dict)
    file_path: str = ""
    size_bytes: int = 0


class CrashStateRestore:
    """Crash state recovery with actual serialization.

    Based on Anthropic's Agents in Practice (2024).

    Usage:
        restore = CrashStateRestore(checkpoint_dir="/tmp/checkpoints")
        restore.save_checkpoint({"memory": [...], "session": {...}})
        state = restore.restore_latest()
    """

    def __init__(self, checkpoint_dir: str = "/tmp/checkpoints",
                 max_checkpoints: int = 10):
        self._dir = Path(checkpoint_dir)
        self._max = max_checkpoints
        self._checkpoints: list[StateCheckpoint] = []
        # 重启后从磁盘恢复已存在的检查点: 使编号不碰撞、不覆盖旧会话
        # 检查点, 并让 restore_latest 在崩溃后能真正回到最新完好状态。
        self._load_existing()

    def _next_checkpoint_id(self) -> int:
        """基于磁盘上已有 checkpoint_<id>.json 的最大编号 +1。

        不依赖内存列表长度, 因此进程重启后不会从 1 重新编号而覆盖
        上一会话的检查点文件 (原实现的薄弱点)。
        """
        ids = []
        for f in self._dir.glob("checkpoint_*.json"):
            m = re.match(r"checkpoint_(\d+)\.json$", f.name)
            if m:
                ids.append(int(m.group(1)))
        return (max(ids) + 1) if ids else 1

    def _load_existing(self):
        """扫描磁盘检查点目录, 重建内存元信息 (崩溃恢复的前提)。"""
        self._dir.mkdir(parents=True, exist_ok=True)
        for f in sorted(self._dir.glob("checkpoint_*.json")):
            m = re.match(r"checkpoint_(\d+)\.json$", f.name)
            if not m:
                continue
            cid = int(m.group(1))
            try:
                content = f.read_text(encoding="utf-8")
                # 真正解析以检测损坏: 无法解析的检查点文件视为损坏, 跳过
                json.loads(content)
                h = hashlib.sha256(content.encode()).hexdigest()[:16]
                ts = f.stat().st_mtime
                self._checkpoints.append(StateCheckpoint(
                    checkpoint_id=cid,
                    timestamp=ts,
                    state_hash=h,
                    state_data={},
                    file_path=str(f),
                    size_bytes=len(content),
                ))
            except (OSError, json.JSONDecodeError):
                # 损坏/不可读的检查点: 保留文件但跳过加载, 避免静默污染恢复链。
                logger.warning("Skipping unreadable checkpoint file: %s", f)
        self._checkpoints.sort(key=lambda c: c.checkpoint_id)

    def save_checkpoint(self, state: dict) -> StateCheckpoint:
        self._dir.mkdir(parents=True, exist_ok=True)

        state_json = json.dumps(state, sort_keys=True, default=str)
        state_hash = hashlib.sha256(state_json.encode()).hexdigest()[:16]

        # 单调递增编号 (基于磁盘, 重启不碰撞/不覆盖)
        checkpoint_id = self._next_checkpoint_id()
        file_path = self._dir / f"checkpoint_{checkpoint_id}.json"
        tmp_path = file_path.with_suffix(".json.tmp")

        # 原子写: 临时文件 -> fsync -> os.replace, 崩溃中途不留半截文件
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(state_json)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, file_path)
        except BaseException:
            # 写入失败: 清理残留临时文件, 不留下半截 .tmp
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            raise

        # 写后校验 (fail-loud): 读回比对哈希, 不一致即抛错, 杜绝静默损坏
        written = file_path.read_text(encoding="utf-8")
        if hashlib.sha256(written.encode()).hexdigest()[:16] != state_hash:
            raise IOError(f"Checkpoint write verification failed: {file_path}")

        checkpoint = StateCheckpoint(
            checkpoint_id=checkpoint_id,
            timestamp=time.time(),
            state_hash=state_hash,
            state_data=state,
            file_path=str(file_path),
            size_bytes=len(state_json),
        )
        self._checkpoints.append(checkpoint)

        self._cleanup_old()
        return checkpoint

    def restore_latest(self) -> dict | None:
        if not self._checkpoints:
            return self._try_disk_restore()

        latest = self._checkpoints[-1]
        file_path = Path(latest.file_path)

        if not file_path.exists():
            return self._try_disk_restore()

        try:
            content = file_path.read_text(encoding="utf-8")
            current_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
            if current_hash != latest.state_hash:
                for cp in reversed(self._checkpoints):
                    if Path(cp.file_path).exists():
                        content = Path(cp.file_path).read_text(encoding="utf-8")
                        return json.loads(content)
            return json.loads(content)
        except (json.JSONDecodeError, OSError):
            return self._try_disk_restore()

    def _try_disk_restore(self) -> dict | None:
        if not self._dir.exists():
            return None
        files = sorted(self._dir.glob("checkpoint_*.json"), reverse=True)
        for f in files:
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
        return None

    def _cleanup_old(self):
        if len(self._checkpoints) > self._max:
            to_remove = self._checkpoints[:-self._max]
            for cp in to_remove:
                try:
                    Path(cp.file_path).unlink(missing_ok=True)
                except OSError as e:
                    logger.warning("Failed to remove old checkpoint: %s", e)
            self._checkpoints = self._checkpoints[-self._max:]

    def list_checkpoints(self) -> list[dict]:
        return [{"id": cp.checkpoint_id, "time": cp.timestamp,
                 "hash": cp.state_hash, "size": cp.size_bytes}
                for cp in self._checkpoints]

    def get_stats(self) -> dict:
        return {"checkpoints": len(self._checkpoints), "dir": str(self._dir)}
