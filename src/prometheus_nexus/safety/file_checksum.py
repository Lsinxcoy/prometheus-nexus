"""FileChecksum — 文件完整性校验.

基于:
- "Cryptographic Hash for Integrity Verification" (SHA-256)
  - 哈希计算: SHA-256文件指纹
  - 校验管理: 记录/验证文件哈希
  - 变更检测: 对比新旧哈希
  - 批量校验: 多文件一次性验证

算法:
    compute_hash(filepath):
        1. 读取文件内容
        2. 计算SHA-256哈希
        3. 返回哈希值
    
    verify(filepath, expected_hash):
        1. 计算当前哈希
        2. 与期望值比较
        3. 返回是否一致

复杂度:
    compute_hash(): O(N) N=文件大小
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import hashlib
import os
import time
from collections import defaultdict


class FileChecksum:
    """文件校验器 — SHA-256完整性验证.
    
    计算和验证文件哈希,检测文件是否被篡改.
    """
    
    def __init__(self):
        """初始化."""
        self._registry: dict[str, dict] = {}
        self._verification_log: list[dict] = []
    
    def compute_hash(self, filepath: str) -> str:
        """计算文件SHA-256哈希.
        
        Args:
            filepath: 文件路径
        
        Returns:
            str: SHA-256哈希值
        """
        sha256 = hashlib.sha256()
        
        with open(filepath, 'rb') as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                sha256.update(chunk)
        
        return sha256.hexdigest()
    
    def register(self, filepath: str, expected_hash: str | None = None) -> dict:
        """注册文件校验.
        
        Args:
            filepath: 文件路径
            expected_hash: 期望哈希(可选,不传则计算当前)
        
        Returns:
            dict: 注册信息
        """
        actual_hash = self.compute_hash(filepath)
        stat = os.stat(filepath)
        
        entry = {
            "filepath": filepath,
            "hash": actual_hash,
            "expected_hash": expected_hash or actual_hash,
            "size": stat.st_size,
            "modified": stat.st_mtime,
            "registered_at": time.time(),
            "last_verified": None,
            "tampered": expected_hash is not None and actual_hash != expected_hash,
        }
        
        self._registry[filepath] = entry
        return entry
    
    def verify(self, filepath: str) -> dict:
        """验证文件完整性.
        
        Args:
            filepath: 文件路径
        
        Returns:
            dict: 验证结果
        """
        if filepath not in self._registry:
            return {
                "valid": False,
                "reason": "not registered",
                "filepath": filepath,
            }
        
        current_hash = self.compute_hash(filepath)
        expected_hash = self._registry[filepath]["expected_hash"]
        
        valid = current_hash == expected_hash
        
        result = {
            "valid": valid,
            "filepath": filepath,
            "expected_hash": expected_hash,
            "current_hash": current_hash,
            "tampered": not valid,
            "verified_at": time.time(),
        }
        
        if filepath in self._registry:
            self._registry[filepath]["last_verified"] = time.time()
            self._registry[filepath]["tampered"] = not valid
        
        self._verification_log.append(result)
        if len(self._verification_log) > 200:
            self._verification_log = self._verification_log[-100:]
        
        return result
    
    def verify_all(self) -> dict:
        """验证所有注册文件.
        
        Returns:
            dict: 批量验证结果
        """
        results = []
        valid_count = 0
        tampered_count = 0
        
        for filepath in list(self._registry.keys()):
            result = self.verify(filepath)
            results.append(result)
            if result["valid"]:
                valid_count += 1
            else:
                tampered_count += 1
        
        return {
            "total": len(results),
            "valid": valid_count,
            "tampered": tampered_count,
            "results": results,
            "ts": time.time(),
        }
    
    def get_stats(self) -> dict:
        """获取统计."""
        registered = len(self._registry)
        tampered = sum(1 for e in self._registry.values() if e.get("tampered"))
        
        return {
            "registered_files": registered,
            "tampered_files": tampered,
            "total_verifications": len(self._verification_log),
        }
