"""Tests for B3-4: temporal weights + conflict detection in stream.py."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import time
from prometheus_nexus.memory.stream import MemoryStream

def test_apply_temporal_weights():
    s = MemoryStream()
    s.add("test", "result_A", 0.8)
    s.add("test", "result_B", 0.7)
    results = [{"node_id": "A", "content": "result_A", "utility": 0.8},
               {"node_id": "B", "content": "result_B", "utility": 0.7}]
    weighted = s.apply_recency_bias(results)
    assert len(weighted) == 2
    for r in weighted:
        assert "recency_score" in r
        assert "final_score" in r

def test_primacy_risk():
    s = MemoryStream()
    results = [{"node_id": "old", "content": "old result", "created_at": time.time() - 8*86400, "access_count": 50},
               {"node_id": "new", "content": "new result", "created_at": time.time() - 100, "access_count": 2}]
    risk = s.get_primacy_risk(results)
    assert "risk" in risk
    assert "dominated_by" in risk

def test_detect_conflicts():
    from prometheus_nexus.memory.stream import detect_conflicts
    results = [{"node_id": "1", "content": "accuracy is 70%", "utility": 0.8},
               {"node_id": "2", "content": "accuracy is 30%", "utility": 0.6}]
    conflicts = detect_conflicts(results)
    assert isinstance(conflicts, list)

def test_no_conflicts():
    from prometheus_nexus.memory.stream import detect_conflicts
    results = [{"node_id": "1", "content": "temperature is 25 degrees", "utility": 0.8},
               {"node_id": "2", "content": "humidity is 60 percent", "utility": 0.6}]
    conflicts = detect_conflicts(results)
    assert len(conflicts) == 0

if __name__ == "__main__":
    test_apply_temporal_weights()
    print("test_apply_temporal_weights ✅")
    test_primacy_risk()
    print("test_primacy_risk ✅")
    test_detect_conflicts()
    print("test_detect_conflicts ✅")
    test_no_conflicts()
    print("test_no_conflicts ✅")
    print("ALL TESTS PASS")
