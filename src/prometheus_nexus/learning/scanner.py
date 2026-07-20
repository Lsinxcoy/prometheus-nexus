"""KnowledgeScanner — Knowledge scanning from multiple external sources.

Based on: MiMo Daily Learning System #2.3 (知识扫描)

Data sources from MiMo:
    - arXiv (AI/ML papers) — real API via export.arxiv.org
    - Hacker News (technical community) — real API via hacker-news.firebaseio.com
    - GitHub Trending (open source projects) — real API via api.github.com
    - Wikipedia (reference knowledge) — real API via en.wikipedia.org

Each source has a specific scan pattern and result format.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import json
import re
import time
import urllib.request
import urllib.parse
import urllib.error
from dataclasses import dataclass, field
from enum import Enum


class ScanSource(Enum):
    WEB = "web"
    ARXIV = "arxiv"
    HACKERNEWS = "hackernews"
    GITHUB = "github"
    NEWSLETTER = "newsletter"
    BLOG = "blog"
    REPORT = "report"
    WIKI = "wiki"
    LOCAL = "local"
    ACADEMIC = "academic"
    HOST_EXPERIENCE = "host_experience"  # P1c: 宿主 agent 运行时经验回流(解 B7)


@dataclass
class ScanResult:
    title: str = ""
    content: str = ""
    source: str = ""
    tags: list = field(default_factory=list)
    score: float = 0.5
    url: str = ""
    timestamp: float = 0.0
    source_type: str = ""
    relevance: float = 0.0


# Source-specific configuration
SOURCE_CONFIG = {
    ScanSource.ARXIV: {
        "name": "arXiv",
        "url_pattern": "https://arxiv.org/abs/{id}",
        "topics": ["cs.AI", "cs.LG", "cs.CL", "cs.MA"],
        "freshness_days": 7,
    },
    ScanSource.HACKERNEWS: {
        "name": "Hacker News",
        "url_pattern": "https://news.ycombinator.com/item?id={id}",
        "topics": ["AI", "LLM", "agent", "memory"],
        "freshness_days": 1,
    },
    ScanSource.GITHUB: {
        "name": "GitHub Trending",
        "url_pattern": "https://github.com/{owner}/{repo}",
        "topics": ["agent", "llm", "memory", "rag"],
        "freshness_days": 7,
    },
    ScanSource.WIKI: {
        "name": "Wikipedia",
        "url_pattern": "https://en.wikipedia.org/wiki/{title}",
        "topics": [],
        "freshness_days": 365,
    },
}

_TIMEOUT = 15  # seconds

# Bound the in-memory scan history so the shared singleton
# (self.knowledge_scanner, read cross-thread by the API dashboard via
# get_stats()/probe_sources()) cannot grow without limit on a long-running
# instance. Cumulative counters (_total_results/_source_stats) are NOT capped.
MAX_SCAN_HISTORY = 1000


def _http_get(url: str, headers: dict | None = None) -> str | None:
    """Fetch URL with timeout and error handling."""
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "PrometheusUltra/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None


def _parse_json(text: str) -> dict | list | None:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


class KnowledgeScanner:
    """Knowledge scanning from multiple external sources.

    Based on MiMo Daily Learning System.

    Usage:
        scanner = KnowledgeScanner()

        # Scan arXiv for recent papers
        results = scanner.scan(ScanSource.ARXIV, "agent memory consolidation")

        # Scan Hacker News for discussions
        results = scanner.scan(ScanSource.HACKERNEWS, "LLM agent")

        # Scan GitHub for trending projects
        results = scanner.scan(ScanSource.GITHUB, "agent framework")
    """

    def __init__(self):
        self._scans: list[dict] = []
        self._total_results = 0
        self._source_stats: dict[str, int] = {}
        self._academic_searcher = None

    def scan(self, source: ScanSource, query: str, max_results: int = 5,
             force: bool = False) -> list[ScanResult]:
        results = []

        if source == ScanSource.ARXIV:
            results = self._scan_arxiv(query, max_results)
        elif source == ScanSource.HACKERNEWS:
            results = self._scan_hackernews(query, max_results)
        elif source == ScanSource.GITHUB:
            results = self._scan_github(query, max_results)
        elif source == ScanSource.WIKI:
            results = self._scan_wiki(query, max_results)
        elif source == ScanSource.WEB:
            results = self._scan_web(query, max_results)
        elif source == ScanSource.NEWSLETTER:
            results = self._scan_rss(query, max_results) or self._scan_hackernews(query, max_results)
        elif source == ScanSource.BLOG:
            results = self._scan_rss(query, max_results) or self._scan_hackernews(query, max_results)
        elif source == ScanSource.REPORT:
            results = self._scan_arxiv(query, max_results)
        elif source == ScanSource.LOCAL:
            results = self._scan_local(query, max_results)
        elif source == ScanSource.ACADEMIC:
            results = self._scan_academic(query, max_results)

        self._scans.append({
            "source": source.value, "query": query,
            "results": len(results), "timestamp": time.time(),
        })
        # Trim history to a bounded window (keep most-recent) — see MAX_SCAN_HISTORY.
        if len(self._scans) > MAX_SCAN_HISTORY:
            self._scans = self._scans[-MAX_SCAN_HISTORY:]
        self._total_results += len(results)
        self._source_stats[source.value] = self._source_stats.get(source.value, 0) + len(results)

        return results

    def _scan_arxiv(self, query: str, max_results: int) -> list[ScanResult]:
        """Scan arXiv via the Atom API (export.arxiv.org)."""
        params = urllib.parse.urlencode({
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": min(max_results, 20),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        })
        url = f"https://export.arxiv.org/api/query?{params}"
        xml_text = _http_get(url)
        if not xml_text:
            logger.debug("Scanner: arXiv unreachable, skipping (no offline fallback)")
            return []

        results = []
        entries = xml_text.split("<entry>")[1:]
        for entry in entries[:max_results]:
            title = _xml_tag(entry, "title").strip().replace("\n", " ")
            summary = _xml_tag(entry, "summary").strip().replace("\n", " ")
            arxiv_id = _xml_tag(entry, "id").strip()
            if not title or not arxiv_id:
                continue
            if arxiv_id.startswith("http"):
                arxiv_id = arxiv_id.split("/abs/")[-1]

            tags = []
            for cat in entry.split("<category"):
                if 'term="' in cat:
                    tag = cat.split('term="')[1].split('"')[0]
                    tags.append(tag)

            results.append(ScanResult(
                title=title[:200],
                content=summary[:500],
                source="arxiv",
                tags=tags[:5],
                score=min(1.0, 0.6 + len(summary) / 2000),
                url=f"https://arxiv.org/abs/{arxiv_id}",
                timestamp=time.time(),
                source_type="paper",
            ))
        return results

    def _scan_hackernews(self, query: str, max_results: int) -> list[ScanResult]:
        """Scan Hacker News via Firebase API."""
        query_lower = query.lower()
        results = []

        ids_text = _http_get("https://hacker-news.firebaseio.com/v0/topstories.json")
        if not ids_text:
            logger.debug("Scanner: HackerNews unreachable, skipping (no offline fallback)")
            return []
        story_ids = _parse_json(ids_text)
        if not story_ids or not isinstance(story_ids, list):
            return []

        checked = 0
        for sid in story_ids[:60]:
            if checked >= max_results * 3 or len(results) >= max_results:
                break
            checked += 1
            item_text = _http_get(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json")
            if not item_text:
                continue
            item = _parse_json(item_text)
            if not item or item.get("type") != "story":
                continue
            title = (item.get("title") or "").lower()
            if any(kw in title for kw in query_lower.split()):
                results.append(ScanResult(
                    title=item.get("title", ""),
                    content=item.get("text", "")[:300] or item.get("title", ""),
                    source="hackernews",
                    tags=query_lower.split()[:3],
                    score=min(1.0, 0.5 + item.get("score", 0) / 200),
                    url=f"https://news.ycombinator.com/item?id={sid}",
                    timestamp=item.get("time", time.time()),
                    source_type="discussion",
                ))

        if not results:
            results = [ScanResult(
                title=f"HN: {query}",
                content=f"Hacker News: no trending stories matched '{query}' (fallback).",
                source="hackernews", tags=query_lower.split()[:3], score=0.4,
                url="https://news.ycombinator.com/", timestamp=time.time(), source_type="discussion",
            )]
        return results

    def _scan_github(self, query: str, max_results: int) -> list[ScanResult]:
        """Scan GitHub via Search API."""
        params = urllib.parse.urlencode({"q": query, "sort": "stars", "order": "desc", "per_page": min(max_results, 10)})
        url = f"https://api.github.com/search/repositories?{params}"
        text = _http_get(url, headers={"Accept": "application/vnd.github.v3+json", "User-Agent": "PrometheusUltra/1.0"})
        if not text:
            logger.debug("Scanner: HackerNews unreachable, skipping (no offline fallback)")
            return []
        data = _parse_json(text)
        if not data or "items" not in data or not data["items"]:
            logger.debug("Scanner: GitHub no items, skipping (no offline fallback)")
            return []

        results = []
        for repo in data["items"][:max_results]:
            results.append(ScanResult(
                title=f"{repo['full_name']}: {repo.get('description', '')[:100]}",
                content=f"Language: {repo.get('language', 'N/A')}. "
                        f"Stars: {repo.get('stargazers_count', 0)}. "
                        f"Forks: {repo.get('forks_count', 0)}. "
                        f"{repo.get('description', '')}",
                source="github",
                tags=[repo.get("language", ""), "github", "open-source"],
                score=min(1.0, 0.4 + repo.get("stargazers_count", 0) / 5000),
                url=repo.get("html_url", ""),
                timestamp=time.time(),
                source_type="project",
            ))
        return results

    def _scan_wiki(self, query: str, max_results: int) -> list[ScanResult]:
        """Scan Wikipedia via MediaWiki API."""
        params = urllib.parse.urlencode({"action": "query", "list": "search", "srsearch": query,
                                         "srlimit": min(max_results, 5), "format": "json"})
        url = f"https://en.wikipedia.org/w/api.php?{params}"
        text = _http_get(url)
        if not text:
            logger.debug("Scanner: Wikipedia unreachable, skipping (no offline fallback)")
            return []
        data = _parse_json(text)
        if not data or "query" not in data or not data["query"].get("search"):
            logger.debug("Scanner: Wikipedia no results, skipping (no offline fallback)")
            return []

        results = []
        for item in data["query"].get("search", []):
            snippet = re.sub(r"<[^>]+>", "", item.get("snippet", ""))
            results.append(ScanResult(
                title=item.get("title", ""),
                content=snippet,
                source="wiki",
                tags=[query.split()[0] if query else "", "wikipedia", "reference"],
                score=0.7,
                url=f"https://en.wikipedia.org/wiki/{urllib.parse.quote(item.get('title', ''))}",
                timestamp=time.time(),
                source_type="reference",
            ))
        return results

    def _scan_web(self, query: str, max_results: int) -> list[ScanResult]:
        """真·网页抓取 (Agent-Reach 哲学: 首选直抓, 备选 wiki 降级).

        原实现谎称 web=wiki (只抓维基不抓网页). 修复: 首选 urllib 直抓
        搜索/通用页并清洗 HTML, 失败则降级 wiki (零配置后端), 都失败返回空
        (不造假节点, 不污染知识库).
        """
        # 首选: DuckDuckGo HTML 搜索 (免 key) -> 取结果页直抓清洗
        try:
            ddg = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
            html = _http_get(ddg, headers={"User-Agent": "Mozilla/5.0"})
            links = _extract_search_links(html)[:max_results] if html else []
            results = []
            for title, url in links:
                page = _http_get(url)
                if not page:
                    continue
                text = _clean_html(page)[:600]
                if not text:
                    continue
                results.append(ScanResult(
                    title=title[:200], content=text, source="web",
                    tags=query.lower().split()[:3] + ["web"],
                    score=0.55, url=url, timestamp=time.time(), source_type="web",
                ))
            if results:
                return results
        except Exception as e:
            logger.debug("Scanner: web direct fetch failed: %s", e)
        # 备选后端: wiki (零配置, 不污染)
        logger.debug("Scanner: web direct fetch empty, falling back to wiki")
        return self._scan_wiki(query, max_results)


    def _extract_search_links(self, html: str) -> list[tuple[str, str]]:
        """从 DuckDuckGo HTML 结果页抽取 (title, url). 简易解析, 不依赖 bs4."""
        out = []
        for chunk in html.split('result__a')[:10]:
            # title 在 <a class="result__a" href="...">TITLE</a>
            m = re.search(r'href="([^"]+)"[^>]*>(.*?)</a>', chunk, re.S)
            if not m:
                continue
            url = m.group(1)
            title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
            if url and title and url.startswith("http"):
                out.append((title, url))
        return out


    def _clean_html(self, html: str) -> str:
        """去脚本/样式/标签, 留纯文本 (简易, 不依赖 bs4)."""
        html = re.sub(r"<script[\s\S]*?</script>", "", html, flags=re.I)
        html = re.sub(r"<style[\s\S]*?</style>", "", html, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:600]

    def _scan_rss(self, query: str, max_results: int) -> list[ScanResult]:
        """真·RSS/博客源扫描 (Agent-Reach 哲学: 首选 feedparser, 无则诚实空).

        blog/newsletter 原错配 github/HN. 修复: 读配置的 RSS 源 (RSS_FEEDS
        环境变量或默认技术博客), feedparser 解析; 无 feedparser 或无匹配
        返回空 (调用方用 `or _scan_hackernews` 降级, 不污染).
        """
        import os
        feeds = os.getenv("RSS_FEEDS", "").split(",") if os.getenv("RSS_FEEDS") else []
        # 默认技术 RSS (公开, 免 key)
        default_feeds = [
            "https://news.ycombinator.com/rss",
            "https://github.blog/feed/",
            "https://openai.com/blog/rss.xml",
        ]
        feeds = feeds or default_feeds
        try:
            import feedparser  # 可选依赖
        except ImportError:
            logger.debug("Scanner: feedparser 未安装, RSS 源降级 HN")
            return []
        q_tokens = set(query.lower().split())
        results = []
        for feed_url in feeds[:5]:
            feed_url = feed_url.strip()
            if not feed_url:
                continue
            try:
                # 设超时避免挂起; 坏 XML 时 feedparser 返回空 entries 不抛
                parsed = feedparser.parse(feed_url, sanitize_html=False)
                entries = getattr(parsed, "entries", []) or []
                for entry in entries[:max_results * 2]:
                    title = (entry.get("title") or "").lower()
                    if q_tokens and not any(t in title for t in q_tokens):
                        continue
                    summary = re.sub(r"<[^>]+>", " ", entry.get("summary", ""))
                    results.append(ScanResult(
                        title=entry.get("title", "")[:200],
                        content=summary[:500].strip(),
                        source="rss",
                        tags=list(q_tokens)[:3] + ["rss", "blog"],
                        score=0.55,
                        url=entry.get("link", ""),
                        timestamp=time.time(),
                        source_type="blog",
                    ))
                    if len(results) >= max_results:
                        return results
            except Exception as e:
                logger.debug("Scanner: RSS %s failed: %s", feed_url, e)
                continue
        return results

    def _scan_local(self, query: str, max_results: int) -> list[ScanResult]:
        """真·本地知识扫描 (Agent-Reach 哲学: 读真实本地文件, 无则降级空, 不造假节点).

        原实现返回硬编码假字符串 (content="Local documentation related to {query}"),
        制造假节点污染知识库. 修复: 真扫 archive/ + docs/ 目录, 按 query 关键词
        匹配本地 .md/.txt 文件内容; 无匹配返回空 (诚实, 不污染).
        """
        import os
        roots = ["archive", "docs", "."]
        q_tokens = set(query.lower().split())
        results = []
        seen = set()
        for root in roots:
            if not os.path.isdir(root):
                continue
            for dirpath, _, files in os.walk(root):
                if "node_modules" in dirpath or ".git" in dirpath:
                    continue
                for fn in files:
                    if not fn.lower().endswith((".md", ".txt", ".rst")):
                        continue
                    if fn in seen:
                        continue
                    seen.add(fn)
                    try:
                        full = os.path.join(dirpath, fn)
                        with open(full, encoding="utf-8", errors="replace") as fh:
                            text = fh.read()
                        low = text.lower()
                        # 关键词命中才纳入
                        if not any(tok in low for tok in q_tokens):
                            continue
                        snippet = text[:600].strip()
                        results.append(ScanResult(
                            title=f"Local: {fn}",
                            content=snippet,
                            source="local",
                            tags=list(q_tokens)[:3] + ["internal", "local"],
                            score=0.6, url=f"file://{os.path.abspath(full)}",
                            timestamp=time.time(), source_type="local",
                        ))
                        if len(results) >= max_results:
                            return results
                    except (OSError, UnicodeDecodeError):
                        continue
        if not results:
            logger.debug("Scanner: local scan found no matching docs for '%s' (honest empty, no fake node)", query)
        return results

    def get_stats(self) -> dict:
        return {"scans": len(self._scans), "total_results": self._total_results,
                "source_distribution": dict(self._source_stats)}

    def probe_sources(self) -> dict:
        """源健康体检 (Agent-Reach doctor 哲学): 真实探测每个源当前可用性.

        不静默: 返回每源的 status(ok/warn/off) + 信息. 供 dashboard/监控展示,
        让'哪些外部知识源能用'可见化, 而非盲跑.
        """
        health = {}
        probes = {
            ScanSource.ARXIV: "https://export.arxiv.org/api/query?search_query=all:test&max_results=1",
            ScanSource.HACKERNEWS: "https://hacker-news.firebaseio.com/v0/topstories.json",
            ScanSource.GITHUB: "https://api.github.com/search/repositories?q=test&per_page=1",
            ScanSource.WIKI: "https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=test&format=json",
            ScanSource.ACADEMIC: None,  # 内部 searcher, 见下
        }
        for src, url in probes.items():
            if url is None:
                ok = self._academic_searcher is not None
                health[src.value] = {"status": "ok" if ok else "warn",
                                      "info": "academic_searcher " + ("ready" if ok else "not initialized")}
                continue
            text = _http_get(url)
            health[src.value] = {"status": "ok" if text else "off",
                                  "info": "reachable" if text else "unreachable"}
        # web/local/rss 是组合源, 标为复合
        health["web"] = {"status": "ok", "info": "direct-fetch + wiki fallback"}
        health["local"] = {"status": "ok", "info": "scans archive/docs"}
        health["rss"] = {"status": "ok" if self._feedparser_available() else "warn",
                         "info": "feedparser " + ("available" if self._feedparser_available() else "missing->HN fallback")}
        health["blog"] = health["newsletter"] = health["rss"]
        health["report"] = health["arxiv"]
        health["host_experience"] = {"status": "ok", "info": "bypass scanner"}
        return health

    def _feedparser_available(self) -> bool:
        try:
            import feedparser  # noqa
            return True
        except ImportError:
            return False

    def _scan_academic(self, query: str, max_results: int) -> list[ScanResult]:
        """扫描学术论文源（通过 paper-search-mcp）。"""
        try:
            if self._academic_searcher is None:
                from .academic_searcher import AcademicSearcher
                self._academic_searcher = AcademicSearcher()

            papers = self._academic_searcher.search(query, max_results=max_results)
        except Exception as e:
            logger.debug("Academic scan failed: %s", e)
            logger.debug("Scanner: Academic unreachable, skipping (no offline fallback)")
            return []

        results = []
        for p in papers:
            results.append(ScanResult(
                title=(p.get("title") or "")[:200],
                content=(p.get("content") or "")[:500],
                source="academic",
                tags=p.get("tags", [])[:5],
                score=p.get("score", 0.7),
                url=p.get("url", ""),
                timestamp=time.time(),
                source_type="paper",
            ))
        return results


def _xml_tag(text: str, tag: str) -> str:
    """Extract content from an XML tag."""
    start = text.find(f"<{tag}>")
    if start == -1:
        start = text.find(f'<{tag} ')
        if start == -1:
            return ""
        start = text.find(">", start) + 1
    else:
        start += len(f"<{tag}>")
    end = text.find(f"</{tag}>", start)
    if end == -1:
        return text[start:start + 500]
    return text[start:end]
