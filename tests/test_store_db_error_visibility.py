"""回归测试: MinervaStore 基础层 DB 错误不得被静默吞掉。

根因: store.py 中 search(空查询) / list_branches / get_node_count /
get_edge_count 的 except sqlite3.Error 分支曾无 logger(裸 return [] / 0),
把数据库故障(表损坏 / 磁盘 IO / 锁竞争)伪装成'无数据 / 计数为 0',
违反本模块自身'DB 错误必须 logger.error'的约定(其余 19 处 DB 错误分支均记录)。
下游 life.py:4302(list_branches 分支 API) 与 life.py:3274(search("") 取最近节点)
因此会在 DB 宕机时静默返回空, 隐藏真实故障。

修复: 四处分支补 logger.error, 保留安全兜底返回值(不改变调用方契约)。

验证: 用抛出 sqlite3.Error 的桩替换 _conn, 断言
  (a) 安全兜底值仍返回(不破坏调用方) —— 向后兼容;
  (b) store logger 确实发出 ERROR(故障可见)。
修复前 (b) 不成立 -> 本测试失败, 故它是真实回归锁而非假绿。
"""
import sys
sys.path.insert(0, "E:/Prometheus-Ultra-MultiTypeKB/src")

import logging
import sqlite3

import pytest

from prometheus_nexus.foundation.store import MinervaStore


class _BrokenConn:
    """模拟数据库故障的连接桩: 任何 execute 都抛 sqlite3.Error。"""

    row_factory = None

    def execute(self, *args, **kwargs):
        raise sqlite3.Error("simulated DB corruption / disk I/O error")

    def commit(self):
        raise sqlite3.Error("simulated")

    def rollback(self):
        raise sqlite3.Error("simulated")


@pytest.fixture
def broken_store():
    s = MinervaStore()
    # 跳过真实 connect: 直接置已连接 + 故障连接桩
    s._connected = True
    s._conn = _BrokenConn()
    return s


def _store_error_logged(caplog, msg_fragment):
    return any(
        r.levelno >= logging.ERROR
        and r.name == "prometheus_nexus.foundation.store"
        and msg_fragment in r.getMessage()
        for r in caplog.records
    )


class TestStoreDBErrorVisibility:
    def test_list_branches_surfaces_db_error(self, broken_store, caplog):
        with caplog.at_level(logging.ERROR, logger="prometheus_nexus.foundation.store"):
            result = broken_store.list_branches()
        assert result == [], "list_branches 故障时应安全兜底为 [] (契约不变)"
        assert _store_error_logged(caplog, "list_branches failed"), \
            "DB 故障被静默吞掉: list_branches 未 logger.error(隐藏薄弱回退)"

    def test_get_node_count_surfaces_db_error(self, broken_store, caplog):
        with caplog.at_level(logging.ERROR, logger="prometheus_nexus.foundation.store"):
            result = broken_store.get_node_count()
        assert result == 0, "get_node_count 故障时应安全兜底为 0 (契约不变)"
        assert _store_error_logged(caplog, "get_node_count failed"), \
            "DB 故障被静默吞掉: get_node_count 未 logger.error(隐藏薄弱回退)"

    def test_get_edge_count_surfaces_db_error(self, broken_store, caplog):
        with caplog.at_level(logging.ERROR, logger="prometheus_nexus.foundation.store"):
            result = broken_store.get_edge_count()
        assert result == 0, "get_edge_count 故障时应安全兜底为 0 (契约不变)"
        assert _store_error_logged(caplog, "get_edge_count failed"), \
            "DB 故障被静默吞掉: get_edge_count 未 logger.error(隐藏薄弱回退)"

    def test_search_empty_query_surfaces_db_error(self, broken_store, caplog):
        with caplog.at_level(logging.ERROR, logger="prometheus_nexus.foundation.store"):
            result = broken_store.search("")
        assert result == [], "search('') 故障时应安全兜底为 [] (契约不变)"
        assert _store_error_logged(caplog, "search (empty query) failed"), \
            "DB 故障被静默吞掉: search('') 未 logger.error(隐藏薄弱回退)"

    def test_healthy_connection_still_works(self, tmp_path):
        """健全性: 真实连接下这些方法正常工作且不过度报错。"""
        s = MinervaStore()
        s._cfg.database_path = str(tmp_path / "ok.db")
        s.connect()
        # 真实空库: list_branches 至少含 main; 无节点时 counts 为 0
        assert "main" in s.list_branches()
        assert s.get_node_count() == 0
        assert s.get_edge_count() == 0
        assert s.search("") == []  # 空库无节点 -> 空 list
        s.close()
