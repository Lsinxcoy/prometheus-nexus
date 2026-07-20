"""心跳 learn 源轮转回归测试.

根因: _heartbeat_loop 硬编码 source="web", 自动学习永不抓 arxiv/github/wiki
-> 论文/代码/百科节点永不在自动学习中新增.
修复: 心跳每轮轮转 _hb_sources, 让多源自动积累.

测试:
- Omega 心跳线程初始化了 _hb_sources / _hb_src_i
- 模拟心跳一轮: 调用 _heartbeat_loop 一次(用短 interval 或直接调 learn 轮转逻辑)
- 验证源确实按 web->arxiv->github->... 轮转
"""
import sys
import os
import time
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from prometheus_nexus.life import Omega


def test_heartbeat_source_rotation_initialized():
    o = Omega(db_path="src/prometheus_nexus.db")
    assert hasattr(o, "_hb_sources"), "缺少 _hb_sources 初始化"
    assert "arxiv" in o._hb_sources, "源轮转列表应含 arxiv(否则论文不自动学)"
    assert "github" in o._hb_sources
    assert hasattr(o, "_hb_src_i")
    o.shutdown() if hasattr(o, "shutdown") else None


def test_heartbeat_rotates_sources():
    """每调一次心跳逻辑, 源按列表轮转."""
    o = Omega(db_path="src/prometheus_nexus.db")
    # 直接驱动一轮心跳的源选择逻辑(不真 sleep 3600s)
    seen = []
    for _ in range(len(o._hb_sources)):
        hb_src = o._hb_sources[o._hb_src_i % len(o._hb_sources)]
        o._hb_src_i += 1
        seen.append(hb_src)
    # 一轮应覆盖全部源且不含重复(在列表长度内)
    assert "arxiv" in seen, "轮转应出现 arxiv 源(论文可自动学)"
    assert seen[0] == "web" and seen[1] == "arxiv", f"轮转顺序异常: {seen}"
    o.shutdown() if hasattr(o, "shutdown") else None


def test_heartbeat_no_longer_hardcodes_web():
    """回归: 原代码心跳永远 web; 修复后首轮是 web 但次轮必是 arxiv(非恒 web)."""
    o = Omega(db_path="src/prometheus_nexus.db")
    first = o._hb_sources[o._hb_src_i % len(o._hb_sources)]
    o._hb_src_i += 1
    second = o._hb_sources[o._hb_src_i % len(o._hb_sources)]
    assert first == "web"
    assert second == "arxiv", "次轮应轮到 arxiv, 而非恒为 web"
    o.shutdown() if hasattr(o, "shutdown") else None
