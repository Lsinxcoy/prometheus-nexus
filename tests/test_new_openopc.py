"""Tests for new OpenOPC mechanisms.

Tests:
1. RiskClassifiedApproval - 风险分级审批
2. SkillDualLayerLoading - 技能双层加载
3. WorkItemDAGScheduler - 工作项DAG调度
"""
import sys
import time
sys.path.insert(0, 'E:/Prometheus-Ultra/src')

from prometheus_nexus.safety.risk_classified_approval import RiskClassifiedApproval, ApprovalPolicy, RiskLevel
from prometheus_nexus.learning.skill_dual_layer import SkillDualLayerLoading, Skill
from prometheus_nexus.execution.work_item_dag import WorkItemDAGScheduler, WorkItem, TaskStatus


def test_risk_classified_approval():
    """Test risk-classified approval system"""
    print("\n=== Testing Risk Classified Approval ===")

    approval = RiskClassifiedApproval()

    # Create low risk request (auto-approved)
    req1 = approval.create_request("req_1", "read_data", 0.2, requested_by="user1")
    print(f"Low risk request: status={req1.status}, risk={req1.risk_level.value}")
    assert req1.status == "approved"
    assert req1.risk_level == RiskLevel.LOW

    # Create medium risk request (needs single approval)
    req2 = approval.create_request("req_2", "write_data", 0.5, requested_by="user2")
    print(f"Medium risk request: status={req2.status}, risk={req2.risk_level.value}")
    assert req2.status == "pending"
    assert req2.risk_level == RiskLevel.MEDIUM

    # Approve it
    result = approval.approve("req_2", "admin1")
    print(f"Approval result: {result}")
    assert result is True
    assert req2.status == "approved"

    # Create high risk request (needs double approval)
    req3 = approval.create_request("req_3", "delete_data", 0.7, requested_by="user3")
    print(f"High risk request: status={req3.status}, risk={req3.risk_level.value}")
    assert req3.risk_level == RiskLevel.HIGH

    # First approval
    approval.approve("req_3", "admin1")
    print(f"After first approval: approved_by={req3.approved_by}")
    assert len(req3.approved_by) == 1

    # Second approval
    approval.approve("req_3", "admin2")
    print(f"After second approval: status={req3.status}")
    assert req3.status == "approved"

    # Check stats
    stats = approval.get_stats()
    print(f"Stats: {stats}")
    assert stats["auto_approved"] == 1
    assert stats["single_approved"] == 1
    assert stats["double_approved"] == 1

    print("✅ Risk Classified Approval working correctly")


def test_skill_dual_layer_loading():
    """Test skill dual-layer loading"""
    print("\n=== Testing Skill Dual Layer Loading ===")

    loader = SkillDualLayerLoading(core_layer_size_limit=1024.0)

    # Register core skills (auto-loaded)
    core_skills = [
        Skill("core_1", "Basic Evolve", priority=9, layer=1, size_kb=100),
        Skill("core_2", "Basic Recall", priority=8, layer=1, size_kb=150),
        Skill("core_3", "Basic Learn", priority=7, layer=1, size_kb=120),
    ]

    for skill in core_skills:
        loader.register_skill(skill)

    # Check core skills are loaded
    stats = loader.get_stats()
    print(f"Core skills loaded: {stats['core_loaded']}")
    assert stats["core_loaded"] == 3

    # Register extension skills (not auto-loaded)
    ext_skills = [
        Skill("ext_1", "Advanced Mutate", priority=6, layer=2, size_kb=200, tags=["evolution"]),
        Skill("ext_2", "Advanced Crossover", priority=5, layer=2, size_kb=180, tags=["evolution"]),
        Skill("ext_3", "Deep Analysis", priority=4, layer=2, size_kb=250, tags=["analysis"]),
    ]

    for skill in ext_skills:
        loader.register_skill(skill)

    # Check extension skills not loaded yet
    stats = loader.get_stats()
    print(f"Extension skills loaded: {stats['extension_loaded']}")
    assert stats["extension_loaded"] == 0

    # Load extension skill on demand
    result = loader.load_skill("ext_1")
    print(f"Loaded ext_1: {result is not None}")
    assert result is not None

    stats = loader.get_stats()
    print(f"After loading ext_1: extension_loaded={stats['extension_loaded']}")
    assert stats["extension_loaded"] == 1

    # Find skills by tag
    evolution_skills = loader.find_skills_by_tag("evolution")
    print(f"Evolution skills found: {len(evolution_skills)}")
    assert len(evolution_skills) == 2

    # Preload high priority skills
    loaded = loader.preload_high_priority(count=2)
    print(f"Preloaded skills: {loaded}")
    assert loaded >= 1

    print("✅ Skill Dual Layer Loading working correctly")


def test_work_item_dag_scheduler():
    """Test work item DAG scheduler"""
    print("\n=== Testing Work Item DAG Scheduler ===")

    scheduler = WorkItemDAGScheduler(max_concurrent=2)

    # Define execute function
    def execute_fn(item: WorkItem):
        # Simulate execution
        time.sleep(0.1)
        return {"success": True, "item": item.item_id}

    # Create work items with dependencies
    items = [
        WorkItem("w1", "Step 1", "init", priority=5),
        WorkItem("w2", "Step 2", "process", dependencies=["w1"], priority=6),
        WorkItem("w3", "Step 3", "validate", dependencies=["w1"], priority=7),
        WorkItem("w4", "Step 4", "finalize", dependencies=["w2", "w3"], priority=8),
    ]

    # Execute DAG
    result = scheduler.create_dag("test_dag", items, execute_fn)

    print(f"DAG status: {result.status.value}")
    print(f"Completed: {result.completed_items}/{result.total_items}")
    print(f"Failed: {result.failed_items}")
    print(f"Duration: {result.duration_ms:.1f}ms")

    assert result.status == TaskStatus.COMPLETED
    assert result.completed_items == 4
    assert result.failed_items == 0

    # Check progress
    progress = scheduler.get_progress("test_dag")
    print(f"Progress: {progress['progress']:.0%}")
    assert progress["progress"] == 1.0

    # Check individual item statuses
    for item_id in ["w1", "w2", "w3", "w4"]:
        status = scheduler.get_item_status(item_id)
        print(f"  {item_id}: {status.value}")
        assert status == TaskStatus.COMPLETED

    # Check stats
    stats = scheduler.get_stats()
    print(f"Stats: {stats}")
    assert stats["successful"] == 4

    print("✅ Work Item DAG Scheduler working correctly")


def run_all_tests():
    """Run all tests"""
    print("=" * 60)
    print("TESTING NEW OPENOPC MECHANISMS")
    print("=" * 60)

    try:
        test_risk_classified_approval()
        test_skill_dual_layer_loading()
        test_work_item_dag_scheduler()

        print("\n" + "=" * 60)
        print("✅ ALL NEW OPENOPC MECHANISM TESTS PASSED")
        print("=" * 60)
        return True

    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
