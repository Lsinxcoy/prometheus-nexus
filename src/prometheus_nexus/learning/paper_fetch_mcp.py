"""PaperFetchMCP — paper-fetch-skill MCP 客户端适配器.

将 paper-fetch-skill (Dictation354/paper-fetch-skill) 作为外部 MCP 服务集成。
输入 DOI/URL/标题 → 输出结构化元数据 + 干净 Markdown 全文。

安装 paper-fetch-skill:
  pip install paper-fetch-skill
  或离线安装包见 https://github.com/Dictation354/paper-fetch-skill

用法:
  fetcher = PaperFetchClient()
  result = fetcher.fetch("10.1038/s41586-026-10265-5")
  print(result["markdown"][:200])
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from typing import Any

logger = logging.getLogger(__name__)


class PaperFetchClient:
    """paper-fetch-skill MCP 客户端。

    通过 subprocess 调用 paper-fetch CLI（不走 MCP stdio 协议，
    直接调用 CLI -> stdout JSON）。
    """

    def __init__(self, executable: str = "paper-fetch"):
        self._executable = executable
        self._available: bool | None = None

    def check_available(self) -> bool:
        """检查 paper-fetch 是否已安装。"""
        if self._available is not None:
            return self._available
        try:
            subprocess.run(
                [self._executable, "--help"],
                capture_output=True, timeout=10,
            )
            self._available = True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self._available = False
        return self._available

    def fetch(self, query: str, output_dir: str | None = None,
              timeout: int = 120) -> dict[str, Any]:
        """抓取论文全文。

        Args:
            query: DOI、URL 或标题。
            output_dir: 输出目录（可选）。
            timeout: 超时秒数。

        Returns:
            {success, markdown, metadata, file_path, error}
        """
        if not self.check_available():
            return {"success": False, "error": "paper-fetch not installed"}

        cmd = [self._executable, "--query", query, "--json"]
        if output_dir:
            cmd.extend(["--output-dir", output_dir])

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"Timeout after {timeout}s"}
        except Exception as e:
            return {"success": False, "error": str(e)}

        if result.returncode != 0:
            return {
                "success": False,
                "error": result.stderr[:500] or f"Exit code {result.returncode}",
            }

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return {
                "success": False,
                "error": "Non-JSON output (paper-fetch --json not supported?)",
                "stdout": result.stdout[:500],
            }

        return {
            "success": True,
            "markdown": data.get("markdown", data.get("content", "")),
            "metadata": data.get("metadata", data),
            "file_path": data.get("file_path", ""),
        }

    def fetch_batch(self, queries: list[str], output_dir: str | None = None,
                    timeout: int = 300) -> list[dict[str, Any]]:
        """批量抓取。"""
        results = []
        for q in queries:
            results.append(self.fetch(q, output_dir, timeout // max(len(queries), 1)))
        return results
