"""CapabilityInbox — 宿主侧能力接收端 (P0 C1, 解"emit 射入虚空").

问题实证:
- HermesAdapter.emit_capability 若无 AGENT_CAPABILITY_ENDPOINT, 只 logger.info 后 return False
- NullHostAdapter.emit_capability 是 no-op
- 没有任何 server 端接收 T4 激活后 emit 的机制 -> 进化产物到不了宿主

本模块提供本地接收端:
- 把 emit 的机制落盘到 inbox JSONL(宿主可轮询/读取并据此生成 tool/prompt)
- 提供 apply_capability() 协议: 宿主(或测试)调用它把机制"应用"到自身(此处生成可执行的机制描述文件, 真落地而非仅日志)
- 这是"建议+宿主确认"语义的精确落地: Ultra 不自动直替宿主, 但提供完整可应用的产物

设计: 不依赖网络. 有 AGENT_CAPABILITY_ENDPOINT 时仍走 HTTP(已有); 无时落本地 inbox, 保证进化产物不丢.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CapabilityReceipt:
    """机制被宿主接收/应用的回执."""
    name: str
    accepted: bool
    applied: bool = False
    note: str = ""


class CapabilityInbox:
    """本地能力收件箱 — 接收 Ultra 经 emit_capability 推送的机制."""

    def __init__(self, path: str = "archive/capability_inbox.jsonl"):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._lock = threading.Lock()
        self._applied: dict[str, dict] = {}
        # 启动时加载已应用记录(幂等)
        self._load_applied()

    def receive(self, spec: dict) -> CapabilityReceipt:
        """接收机制(落盘 inbox). 返回回执.

        spec 来自 registry 激活后的 _consume_t4:
        {name, category, target_location, draft_code, claim, activated_at}
        """
        name = spec.get("name", "?")
        try:
            with self._lock:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"event": "received", **spec}, ensure_ascii=False) + "\n")
            logger.info("CapabilityInbox: received %s (target=%s)", name,
                        spec.get("target_location", {}).get("module", "?"))
            return CapabilityReceipt(name=name, accepted=True, note="stored_in_inbox")
        except Exception as e:
            logger.warning("CapabilityInbox: receive failed: %s", e)
            return CapabilityReceipt(name=name, accepted=False, note=str(e))

    def apply_capability(self, name: str, host_id: str = "default") -> CapabilityReceipt:
        """应用机制到宿主(生成可执行的机制文件, 真落地而非仅日志).

        此处生成 archive/capabilities/<name>.applied.json 描述文件, 含:
        - target_location(由 P7 行为定位给出)
        - draft_code(机制草案)
        - host_id(多宿主隔离)
        宿主 agent 读取该文件即可生成对应 tool/prompt. 这是"应用"的最小可验证落地.
        """
        try:
            entries = self._read_entries()
            spec = next((e for e in entries if e.get("name") == name), None)
            if spec is None:
                return CapabilityReceipt(name=name, accepted=False, applied=False, note="not_in_inbox")
            out_dir = os.path.join(os.path.dirname(self.path), "applied")
            os.makedirs(out_dir, exist_ok=True)
            applied_path = os.path.join(out_dir, f"{name}.applied.json")
            payload = {
                "name": name,
                "host_id": host_id,
                "target_location": spec.get("target_location", {}),
                "draft_code": spec.get("draft_code", ""),
                "claim": spec.get("claim", ""),
                "applied_at": __import__("time").time(),
            }
            with self._lock:
                with open(applied_path, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
                self._applied[name] = payload
            logger.info("CapabilityInbox: applied %s -> %s", name, applied_path)
            return CapabilityReceipt(name=name, accepted=True, applied=True, note=applied_path)
        except Exception as e:
            logger.warning("CapabilityInbox: apply failed: %s", e)
            return CapabilityReceipt(name=name, accepted=False, applied=False, note=str(e))

    def pending(self) -> list[dict]:
        """返回 inbox 中尚未应用的机制(宿主轮询用).

        注意: _read_entries 已对单条损坏行显式告警(cycle3), 但本聚合入口仍需对
        '整文件不可读'(权限/锁/磁盘IO/未知异常) 显式暴露 —— 否则 except 会静默返回 [],
        宿主误判'全部已应用'而停止应用, 机制永远不落地(能力漂移)且无任何错误信号.
        """
        try:
            entries = self._read_entries()
            applied = set(self._applied.keys())
            return [e for e in entries if e.get("name") not in applied]
        except Exception as e:
            # 不静默吞: inbox 读不出 ≠ inbox 空. 告警让运维/监控看到'读失败',
            # 避免宿主把'读不了'当成'都应用完了'. 仍安全返回 [] 不崩宿主轮询.
            logger.warning(
                "CapabilityInbox: pending() 读取 inbox 失败(误报为空=全部已应用风险): %s", e
            )
            return []

    # --- 内部 ---
    def _read_entries(self) -> list[dict]:
        if not os.path.exists(self.path):
            return []
        out = []
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception as e:
                    # 不静默丢: 腐蚀的 inbox 行会让对应机制永不 apply / 被 pending 无限重报.
                    # 显式告警, 让运维/监控看到数据丢失, 而非无声吞掉.
                    logger.warning("CapabilityInbox: 跳过损坏的 inbox 行 (已丢该机制): %s | 行=%r",
                                   e, line[:200])
        return out

    def _load_applied(self) -> None:
        out_dir = os.path.join(os.path.dirname(self.path), "applied")
        if not os.path.isdir(out_dir):
            return
        for fn in os.listdir(out_dir):
            if fn.endswith(".applied.json"):
                try:
                    with open(os.path.join(out_dir, fn), encoding="utf-8") as f:
                        p = json.load(f)
                    self._applied[p["name"]] = p
                except Exception as e:
                    # 不静默丢: 腐蚀的 applied 记录会让 _load_applied 失败 -> pending() 把
                    # 已应用机制重新报为 pending -> 宿主重复 apply (能力漂移). 显式告警.
                    logger.warning("CapabilityInbox: 跳过损坏的 applied 记录 %s: %s", fn, e)
