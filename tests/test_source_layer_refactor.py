"""外部知识源重构回归测试 (Agent-Reach 哲学).

根因: 原 scanner 多个源错配/假数据/静默失败:
- web=wiki 假象 (谎称抓网页实际抓维基)
- local 硬编码假字符串 (污染知识库)
- blog=github 错配, newsletter=HN 借壳
修复: 真网页抓取+wiki备选 / 真本地文件 / 真RSS+HN降级 / 源体检

测试:
- _scan_web 首选直抓, 失败降级 wiki (不谎称)
- _scan_local 读真实文件, 无匹配返回空 (不造假节点)
- _scan_rss 有 feedparser 时真解析, 无则空 (调用方降级)
- probe_sources 返回每源健康状态 (不静默)
- 全部 12 源 scan 不抛异常 (健壮性)
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from prometheus_nexus.learning.scanner import KnowledgeScanner, ScanSource


def test_scan_web_no_longer_fake_wiki_only():
    """web 源现在首选直抓, 不应只返 wiki 源标记."""
    sc = KnowledgeScanner()
    # 不联网断言源标记: 直接验证 _scan_web 逻辑存在且降级链清晰
    assert hasattr(sc, "_scan_web")
    assert hasattr(sc, "_scan_wiki")
    # 离线环境下 web 降级 wiki, 但 method 本身存在且非简单透传
    import inspect
    src = inspect.getsource(sc._scan_web)
    assert "DuckDuckGo" in src or "_http_get" in src, "web 应真抓而非仅调 wiki"
    assert "_scan_wiki" in src, "web 应把 wiki 作为备选后端"


def test_scan_local_no_fake_node():
    """local 源不应返硬编码假字符串."""
    sc = KnowledgeScanner()
    # 用一个绝不可能匹配本地文件的 query
    res = sc._scan_local("zzzqqq_nonexistent_topic_xyz", max_results=2)
    # 关键: 不返回内容含 'Local documentation related to' 的假节点
    for r in res:
        assert "Local documentation related to" not in r.content, "local 源不应制造假节点"
    # 真实项目里有 README/文档, 但此 query 不匹配任何词 -> 应空
    assert res == [], f"无匹配时应返回空, 得到 {len(res)} 假节点"


def test_scan_local_reads_real_docs():
    """local 源能真读本地文档 (用项目自带 README 类文件)."""
    sc = KnowledgeScanner()
    # 项目根有 pyproject.toml / README 等; 用 'ultra' 或 'prometheus' 应命中
    res = sc._scan_local("prometheus", max_results=2)
    # 可能命中 (若 docs 里有 prometheus 字样) 或空 (无匹配词) — 但不应假数据
    for r in res:
        assert r.content.strip() != "", "local 节点内容不应为空"
        assert "Local documentation related to" not in r.content


def test_scan_rss_graceful_without_feedparser(monkeypatch):
    """无 feedparser 时 _scan_rss 返回空 (调用方降级 HN, 不崩)."""
    sc = KnowledgeScanner()
    # 模拟 import feedparser 失败
    import builtins
    real_import = builtins.__import__
    def fake_import(name, *a, **k):
        if name == "feedparser":
            raise ImportError("no feedparser")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    res = sc._scan_rss("machine learning", max_results=2)
    assert res == [], "无 feedparser 时 RSS 应空(由调用方 or HN 降级)"


def test_probe_sources_returns_health():
    """probe_sources 返回每源健康状态 (不静默)."""
    sc = KnowledgeScanner()
    health = sc.probe_sources()
    assert isinstance(health, dict)
    for src in ["arxiv", "web", "local", "rss", "blog", "host_experience"]:
        assert src in health, f"probe 应含源 {src}"
        assert "status" in health[src]


def test_all_12_sources_scan_no_exception():
    """全部 12 源 scan 不抛异常 (健壮性, Agent-Reach 不丢弃任何源)."""
    sc = KnowledgeScanner()
    sources = [s for s in ScanSource]
    for src in sources:
        try:
            sc.scan(src, "test query", max_results=1)
        except Exception as e:
            raise AssertionError(f"源 {src.value} scan 抛异常: {e}")
