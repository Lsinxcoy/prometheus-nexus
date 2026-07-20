"""Pytest 全局配置: 隔离 Omega 的 store db, 避免测试间共享 prometheus_memory.db 污染。

每个 Omega() 实例用独立临时文件数据库, 消除测试顺序/累积导致的
sqlite3 冲突与状态污染(全量跑 60+ 文件时尤为明显)。

注意: 不能用 :memory: —— SQLite 的 :memory: 每个连接独立, 而 MinervaStore
内部某些路径可能复用/新建连接, 导致写入不可见。临时文件 db 则无此问题。
"""
import os
import tempfile

import pytest


@pytest.fixture(autouse=True)
def _isolate_store_db(monkeypatch):
    """让 Omega 默认 db 指向独立临时文件, 每个测试隔离。"""
    import prometheus_nexus.life as life_mod
    orig_init = life_mod.Omega.__init__

    _counter = {"n": 0}

    def _patched_init(self, config=None, db_path=None, *a, **kw):
        if db_path is None:
            _counter["n"] += 1
            tmp = tempfile.gettempdir()
            db_path = os.path.join(tmp, f"ultra_test_db_{os.getpid()}_{_counter['n']}.db")
        return orig_init(self, config, db_path, *a, **kw)

    monkeypatch.setattr(life_mod.Omega, "__init__", _patched_init)

    # owner_harm 的违规日志持久化到固定 archive/ 路径(跨重启不丢),
    # 但测试假设全新实例 violation_count==0. 此处把该路径也隔离到临时目录,
    # 避免历史运行残留污染(否则每次跑 Omega 都会累计写日志).
    from prometheus_nexus.safety.owner_harm import OwnerHarmTrustBoundary
    _oh_init = OwnerHarmTrustBoundary.__init__

    def _oh_isolated_init(self, *a, **kw):
        _oh_init(self, *a, **kw)
        self._viol_log_path = os.path.join(
            tempfile.gettempdir(),
            f"ultra_owner_harm_viol_{os.getpid()}_{id(self)}.json",
        )

    monkeypatch.setattr(OwnerHarmTrustBoundary, "__init__", _oh_isolated_init)


def pytest_collection_modifyitems(config, items):
    """集成 server 测试需外部/真实 server, 无 RUN_SERVER_TESTS 环境变量时跳过。

    test_hermes_integration 需手动启动外部 API server(端口9200) → 跳过。

    test_api_server 的 TestStart/TestStop 现已改用隔离空闲端口 + 真实断言:
    不再与 9200 实例冲突、stop() 也会真正终止 uvicorn 并释放端口, 不会遗留
    线程/端口污染后续测试, 故默认运行。修复前它们被整体跳过 → 生命周期零覆盖,
    且启用时断言为假绿(assert isinstance(e, Exception) / except: pass)。
    """
    if os.environ.get("RUN_SERVER_TESTS") == "1":
        return
    skip_server = pytest.mark.skip(
        reason="集成 server 测试需 RUN_SERVER_TESTS=1 且外部/真实 server 可用"
    )
    for item in items:
        path = item.nodeid
        if "test_hermes_integration.py" in path:
            item.add_marker(skip_server)
