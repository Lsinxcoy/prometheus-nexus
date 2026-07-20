"""SourceFetcher — 拉取外部源的全文/代码，供 T3/T4 进化轨编译机制用。

与 scanner.py 的区别:
- scanner 拉的是"黄页级"元数据(摘要/stars)，用于语义层 + 吸收
- 本模块拉的是"可编译级"内容(论文全文 / repo 代码)，仅 T3/T4 按需调用
  这样不预存全文到 store，避免知识库膨胀。
"""
from __future__ import annotations

import logging
import re
import urllib.parse
import zipfile
import io
import httpx  # 模块级导入, 便于测试 monkeypatch

logger = logging.getLogger(__name__)


def _http_get(url: str, headers: dict | None = None) -> str:
    try:
        import httpx
        resp = httpx.get(url, headers=headers or {}, timeout=30.0, follow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        logger.debug("SourceFetcher http failed: %s", e)
        return ""


def fetch_arxiv_fulltext(arxiv_id: str, max_chars: int = 20000) -> str:
    """拉取 arXiv 论文全文(从 e-print tarball 解压读 .tex)。失败降级返回空串。"""
    aid = arxiv_id.strip()
    if aid.startswith("http"):
        aid = aid.split("/abs/")[-1]
    url = f"https://arxiv.org/e-print/{aid}"
    try:
        resp = httpx.get(url, timeout=60.0, follow_redirects=True)
        resp.raise_for_status()
        # arXiv e-print 返回 .tar.gz (tar 压缩包), 非 zip.
        # V3.7c 修复: 之前用 zipfile 解 tar.gz 报错 'File is not a zip file' (被 mock 掩盖,
        #   真拉 arxiv 才暴露). 改用 tarfile 解压读 .tex.
        tex_texts = []
        content = resp.content
        # 先试 tar.gz (arxiv e-print 真实格式)
        try:
            import tarfile
            with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as tar:
                for m in tar.getmembers():
                    if m.name.endswith(".tex") and m.isfile():
                        try:
                            tex_texts.append(tar.extractfile(m).read().decode("utf-8", errors="ignore"))
                        except Exception:
                            pass
        except Exception:
            # 兜底: 试 zip (以防个别端点返回 zip)
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as z:
                    for name in z.namelist():
                        if name.endswith(".tex"):
                            try:
                                tex_texts.append(z.read(name).decode("utf-8", errors="ignore"))
                            except Exception:
                                pass
            except Exception as e:
                logger.debug("SourceFetcher arxiv fulltext failed: %s", e)
                return ""
        full = "\n".join(tex_texts)
        # 去注释/命令噪声(轻量)
        full = re.sub(r"%.*", "", full)
        full = re.sub(r"\\(usepackage|documentclass|begin|end)\{[^}]*\}", " ", full)
        return full[:max_chars]
    except Exception as e:
        logger.debug("SourceFetcher arxiv fulltext failed: %s", e)
        return ""


def fetch_repo_overview(repo_full_name: str, max_chars: int = 15000) -> str:
    """拉取 GitHub repo 的 README + 关键 Python 文件概览，供机制提取。"""
    # README
    readme = _http_get(
        f"https://raw.githubusercontent.com/{repo_full_name}/main/README.md"
    ) or _http_get(f"https://raw.githubusercontent.com/{repo_full_name}/master/README.md")
    # 顶层文件树
    api = _http_get(
        f"https://api.github.com/repos/{repo_full_name}/contents/",
        headers={"Accept": "application/vnd.github.v3+json", "User-Agent": "PrometheusUltra/1.0"},
    )
    files = []
    if api:
        import json
        try:
            for item in json.loads(api):
                if item.get("type") == "file" and item.get("name", "").endswith((".py", ".md")):
                    files.append(item["name"])
        except Exception:
            pass
    overview = f"# {repo_full_name}\n\n## README\n{readme}\n\n## Top-level files\n{', '.join(files[:30])}\n"
    return overview[:max_chars]


def fetch_repo_source(repo_full_name: str, filenames: list[str], max_chars: int = 20000) -> str:
    """拉取 repo 指定 .py 源文件内容, 供 AST 提取真实参数/类(Phase 2 学习步).

    仅取文本源码, 不执行外部代码(安全边界). 失败的文件静默跳过.
    """
    chunks = []
    total = 0
    for fn in filenames[:8]:  # 限前 8 个文件, 避免超大 repo
        if not fn.endswith(".py"):
            continue
        raw = _http_get(
            f"https://raw.githubusercontent.com/{repo_full_name}/main/{fn}"
        ) or _http_get(
            f"https://raw.githubusercontent.com/{repo_full_name}/master/{fn}"
        )
        if not raw:
            continue
        if total + len(raw) > max_chars:
            raw = raw[: max(0, max_chars - total)]
        chunks.append(f"# === {fn} ===\n{raw}")
        total += len(raw)
        if total >= max_chars:
            break
    return "\n\n".join(chunks)
