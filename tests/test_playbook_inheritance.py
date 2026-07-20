"""针对 PlaybookInheritance.resolve_variable 父链继承的回归测试。

根因 (cycle-2 修复): Playbook.resolve_variable 文档声明"优先本地、其次父 Playbook
变量", 但原实现仅检查 self.variables 后直接 return None (TODO 未实现)。任何只在
父 Playbook 定义、子 Playbook 未拍平的变量都会被静默解析为 None, 导致继承配置丢失。

本测试覆盖:
  - 直接设 parent_playbook_id 但未拍平子变量的子 Playbook 能解析到父变量 (核心 bug)
  - 多级继承链 (祖父->父->子)
  - 本地变量优先于父变量
  - create_derived_playbook 拍平路径仍正确解析
  - 全链缺失变量返回 None
  - 未注入 resolver 的孤立 Playbook 优雅降级 (返回 None, 不抛异常)
"""
from __future__ import annotations

from prometheus_nexus.evolution.playbook_inheritance import (
    Playbook,
    PlaybookInheritance,
)


def _sys() -> PlaybookInheritance:
    return PlaybookInheritance()


def test_child_with_unflattened_parent_var_resolves():
    """核心 bug: 子 Playbook 仅设 parent_playbook_id, 变量只定义在父上 -> 必须解析到父值。"""
    sys = _sys()
    parent = Playbook(playbook_id="p1", name="parent",
                      variables={"endpoint": "https://api.example.com", "token": "secret"})
    child = Playbook(playbook_id="c1", name="child", parent_playbook_id="p1")
    assert sys.register_playbook(parent) is True
    assert sys.register_playbook(child) is True

    assert child.resolve_variable("endpoint") == "https://api.example.com"
    assert child.resolve_variable("token") == "secret"


def test_multilevel_inheritance_chain():
    """多级继承链: 孙 Playbook 解析到祖父定义的变量。"""
    sys = _sys()
    grand = Playbook(playbook_id="g", name="grand", variables={"region": "us-east"})
    parent = Playbook(playbook_id="p", name="parent", parent_playbook_id="g")
    child = Playbook(playbook_id="c", name="child", parent_playbook_id="p")
    sys.register_playbook(grand)
    sys.register_playbook(parent)
    sys.register_playbook(child)

    assert child.resolve_variable("region") == "us-east"
    # 继承链顺序正确: child -> parent -> grand
    assert sys.get_inheritance_chain("c") == ["c", "p", "g"]


def test_local_variable_overrides_parent():
    """本地变量优先于父变量。"""
    sys = _sys()
    parent = Playbook(playbook_id="p", name="parent", variables={"mode": "strict"})
    child = Playbook(playbook_id="c", name="child", parent_playbook_id="p",
                     variables={"mode": "lenient"})
    sys.register_playbook(parent)
    sys.register_playbook(child)

    assert child.resolve_variable("mode") == "lenient"


def test_derived_playbook_flatten_still_resolves():
    """create_derived_playbook 已拍平父变量, resolve_variable 仍能解析 (本地)。"""
    sys = _sys()
    base = Playbook(playbook_id="base", name="base", variables={"buf": 1024})
    sys.register_playbook(base)
    derived = sys.create_derived_playbook("base", "d1", "derived",
                                          override_variables={"extra": 7})
    assert derived is not None
    assert derived.resolve_variable("buf") == 1024
    assert derived.resolve_variable("extra") == 7


def test_missing_variable_returns_none():
    """全链均无该变量 -> 返回 None (不抛异常)。"""
    sys = _sys()
    parent = Playbook(playbook_id="p", name="parent", variables={"a": 1})
    child = Playbook(playbook_id="c", name="child", parent_playbook_id="p")
    sys.register_playbook(parent)
    sys.register_playbook(child)

    assert child.resolve_variable("nonexistent") is None


def test_orphan_playbook_without_resolver_degrades_gracefully():
    """未注入 resolver 的孤立 Playbook: 解析父变量优雅返回 None, 而非抛异常。"""
    orphan = Playbook(playbook_id="o", name="orphan", parent_playbook_id="missing")
    # parent_resolver 默认为 None, 且父不在 _playbooks 中
    assert orphan.resolve_variable("x") is None


def test_cycle_inheritance_does_not_infinite_loop():
    """防御: 若继承链出现环, resolve_variable 不应死循环 (父查找返回 None 即可终止)。"""
    sys = _sys()
    a = Playbook(playbook_id="a", name="a", parent_playbook_id="b", variables={"v": 1})
    b = Playbook(playbook_id="b", name="b", parent_playbook_id="a")
    # 故意构造环: a->b->a
    sys._playbooks["a"] = a
    sys._playbooks["b"] = b
    sys._inheritance_map["a"] = "b"
    sys._inheritance_map["b"] = "a"
    a.parent_resolver = lambda pid: sys._playbooks.get(pid)
    b.parent_resolver = lambda pid: sys._playbooks.get(pid)
    # 解析 b 上不存在的变量: 走到 a(有v) 然后 a->b 再次查找; b 无 v -> None, 不会无限递归
    assert b.resolve_variable("v") == 1
