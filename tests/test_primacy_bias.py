"""Tests for primacy bias (B4-4 enhanced)."""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from prometheus_nexus.memory.stream import MemoryStream
from prometheus_nexus.memory.stream import apply_temporal_weights

def test_apply_recency_bias():
    s = MemoryStream()
    now = time.time()
    r = s.apply_recency_bias([
        {"utility": 0.8, "created_at": now - 7200, "id": "old"},
        {"utility": 0.6, "created_at": now - 100, "id": "new"},
    ])
    assert len(r) == 2
    assert "recency_score" in r[0]
    assert "final_score" in r[0]

def test_get_primacy_risk():
    s = MemoryStream()
    now = time.time()
    r = s.get_primacy_risk([
        {"utility": 0.9, "created_at": now - 10*86400, "access_count": 100, "id": "dominator"},
        {"utility": 0.7, "created_at": now - 100, "access_count": 2, "id": "newer"},
    ])
    assert r["risk"] > 0

def test_apply_temporal_weights_module():
    now = time.time()
    r = apply_temporal_weights([
        {"ts": now - 7200, "content": "old"},
        {"ts": now - 100, "content": "new"},
    ])
    assert len(r) == 2
    assert "temporal_weight" in r[0]
    assert r[0]["temporal_weight"] > r[1]["temporal_weight"]

if __name__ == "__main__":
    test_apply_recency_bias(); print("test_apply_recency_bias ✅")
    test_get_primacy_risk(); print("test_get_primacy_risk ✅")
    test_apply_temporal_weights_module(); print("test_apply_temporal_weights_module ✅")
    print("ALL PASS")
