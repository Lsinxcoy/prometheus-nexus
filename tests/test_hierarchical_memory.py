"""Tests for HORMA hierarchical memory + RL navigator (B3-1)."""
from __future__ import annotations

from prometheus_nexus.memory.hierarchical_memory import HierarchicalMemory
from prometheus_nexus.memory.rl_navigator import RLNavigator


def test_hierarchical_memory_store_and_retrieve() -> None:
    hm = HierarchicalMemory()
    hm.store("n1", "/ai/memory/test", 0.8, content="hello world")

    results = hm.retrieve("/ai/memory")
    assert len(results) >= 1
    assert results[0]["node_id"] == "n1"
    assert results[0]["score"] > 0


def test_hierarchical_memory_get_path() -> None:
    hm = HierarchicalMemory()
    hm.store("n1", "/ai/memory/test", 0.8)
    assert hm.get_path("n1") == "/ai/memory/test"
    assert hm.get_path("nonexistent") is None


def test_hierarchical_memory_get_stats() -> None:
    hm = HierarchicalMemory()
    hm.store("n1", "/ai/memory", 0.5)
    hm.store("n2", "/ai/memory/sub", 0.6)
    stats = hm.get_stats()
    assert stats["total_nodes"] == 2
    assert stats["total_paths"] >= 2


def test_hierarchical_memory_path_normalisation() -> None:
    hm = HierarchicalMemory()
    hm.store("n1", "ai/memory", 0.5)
    assert hm.get_path("n1") == "/ai/memory"

    hm.store("n2", "/", 0.5)
    assert hm.get_path("n2") == "/"


def test_hierarchical_memory_multiple_nodes() -> None:
    hm = HierarchicalMemory()
    hm.store("a", "/tasks/alpha", 0.9, content="alpha task")
    hm.store("b", "/tasks/beta", 0.6, content="beta task")
    hm.store("c", "/science", 0.8, content="science")

    results = hm.retrieve("/tasks", max_results=5)
    ids = {r["node_id"] for r in results}
    assert "a" in ids
    assert "b" in ids
    # c is at /science — may appear via root fallback but should be scored lower
    if "c" in ids:
        a_score = next(r["score"] for r in results if r["node_id"] == "a")
        c_score = next(r["score"] for r in results if r["node_id"] == "c")
        assert a_score > c_score, "nodes under /tasks should outrank /science"


def test_hierarchical_memory_thread_safety() -> None:
    import threading
    hm = HierarchicalMemory()
    errors: list[Exception] = []

    def worker(n: int) -> None:
        try:
            for i in range(50):
                hm.store(f"node_{n}_{i}", f"/thread/{n}/{i}", 0.5)
                hm.retrieve("/thread")
                hm.get_path(f"node_{n}_{i}")
                hm.get_stats()
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Thread safety errors: {errors}"
    stats = hm.get_stats()
    assert stats["total_nodes"] == 4 * 50


def test_rl_navigator_navigate() -> None:
    hm = HierarchicalMemory()
    hm.store("n1", "/tasks/explore", 0.9, content="explore")
    hm.store("n2", "/tasks/explore/step1", 0.6, content="step1")
    hm.store("n3", "/tasks/explore/step1/detail", 0.7, content="detail")

    nav = RLNavigator()
    context, actions = nav.navigate(hm, "/tasks/explore", max_depth=5)

    assert len(context) >= 1
    assert isinstance(actions, list)
    assert all(a in (0, 1) for a in actions)


def test_rl_navigator_train() -> None:
    hm = HierarchicalMemory()
    hm.store("n1", "/tasks/explore", 0.9, content="explore")
    hm.store("n2", "/tasks/explore/step1", 0.6, content="step1")
    hm.store("n3", "/tasks/eval", 0.4, content="eval")
    hm.store("n4", "/science/biology", 0.8, content="biology")

    nav = RLNavigator(learning_rate=0.01, token_penalty=0.05)
    summary = nav.train(episodes=50, eval_hierarchy=hm,
                        eval_queries=["/tasks/explore", "/science/biology"])

    assert "avg_reward" in summary
    assert "success_rate" in summary
    assert "avg_tokens" in summary
    assert summary["episodes"] >= 50


def test_rl_navigator_get_stats() -> None:
    nav = RLNavigator()
    stats = nav.get_stats()
    assert stats["total_episodes"] >= 0
    assert "avg_reward" in stats
    assert "success_rate" in stats
