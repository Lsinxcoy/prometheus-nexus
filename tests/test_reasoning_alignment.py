"""Tests for ReasoningAlignmentChecker (B5-4)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from prometheus_nexus.safety.reasoning_alignment import ReasoningAlignmentChecker

def test_same_answer_same_path():
    c = ReasoningAlignmentChecker()
    r = c.check_alignment([
        {"answer": "42", "reasoning": "Step 1: calculate"},
        {"answer": "42", "reasoning": "Step 1: calculate"},
    ])
    assert r["aligned"]

def test_same_answer_diff_path():
    c = ReasoningAlignmentChecker()
    r = c.check_alignment([
        {"answer": "42", "reasoning": "Step 1: add 1+1  "},
        {"answer": "42", "reasoning": "Step 2: multiply 6*7"},
    ])
    assert not r["aligned"]
    assert r["cara_score"] < 1.0

def test_diff_answer():
    c = ReasoningAlignmentChecker()
    r = c.check_alignment([
        {"answer": "42", "reasoning": "Some reasoning"},
        {"answer": "43", "reasoning": "Other reasoning"},
    ])
    assert r["cara_score"] < 1.0

def test_single_path():
    c = ReasoningAlignmentChecker()
    r = c.check_alignment([{"answer": "42", "reasoning": "test"}])
    assert r["aligned"]

if __name__ == "__main__":
    test_same_answer_same_path(); print("test_same_answer_same_path ✅")
    test_same_answer_diff_path(); print("test_same_answer_diff_path ✅")
    test_diff_answer(); print("test_diff_answer ✅")
    test_single_path(); print("test_single_path ✅")
    print("ALL PASS")
