"""反刍状态接入 dashboard + 监控可见性测试 (修正版).

反刍机制本身正常(learn内周期性触发, 增量30min/全量6h), 但监控对其失明.
本测试验证触发逻辑 + get_stats 形状 (用真实实例化而非 __new__ 跳过 __init__).
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from prometheus_nexus.learning.knowledge_rumination import KnowledgeRuminationEngine


def _make_engine(now: float):
    """真实实例化引擎 (轻量, omega=None 不连DB), 并把时间基准设到 now."""
    eng = KnowledgeRuminationEngine(omega=None)
    eng.last_full_rumination = now
    eng.last_incremental_rumination = now
    eng.history = []
    return eng


def test_rumination_full_due_after_6h():
    """距上次全量 > 6h 应触发 full."""
    base = 1_000_000.0
    eng = _make_engine(base)
    # 模拟过了 7 小时
    due = eng.next_rumination_due(now=base + 7 * 3600)
    assert due["mode"] == "full", f"过6h应触发full, 得 {due['mode']}"


def test_rumination_incremental_due_after_30m():
    """全量未到, 但增量过 30min 应触发 incremental."""
    base = 1_000_000.0
    eng = _make_engine(base)
    eng.last_full_rumination = base  # 全量刚跑
    # 过 35 分钟 (增量到, 全量未到)
    due = eng.next_rumination_due(now=base + 35 * 60)
    assert due["mode"] == "incremental", f"过30m应触发incremental, 得 {due['mode']}"


def test_rumination_skip_when_recent():
    """刚跑过 (<30min) 应 skip."""
    base = 1_000_000.0
    eng = _make_engine(base)
    due = eng.next_rumination_due(now=base + 60)  # 仅过 1 分钟
    assert due["mode"] == "skip", f"刚跑过应 skip, 得 {due['mode']}"


def test_get_stats_shape():
    """get_stats 返回 last_full/last_incremental/history_len 等键."""
    base = 1_000_000.0
    eng = _make_engine(base)
    eng.history = [1, 2, 3]
    st = eng.get_stats()
    assert "last_full" in st and "last_incremental" in st and "history_len" in st
    assert st["history_len"] == 3
