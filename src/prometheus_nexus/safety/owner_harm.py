"""Owner-Harm Trust Boundary — Multi-agent memory access control.

Every knowledge artifact has an "owner" (the agent/system that created it).
Operations that cross trust boundaries (e.g. using memory from agent A while
operating as agent B) require explicit permission. This prevents:

- Cross-contamination: memory from one agent contaminating another
- Hallucination transfer: false beliefs propagating across agents
- Authority confusion: one agent speaking with another's epistemic authority

This module implements trust-boundary enforcement originally derived from
the Owner-Harm concept in agent safety literature. The conceptual model
draws on common patterns from multi-agent security and access control.

Usage::

    ohtb = OwnerHarmTrustBoundary()
    ohtb.register_owner("node_1", "agent_alpha")
    result = ohtb.check_access("node_1", "agent_beta")  # denied
    result = ohtb.check_access("node_1", "agent_alpha")  # allowed
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class OwnerHarmTrustBoundary:
    """Trust-boundary enforcement for multi-agent memory access.

    Each memory/knowledge artifact (node) is owned by exactly one agent.
    Cross-owner access requires explicit trust grants. The ``system`` owner
    is a universal accessor that bypasses all checks.

    State
    -----
    _owners : dict[str, str]
        node_id → owner_id  mapping.
    _trust_matrix : dict[str, set[str]]
        owner_id → set of trusted owner_ids.
    _boundary_violations : list[dict]
        Chronological history of denied access attempts.
    _default_owner : str
        Fallback owner for unregistered nodes (default ``"system"``).
    _cross_boundary_threshold : int
        Violations before automatic action (default ``3``).
    """

    def __init__(self, default_owner: str = "system",
                 cross_boundary_threshold: int = 3):
        self._owners: dict[str, str] = {}
        self._trust_matrix: dict[str, set[str]] = {}
        self._boundary_violations: list[dict] = []
        self._default_owner: str = default_owner
        self._cross_boundary_threshold: int = cross_boundary_threshold
        # violation 持久化: 跨重启不丢, 便于监控定性良性/恶性
        import os
        self._viol_log_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "archive", "owner_harm_violations.json")
        self._viol_max_keep = 500

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_owner(self, node_id: str, owner_id: str) -> dict:
        """Register *owner_id* as the owner of *node_id*.

        Returns ``{"registered": True, "owner": owner_id}``.
        """
        self._owners[node_id] = owner_id
        logger.debug("Owner-Harm: registered node %s → owner %s", node_id, owner_id)
        return {"registered": True, "owner": owner_id}

    def register_trust(self, grantor: str, grantee: str) -> dict:
        """*grantor* grants trust to *grantee* to access its artifacts.

        Returns ``{"trust_granted": True, "grantor": grantor, "grantee": grantee}``.
        """
        if grantor not in self._trust_matrix:
            self._trust_matrix[grantor] = set()
        self._trust_matrix[grantor].add(grantee)
        logger.debug("Owner-Harm: %s trusts %s", grantor, grantee)
        return {"trust_granted": True, "grantor": grantor, "grantee": grantee}

    def revoke_trust(self, grantor: str, grantee: str) -> dict:
        """Revoke previously granted trust from *grantor* to *grantee*.

        Returns ``{"trust_revoked": True, "grantor": grantor, "grantee": grantee}``.
        """
        trusts = self._trust_matrix.get(grantor)
        if trusts and grantee in trusts:
            trusts.discard(grantee)
            logger.debug("Owner-Harm: %s revoked trust from %s", grantor, grantee)
        return {"trust_revoked": True, "grantor": grantor, "grantee": grantee}

    def check_access(self, node_id: str, requester: str) -> dict:
        """Check whether *requester* may access *node_id*'s content.

        Access is allowed if one of:
        - *requester* is the node's owner
        - The owner has granted trust to *requester*
        - *requester* is ``"system"`` (universal accessor)

        Returns ``{"allowed": bool, "owner": str, "requester": str,
        "reason": str}``. Denied attempts are recorded as boundary
        violations.
        """
        owner = self._owners.get(node_id, self._default_owner)

        # -- Allowed cases ---------------------------------------------------
        if requester == owner:
            return {
                "allowed": True,
                "owner": owner,
                "requester": requester,
                "reason": "requester is the owner",
            }

        if requester == "system":
            return {
                "allowed": True,
                "owner": owner,
                "requester": requester,
                "reason": "system bypasses trust boundaries",
            }

        if owner in self._trust_matrix and requester in self._trust_matrix[owner]:
            return {
                "allowed": True,
                "owner": owner,
                "requester": requester,
                "reason": f"owner {owner} trusts {requester}",
            }

        # -- Denied — record violation ---------------------------------------
        import time as _time
        violation = {
            "ts": _time.time(),
            "node_id": node_id,
            "owner": owner,
            "requester": requester,
            "reason": f"{requester} does not have trust from owner {owner}",
        }
        self._boundary_violations.append(violation)
        self._persist_violation(violation)
        logger.warning(
            "Owner-Harm boundary violation: %s tried to access %s (owned by %s)",
            requester, node_id, owner,
        )

        # Auto-trigger threshold warning
        if len(self._boundary_violations) >= self._cross_boundary_threshold:
            logger.warning(
                "Owner-Harm: boundary violation threshold reached "
                "(%d ≥ %d)",
                len(self._boundary_violations),
                self._cross_boundary_threshold,
            )

        return {
            "allowed": False,
            "owner": owner,
            "requester": requester,
            "reason": violation["reason"],
        }

    def get_owners_stats(self) -> dict:
        """Return summary statistics about owners and trust.

        Returns ``{"total_owners": int, "total_artifacts": int,
        "trust_relationships": int, "violation_count": int}``.
        violation_count 含内存 + 持久化累计 (跨重启不丢).
        """
        unique_owners = set(self._owners.values())
        trust_relationships = sum(len(trusted) for trusted in self._trust_matrix.values())
        # 内存 + 持久化文件累计
        persisted = 0
        try:
            import os, json
            if os.path.exists(self._viol_log_path):
                persisted = len(json.load(open(self._viol_log_path, encoding="utf-8")))
        except Exception:
            persisted = 0
        return {
            "total_owners": len(unique_owners),
            "total_artifacts": len(self._owners),
            "trust_relationships": trust_relationships,
            "violation_count": persisted,
        }

    def _persist_violation(self, violation: dict) -> None:
        """追加 violation 到 archive/owner_harm_violations.json (跨重启持久化)."""
        try:
            import os, json
            os.makedirs(os.path.dirname(self._viol_log_path), exist_ok=True)
            buf = []
            if os.path.exists(self._viol_log_path):
                try:
                    buf = json.load(open(self._viol_log_path, encoding="utf-8"))
                except Exception:
                    buf = []
            buf.append(violation)
            if len(buf) > self._viol_max_keep:
                buf = buf[-self._viol_max_keep:]
            json.dump(buf, open(self._viol_log_path, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug("Owner-Harm persist violation failed: %s", e)

    def get_boundary_violations(self, limit: int = 10) -> list[dict]:
        """Return the most recent boundary violation attempts, up to *limit*."""
        return list(self._boundary_violations[-limit:])

    def flag_suspicious(self, artifact_id: str, reason: str, details: list[str]) -> dict:
        """Flag an artifact as suspicious (e.g. potential memory poisoning).

        Used by MPBench/Sleeper/Trojan Hippo defenses to mark content
        that may contain trigger keywords or injection payloads.

        Args:
            artifact_id: The node ID or content identifier.
            reason: Classification of the suspicion (e.g. 'trigger_keywords').
            details: Specific trigger items found.

        Returns: {"flagged": True, "artifact_id": str, "reason": str}
        """
        logger.warning("Owner-Harm: flagged %s as suspicious: %s (%s)",
                       artifact_id, reason, details)
        if not hasattr(self, '_suspicious_flags'):
            self._suspicious_flags = []
        self._suspicious_flags.append({
            "artifact_id": artifact_id,
            "reason": reason,
            "details": details,
        })
        return {"flagged": True, "artifact_id": artifact_id, "reason": reason}
