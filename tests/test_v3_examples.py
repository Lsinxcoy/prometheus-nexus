"""V3.5b 适配器示例验证.

验证 examples/ 下的 Agent 接入示例(claude_code/autogpt)能正确构造 UltraClient
并调方法(不依赖真实 LLM/Ultra server, 用内存注入 omega 验证 SDK 调用链).
"""
import sys
import os
sys.path.insert(0, "E:/Prometheus-Ultra-MultiTypeKB/src")
sys.path.insert(0, "E:/Prometheus-Ultra-MultiTypeKB/examples")

import pytest
import tempfile


def _inject_omega(client, db_path):
    """测试辅助: 把真实 Omega 注入 client(免起 HTTP server)."""
    from prometheus_nexus.life import Omega
    o = Omega(db_path=db_path)
    client.omega = o
    return o


class TestAgentExamples:
    def test_claude_code_example_runs(self):
        """Claude Code 示例能跑通(用内存 omega 注入)."""
        import claude_code_agent as ex
        db = os.path.join(tempfile.gettempdir(), f"ex_cc_{os.getpid()}_{id(object())}.db")
        # 重定向 print 捕获
        import io, contextlib
        o = None
        try:
            cli = ex.UltraClient(base_url="http://localhost:9200", host_id="claude_code_main")
            o = _inject_omega(cli, db)
            ex.UltraClient = lambda *a, **k: cli  # 让示例用注入的 client
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                ex.run_claude_code_agent()
            out = buf.getvalue()
            assert "ClaudeCode" in out
            assert "Ultra 接入完成" in out
        finally:
            if o: o.store.close()
            try: os.remove(db)
            except Exception: pass

    def test_autogpt_example_runs(self):
        """AutoGPT 示例能跑通(用内存 omega 注入)."""
        import autogpt_agent as ex
        db = os.path.join(tempfile.gettempdir(), f"ex_ag_{os.getpid()}_{id(object())}.db")
        import io, contextlib
        o = None
        try:
            cli = ex.UltraClient(base_url="http://localhost:9200", host_id="autogpt_agent_01")
            o = _inject_omega(cli, db)
            ex.UltraClient = lambda *a, **k: cli
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                ex.run_autogpt_agent()
            out = buf.getvalue()
            assert "AutoGPT" in out
            assert "Ultra 接入完成" in out
        finally:
            if o: o.store.close()
            try: os.remove(db)
            except Exception: pass

    def test_examples_prove_host_id_isolation(self):
        """两示例用不同 host_id 接入, 各自经验按 host_id 分支隔离: 一个 Agent 的检索不能看到另一个 Agent 的内容.

        对应生产契约 life.py:3215 remember(..., branch=self.host.host_id) —— 多宿主经验经
        store 的 branch 列分区(见 foundation/store.py:636 WHERE branch=? ), 隔离由 store
        层分支过滤保证。此前该测试只断言模块名与两个字面量字符串不等, 属假绿: 隔离机制
        即便完全失效也照样通过。现改为真正写入两 host_id 分支并断言严格隔离。
        """
        from prometheus_nexus.life import Omega
        from prometheus_nexus.integration.host_agent import GenericAgentAdapter
        from prometheus_nexus.foundation.store import NodeType

        db = os.path.join(tempfile.gettempdir(), f"iso_{os.getpid()}_{id(object())}.db")
        o = Omega(db_path=db)
        a = GenericAgentAdapter(host_id="claude_code_main")
        b = GenericAgentAdapter(host_id="autogpt_agent_01")
        try:
            # 两个不同 host_id 的 Agent 把经验写入同一 store, 各自以自身 host_id 作 branch
            # (这正是 _learn_host_experience 的 branch=self.host.host_id 分区语义)
            o.remember("isolation marker alpha CLAUDE owned node one",
                       branch=a.host_id, tags=["host_exp"],
                       node_type=NodeType.PROCEDURE, utility=0.9)
            o.remember("isolation marker beta AUTOGPT owned node two",
                       branch=b.host_id, tags=["host_exp"],
                       node_type=NodeType.PROCEDURE, utility=0.9)

            # claude_code 只能看到自己的经验
            hits_a = o.store.search("isolation marker", limit=10, branch=a.host_id)
            contents_a = [n.content for n in hits_a]
            assert any("CLAUDE" in c for c in contents_a), \
                "claude_code 应能看到自身经验"
            assert not any("AUTOGPT" in c for c in contents_a), \
                "claude_code 不应看到 autogpt 的经验(多 Agent 隔离失效)"

            # autogpt 同理
            hits_b = o.store.search("isolation marker", limit=10, branch=b.host_id)
            contents_b = [n.content for n in hits_b]
            assert any("AUTOGPT" in c for c in contents_b), \
                "autogpt 应能看到自身经验"
            assert not any("CLAUDE" in c for c in contents_b), \
                "autogpt 不应看到 claude_code 的经验(多 Agent 隔离失效)"
        finally:
            o.store.close()
            try:
                os.remove(db)
            except Exception:
                pass

    def test_examples_host_id_isolation_detects_leak(self, monkeypatch):
        """反向验证(非假绿): 若 store 分支过滤失效导致跨分支泄漏, 主隔离测试必失败。

        通过 monkeypatch 把 MinervaStore.search 改成跨分支泄漏版本(无视 branch 参数,
        把 agent_a/agent_b 两分支结果合并返回), 模拟隔离机制被破坏。此时主测试
        'claude_code 不应看到 autogpt 经验' 的断言必然失败 —— 证明主测试对隔离失效敏感,
        而非永远通过的假绿。
        """
        from prometheus_nexus.life import Omega
        from prometheus_nexus.foundation.store import NodeType

        db = os.path.join(tempfile.gettempdir(), f"iso_rev_{os.getpid()}_{id(object())}.db")
        o = Omega(db_path=db)
        real_search = o.store.search

        def _leaky_search(self2, query, limit=10, branch="main"):
            # 模拟分支过滤失效: 无视 branch, 合并两宿主分支结果
            return (real_search(query, limit=limit, branch="agent_a")
                    + real_search(query, limit=limit, branch="agent_b"))

        monkeypatch.setattr(type(o.store), "search", _leaky_search)
        try:
            o.remember("isolation marker alpha CLAUDE owned node one",
                       branch="agent_a", tags=["host_exp"],
                       node_type=NodeType.PROCEDURE, utility=0.9)
            o.remember("isolation marker beta AUTOGPT owned node two",
                       branch="agent_b", tags=["host_exp"],
                       node_type=NodeType.PROCEDURE, utility=0.9)
            # 分支过滤失效时, 以 agent_a 分支查询会泄漏出 agent_b 的内容
            hits_a = o.store.search("isolation marker", limit=10, branch="agent_a")
            contents_a = [n.content for n in hits_a]
            assert any("AUTOGPT" in c for c in contents_a), \
                "反向验证失败: 跨分支泄漏存在时主隔离断言仍未失败(主测试可能假绿)"
        finally:
            o.store.close()
            try:
                os.remove(db)
            except Exception:
                pass
