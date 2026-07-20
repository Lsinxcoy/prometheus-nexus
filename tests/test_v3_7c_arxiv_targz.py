"""V3.7c: arXiv e-print tar.gz 解压修复(之前 zipfile 解 tar.gz 报错).

验证: fetch_arxiv_fulltext 能正确从 .tar.gz 解压读 .tex (不依赖网络,
用内存构造 tar.gz 字节). 真拉 arxiv 时被 mock 掩盖, 此测试固化修复.
"""
import sys
sys.path.insert(0, "E:/Prometheus-Ultra-MultiTypeKB/src")

import io
import tarfile
import zipfile
import pytest


def _make_targz(tex_name: str, tex_content: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        data = tex_content.encode("utf-8")
        ti = tarfile.TarInfo(name=tex_name)
        ti.size = len(data)
        tar.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


class TestArxivTarGz:
    def test_targz_extracted(self, monkeypatch):
        """构造 .tar.gz 字节, 验证 fetch_arxiv_fulltext 读出 .tex 内容."""
        from prometheus_nexus.mechanisms import source_fetcher as sf
        tex = r"\documentclass{article}\begin{document}We propose a caching method.\end{document}"
        payload = _make_targz("paper/main.tex", tex)

        class _Resp:
            content = payload
            def raise_for_status(self): pass
        monkeypatch.setattr(sf.httpx, "get", lambda *a, **k: _Resp())
        out = sf.fetch_arxiv_fulltext("2401.12345")
        assert "caching method" in out, "应从 tar.gz 解压读到 .tex 正文"
        assert "documentclass" not in out, "噪声命令应被剥离"

    def test_zip_fallback(self, monkeypatch):
        """兜底: 若端点返回 zip 仍能读 .tex."""
        from prometheus_nexus.mechanisms import source_fetcher as sf
        tex = "We propose a fusion approach for retrieval."
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("main.tex", tex)
        payload = buf.getvalue()

        class _Resp:
            content = payload
            def raise_for_status(self): pass
        monkeypatch.setattr(sf.httpx, "get", lambda *a, **k: _Resp())
        out = sf.fetch_arxiv_fulltext("2401.99999")
        assert "fusion approach" in out
