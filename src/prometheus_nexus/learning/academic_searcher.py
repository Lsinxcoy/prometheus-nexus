"""AcademicSearcher — paper-search-mcp 学术论文搜索适配器.

集成 openags/paper-search-mcp（21 个学术源，2053 stars）。
通过 pip 安装，直接调用其学术平台的 search() 方法。
支持通过代理访问部分受限源（Google Scholar 等）。
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def _setup_proxy():
    """设置代理环境变量（如果已配置）。"""
    proxy = os.environ.get("ULTRA_PROXY", os.environ.get("HTTPS_PROXY", ""))
    if proxy:
        os.environ.setdefault("HTTP_PROXY", proxy)
        os.environ.setdefault("HTTPS_PROXY", proxy)
        logger.info("Academic search proxy: %s", proxy)


class AcademicSearcher:
    """学术论文搜索器——包装 paper-search-mcp 的各个平台 searcher。

    不启动 MCP 服务器，直接调用各平台的 searcher 类的 search() 接口。
    适配 KnowledgeScanner 的 ScanResult 格式。
    """

    def __init__(self):
        self._searchers: dict[str, Any] = {}
        self._initialized = False

    def _ensure_initialized(self):
        """初始化所有学术论文 searcher 实例。

        过滤 paper_search_mcp 在 import 时泄漏到 stdout 的协程 repr。
        """
        if self._initialized:
            return

        _setup_proxy()

        # 临时过滤 stdout 中的协程 repr（paper_search_mcp import 时触发 async main()）
        import io, sys as _sys
        _orig_stdout = _sys.stdout
        _sys.stdout = io.StringIO()

        try:
            from paper_search_mcp.academic_platforms.arxiv import ArxivSearcher
            from paper_search_mcp.academic_platforms.pubmed import PubMedSearcher
            from paper_search_mcp.academic_platforms.biorxiv import BioRxivSearcher
            from paper_search_mcp.academic_platforms.medrxiv import MedRxivSearcher
            from paper_search_mcp.academic_platforms.google_scholar import GoogleScholarSearcher
            from paper_search_mcp.academic_platforms.semantic import SemanticSearcher
            from paper_search_mcp.academic_platforms.crossref import CrossRefSearcher
            from paper_search_mcp.academic_platforms.openalex import OpenAlexSearcher
            from paper_search_mcp.academic_platforms.pmc import PMCSearcher
            from paper_search_mcp.academic_platforms.core import CORESearcher
            from paper_search_mcp.academic_platforms.europepmc import EuropePMCSearcher
            from paper_search_mcp.academic_platforms.dblp import DBLPSearcher
            from paper_search_mcp.academic_platforms.citeseerx import CiteSeerXSearcher
            from paper_search_mcp.academic_platforms.doaj import DOAJSearcher
            from paper_search_mcp.academic_platforms.zenodo import ZenodoSearcher
            from paper_search_mcp.academic_platforms.hal import HALSearcher
            from paper_search_mcp.academic_platforms.ssrn import SSRNSearcher
            from paper_search_mcp.academic_platforms.openaire import OpenAiresearcher

            self._searchers = {
                "arxiv": ArxivSearcher(),
                "pubmed": PubMedSearcher(),
                "biorxiv": BioRxivSearcher(),
                "medrxiv": MedRxivSearcher(),
                "google_scholar": GoogleScholarSearcher(),
                "semantic": SemanticSearcher(),
                "crossref": CrossRefSearcher(),
                "openalex": OpenAlexSearcher(),
                "pmc": PMCSearcher(),
                "core": CORESearcher(),
                "europepmc": EuropePMCSearcher(),
                "dblp": DBLPSearcher(),
                "citeseerx": CiteSeerXSearcher(),
                "doaj": DOAJSearcher(),
                "zenodo": ZenodoSearcher(),
                "hal": HALSearcher(),
                "ssrn": SSRNSearcher(),
                "openaire": OpenAiresearcher(),
            }
            self._initialized = True
            logger.info("AcademicSearcher initialized: %d sources", len(self._searchers))
        except ImportError as e:
            logger.warning("AcademicSearcher unavailable: %s (pip install paper-search-mcp)", e)
        except Exception as e:
            logger.warning("AcademicSearcher init failed: %s", e)
        finally:
            _sys.stdout = _orig_stdout

    def search(self, query: str, max_results: int = 5, source: str = "all",
               year: str = None) -> list[dict]:
        """搜索学术论文。

        Args:
            query: 搜索查询。
            max_results: 最大结果数。
            source: 平台名（'arxiv', 'all' 等）。
            year: 年份过滤。

        Returns:
            列表，每个元素与 KnowledgeScanner ScanResult 结构兼容。
            每个元素: {title, content(摘要), source, tags, url, score}
        """
        self._ensure_initialized()
        if not self._initialized:
            return []

        # 确定搜索哪些源——先从免费源开始，防止同时轰炸所有 API
        free_sources = ["arxiv", "crossref", "openalex", "pubmed",
                        "dblp", "openaire", "europepmc"]

        if source and source != "all":
            if source in free_sources or source in self._searchers:
                sources_to_search = [source]
            else:
                sources_to_search = [source]
        else:
            sources_to_search = free_sources[:3]  # 默认只搜前 3 个免费源

        all_papers = []

        for source_name in sources_to_search:
            searcher = self._searchers.get(source_name)
            if not searcher:
                continue

            try:
                kwargs = {"max_results": max_results}
                if year:
                    kwargs["year"] = year
                papers = searcher.search(query, **kwargs)
            except Exception as e:
                logger.debug("Academic search %s failed: %s", source_name, e)
                continue

            for p in papers:
                all_papers.append(self._paper_to_dict(p, source_name))

            # 如果搜索单一源，够了
            if source and source != "all":
                break

        # 去重（基于 DOI/标题）
        seen = set()
        deduped = []
        for p in all_papers:
            key = p.get("doi", "") or p.get("title", "")[:50]
            if key in seen:
                continue
            seen.add(key)
            deduped.append(p)

        return deduped

    def _paper_to_dict(self, paper, source_name: str) -> dict:
        """将 paper-search-mcp 的 Paper 对象转为 dict。"""
        # paper 可能是一个 Paper dataclass 实���，也可能是 dict
        if isinstance(paper, dict):
            title = paper.get("title", "")
            abstract = paper.get("abstract", paper.get("summary", ""))
            doi = paper.get("doi", "")
            url = paper.get("url", "")
            authors = paper.get("authors", [])
        else:
            title = getattr(paper, "title", "")
            abstract = getattr(paper, "abstract", "") or ""
            doi = getattr(paper, "doi", "")
            url = getattr(paper, "url", "")

        # 构建标签
        tags = [source_name, "academic"]
        if doi:
            tags.append(f"doi:{doi}")

        return {
            "title": title,
            "content": abstract,
            "source": f"academic:{source_name}",
            "tags": tags,
            "url": url,
            "score": 0.8,
        }
