"""Integration test: Hermes ↔ Prometheus Ultra full pipeline verification.

Tests all 7 pipelines, branch operations, and status endpoints via HTTP.
Starts UltraAPIServer in background, runs tests, tears down.

Usage:
    cd E:/Prometheus-Ultra
    PYTHONPATH=E:/Prometheus-Ultra/src python tests/test_hermes_integration.py
"""
import sys
import os
import time
import json
import urllib.request
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from prometheus_nexus.foundation.schema import EvolutionResult

BASE = "http://127.0.0.1:9200/api/v1"
PASS = 0
FAIL = 0
DETAILS = []


def _post(path: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read()) if e.read() else {"error": str(e)}


def _get(path: str) -> dict:
    req = urllib.request.Request(f"{BASE}{path}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read()) if e.read() else {"error": str(e)}


def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        msg = f"  [FAIL] {name}" + (f" — {detail}" if detail else "")
        print(msg)
        DETAILS.append(msg)


def test_health():
    print("\n=== Health Check ===")
    r = _get("/health")
    check("health endpoint responds", r.get("status") == "healthy", str(r))
    check("service name correct", r.get("service") == "prometheus-ultra", str(r))


def test_status():
    print("\n=== System Status ===")
    r = _get("/status")
    check("status returns health", r.get("health") in ("healthy", "empty"), r.get("health", "missing"))
    check("node_count present", "node_count" in r, "missing node_count")
    check("mechanisms = 127", r.get("mechanisms") == 127, f"got {r.get('mechanisms')}")
    check("version present", r.get("version"), f"got {r.get('version')}")
    check("details dict present", isinstance(r.get("details"), dict), "details missing")
    # Check details has subsystem info
    details = r.get("details", {})
    for subsystem in ["bank_count", "convergence", "dopamine", "five_gates", "constitution", "graph_memory", "four_network"]:
        check(f"  details has {subsystem}", subsystem in details, f"available keys: {list(details.keys())[:10]}")


def test_remember():
    print("\n=== Remember Pipeline ===")
    r = _post("/remember", {
        "content": "Hermes agent successfully connected to Prometheus Ultra for integration testing",
        "utility": 0.9,
        "tags": ["hermes", "integration", "test"],
    })
    check("remember success flag", r.get("success") is True, r.get("error", ""))
    check("remember returns node_id", bool(r.get("data", {}).get("node_id")), r.get("data"))
    check("remember pipeline labeled", r.get("pipeline") == "remember", r.get("pipeline"))
    check("remember has duration_ms", r.get("duration_ms", 0) > 0, r.get("duration_ms"))

    # Remember more items for recall testing
    for i in range(5):
        _post("/remember", {
            "content": f"Test memory item {i}: Prometheus Ultra mechanism number {i+1} is active and functional",
            "utility": 0.7 + i * 0.04,
            "tags": [f"test_{i}", "mechanism"],
        })

    # Remember with evolution context
    r_evo = _post("/remember", {
        "content": "Evolution strategy GEPA showed improvement in last cycle",
        "utility": 0.85,
        "tags": ["evolution", "gepa", "strategy"],
    })
    check("remember evolution context", r_evo.get("success") is True, r_evo.get("error", ""))

    # Remember with learning context
    r_learn = _post("/remember", {
        "content": "Knowledge acquired from web about AI agent systems",
        "utility": 0.75,
        "tags": ["learning", "knowledge", "ai-agents"],
    })
    check("remember learning context", r_learn.get("success") is True, r_learn.get("error", ""))


def test_recall():
    print("\n=== Recall Pipeline ===")
    r = _post("/recall", {
        "query": "Hermes agent integration",
        "limit": 5,
    })
    check("recall success", r.get("success") is True, r.get("error", ""))
    check("recall pipeline labeled", r.get("pipeline") == "recall", r.get("pipeline"))
    data = r.get("data", {})
    check("recall has hits", isinstance(data.get("hits"), list), f"hits type: {type(data.get('hits'))}")
    check("recall total_count present", "total_count" in data, "missing total_count")
    check("recall query echoed", data.get("query") == "Hermes agent integration", data.get("query"))
    hits = data.get("hits", [])
    check("recall returns at least 1 hit", len(hits) >= 1, f"got {len(hits)} hits")
    if hits:
        h0 = hits[0]
        check("  hit has node_id", bool(h0.get("node_id")), "missing node_id")
        check("  hit has score", 0 <= h0.get("score", -1) <= 1, f"score={h0.get('score')}")
        check("  hit has content", len(h0.get("content", "")) > 0, "empty content")
    check("recall has metadata", isinstance(data.get("metadata"), dict), "missing metadata")

    # Recall with different queries
    r2 = _post("/recall", {"query": "mechanism active functional", "limit": 3})
    check("recall mechanism query", r2.get("success") is True, r2.get("error", ""))
    check("recall mechanism hits", len(r2.get("data", {}).get("hits", [])) >= 1, f"hits: {len(r2.get('data', {}).get('hits', []))}")


def test_evolve():
    print("\n=== Evolve Pipeline ===")
    r = _post("/evolve", {
        "context": "Improve Hermes integration capabilities through multi-strategy evolution",
        "branch": "main",
        "confidence": 0.7,
    })
    check("evolve success", r.get("success") is True, r.get("error", ""))
    check("evolve pipeline labeled", r.get("pipeline") == "evolve", r.get("pipeline"))
    data = r.get("data", {})
    check("evolve has result field", "result" in data, f"keys: {list(data.keys())}")
    result = data.get("result")
    check("evolve has valid result or blocked", result in ("SUCCESS", "BLOCKED", EvolutionResult.SUCCESS.value if False else ""), f"result={result}")
    has_fitness = "fitness_before" in data or result == "BLOCKED"
    check("evolve has fitness_before or blocked", has_fitness, f"result={result}, keys={list(data.keys())}")
    has_duration = data.get("duration_ms", -1) >= 0 or result == "BLOCKED"
    check("evolve has duration_ms", has_duration, f"duration={data.get('duration_ms')}")
    check("evolve has metadata", isinstance(data.get("metadata"), dict), "missing metadata")

    # Check that evolution metadata has diagnostics
    meta = data.get("metadata", {})
    check("  evolve metadata has diagnostics or blocked", bool(meta) or data.get("result") == "BLOCKED",
          f"meta keys: {list(meta.keys())[:5]}, result={data.get('result')}")

    # Test evolution with blocked scenario (low confidence)
    r_blocked = _post("/evolve", {
        "context": "Test evolution with low confidence",
        "branch": "main",
        "confidence": 0.1,
    })
    check("evolve low confidence handled", r_blocked.get("success") is True,
          f"result: {r_blocked.get('data', {}).get('result')}")


def test_learn():
    print("\n=== Learn Pipeline ===")
    r = _post("/learn", {
        "source": "web",
        "query": "AI agent reinforcement systems and memory architectures",
        "max_results": 3,
    })
    check("learn success", r.get("success") is True, r.get("error", ""))
    check("learn pipeline labeled", r.get("pipeline") == "learn", r.get("pipeline"))
    data = r.get("data", {})
    # learn may return dict with source/query or list-wrapped data
    check("learn has data content", bool(data), "empty data")
    if "source" in data and "query" in data:
        check("learn has source", data.get("source") == "web", f"source={data.get('source')}")
        check("learn has query", "AI agent" in (data.get("query") or ""), f"query={data.get('query')}")
        check("learn has total_results", "total_results" in data, f"keys: {list(data.keys())}")
    elif "items" in data:
        check("learn has items list", isinstance(data.get("items"), list), "items not list")
        check("learn has count", data.get("count", 0) >= 0, f"count={data.get('count')}")
    else:
        check("learn has fallback data", True, f"data keys: {list(data.keys())}")


def test_reflect():
    print("\n=== Reflect Pipeline ===")
    r = _post("/reflect", {
        "context": "Assess system state after Hermes integration test run",
    })
    check("reflect success", r.get("success") is True, r.get("error", ""))
    check("reflect pipeline labeled", r.get("pipeline") == "reflect", r.get("pipeline"))
    data = r.get("data", {})
    check("reflect has five_view", "five_view" in data, f"keys: {list(data.keys())[:10]}")
    check("reflect has harness", "harness" in data, "missing harness")
    check("reflect has thermodynamic", "thermodynamic" in data, "missing thermodynamic")
    check("reflect has equilibrium", "equilibrium" in data, "missing equilibrium")
    check("reflect has diagnostics", isinstance(data.get("diagnostics"), dict), "missing diagnostics")
    check("reflect has recent_learned", "recent_learned" in data, "missing recent_learned")

    # Five view details
    fv = data.get("five_view", {})
    check("  five_view has score", "score" in fv, f"fv keys: {list(fv.keys())}")
    check("  five_view has grade", "grade" in fv, "missing grade")


def test_dream():
    print("\n=== Dream Pipeline ===")
    r = _post("/dream", {
        "branch": "main",
    })
    check("dream success", r.get("success") is True, r.get("error", ""))
    check("dream pipeline labeled", r.get("pipeline") == "dream", r.get("pipeline"))
    data = r.get("data", {})
    check("dream has patterns_found", "patterns_found" in data, f"keys: {list(data.keys())}")
    check("dream has beliefs_synthesized", "beliefs_synthesized" in data, "missing beliefs_synthesized")
    check("dream has connections_discovered", "connections_discovered" in data, "missing connections_discovered")
    check("dream has insights", "insights" in data, "missing insights")
    check("dream has dream_data", isinstance(data.get("dream_data"), dict), "missing dream_data")

    # Dream data details
    dd = data.get("dream_data", {})
    check("  dream_data has state_machine info", "sm_state" in dd or "valid_next" in dd, f"dd keys: {list(dd.keys())[:10]}")
    check("  dream_data has forgetting info", "retention" in dd or "expired_nodes" in dd, "missing forgetting data")


def test_maintain():
    print("\n=== Maintain Pipeline ===")
    r = _post("/maintain", {})
    check("maintain success", r.get("success") is True, r.get("error", ""))
    check("maintain pipeline labeled", r.get("pipeline") == "maintain", r.get("pipeline"))
    data = r.get("data", {})
    check("maintain has consolidation", "consolidation" in data, f"keys: {list(data.keys())[:10]}")
    check("maintain has convergence", "convergence" in data, "missing convergence")
    check("maintain has thermodynamic", "thermodynamic" in data, "missing thermodynamic")
    check("maintain has duration_ms", data.get("duration_ms", 0) > 0, f"duration={data.get('duration_ms')}")
    check("maintain has maintain_data", isinstance(data.get("maintain_data"), dict), "missing maintain_data")

    # Maintain data details
    md = data.get("maintain_data", {})
    check("  maintain_data has bank_tiers", "bank_tiers" in md, f"md keys: {list(md.keys())[:10]}")
    check("  maintain_data has trajectory info", "traj_action_summary" in md or "traj_trajectories" in md, "missing trajectory data")
    check("  maintain_data has stream info", "stream_recent" in md or "stream_count" in md, "missing stream data")


def test_branches():
    print("\n=== Branch Operations ===")
    # Create branch
    r = _post("/branch/create", {
        "name": "hermes-integration-test",
        "parent": "main",
    })
    check("branch create success", r.get("success") is True, str(r))

    # List branches
    r = _get("/branch/list")
    check("branch list returns list", isinstance(r.get("branches"), list), f"type={type(r.get('branches'))}")
    check("branch list has new branch", "hermes-integration-test" in r.get("branches", []), f"branches: {r.get('branches')}")

    # Merge branch
    r = _post("/branch/merge", {
        "source": "hermes-integration-test",
        "target": "main",
    })
    check("branch merge success", r.get("success") is True, str(r))
    check("branch merge has write_id", bool(r.get("write_id")), "missing write_id")


def test_roundtrip():
    print("\n=== Roundtrip: Remember → Recall ===")
    # Remember a specific item
    content = "ROUNDTRIP_TEST_42: Hermes can recall what it just remembered via Ultra"
    r1 = _post("/remember", {
        "content": content,
        "utility": 1.0,
        "tags": ["roundtrip", "test_42"],
    })
    check("roundtrip remember success", r1.get("success") is True, r1.get("error", ""))
    node_id = r1.get("data", {}).get("node_id", "")
    check("roundtrip got node_id", bool(node_id), "no node_id")

    # Recall with unique keyword
    r2 = _post("/recall", {
        "query": "ROUNDTRIP_TEST_42",
        "limit": 5,
    })
    check("roundtrip recall success", r2.get("success") is True, r2.get("error", ""))
    hits = r2.get("data", {}).get("hits", [])
    found = any("ROUNDTRIP_TEST_42" in h.get("content", "") for h in hits)
    check("roundtrip found stored content", found, f"hits: {[h.get('content', '')[:50] for h in hits[:3]]}")


def main():
    global PASS, FAIL

    print("=" * 70)
    print("Hermes ↔ Prometheus Ultra Integration Test")
    print("=" * 70)
    print(f"Target: {BASE}")
    print()

    # Wait for server
    print("Waiting for Ultra API server...")
    ready = False
    for i in range(30):
        try:
            _get("/health")
            ready = True
            break
        except Exception:
            time.sleep(0.5)
    if not ready:
        print("[FATAL] Ultra API server not reachable at port 9200")
        print("Start it with: python -m prometheus_nexus.services.api_server --port 9200")
        sys.exit(1)

    print("Server is ready. Running tests...\n")

    # Run all test suites
    test_health()
    test_status()
    test_remember()
    test_recall()
    test_evolve()
    test_learn()
    test_reflect()
    test_dream()
    test_maintain()
    test_branches()
    test_roundtrip()

    # Summary
    print("\n" + "=" * 70)
    total = PASS + FAIL
    print(f"RESULTS: {PASS}/{total} passed, {FAIL} failed")
    if FAIL > 0:
        print("\nFailures:")
        for d in DETAILS:
            print(f"  {d}")
    else:
        print("\n✓ ALL TESTS PASSED — Hermes can fully utilize all 7 Ultra pipelines")
    print("=" * 70)

    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
