"""方案 A 回归测试: 机制注册表持久化 + 重启恢复。

根因: MechanismRegistry 原纯内存, Omega 构造不恢复 -> 机制重启全丢,
B1 消费率/D1 回流在空 registry 上跑。
修复: registry 加 JSON 持久化(__init__ path + _load/_persist), Omega 传
archive/mechanisms.json。

测试验证:
- register 写文件
- 新 MechanismRegistry(path=同文件) 能 load 回机制
- D1 _mark_consumed 后 consumed_at 持久, 重启后仍在
"""
import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from prometheus_nexus.mechanisms.registry import MechanismRegistry
from prometheus_nexus.integration.host_agent import GenericAgentAdapter
from prometheus_nexus.life import Omega


def test_register_persists_to_json(tmp_path):
    """register 后 JSON 文件落盘, 含机制条目。"""
    p = str(tmp_path / "mechanisms.json")
    reg = MechanismRegistry(path=p)
    reg.register("m_test", {"effect_mean": 0.5}, category="general")
    assert os.path.exists(p), "register 后应落盘 JSON"
    blob = json.loads(open(p, encoding="utf-8").read())
    assert "m_test" in blob["mechanisms"]
    # data 存在 entry["data"] 子字典 (register 的 data 参数)
    assert blob["mechanisms"]["m_test"]["data"].get("effect_mean") == 0.5


def test_restart_loads_mechanisms(tmp_path):
    """新 MechanismRegistry(path=同文件) 启动时恢复机制态。"""
    p = str(tmp_path / "mechanisms.json")
    reg1 = MechanismRegistry(path=p)
    reg1.register("m_a", {"status": "enabled"}, pending=False)
    reg1.register("m_b", {"status": "pending"}, pending=True)

    # 模拟"重启": 新实例读同一文件
    reg2 = MechanismRegistry(path=p)
    assert "m_a" in reg2._mechanisms, "重启后应恢复 m_a"
    assert "m_b" in reg2._mechanisms, "重启后应恢复 m_b"
    assert "m_a" in reg2._enabled, "非 pending 机制应进 _enabled"


def test_consumed_at_persists_across_restart(tmp_path):
    """D1: _mark_consumed 写 consumed_at 并持久, 重启后仍可见 (解 B1 死维度)。"""
    p = str(tmp_path / "mechanisms.json")
    reg = MechanismRegistry(path=p)
    reg.register("m_x", {}, pending=False)

    # 模拟宿主 emit -> host_agent._mark_consumed 写 consumed_at + 持久
    omega = type("O", (), {"mechanism_registry": reg})()
    ad = GenericAgentAdapter(host_id="test")
    ad._omega = omega
    ad._mark_consumed("m_x")

    assert reg._mechanisms["m_x"].get("consumed_at") is not None

    # 重启后 consumed_at 仍在
    reg2 = MechanismRegistry(path=p)
    assert reg2._mechanisms["m_x"].get("consumed_at") is not None, \
        "重启后 consumed_at 应持久(否则 B1 消费率维度重启即丢)"


def test_none_path_stays_in_memory(tmp_path):
    """path=None 时纯内存, 不落盘(测试/临时安全)。"""
    reg = MechanismRegistry()  # 无 path
    reg.register("mem_only", {})
    assert reg._mechanisms.get("mem_only") is not None
    # 不应在 tmp_path 下写任何文件 (无 path -> _persist 直接 return)
    written = list(tmp_path.iterdir()) if tmp_path.exists() else []
    assert written == [], f"无 path 不应落盘, 但写了: {written}"
