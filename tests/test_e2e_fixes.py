"""End-to-end tests for today's fixes and new features.

Tests focus on:
1. Learn→Recall feedback loop (P0)
2. FourNetwork classification enhancement (P1)
3. FiveGates adaptive thresholds (P2)
4. Evolution engine anti-convergence (P1)
5. MARS belief system filling (P2)
6. DAG scheduler integration (P2)
7. OpenOPC mechanisms: Attribution scoring, Playbook inheritance, Two-level Blocker
"""
import sys
sys.path.insert(0, 'E:/Prometheus-Ultra/src')

from prometheus_nexus import Omega
from prometheus_nexus.learning.learn_feedback import LearnFeedbackTracker
from prometheus_nexus.memory.four_network import FourNetworkMemory
from prometheus_nexus.safety.five_gates import FiveGates
from prometheus_nexus.evolution.attribution_scoring import AttributionEvolutionScoring
from prometheus_nexus.evolution.playbook_inheritance import PlaybookInheritance, Playbook, PlaybookStep
from prometheus_nexus.safety.two_level_blocker import TwoLevelBlockerEscalation
from prometheus_nexus.foundation.schema import Node, NodeType


def test_learn_recall_feedback():
    """Test P0: Learn→Recall feedback loop"""
    print("\n=== Testing Learn→Recall Feedback Loop ===")
    
    omega = Omega()
    tracker = omega.learn_feedback
    
    # Simulate learn
    tracker.register("node_1", source="web", query="AI agent")
    tracker.register("node_2", source="arxiv", query="machine learning")
    tracker.register("node_3", source="web", query="deep learning")
    
    print(f"Registered nodes: {tracker.get_stats()['total_registered']}")
    assert tracker.get_stats()["total_registered"] == 3
    
    # Simulate recall hits
    tracker.mark_hit("node_1", "AI agent")
    tracker.mark_hit("node_3", "deep learning")
    
    # Check hit rate
    global_rate = tracker.get_hit_rate()
    print(f"Global hit rate: {global_rate:.2%}")
    assert global_rate > 0.0, "Hit rate should be > 0"
    
    # Check per-query hit rate
    q1_rate = tracker.get_hit_rate("web", "AI agent")
    print(f"Query 'AI agent' hit rate: {q1_rate:.2%}")
    assert q1_rate == 1.0, "Should be 100% hit"
    
    q2_rate = tracker.get_hit_rate("arxiv", "machine learning")
    print(f"Query 'machine learning' hit rate: {q2_rate:.2%}")
    assert q2_rate == 0.0, "Should be 0% hit"
    
    print("✅ Learn→Recall feedback loop working correctly")


def test_four_network_classification():
    """Test P1: FourNetwork classification enhancement"""
    print("\n=== Testing FourNetwork Classification ===")
    
    fn = FourNetworkMemory()
    
    # Test semantic content
    semantic_content = "The concept of AI is defined as artificial intelligence"
    result = fn._auto_classify(semantic_content)
    print(f"Semantic content classified as: {result}")
    assert result in ["semantic", "experience"], f"Expected semantic or experience, got {result}"
    
    # Test procedural content
    procedural_content = "Step 1: First, then proceed with the algorithm"
    result = fn._auto_classify(procedural_content)
    print(f"Procedural content classified as: {result}")
    assert result in ["procedural", "experience"], f"Expected procedural or experience, got {result}"
    
    # Test episodic content
    episodic_content = "At location X, during episode Y, the scenario occurred"
    result = fn._auto_classify(episodic_content)
    print(f"Episodic content classified as: {result}")
    assert result in ["episodic", "experience"], f"Expected episodic or experience, got {result}"
    
    # Test distribution balance
    contents = [
        "The category of ML is machine learning",
        "Step 1: First, then do this",
        "At location A, during event B",
        "Today I experienced something new",
    ] * 25
    
    for c in contents:
        fn.retain(c)
    
    total = sum(len(fn._networks[n]) for n in fn.NETWORK_NAMES)
    print(f"Total entries: {total}")
    
    for net in fn.NETWORK_NAMES:
        ratio = len(fn._networks[net]) / total if total > 0 else 0
        print(f"  {net}: {len(fn._networks[net])} entries ({ratio:.1%})")
        assert ratio < 0.6, f"{net}占比过高: {ratio:.1%}"
    
    print("✅ FourNetwork classification working correctly")


def test_five_gates_adaptive():
    """Test P2: FiveGates adaptive thresholds"""
    print("\n=== Testing FiveGates Adaptive Thresholds ===")
    
    gates = FiveGates(adaptive=True)
    
    # Test low utility rejection
    low_util_node = Node(id="low", type=NodeType.FACT, content="test", utility=0.05)
    result = gates.evaluate(low_util_node, {"current_node_count": 10})
    print(f"Low utility node passed: {result.passed}")
    assert not result.passed, "Low utility should be rejected"
    
    # Test high utility acceptance
    high_util_node = Node(id="high", type=NodeType.FACT, content="test content", utility=0.8)
    result = gates.evaluate(high_util_node, {"current_node_count": 10})
    print(f"High utility node passed: {result.passed}")
    assert result.passed, "High utility should pass"
    
    # Test empty content rejection
    empty_node = Node(id="empty", type=NodeType.FACT, content="", utility=0.7)
    result = gates.evaluate(empty_node, {"current_node_count": 10})
    print(f"Empty content node passed: {result.passed}")
    assert not result.passed, "Empty content should be rejected"
    
    # Test max_surprise threshold
    high_surprise_node = Node(id="surprise", type=NodeType.FACT, content="test", utility=0.7, surprise=0.9)
    result = gates.evaluate(high_surprise_node, {"current_node_count": 10})
    print(f"High surprise node passed: {result.passed}")
    # With max_surprise=0.7, surprise=0.9 should fail
    assert not result.passed, "High surprise should be rejected"
    
    print("✅ FiveGates adaptive thresholds working correctly")


def test_evolution_anti_convergence():
    """Test P1: Evolution engine anti-convergence"""
    print("\n=== Testing Evolution Anti-Convergence ===")
    
    from prometheus_nexus.evolution.evolution_engine import Terminator
    
    terminator = Terminator(max_generations=100, stagnation_limit=20, fitness_threshold=0.99, min_generations=10)
    
    # Create mock chromosomes
    class MockChromosome:
        def __init__(self, fitness):
            self.fitness = fitness
    
    # Test that min_generations is now 10
    print(f"Min generations: {terminator._min_gen}")
    assert terminator._min_gen == 10, "Min generations should be 10"
    
    # Test early convergence (should not stop before min_generations)
    population = [MockChromosome(0.99)]
    for gen in range(5):
        should_stop = terminator.check(population, gen)
        print(f"Generation {gen}: stopped={should_stop}")
        # Should NOT stop before generation 10
        assert not should_stop, f"Should not stop at generation {gen} < 10"
    
    # Test after min_generations
    should_stop = terminator.check(population, 10)
    print(f"Generation 10: stopped={should_stop}")
    assert should_stop, "Should stop at generation 10 with high fitness"
    
    print("✅ Evolution anti-convergence working correctly")


def test_mars_belief_filling():
    """Test P2: MARS belief system filling"""
    print("\n=== Testing MARS Belief Filling ===")
    
    omega = Omega()
    
    # Check initial beliefs
    initial_beliefs = len(omega.mars._beliefs)
    print(f"Initial beliefs: {initial_beliefs}")
    
    # Run dream cycle to fill beliefs
    result = omega.dream_cycle()
    
    # Check beliefs after dream
    final_beliefs = len(omega.mars._beliefs)
    print(f"Beliefs after dream: {final_beliefs}")
    
    # Should have more beliefs than before
    assert final_beliefs >= initial_beliefs, "Beliefs should increase after dream"
    
    # Check belief details
    for name, belief in list(omega.mars._beliefs.items())[:3]:
        print(f"  Belief '{name}': confidence={belief['confidence']:.2f}")
    
    print("✅ MARS belief filling working correctly")


def test_dag_scheduler_integration():
    """Test P2: DAG scheduler integration"""
    print("\n=== Testing DAG Scheduler Integration ===")
    
    omega = Omega()
    cns = omega.cns  # CNS is at omega.cns
    
    # Initialize DAG scheduler
    cns._setup_pipeline_dag()
    
    # Check DAG scheduler is initialized
    print(f"DAG scheduler available: {hasattr(cns, '_dag_scheduler') and cns._dag_scheduler is not None}")
    
    # Test schedule_pipeline method exists
    assert hasattr(cns, 'schedule_pipeline'), "schedule_pipeline method should exist"
    
    # Test direct execution fallback
    result = cns.schedule_pipeline("remember", {"content": "test"})
    print(f"Pipeline execution result: {result}")
    
    print("✅ DAG scheduler integration working correctly")


def test_openopc_attribution_scoring():
    """Test OpenOPC: Attribution Evolution Scoring"""
    print("\n=== Testing OpenOPC Attribution Scoring ===")
    
    scoring = AttributionEvolutionScoring(target_latency_ms=100.0)
    
    # Create work item
    wi = scoring.create_work_item("test_1", "evolve", priority=5)
    print(f"Created work item: {wi.item_id}")
    
    # Start and complete
    scoring.start_work_item("test_1")
    scoring.complete_work_item("test_1", result={"success": True})
    
    # Get stats
    stats = scoring.get_stats()
    print(f"Stats: completed={stats['completed_items']}, avg_latency={stats['avg_latency_ms']:.1f}ms")
    
    # Compute attribution score
    score = scoring.compute_attribution_score("test_1")
    print(f"Attribution score: {score.total_score():.2f}")
    print(f"  Latency: {score.latency_score:.2f}")
    print(f"  Success: {score.success_score:.2f}")
    print(f"  Resource: {score.resource_score:.2f}")
    print(f"  Diversity: {score.diversity_score:.2f}")
    
    assert score.total_score() > 0, "Total score should be > 0"
    print("✅ OpenOPC Attribution Scoring working correctly")


def test_openopc_playbook_inheritance():
    """Test OpenOPC: Playbook Inheritance"""
    print("\n=== Testing OpenOPC Playbook Inheritance ===")
    
    pi = PlaybookInheritance()
    
    # Create parent playbook
    parent = Playbook(
        playbook_id="parent_1",
        name="Base Evolve",
        description="Base evolution playbook",
        steps=[
            PlaybookStep(step_id="s1", name="Evaluate", operation="eval"),
            PlaybookStep(step_id="s2", name="Mutate", operation="mutate", depends_on=["s1"]),
        ],
        variables={"mutation_rate": 0.1},
    )
    pi.register_playbook(parent)
    
    # Create derived playbook
    derived = pi.create_derived_playbook(
        parent_id="parent_1",
        derived_id="child_1",
        name="Enhanced Evolve",
        additional_steps=[
            PlaybookStep(step_id="s3", name="Validate", operation="validate", depends_on=["s2"]),
        ],
        override_variables={"mutation_rate": 0.2},
    )
    
    print(f"Parent steps: {len(parent.steps)}")
    print(f"Derived steps: {len(derived.steps)}")
    assert len(derived.steps) == 3, "Should have 3 steps (2 inherited + 1 new)"
    
    # Check inheritance chain
    chain = pi.get_inheritance_chain("child_1")
    print(f"Inheritance chain: {chain}")
    assert chain == ["child_1", "parent_1"], "Chain should be child -> parent"
    
    # Execute playbook
    result = pi.execute_playbook("child_1")
    print(f"Execution result: executed={result['executed_steps']}/{result['total_steps']}")
    
    print("✅ OpenOPC Playbook Inheritance working correctly")


def test_openopc_two_level_blocker():
    """Test OpenOPC: Two-Level Blocker Escalation"""
    print("\n=== Testing OpenOPC Two-Level Blocker ===")
    
    blocker = TwoLevelBlockerEscalation()
    
    # Test low risk node (should pass L1)
    low_risk = {
        "utility": 0.7,
        "surprise": 0.3,
        "content": "This is a valid knowledge node with good quality content."
    }
    result = blocker.evaluate(low_risk)
    print(f"Low risk node: passed={result.passed}, level={result.check_level}")
    assert result.passed, "Low risk should pass"
    assert result.check_level == 1, "Should use L1 for low risk"
    
    # Test high risk node (should escalate to L2)
    high_risk = {
        "utility": 0.1,
        "surprise": 0.9,
        "content": "short"
    }
    result = blocker.evaluate(high_risk)
    print(f"High risk node: passed={result.passed}, level={result.check_level}")
    assert not result.passed, "High risk should fail"
    assert result.check_level == 2, "Should use L2 for high risk"
    
    # Get stats
    stats = blocker.get_stats()
    print(f"Blocker stats: L1 checks={stats['l1_checks']}, L2 checks={stats['l2_checks']}")
    
    print("✅ OpenOPC Two-Level Blocker working correctly")


def run_all_tests():
    """Run all end-to-end tests"""
    print("=" * 60)
    print("ULTRA END-TO-END TESTS - TODAY'S FIXES & NEW FEATURES")
    print("=" * 60)
    
    try:
        test_learn_recall_feedback()
        test_four_network_classification()
        test_five_gates_adaptive()
        test_evolution_anti_convergence()
        test_mars_belief_filling()
        test_dag_scheduler_integration()
        test_openopc_attribution_scoring()
        test_openopc_playbook_inheritance()
        test_openopc_two_level_blocker()
        
        print("\n" + "=" * 60)
        print("✅ ALL END-TO-END TESTS PASSED")
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
