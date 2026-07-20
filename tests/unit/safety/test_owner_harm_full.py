"""Tests for OwnerHarmTrustBoundary — 100% coverage target.

Implements trust-boundary enforcement for multi-agent memory access control.
"""
import pytest
from prometheus_nexus.safety.owner_harm import OwnerHarmTrustBoundary


class TestInit:
    """Test initialization."""

    def test_init_default(self):
        ohtb = OwnerHarmTrustBoundary()
        assert ohtb._owners == {}
        assert ohtb._trust_matrix == {}
        assert ohtb._boundary_violations == []
        assert ohtb._default_owner == "system"
        assert ohtb._cross_boundary_threshold == 3

    def test_init_custom_default_owner(self):
        ohtb = OwnerHarmTrustBoundary(default_owner="admin")
        assert ohtb._default_owner == "admin"

    def test_init_custom_threshold(self):
        ohtb = OwnerHarmTrustBoundary(cross_boundary_threshold=5)
        assert ohtb._cross_boundary_threshold == 5

    def test_init_both_params(self):
        ohtb = OwnerHarmTrustBoundary(default_owner="root", cross_boundary_threshold=10)
        assert ohtb._default_owner == "root"
        assert ohtb._cross_boundary_threshold == 10


class TestRegisterOwner:
    """Test register_owner method."""

    def test_register_owner_basic(self):
        ohtb = OwnerHarmTrustBoundary()
        result = ohtb.register_owner("node_1", "agent_alpha")
        assert result["registered"] is True
        assert result["owner"] == "agent_alpha"
        assert ohtb._owners["node_1"] == "agent_alpha"

    def test_register_owner_multiple(self):
        ohtb = OwnerHarmTrustBoundary()
        ohtb.register_owner("node_1", "agent_alpha")
        ohtb.register_owner("node_2", "agent_beta")
        ohtb.register_owner("node_3", "agent_alpha")
        assert len(ohtb._owners) == 3
        assert ohtb._owners["node_1"] == "agent_alpha"
        assert ohtb._owners["node_2"] == "agent_beta"
        assert ohtb._owners["node_3"] == "agent_alpha"

    def test_register_owner_overwrite(self):
        ohtb = OwnerHarmTrustBoundary()
        ohtb.register_owner("node_1", "agent_alpha")
        result = ohtb.register_owner("node_1", "agent_beta")
        assert result["owner"] == "agent_beta"
        assert ohtb._owners["node_1"] == "agent_beta"

    def test_register_owner_system(self):
        ohtb = OwnerHarmTrustBoundary()
        result = ohtb.register_owner("node_1", "system")
        assert result["registered"] is True
        assert result["owner"] == "system"


class TestRegisterTrust:
    """Test register_trust method."""

    def test_register_trust_basic(self):
        ohtb = OwnerHarmTrustBoundary()
        result = ohtb.register_trust("agent_alpha", "agent_beta")
        assert result["trust_granted"] is True
        assert result["grantor"] == "agent_alpha"
        assert result["grantee"] == "agent_beta"
        assert "agent_beta" in ohtb._trust_matrix["agent_alpha"]

    def test_register_trust_creates_entry(self):
        ohtb = OwnerHarmTrustBoundary()
        ohtb.register_trust("agent_alpha", "agent_beta")
        assert "agent_alpha" in ohtb._trust_matrix

    def test_register_trust_multiple_grantees(self):
        ohtb = OwnerHarmTrustBoundary()
        ohtb.register_trust("agent_alpha", "agent_beta")
        ohtb.register_trust("agent_alpha", "agent_gamma")
        assert len(ohtb._trust_matrix["agent_alpha"]) == 2

    def test_register_trust_duplicate(self):
        ohtb = OwnerHarmTrustBoundary()
        ohtb.register_trust("agent_alpha", "agent_beta")
        result = ohtb.register_trust("agent_alpha", "agent_beta")
        assert result["trust_granted"] is True
        # Should not duplicate
        assert len(ohtb._trust_matrix["agent_alpha"]) == 1

    def test_register_trust_bidirectional(self):
        ohtb = OwnerHarmTrustBoundary()
        ohtb.register_trust("agent_alpha", "agent_beta")
        ohtb.register_trust("agent_beta", "agent_alpha")
        assert "agent_beta" in ohtb._trust_matrix["agent_alpha"]
        assert "agent_alpha" in ohtb._trust_matrix["agent_beta"]


class TestRevokeTrust:
    """Test revoke_trust method."""

    def test_revoke_trust_existing(self):
        ohtb = OwnerHarmTrustBoundary()
        ohtb.register_trust("agent_alpha", "agent_beta")
        result = ohtb.revoke_trust("agent_alpha", "agent_beta")
        assert result["trust_revoked"] is True
        assert "agent_beta" not in ohtb._trust_matrix["agent_alpha"]

    def test_revoke_trust_nonexistent(self):
        ohtb = OwnerHarmTrustBoundary()
        result = ohtb.revoke_trust("agent_alpha", "agent_beta")
        assert result["trust_revoked"] is True
        # Should not raise error

    def test_revoke_trust_grantor_not_in_matrix(self):
        ohtb = OwnerHarmTrustBoundary()
        result = ohtb.revoke_trust("agent_alpha", "agent_beta")
        assert result["trust_revoked"] is True

    def test_revoke_trust_partial(self):
        ohtb = OwnerHarmTrustBoundary()
        ohtb.register_trust("agent_alpha", "agent_beta")
        ohtb.register_trust("agent_alpha", "agent_gamma")
        ohtb.revoke_trust("agent_alpha", "agent_beta")
        assert "agent_beta" not in ohtb._trust_matrix["agent_alpha"]
        assert "agent_gamma" in ohtb._trust_matrix["agent_alpha"]


class TestCheckAccess:
    """Test check_access method."""

    def test_check_access_owner_is_requester(self):
        ohtb = OwnerHarmTrustBoundary()
        ohtb.register_owner("node_1", "agent_alpha")
        result = ohtb.check_access("node_1", "agent_alpha")
        assert result["allowed"] is True
        assert result["reason"] == "requester is the owner"

    def test_check_access_system_bypass(self):
        ohtb = OwnerHarmTrustBoundary()
        ohtb.register_owner("node_1", "agent_alpha")
        result = ohtb.check_access("node_1", "system")
        assert result["allowed"] is True
        assert result["reason"] == "system bypasses trust boundaries"

    def test_check_access_trust_granted(self):
        ohtb = OwnerHarmTrustBoundary()
        ohtb.register_owner("node_1", "agent_alpha")
        ohtb.register_trust("agent_alpha", "agent_beta")
        result = ohtb.check_access("node_1", "agent_beta")
        assert result["allowed"] is True
        assert "trusts" in result["reason"]

    def test_check_access_denied_no_trust(self):
        ohtb = OwnerHarmTrustBoundary()
        ohtb.register_owner("node_1", "agent_alpha")
        result = ohtb.check_access("node_1", "agent_beta")
        assert result["allowed"] is False
        assert "does not have trust" in result["reason"]

    def test_check_access_unregistered_node_default_owner(self):
        ohtb = OwnerHarmTrustBoundary()
        result = ohtb.check_access("unknown_node", "agent_beta")
        assert result["allowed"] is False
        assert result["owner"] == "system"

    def test_check_access_unregistered_node_system_requester(self):
        ohtb = OwnerHarmTrustBoundary()
        result = ohtb.check_access("unknown_node", "system")
        assert result["allowed"] is True

    def test_check_access_records_violation(self):
        ohtb = OwnerHarmTrustBoundary()
        ohtb.register_owner("node_1", "agent_alpha")
        ohtb.check_access("node_1", "agent_beta")
        assert len(ohtb._boundary_violations) == 1

    def test_check_access_threshold_warning(self):
        ohtb = OwnerHarmTrustBoundary(cross_boundary_threshold=2)
        ohtb.register_owner("node_1", "agent_alpha")
        ohtb.check_access("node_1", "agent_beta")
        ohtb.check_access("node_1", "agent_gamma")
        assert len(ohtb._boundary_violations) == 2

    def test_check_access_returns_owner_info(self):
        ohtb = OwnerHarmTrustBoundary()
        ohtb.register_owner("node_1", "agent_alpha")
        result = ohtb.check_access("node_1", "agent_beta")
        assert result["owner"] == "agent_alpha"
        assert result["requester"] == "agent_beta"

    def test_check_access_trust_chain(self):
        ohtb = OwnerHarmTrustBoundary()
        ohtb.register_owner("node_1", "agent_alpha")
        ohtb.register_trust("agent_alpha", "agent_beta")
        ohtb.register_trust("agent_alpha", "agent_gamma")
        result1 = ohtb.check_access("node_1", "agent_beta")
        result2 = ohtb.check_access("node_1", "agent_gamma")
        assert result1["allowed"] is True
        assert result2["allowed"] is True


class TestGetOwnersStats:
    """Test get_owners_stats method."""

    def test_get_owners_stats_empty(self):
        ohtb = OwnerHarmTrustBoundary()
        stats = ohtb.get_owners_stats()
        assert stats["total_owners"] == 0
        assert stats["total_artifacts"] == 0
        assert stats["trust_relationships"] == 0
        assert stats["violation_count"] == 0

    def test_get_owners_stats_with_data(self):
        ohtb = OwnerHarmTrustBoundary()
        ohtb.register_owner("node_1", "agent_alpha")
        ohtb.register_owner("node_2", "agent_alpha")
        ohtb.register_owner("node_3", "agent_beta")
        ohtb.register_trust("agent_alpha", "agent_beta")
        ohtb.register_trust("agent_alpha", "agent_gamma")
        # agent_gamma is NOT trusted by agent_beta, so this should be denied
        ohtb.check_access("node_3", "agent_gamma")  # node_3 owned by agent_beta

        stats = ohtb.get_owners_stats()
        assert stats["total_owners"] == 2
        assert stats["total_artifacts"] == 3
        assert stats["trust_relationships"] == 2
        assert stats["violation_count"] == 1

    def test_get_owners_stats_single_owner(self):
        ohtb = OwnerHarmTrustBoundary()
        ohtb.register_owner("node_1", "agent_alpha")
        ohtb.register_owner("node_2", "agent_alpha")
        stats = ohtb.get_owners_stats()
        assert stats["total_owners"] == 1
        assert stats["total_artifacts"] == 2


class TestGetBoundaryViolations:
    """Test get_boundary_violations method."""

    def test_get_boundary_violations_empty(self):
        ohtb = OwnerHarmTrustBoundary()
        violations = ohtb.get_boundary_violations()
        assert violations == []

    def test_get_boundary_violations_limit(self):
        ohtb = OwnerHarmTrustBoundary()
        ohtb.register_owner("node_1", "agent_alpha")
        for i in range(5):
            ohtb.check_access("node_1", f"agent_{i}")

        violations = ohtb.get_boundary_violations(limit=3)
        assert len(violations) == 3

    def test_get_boundary_violations_all(self):
        ohtb = OwnerHarmTrustBoundary()
        ohtb.register_owner("node_1", "agent_alpha")
        for i in range(5):
            ohtb.check_access("node_1", f"agent_{i}")

        violations = ohtb.get_boundary_violations(limit=10)
        assert len(violations) == 5

    def test_get_boundary_violations_structure(self):
        ohtb = OwnerHarmTrustBoundary()
        ohtb.register_owner("node_1", "agent_alpha")
        ohtb.check_access("node_1", "agent_beta")

        violations = ohtb.get_boundary_violations()
        assert len(violations) == 1
        v = violations[0]
        assert "node_id" in v
        assert "owner" in v
        assert "requester" in v
        assert "reason" in v


class TestFlagSuspicious:
    """Test flag_suspicious method."""

    def test_flag_suspicious_basic(self):
        ohtb = OwnerHarmTrustBoundary()
        result = ohtb.flag_suspicious(
            "artifact_1",
            "trigger_keywords",
            ["Remember", "transfer"],
        )
        assert result["flagged"] is True
        assert result["artifact_id"] == "artifact_1"
        assert result["reason"] == "trigger_keywords"

    def test_flag_suspicious_creates_flags_list(self):
        ohtb = OwnerHarmTrustBoundary()
        ohtb.flag_suspicious("artifact_1", "reason1", ["detail1"])
        assert hasattr(ohtb, '_suspicious_flags')
        assert len(ohtb._suspicious_flags) == 1

    def test_flag_suspicious_multiple(self):
        ohtb = OwnerHarmTrustBoundary()
        ohtb.flag_suspicious("artifact_1", "reason1", ["detail1"])
        ohtb.flag_suspicious("artifact_2", "reason2", ["detail2"])
        assert len(ohtb._suspicious_flags) == 2

    def test_flag_suspicious_preserves_details(self):
        ohtb = OwnerHarmTrustBoundary()
        details = ["Remember $1000", "password is admin"]
        ohtb.flag_suspicious("artifact_1", "trigger_keywords", details)
        flag = ohtb._suspicious_flags[0]
        assert flag["details"] == details


class TestIntegration:
    """Integration tests for OwnerHarmTrustBoundary."""

    def test_full_workflow(self):
        ohtb = OwnerHarmTrustBoundary()

        # Register owners
        ohtb.register_owner("memory_1", "agent_alpha")
        ohtb.register_owner("memory_2", "agent_beta")

        # Grant trust
        ohtb.register_trust("agent_alpha", "agent_beta")

        # Check access
        r1 = ohtb.check_access("memory_1", "agent_alpha")  # owner
        r2 = ohtb.check_access("memory_1", "agent_beta")   # trusted
        r3 = ohtb.check_access("memory_2", "agent_alpha")  # denied

        assert r1["allowed"] is True
        assert r2["allowed"] is True
        assert r3["allowed"] is False

        # Check stats
        stats = ohtb.get_owners_stats()
        assert stats["total_owners"] == 2
        assert stats["total_artifacts"] == 2
        assert stats["trust_relationships"] == 1
        assert stats["violation_count"] == 1

    def test_system_universal_access(self):
        ohtb = OwnerHarmTrustBoundary()
        ohtb.register_owner("memory_1", "agent_alpha")
        ohtb.register_owner("memory_2", "agent_beta")

        # System can access everything
        r1 = ohtb.check_access("memory_1", "system")
        r2 = ohtb.check_access("memory_2", "system")

        assert r1["allowed"] is True
        assert r2["allowed"] is True

    def test_trust_revocation(self):
        ohtb = OwnerHarmTrustBoundary()
        ohtb.register_owner("memory_1", "agent_alpha")
        ohtb.register_trust("agent_alpha", "agent_beta")

        # Access granted
        r1 = ohtb.check_access("memory_1", "agent_beta")
        assert r1["allowed"] is True

        # Revoke trust
        ohtb.revoke_trust("agent_alpha", "agent_beta")

        # Access denied
        r2 = ohtb.check_access("memory_1", "agent_beta")
        assert r2["allowed"] is False

    def test_violation_tracking(self):
        ohtb = OwnerHarmTrustBoundary()
        ohtb.register_owner("memory_1", "agent_alpha")

        # Create violations
        requesters = ["agent_beta", "agent_gamma", "agent_delta"]
        for r in requesters:
            ohtb.check_access("memory_1", r)

        # Check violations recorded
        violations = ohtb.get_boundary_violations()
        assert len(violations) == 3

        # All should be from different requesters
        violation_requesters = [v["requester"] for v in violations]
        assert set(violation_requesters) == set(requesters)

    def test_default_owner_behavior(self):
        ohtb = OwnerHarmTrustBoundary()

        # Unregistered node defaults to "system"
        r1 = ohtb.check_access("unknown", "some_agent")
        assert r1["owner"] == "system"

        # Custom default owner
        ohtb2 = OwnerHarmTrustBoundary(default_owner="admin")
        r2 = ohtb2.check_access("unknown", "some_agent")
        assert r2["owner"] == "admin"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])