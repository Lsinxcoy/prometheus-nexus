"""Tests for OwnerHarmTrustBoundary — arXiv 2606.04704."""
from __future__ import annotations

import pytest

from prometheus_nexus.safety.owner_harm import OwnerHarmTrustBoundary


class TestOwnerHarmTrustBoundary:
    """Test suite for OwnerHarmTrustBoundary."""

    # ------------------------------------------------------------------
    # 1. Register owner → same owner can access
    # ------------------------------------------------------------------

    def test_owner_can_access_own_node(self):
        """After registering an owner, the same owner can access the node."""
        ohtb = OwnerHarmTrustBoundary()

        ohtb.register_owner("node_1", "agent_alpha")
        result = ohtb.check_access("node_1", "agent_alpha")

        assert result["allowed"] is True
        assert result["owner"] == "agent_alpha"
        assert result["requester"] == "agent_alpha"
        assert result["reason"] == "requester is the owner"

    # ------------------------------------------------------------------
    # 2. Different owner CANNOT access
    # ------------------------------------------------------------------

    def test_different_owner_denied(self):
        """A different owner is denied access to another's node."""
        ohtb = OwnerHarmTrustBoundary()

        ohtb.register_owner("node_1", "agent_alpha")
        result = ohtb.check_access("node_1", "agent_beta")

        assert result["allowed"] is False
        assert result["owner"] == "agent_alpha"
        assert result["requester"] == "agent_beta"

    # ------------------------------------------------------------------
    # 3. System owner can access anything
    # ------------------------------------------------------------------

    def test_system_can_access_any_node(self):
        """The 'system' owner bypasses all trust checks."""
        ohtb = OwnerHarmTrustBoundary()

        ohtb.register_owner("node_1", "agent_alpha")
        result = ohtb.check_access("node_1", "system")

        assert result["allowed"] is True
        assert result["reason"] == "system bypasses trust boundaries"

    def test_system_can_access_unowned_node(self):
        """System can also access nodes that have no registered owner."""
        ohtb = OwnerHarmTrustBoundary()

        result = ohtb.check_access("unregistered_node", "system")

        assert result["allowed"] is True
        assert result["owner"] == "system"

    # ------------------------------------------------------------------
    # 4. Trust grant → grantee now can access
    # ------------------------------------------------------------------

    def test_trust_grant_allows_access(self):
        """After grantor trusts grantee, grantee can access the node."""
        ohtb = OwnerHarmTrustBoundary()

        ohtb.register_owner("node_1", "agent_alpha")
        ohtb.register_trust("agent_alpha", "agent_beta")

        result = ohtb.check_access("node_1", "agent_beta")

        assert result["allowed"] is True
        assert result["reason"] == "owner agent_alpha trusts agent_beta"

    def test_trust_grant_returns_correct_dict(self):
        """register_trust returns the expected structure."""
        ohtb = OwnerHarmTrustBoundary()

        result = ohtb.register_trust("alice", "bob")

        assert result["trust_granted"] is True
        assert result["grantor"] == "alice"
        assert result["grantee"] == "bob"

    # ------------------------------------------------------------------
    # 5. Revoke trust → grantee cannot access
    # ------------------------------------------------------------------

    def test_revoke_trust_denies_access(self):
        """After trust is revoked, grantee can no longer access."""
        ohtb = OwnerHarmTrustBoundary()

        ohtb.register_owner("node_1", "agent_alpha")
        ohtb.register_trust("agent_alpha", "agent_beta")

        # Access works with trust
        assert ohtb.check_access("node_1", "agent_beta")["allowed"] is True

        # Revoke and retry
        ohtb.revoke_trust("agent_alpha", "agent_beta")
        result = ohtb.check_access("node_1", "agent_beta")

        assert result["allowed"] is False
        assert "does not have trust" in result["reason"]

    def test_revoke_trust_returns_correct_dict(self):
        """revoke_trust returns the expected structure."""
        ohtb = OwnerHarmTrustBoundary()

        ohtb.register_trust("alice", "bob")
        result = ohtb.revoke_trust("alice", "bob")

        assert result["trust_revoked"] is True
        assert result["grantor"] == "alice"
        assert result["grantee"] == "bob"

    def test_revoke_nonexistent_trust_does_not_raise(self):
        """Revoking a trust that does not exist is a no-op."""
        ohtb = OwnerHarmTrustBoundary()

        result = ohtb.revoke_trust("alice", "bob")

        assert result["trust_revoked"] is True

    # ------------------------------------------------------------------
    # 6. Owner stats
    # ------------------------------------------------------------------

    def test_owner_stats_empty(self):
        """Fresh instance reports zero counts."""
        ohtb = OwnerHarmTrustBoundary()
        stats = ohtb.get_owners_stats()

        assert stats["total_owners"] == 0
        assert stats["total_artifacts"] == 0
        assert stats["trust_relationships"] == 0
        assert stats["violation_count"] == 0

    def test_owner_stats_after_registrations(self):
        """Stats reflect registered owners, artifacts, and trusts."""
        ohtb = OwnerHarmTrustBoundary()

        ohtb.register_owner("node_1", "agent_alpha")
        ohtb.register_owner("node_2", "agent_alpha")
        ohtb.register_owner("node_3", "agent_beta")
        ohtb.register_trust("agent_alpha", "agent_beta")
        ohtb.register_trust("agent_beta", "agent_alpha")

        stats = ohtb.get_owners_stats()

        assert stats["total_owners"] == 2
        assert stats["total_artifacts"] == 3
        assert stats["trust_relationships"] == 2
        assert stats["violation_count"] == 0

    # ------------------------------------------------------------------
    # 7. Boundary violations recorded and retrievable
    # ------------------------------------------------------------------

    def test_violations_recorded_on_denied_access(self):
        """Denied access attempts are logged as boundary violations."""
        ohtb = OwnerHarmTrustBoundary()

        ohtb.register_owner("node_1", "agent_alpha")

        # Attempt access from non-owner
        ohtb.check_access("node_1", "intruder")
        ohtb.check_access("node_1", "another_intruder")

        violations = ohtb.get_boundary_violations()
        assert len(violations) == 2

        # Each violation should have the right keys
        for v in violations:
            assert "node_id" in v
            assert "owner" in v
            assert "requester" in v
            assert "reason" in v

        assert violations[0]["requester"] == "intruder"
        assert violations[1]["requester"] == "another_intruder"

    def test_violations_respect_limit(self):
        """get_boundary_violations returns at most *limit* entries."""
        ohtb = OwnerHarmTrustBoundary()

        ohtb.register_owner("node_1", "agent_alpha")
        for i in range(10):
            ohtb.check_access("node_1", f"intruder_{i}")

        assert len(ohtb.get_boundary_violations(limit=3)) == 3
        assert len(ohtb.get_boundary_violations(limit=99)) == 10

    def test_violations_increment_stats(self):
        """Violation count is reflected in get_owners_stats()."""
        ohtb = OwnerHarmTrustBoundary()

        ohtb.register_owner("node_1", "agent_alpha")
        assert ohtb.get_owners_stats()["violation_count"] == 0

        ohtb.check_access("node_1", "intruder")
        assert ohtb.get_owners_stats()["violation_count"] == 1

        ohtb.check_access("node_1", "another_intruder")
        assert ohtb.get_owners_stats()["violation_count"] == 2

    # ------------------------------------------------------------------
    # 8. Edge cases
    # ------------------------------------------------------------------

    def test_unregistered_node_defaults_to_system(self):
        """An unregistered node has the default 'system' owner."""
        ohtb = OwnerHarmTrustBoundary()

        result = ohtb.check_access("nonexistent", "some_agent")

        assert result["allowed"] is False
        assert result["owner"] == "system"

    def test_register_owner_overwrites_previous(self):
        """Registering a new owner for the same node overwrites the old one."""
        ohtb = OwnerHarmTrustBoundary()

        ohtb.register_owner("node_1", "agent_alpha")
        ohtb.register_owner("node_1", "agent_beta")

        result = ohtb.check_access("node_1", "agent_alpha")
        assert result["allowed"] is False

        result = ohtb.check_access("node_1", "agent_beta")
        assert result["allowed"] is True

    def test_register_owner_returns_correct_dict(self):
        """register_owner returns the expected structure."""
        ohtb = OwnerHarmTrustBoundary()

        result = ohtb.register_owner("node_x", "alice")

        assert result["registered"] is True
        assert result["owner"] == "alice"
