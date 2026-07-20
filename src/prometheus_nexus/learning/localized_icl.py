"""LocalizedICL — L-ICL 定向修正 (arXiv 2602.00276).

论文核心方法：
2000 字符定向修正 > 20000 字符完整轨迹检索。
30-60 样本达峰值性能。
找到首个约束违反步骤 → 注入该步骤的 ICL 修正示例。

Multi-round iterative refinement with embedding-based demonstration retrieval.
"""

from __future__ import annotations
import logging
import math
import random
from collections import Counter
from typing import Any

logger = logging.getLogger(__name__)

# ── simple character n-gram embedding (no external deps) ──────────────────────


def _char_ngram_embed(text: str, n: int = 3) -> dict[str, float]:
    """Character n-gram frequency vector for semantic similarity."""
    text = text.lower()
    counts: Counter[str] = Counter()
    for i in range(len(text) - n + 1):
        counts[text[i:i + n]] += 1
    total = sum(counts.values()) or 1
    return {k: v / total for k, v in counts.items()}


def _cosine_sim(a: dict[str, float], b: dict[str, float]) -> float:
    keys = set(a) | set(b)
    dot = sum(a.get(k, 0.0) * b.get(k, 0.0) for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na < 1e-10 or nb < 1e-10:
        return 0.0
    return dot / (na * nb)


# ── LocalizedICL ──────────────────────────────────────────────────────────────


class LocalizedICL:
    """L-ICL 定向修正器 with multi-round iterative refinement."""

    def __init__(self, max_rounds: int = 5, success_threshold: float = 0.85):
        self._corrections: list[dict] = []
        self._total = 0
        self._round = 0
        self._max_rounds = max_rounds
        self._success_threshold = success_threshold

        # Demonstration pool for semantic retrieval
        self._demo_pool: list[dict] = [
            # (violation_type, action_description, patch_example, embedding)
        ]
        # Pre-built seed demonstrations
        self._seed_demos()

    # ── public API ───────────────────────────────────────────────────────────��

    def generate_correction(self, trajectory: list[dict], state: dict = None) -> dict:
        """生成定向修正（原始单通道方法，保持向后兼容）。

        Args:
            trajectory: [{"step": int, "action": str, "success": bool, "constraint": str, ...}]
            state: 当前状态（可选）

        Returns:
            {"patch_step": int, "patch_example": str, "reason": str, "violation_type": str}
        """
        self._total += 1
        if not trajectory:
            return {"patch_step": -1, "patch_example": "No trajectory to correct",
                    "reason": "empty", "violation_type": "none"}

        # 找到第一个约束违反步骤
        for i, step in enumerate(trajectory):
            if not step.get("success", True):
                violation_type = step.get("constraint", "unknown")
                action = step.get("action", "")
                params = step.get("params", {})

                # 生成定向 ICL 修正示例
                patch_example = self._build_patch_example(violation_type, action, params)

                result = {
                    "patch_step": i,
                    "patch_example": patch_example,
                    "reason": f"Step {i}: {action} failed due to {violation_type}",
                    "violation_type": violation_type,
                }
                self._corrections.append(result)
                return result

        result = {
            "patch_step": -1,
            "patch_example": "",
            "reason": "All steps successful",
            "violation_type": "none",
        }
        self._corrections.append(result)
        return result

    def iterative_correction(self, trajectory: list[dict],
                             state: dict = None,
                             eval_fn=None) -> dict:
        """Multi-round iterative refinement with semantic retrieval and early stopping.

        Args:
            trajectory: 原始轨迹
            state: 当前状态（可选）
            eval_fn: callable(trajectory_after_patch) -> {"success": bool, "score": float}
                     用于评估修正是否成功。如果为 None，则使用启发式判断。

        Returns:
            {"rounds": int, "converged": bool, "corrections": list[dict],
             "final_trajectory": list[dict] | None, "stats": dict}
        """
        self._round = 0
        history: list[dict] = []
        current_traj = list(trajectory)

        for r in range(1, self._max_rounds + 1):
            self._round = r

            # ── 1. 找到首个违反步骤 ──
            violations = []
            for step in current_traj:
                if not step.get("success", True):
                    violations.append(step)
            if not violations:
                break  # 全部成功 → early stop

            first_violation = violations[0]
            vtype = first_violation.get("constraint", "unknown")
            action = first_violation.get("action", "")
            params = first_violation.get("params", {})

            # ── 2. Semantic retrieval of best demonstration ──
            query_text = f"{vtype} {action} {params}"
            patch_example = self._semantic_retrieve(query_text, vtype)

            correction = {
                "round": r,
                "patch_step": current_traj.index(first_violation),
                "patch_example": patch_example,
                "violation_type": vtype,
                "action": action,
                "params": params,
                "retrieval_mode": "semantic" if patch_example != self._build_patch_example(vtype, action, params) else "template",
            }

            # ── 3. Apply correction (hypothetically patch the trajectory) ──
            # In practice, the caller applies the patch; we simulate by marking
            # the violation as resolved for the next iteration.
            corrected = dict(first_violation)
            corrected["success"] = True
            corrected["corrected_by"] = patch_example
            # Find and replace the violation step in the working copy
            for idx, st in enumerate(current_traj):
                if st is first_violation:
                    current_traj[idx] = corrected
                    break

            history.append(correction)

            # ── 4. Evaluate success ──
            if eval_fn is not None:
                eval_result = eval_fn(current_traj)
                if eval_result.get("success", False):
                    score = eval_result.get("score", 1.0)
                    if score >= self._success_threshold:
                        break  # early stopping
            else:
                # Heuristic: if this was the only violation, we're done
                if len(violations) <= 1:
                    break

        result = {
            "rounds": self._round,
            "converged": len([s for s in current_traj if not s.get("success", True)]) == 0,
            "corrections": history,
            "final_trajectory": current_traj,
            "stats": {
                "total_rounds_used": self._round,
                "corrections_applied": len(history),
                "max_allowed_rounds": self._max_rounds,
                "early_stopped": self._round < self._max_rounds,
            },
        }
        self._corrections.append(result)
        return result

    # ── semantic retrieval ────────────────────────────────────────────────────

    def _embed_text(self, text: str) -> dict[str, float]:
        """Character tri-gram embedding."""
        return _char_ngram_embed(text, n=3)

    def _seed_demos(self):
        """Populate the demonstration pool with 30+ examples per paper requirement.

        The paper (arXiv 2602.00276) shows 30-60 samples achieve peak performance.
        """
        seeds = [
            ("syntax", "function_call",
             "# Incorrect: fn(a,b,c) without validation\n# Correct: validated_fn(a,b,c) with type checks"),
            ("syntax", "import",
             "# Incorrect: wildcard import *\n# Correct: from module import specific_name"),
            ("syntax", "assignment",
             "# Incorrect: a = b = c\n# Correct: a, b, c = 1, 2, 3"),
            ("syntax", "loop",
             "# Incorrect: for i in range: pass\n# Correct: for i in range(len(items)): process(items[i])"),
            ("syntax", "conditional",
             "# Incorrect: if x = 5:\n# Correct: if x == 5:"),
            ("permission", "file_access",
             "# Permission denied for file write\n# Solution: open file with 'w' mode only after os.access(path, os.W_OK)"),
            ("permission", "api_call",
             "# API token expired\n# Solution: refresh token before call or use retry_with_auth() wrapper"),
            ("permission", "directory_list",
             "# Permission denied for directory listing\n# Solution: use os.scandir() with try/except PermissionError"),
            ("permission", "socket_connect",
             "# Connection refused - port restricted\n# Solution: request elevated privileges or use port > 1024"),
            ("timeout", "network_request",
             "# Request timed out after 5s\n# Solution: reduce payload or set increased timeout=30"),
            ("timeout", "database_query",
             "# Query timeout — full table scan\n# Solution: add index on filtered column, limit rows"),
            ("timeout", "file_download",
             "# Download timed out\n# Solution: use streaming download with chunked transfer"),
            ("timeout", "process_exec",
             "# Subprocess timed out\n# Solution: add timeout=60 to subprocess.run()"),
            ("not_found", "file_read",
             "# FileNotFoundError\n# Solution: os.path.exists() check before open, or try/except with fallback"),
            ("not_found", "key_lookup",
             "# KeyError in dict access\n# Solution: use dict.get(key, default) or key in dict guard"),
            ("not_found", "import_module",
             "# ModuleNotFoundError\n# Solution: add try/except ImportError with pip install fallback"),
            ("not_found", "route_handler",
             "# 404 Not Found\n# Solution: verify URL pattern matches registered routes"),
            ("type_error", "concatenation",
             "# TypeError: can only concatenate str (not int) to str\n# Solution: use f'{value}' or str(value)"),
            ("type_error", "function_args",
             "# TypeError: missing required positional argument\n# Solution: check function signature and provide all required args"),
            ("type_error", "iteration",
             "# TypeError: 'int' object is not iterable\n# Solution: wrap in list() or check type before iteration"),
            ("value_error", "parsing",
             "# ValueError: invalid literal for int()\n# Solution: validate input before conversion, use try/except ValueError"),
            ("value_error", "range",
             "# ValueError: math domain error\n# Solution: check input domain before math operations"),
            ("boundary", "array_index",
             "# IndexError: list index out of range\n# Solution: check len() before indexing, use list[-1] with guard"),
            ("boundary", "empty_iteration",
             "# StopIteration\n# Solution: use for loop instead of next() without default"),
            ("boundary", "recursion_depth",
             "# RecursionError: maximum recursion depth exceeded\n# Solution: convert recursion to iterative loop"),
            ("concurrency", "race_condition",
             "# Unexpected state due to concurrent access\n# Solution: use threading.Lock() or asyncio.Lock()"),
            ("concurrency", "deadlock",
             "# Application hangs - possible deadlock\n# Solution: use timeout-based locks or lock ordering protocol"),
            ("concurrency", "stale_data",
             "# Cache returned stale value after write\n# Solution: implement cache invalidation or write-through strategy"),
            ("io_error", "disk_full",
             "# OSError: No space left on device\n# Solution: check disk space before write, clean up temp files"),
            ("io_error", "connection_reset",
             "# ConnectionResetError\n# Solution: implement retry with exponential backoff"),
            ("io_error", "broken_pipe",
             "# BrokenPipeError\n# Solution: catch BrokenPipeError, flush before close"),
            ("unknown", "general",
             "# Generic failure\n# Solution: add structured logging before/after the operation"),
            ("unknown", "error_handling",
             "# Unhandled exception\n# Solution: wrap in try/except with specific exception types"),
        ]
        for vtype, action, example in seeds:
            emb = self._embed_text(f"{vtype} {action} {example}")
            self._demo_pool.append({
                "violation_type": vtype,
                "key": action,
                "example": example,
                "embedding": emb,
            })

    def _semantic_retrieve(self, query: str, vtype: str, top_k: int = 3) -> str:
        """Retrieve the most semantically similar demo from the pool.

        Filters to demos matching the violation type, then ranks by cosine
        similarity on character tri-gram embeddings.
        """
        query_emb = self._embed_text(query)

        # Filter candidates by violation type, fall back to all on empty
        candidates = [d for d in self._demo_pool if d["violation_type"] == vtype]
        if not candidates:
            candidates = list(self._demo_pool)

        scored = []
        for demo in candidates:
            sim = _cosine_sim(query_emb, demo["embedding"])
            scored.append((sim, demo["example"]))

        scored.sort(key=lambda x: -x[0])

        # Return top match if similarity is meaningful, else template fallback
        if scored and scored[0][0] > 0.05:
            return scored[0][1]

        # Fallback to template
        return self._build_patch_example(vtype, "", {})

    # ── template fallback (unchanged signature) ───────────────────────────────

    def _build_patch_example(self, violation_type: str, action: str, params: dict) -> str:
        """基于违反类型生成 ICL 修正示例。"""
        examples = {
            "syntax": f"# Incorrect: {action}({params})\n# Correct: proper_{action}({params})",
            "permission": f"# Permission denied for {action}\n# Solution: check access before {action}",
            "timeout": f"# {action} timed out\n# Solution: reduce scope or increase timeout",
            "not_found": f"# {action} target not found\n# Solution: verify target exists before {action}",
            "unknown": f"# {action} failed\n# Solution: retry with validated parameters",
        }
        return examples.get(violation_type, examples["unknown"])

    # ── stats ─────────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        corrections_made = sum(1 for c in self._corrections if isinstance(c, dict) and c.get("patch_step", -1) >= 0)
        return {
            "total": self._total,
            "corrections_made": corrections_made,
            "correction_rate": round(corrections_made / max(self._total, 1), 4),
            "iterative_rounds_used": self._round,
            "max_rounds": self._max_rounds,
            "demo_pool_size": len(self._demo_pool),
        }
