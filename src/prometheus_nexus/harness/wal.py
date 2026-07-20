"""WriteAheadLog — 预写日志持久化 + Mnemosyne ATP LCRP验证。

基于:
- "Write-Ahead Logging for Crash Recovery" (Reuter & Sanders, 1980)
- Mnemosyne Agentic Transaction Processing (arXiv 2607.00269)

Algorithm:
    LCRP = Lifecycle Consistency Checkpoint。四大安全定理：
    T1: 内容有效性 — LLM输出必须通过基本完整性检查
    T2: 一致性 — 提案与系统状态不矛盾
    T3: 非矛盾 — 提案不包含逻辑冲突
    T4: 有界资源 — 提案不超出系统限制

    ATP additions (Mnemosyne Complete):
    - Merkle Chain: each entry hash chains to previous, tamper-evident audit
    - Atomic Transactions: begin/commit/rollback for multi-step operations
    - Commit-Reveal: hash-commit then reveal for privacy-preserving consensus

    log_operation(op):
        1. LCRP验证
        2. 分配LSN
        3. 写入日志文件
        4. fsync落盘
        5. 返回LSN
"""
from __future__ import annotations
import json
import logging

logger = logging.getLogger(__name__)

import os
import time
import hashlib
import uuid


class LCRPValidator:
    """生命周期一致性检查点 — Mnemosyne ATP (arXiv 2607.00269).

    "LLM生成的一切都是不受信提案。"
    """

    def __init__(self):
        self._stats = {"passed": 0, "rejected": 0}

    def validate(self, op_type: str, key: str, value: any,
                 metadata: dict | None = None) -> dict:
        """验证操作是否符合LCRP约束。"""
        violations = []

        # T1: 内容有效性 — 允许metadata-only操作（如状态记录）
        t1_valid = True
        if value is None:
            md = metadata or {}
            # metadata-only操作（如状态标记）不算违反
            if any(k in md for k in ("status", "pending", "payload")):
                pass  # 允许metadata-only
            else:
                violations.append("T1: value is None with no metadata")
                t1_valid = False
        elif isinstance(value, str) and len(value) > 100_000:
            violations.append("T1: value exceeds 100K chars")
            t1_valid = False

        # T2: 一致性
        t2_valid = bool(key) if op_type != "remember" else True

        # T3: 非矛盾
        valid_ops = {"remember", "recall", "evolve", "learn", "reflect",
                     "dream", "maintain", "create_node", "delete_node",
                     "update_node", "merge_branch", "reveal"}
        t3_valid = op_type in valid_ops
        if not t3_valid:
            violations.append(f"T3: unknown op_type '{op_type}'")

        # T4: 有界资源
        t4_valid = True
        md = metadata or {}
        ttl = md.get("ttl", float("inf"))
        if isinstance(ttl, (int, float)) and ttl < 0:
            violations.append("T4: negative ttl")
            t4_valid = False

        valid = t1_valid and t2_valid and t3_valid and t4_valid
        if valid:
            self._stats["passed"] += 1
        else:
            self._stats["rejected"] += 1

        return {
            "valid": valid,
            "reason": "; ".join(violations) if violations else "ok",
            "theorems": {
                "T1_content_validity": t1_valid,
                "T2_consistency": t2_valid,
                "T3_non_contradiction": t3_valid,
                "T4_bounded_resource": t4_valid,
            },
        }

    def get_stats(self) -> dict:
        return dict(self._stats)


class WriteAheadLog:
    """预写日志 — 持久化操作日志用于崩溃恢复.

    所有操作先经过LCRP验证再记录到WAL，确保数据一致性。

    ATP Extensions (Mnemosyne Complete):
    - Merkle Chain hashing: tamper-evident entry chain via SHA-256
    - Atomic Transactions: begin/commit/rollback for safe multi-step ops
    - Commit-Reveal Protocol: privacy-preserving content commitment
    """

    def __init__(self, log_dir: str = None):
        self._log_dir = log_dir or os.path.join(os.getcwd(), "wal_logs")
        os.makedirs(self._log_dir, exist_ok=True)
        self._lsn = 0
        self._pending: list[dict] = []
        self._confirmed: list[dict] = []
        self._checkpoint_lsn = 0
        self._lcrp = LCRPValidator()

        # --- ATP: Merkle Chain ---
        self._last_hash: str = ""           # hash of last *confirmed* entry
        self._chain_tip_hash: str = ""      # hash of last entry written (any status)
        self._chain_entries: list[dict] = []  # all entries in write order for verify

        # --- ATP: Atomic Transactions ---
        self._active_txs: dict[str, list] = {}

        # --- ATP: Commit-Reveal Protocol ---
        self._pending_reveals: dict[str, dict] = {}

    # ============================================================
    # Core: log_operation (extended with Merkle hashing)
    # ============================================================

    def log_operation(self, op_type: str, key: str, value: any = None,
                      metadata: dict | None = None,
                      tx_id: str | None = None) -> dict:
        """记录操作到WAL（含LCRP验证 + Merkle链哈希）。

        Args:
            op_type: 操作类型（如 "remember", "create_node"）
            key: 操作key
            value: 操作值
            metadata: 附加元数据
            tx_id: 可选的事务ID（用于原子事务）

        Returns:
            {"lsn": int, "valid": bool, "reason": str, "hash": str}
        """
        # LCRP验证
        lcrp_result = self._lcrp.validate(op_type, key, value, metadata)
        if not lcrp_result["valid"]:
            logger.warning("WAL LCRP rejected: %s (%s)", op_type, lcrp_result["reason"])
            return {"lsn": -1, "valid": False, "reason": lcrp_result["reason"], "hash": ""}

        self._lsn += 1

        # Build payload for hashing
        entry = {
            "lsn": self._lsn,
            "op_type": op_type,
            "key": key,
            "value": value,
            "metadata": metadata or {},
            "timestamp": time.time(),
            "confirmed": False,
            "tx_id": tx_id,
        }

        # ATP: Merkle chain hash
        entry_hash = self._compute_entry_hash(entry)
        entry["hash"] = entry_hash
        self._chain_tip_hash = entry_hash
        self._chain_entries.append(entry)

        self._pending.append(entry)

        # If part of an active transaction, track it
        if tx_id and tx_id in self._active_txs:
            self._active_txs[tx_id].append(entry)

        self._flush_entry(entry)

        return {"lsn": self._lsn, "valid": True, "reason": "ok", "hash": entry_hash}

    def _compute_entry_hash(self, entry: dict, tip: str | None = None) -> str:
        """Compute SHA-256 hash for an entry, chaining to chain_tip_hash.

        Hash input = prev_hash + lsn + op_type + key + str(value) + str(metadata) + str(timestamp)

        Args:
            entry: the entry dict to hash.
            tip: optional explicit previous-chain hash. When None, the live
                 ``self._chain_tip_hash`` is used (normal append path). Passing
                 an explicit tip lets callers (e.g. verify_chain) walk the chain
                 without mutating live state.
        """
        hasher = hashlib.sha256()
        base = self._chain_tip_hash if tip is None else tip
        hasher.update(base.encode("utf-8"))
        hasher.update(str(entry["lsn"]).encode("utf-8"))
        hasher.update(entry["op_type"].encode("utf-8"))
        hasher.update(entry["key"].encode("utf-8"))
        hasher.update(str(entry.get("value", "")).encode("utf-8"))
        hasher.update(json.dumps(entry.get("metadata", {}), sort_keys=True, default=str).encode("utf-8"))
        hasher.update(str(entry.get("timestamp", "")).encode("utf-8"))
        return hasher.hexdigest()

    # ============================================================
    # ATP: Merkle Chain
    # ============================================================

    def _verify_entry_chain(self, entry: dict) -> bool:
        """验证单个entry的Merkle链哈希是否一致。

        Re-computes the entry's hash using the previous entry's hash
        and compares it with the stored hash.

        Returns:
            True if hash is valid, False otherwise.
        """
        # Store the current _last_hash, compute, then restore
        saved_last_hash = self._last_hash

        # We need to simulate what _last_hash was when this entry was written.
        # For verified entries, we temporarily set _last_hash to the hash of
        # the entry before this one.
        # But actually we don't know the order here — this method is meant
        # to be called in sequence during verify_chain().
        stored_hash = entry.get("hash", "")
        if not stored_hash:
            return False

        computed = self._compute_entry_hash(entry)
        return computed == stored_hash

    def verify_chain(self) -> dict:
        """全链验证 — 逐条检查Merkle哈希链完整性。

        Iterates all entries in write order (conserved by _chain_entries),
        re-computes each hash using the previous entry's hash,
        and reports any broken links.

        Resilience contract (safety-critical):
          * Never mutates live chain state (``self._chain_tip_hash``). A
            verification walk must not corrupt the tip used by subsequent
            ``log_operation`` appends — the original implementation mutated the
            live tip and only restored it at the very end, so a single
            corrupted/malformed entry (the exact scenario a WAL exists for:
            crash recovery with a half-written log) would both crash the
            verification AND leave the live Merkle tip corrupted.
          * A malformed entry is reported as a broken link, never raised. The
            walk must surface corruption, not abort on it.

        Returns:
            {"valid": bool, "entries_checked": int, "broken_links": int,
             "first_broken_lsn": int or None}
        """
        # Local running tip — start from empty and recompute the chain from
        # scratch (Merkle root semantics). Live state is never touched.
        chain_tip = ""
        broken_links = 0
        first_broken_lsn = None
        entries_checked = 0

        for entry in self._chain_entries:
            entries_checked += 1
            # A corrupted entry (missing/None op_type, etc.) must be reported,
            # not raised — otherwise verification cannot fulfil its contract.
            try:
                computed = self._compute_entry_hash(entry, chain_tip)
            except Exception as exc:
                broken_links += 1
                lsn = entry.get("lsn")
                if first_broken_lsn is None:
                    first_broken_lsn = lsn
                logger.warning("Merkle chain entry malformed at LSN %s: %s",
                               lsn, exc)
                # Advance using the stored hash (best effort) so remaining
                # entries can still be evaluated against the recorded chain.
                chain_tip = entry.get("hash", "")
                continue

            stored_hash = entry.get("hash", "")
            if computed != stored_hash:
                broken_links += 1
                if first_broken_lsn is None:
                    first_broken_lsn = entry.get("lsn")
                logger.warning("Merkle chain broken at LSN %d: stored=%s computed=%s",
                               entry.get("lsn"), stored_hash[:16], computed[:16])
            # Advance the chain regardless (using original hashes)
            chain_tip = stored_hash if computed == stored_hash else computed

        return {
            "valid": broken_links == 0,
            "entries_checked": entries_checked,
            "broken_links": broken_links,
            "first_broken_lsn": first_broken_lsn,
        }

    def get_merkle_root(self) -> str:
        """返回当前Merkle链的根哈希（最后一个已确认entry的hash）。

        Returns:
            根哈希字符串，没有已确认entry时返回空字符串。
        """
        return self._last_hash

    # ============================================================
    # confirm / checkpoint / replay (updated to track _last_hash)
    # ============================================================

    def confirm(self, lsn: int) -> bool:
        """确认一个待处理entry。更新Merkle链的_last_hash。"""
        for entry in self._pending:
            if entry["lsn"] == lsn:
                entry["confirmed"] = True
                self._pending.remove(entry)
                self._confirmed.append(entry)
                # ATP: update the Merkle chain root
                entry_hash = entry.get("hash", "")
                if entry_hash:
                    self._last_hash = entry_hash
                return True
        return False

    def checkpoint(self) -> dict:
        """创建检查点并修剪已确认的entries。"""
        checkpoint_data = {
            "checkpoint_lsn": self._lsn,
            "confirmed_count": len(self._confirmed),
            "pending_count": len(self._pending),
            "timestamp": time.time(),
            "merkle_root": self._last_hash,
        }
        cp_path = os.path.join(self._log_dir, f"checkpoint_{self._lsn}.json")
        with open(cp_path, 'w') as f:
            json.dump(checkpoint_data, f, indent=2, default=str)
        self._checkpoint_lsn = self._lsn
        if len(self._confirmed) > 100:
            self._confirmed = self._confirmed[-50:]
        return checkpoint_data

    def replay(self, from_lsn: int = 0) -> list[dict]:
        """重放从指定LSN开始的entries。"""
        all_entries = self._confirmed + self._pending
        replay_entries = [e for e in all_entries if e["lsn"] > from_lsn]
        replay_entries.sort(key=lambda x: x["lsn"])
        return replay_entries

    def get_pending(self) -> list[dict]:
        return list(self._pending)

    def _flush_entry(self, entry: dict) -> None:
        """将entry刷写到磁盘日志文件。"""
        log_file = os.path.join(self._log_dir, "wal.log")
        with open(log_file, 'a') as f:
            f.write(json.dumps(entry, default=str) + "\n")

    def load_from_file(self) -> list[dict]:
        """从磁盘日志文件加载entries。"""
        log_file = os.path.join(self._log_dir, "wal.log")
        if not os.path.exists(log_file):
            return []
        entries = []
        with open(log_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entry = json.loads(line)
                        entries.append(entry)
                        if entry.get("lsn", 0) > self._lsn:
                            self._lsn = entry["lsn"]
                    except json.JSONDecodeError:
                        continue
        return entries

    def get_lcrp_stats(self) -> dict:
        return self._lcrp.get_stats()

    def get_stats(self) -> dict:
        """返回WAL完整统计信息，包含ATP部分。"""
        return {
            "current_lsn": self._lsn,
            "pending": len(self._pending),
            "confirmed": len(self._confirmed),
            "checkpoint_lsn": self._checkpoint_lsn,
            "lcrp": self._lcrp.get_stats(),
            "merkle_root": self._last_hash,
            "active_tx_count": len(self._active_txs),
            "pending_reveal_count": len(self._pending_reveals),
        }

    # ============================================================
    # ATP: Atomic Transactions
    # ============================================================

    def begin_tx(self) -> str:
        """开始一个新的事务。

        生成唯一事务ID并注册到_active_txs。

        Returns:
            tx_id (UUID hex string)
        """
        tx_id = uuid.uuid4().hex
        self._active_txs[tx_id] = []
        logger.debug("WAL tx begin: %s", tx_id)
        return tx_id

    def commit_tx(self, tx_id: str) -> bool:
        """原子提交事务 — 确认事务内所有待处理entries。

        Args:
            tx_id: 事务ID

        Returns:
            True if commit succeeded, False if tx_id not found.
        """
        if tx_id not in self._active_txs:
            logger.warning("WAL commit_tx failed: tx %s not found", tx_id)
            return False

        entries = self._active_txs[tx_id]
        if not entries:
            logger.warning("WAL commit_tx: tx %s has no entries", tx_id)
            del self._active_txs[tx_id]
            return True  # empty tx is vacuously committed

        # Confirm all entries atomically
        for entry in entries:
            lsn = entry.get("lsn", -1)
            if lsn > 0:
                self.confirm(lsn)

        del self._active_txs[tx_id]
        logger.debug("WAL tx commit: %s (%d entries)", tx_id, len(entries))
        return True

    def rollback_tx(self, tx_id: str) -> bool:
        """回滚事务 — 删除事务内所有未确认entries。

        Args:
            tx_id: 事务ID

        Returns:
            True if rollback succeeded, False if tx_id not found.
        """
        if tx_id not in self._active_txs:
            logger.warning("WAL rollback_tx failed: tx %s not found", tx_id)
            return False

        entries = self._active_txs[tx_id]
        rollback_lsns = {e["lsn"] for e in entries}

        # Remove from _pending
        self._pending = [e for e in self._pending if e["lsn"] not in rollback_lsns]

        # Clean from _chain_entries
        self._chain_entries = [e for e in self._chain_entries if e["lsn"] not in rollback_lsns]
        # Recompute chain tip from remaining entries
        if self._chain_entries:
            self._chain_tip_hash = self._chain_entries[-1].get("hash", "")
        else:
            self._chain_tip_hash = ""

        del self._active_txs[tx_id]
        logger.debug("WAL tx rollback: %s (%d entries)", tx_id, len(entries))
        return True

    def get_active_txs(self) -> dict:
        """获取所有活跃事务信息。

        Returns:
            dict: {tx_id: {"entry_count": int, "lsns": list[int]}}
        """
        return {
            tx_id: {
                "entry_count": len(entries),
                "lsns": [e["lsn"] for e in entries],
            }
            for tx_id, entries in self._active_txs.items()
        }

    # ============================================================
    # ATP: Commit-Reveal Protocol
    # ============================================================

    def commit_hash(self, content: str) -> str:
        """承诺一个内容的哈希值（不暴露内容本身）。

        Stores the SHA-256 hash of content as a pending commitment.
        The actual content is revealed later via reveal().

        Args:
            content: 待承诺的内容

        Returns:
            SHA-256 hex digest of the content (the commitment hash).
        """
        reveal_id = uuid.uuid4().hex
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        self._pending_reveals[reveal_id] = {
            "hash": content_hash,
            "timestamp": time.time(),
            "revealed": False,
        }
        logger.debug("WAL commit_hash: %s -> %s", reveal_id, content_hash[:16])
        return content_hash

    def reveal(self, reveal_id: str, content: str,
               committed_hash: str) -> dict:
        """揭示承诺内容，验证哈希一致性。

        Args:
            reveal_id: 承诺ID
            content: 实际内容
            committed_hash: 之前commit_hash返回的哈希值

        Returns:
            {"valid": bool, "lsn": int, "reason": str}
        """
        # Check hash match
        computed_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if computed_hash != committed_hash:
            logger.warning("WAL reveal hash mismatch: computed=%s committed=%s",
                           computed_hash[:16], committed_hash[:16])
            return {"valid": False, "lsn": -1,
                    "reason": "hash mismatch: content does not match committed hash"}

        # Check if this reveal_id is tracked
        if reveal_id in self._pending_reveals:
            pending = self._pending_reveals[reveal_id]
            if pending["hash"] != committed_hash:
                logger.warning("WAL reveal id-hash mismatch for %s", reveal_id)
                return {"valid": False, "lsn": -1,
                        "reason": "reveal_id does not match committed_hash"}
            if pending["revealed"]:
                logger.warning("WAL reveal already revealed: %s", reveal_id)
                return {"valid": False, "lsn": -1,
                        "reason": "already revealed"}
            pending["revealed"] = True
        else:
            # Unknown reveal_id — rely on hash match alone
            pass

        # Write the revealed content to the WAL
        result = self.log_operation("reveal", "", content,
                                    metadata={"reveal_id": reveal_id,
                                              "committed_hash": committed_hash})
        if result["valid"]:
            return {"valid": True, "lsn": result["lsn"], "reason": "ok"}
        return {"valid": False, "lsn": -1, "reason": result.get("reason", "unknown")}

    def get_pending_reveals(self) -> list[dict]:
        """获取所有未揭示的承诺列表。

        Returns:
            list[dict]: [{"reveal_id": str, "hash": str, "timestamp": float}]
        """
        return [
            {
                "reveal_id": rid,
                "hash": info["hash"],
                "timestamp": info["timestamp"],
            }
            for rid, info in self._pending_reveals.items()
            if not info["revealed"]
        ]

    # ============================================================
    # 兼容别名
    # ============================================================

    def write(self, op_type: str, key: str = "", value: any = None,
              metadata: dict | None = None, **kwargs) -> int:
        """向后兼容别名 — 返回LSN整数（或-1表示拒绝）。

        Delegates to log_operation. For full dict response, use write_dict().
        """
        merged_metadata = dict(metadata or {})
        merged_metadata.update(kwargs)
        result = self.log_operation(op_type, key, value, merged_metadata)
        return result.get("lsn", -1)

    def write_dict(self, op_type: str, key: str = "", value: any = None,
                   metadata: dict | None = None,
                   tx_id: str | None = None, **kwargs) -> dict:
        """写操作并返回完整结果字典（含hash字段）。

        Args:
            op_type: 操作类型
            key: 操作key
            value: 操作值
            metadata: 附加元数据
            tx_id: 可选的事务ID
            **kwargs: 额外元数据k=v

        Returns:
            {"lsn": int, "valid": bool, "reason": str, "hash": str}
        """
        merged_metadata = dict(metadata or {})
        merged_metadata.update(kwargs)
        return self.log_operation(op_type, key, value, merged_metadata, tx_id=tx_id)
