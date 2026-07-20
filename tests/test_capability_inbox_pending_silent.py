"""cycle21: CapabilityInbox.pending() 聚合入口静默吞错修复验证.

根因: pending() 是宿主轮询'还有哪些机制待应用'的聚合入口, 原实现
`except Exception: return []` 把整文件级读失败(权限/锁/磁盘IO/未知异常)
伪装成'无待应用', 宿主误判'全部已应用'而停止应用 -> 机制永远不落地(能力漂移),
且零错误信号. cycle3 仅修内层逐行解析器, 此聚合入口仍吞错. 修复: 显式 logger.warning
暴露读失败, 仍安全返回 [] 不崩宿主轮询.

这些测试验证:
  1) inbox 整文件读失败 -> pending() 仍返回 [] (安全契约不变) 且必出 WARNING (失败可见).
  2) 健康路径: 未应用机制被 pending 返回, 应用后从 pending 排除; 全程无假阳 WARNING.
  3) 回归: 逐行损坏场景仍由 _read_entries 告警 + pending 返回合法条目(修复未破坏 cycle3).
"""

import json
import logging
from unittest.mock import patch

from prometheus_nexus.integration.capability_inbox import CapabilityInbox


def _make_inbox(tmp_path, lines):
    inbox_path = tmp_path / "inbox.jsonl"
    inbox_path.write_text("\n".join(lines), encoding="utf-8")
    return CapabilityInbox(path=str(inbox_path))


def test_pending_surfaces_read_failure(caplog, tmp_path):
    """inbox 整文件读不出时, pending() 必须告警(不再静默当空), 仍安全返回 [].

    这是本修复的核心: 此前 except Exception: return [] 让宿主把'读不了'当成'都应用完'.
    """
    inbox = _make_inbox(tmp_path, [json.dumps({"event": "received", "name": "m1"})])

    caplog.set_level(logging.WARNING,
                     logger="prometheus_nexus.integration.capability_inbox")

    # 模拟整文件级读失败(权限/锁/磁盘IO/未知异常)
    with patch.object(inbox, "_read_entries", side_effect=OSError("permission denied")):
        result = inbox.pending()

    # 安全契约不变: 异常时仍返回空 list, 不崩宿主轮询
    assert result == [], f"pending() 异常时应安全返回 [], 实际 {result!r}"
    # 失败必须可见: 修复前此处零日志(静默吞错), 修复后必出 WARNING
    assert any("pending() 读取 inbox 失败" in r.message for r in caplog.records), \
        "inbox 读失败应触发 WARNING, 但无任何日志(静默吞错未修复)"


def test_pending_healthy_returns_pending_and_excludes_applied(caplog, tmp_path):
    """健康路径: 未应用机制被返回; 应用后从 pending 排除; 全程无假阳 WARNING."""
    inbox = _make_inbox(tmp_path, [json.dumps({"event": "received", "name": "m1"})])

    caplog.set_level(logging.WARNING,
                     logger="prometheus_nexus.integration.capability_inbox")

    pending_before = inbox.pending()
    assert len(pending_before) == 1
    assert pending_before[0]["name"] == "m1"

    # 应用后应从 pending 排除
    receipt = inbox.apply_capability("m1", host_id="default")
    assert receipt.applied is True
    assert inbox.pending() == []

    # 健康路径不应产生任何 WARNING(确认修复只在真实失败时告警)
    assert not any("pending() 读取 inbox 失败" in r.message for r in caplog.records), \
        "健康路径不应触发 pending 读失败告警"


def test_pending_corrupt_line_surfaces_per_line_and_keeps_good(caplog, tmp_path):
    """回归: 逐行损坏场景仍由 _read_entries 告警, pending 返回合法条目(未破坏 cycle3)."""
    inbox = _make_inbox(tmp_path, [
        json.dumps({"event": "received", "name": "good"}),
        "{ 这一行是损坏的 JSON ",  # 非法 JSON
    ])

    caplog.set_level(logging.WARNING,
                     logger="prometheus_nexus.integration.capability_inbox")

    result = inbox.pending()
    # 合法行仍正常返回, 损坏行被跳过
    assert len(result) == 1
    assert result[0]["name"] == "good"
    # 损坏行应触发 _read_entries 的逐行告警(cycle3 行为保持)
    assert any("损坏的 inbox 行" in r.message for r in caplog.records), \
        "逐行损坏应触发 cycle3 的逐行告警"
    # 聚合入口本身不应再重复报'读失败'(因为实际读成功了)
    assert not any("pending() 读取 inbox 失败" in r.message for r in caplog.records), \
        "整文件读取成功时不应误报读失败"
