"""Tests for LocalizedICL (B6-3)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from prometheus_nexus.learning.localized_icl import LocalizedICL

def test_first_failure():
    l = LocalizedICL()
    r = l.generate_correction([
        {"step": 1, "action": "read", "success": True},
        {"step": 2, "action": "write", "success": False},
    ])
    assert r["patch_step"] == 1

def test_no_failure():
    l = LocalizedICL()
    r = l.generate_correction([
        {"step": 1, "action": "read", "success": True},
    ])
    assert r["patch_step"] == -1

def test_empty_trajectory():
    l = LocalizedICL()
    r = l.generate_correction([])
    assert r["patch_step"] == -1

def test_multiple_failures():
    l = LocalizedICL()
    r = l.generate_correction([
        {"step": 0, "action": "search", "success": True},
        {"step": 1, "action": "read", "success": False},
        {"step": 2, "action": "write", "success": False},
    ])
    assert r["patch_step"] == 1  # first failure

if __name__ == "__main__":
    test_first_failure(); print("test_first_failure ✅")
    test_no_failure(); print("test_no_failure ✅")
    test_empty_trajectory(); print("test_empty_trajectory ✅")
    test_multiple_failures(); print("test_multiple_failures ✅")
    print("ALL PASS")
