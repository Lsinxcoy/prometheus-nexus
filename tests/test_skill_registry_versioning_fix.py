"""SkillRegistry 版本管理弱点修复验证 (cycle 42).

薄弱点:
  1. register() 文档声明'版本管理: 递增版本号', 但重名再注册时 _skill_map[name]
     只指向最新条目, 而 _skills 累积全部副本 -> get_active_skills()/search()
     返回重复 active 条目(同名多活跃), 违反'每 name 仅一个活跃技能'不变量。
  2. register(version=...) 幽灵参数: 显式版本号被静默忽略, 永远用自增 int 覆盖。

修复后断言 (在修复前本文件 3/4 用例必失败, 非假绿):
  - 重名再注册 -> get_active_skills 仍只返回 1 个该 name 的活跃条目, 且为最新版本;
    get_skill(name) 返回最新版本; 旧副本不得作为独立活跃条目出现。
  - 显式 version 被尊重(不再被 int 自增覆盖)。
"""
import pytest

from prometheus_nexus.skills.registry import SkillRegistry


def test_reregister_same_name_yields_single_active_entry():
    r = SkillRegistry()
    r.register(name="foo", tags=["a"])
    r.register(name="foo", tags=["b"])  # 新版本
    active = r.get_active_skills()
    foo_entries = [s for s in active if s["name"] == "foo"]
    assert len(foo_entries) == 1, f"重名再注册不应产生重复活跃条目, 实际: {foo_entries}"
    assert foo_entries[0]["version"] == 2
    # get_skill 返回最新版本
    assert r.get_skill("foo")["version"] == 2
    # 旧 tag 副本不应以独立活跃条目出现
    assert sum(1 for s in r.get_active_skills() if s["name"] == "foo") == 1


def test_reregister_supersedes_old_entry_status():
    r = SkillRegistry()
    r.register(name="bar")
    first = r.get_skill("bar")
    r.register(name="bar")
    # 旧条目应被标记为 superseded(不再 active)
    assert first["status"] == "superseded"
    assert r.get_skill("bar")["status"] == "active"


def test_explicit_version_honored_not_ignored():
    r = SkillRegistry()
    res = r.register(name="baz", version="2.0")
    assert res["version"] == "2.0", "显式 version 不应被静默忽略"
    assert r.get_skill("baz")["version"] == "2.0"


def test_auto_increment_when_version_omitted():
    r = SkillRegistry()
    r.register(name="qux")
    r.register(name="qux")
    r.register(name="qux")
    assert r.get_skill("qux")["version"] == 3
