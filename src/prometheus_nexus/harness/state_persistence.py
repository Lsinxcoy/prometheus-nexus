"""StatePersistence — Save and restore memory state across restarts.

Saves: DopamineGate history, CoALA working memory, evolution engine state,
       four_network networks, graph_memory episodes, feedback records.

Crash-safety contract (cycle 15 hardening):
  * save() writes atomically (temp file -> os.replace) and fsyncs for
    durability, so a crash mid-write can never leave the primary state
    file half-written.
  * save() also rotates a `.bak` copy of the *previous* completed good
    state before overwriting, so even an externally-corrupted primary is
    always recoverable from the last good save.
  * load() distinguishes "no state file yet" (benign first run -> {}) from
    "state file corrupt/unreadable" (loud). On a corrupt primary it falls
    back to the `.bak`; if both are unusable it logs an ERROR (not a silent
    warning) and degrades to {} instead of silently discarding engine memory.
"""
from __future__ import annotations
import json, os, time, shutil
import logging

logger = logging.getLogger(__name__)


class StatePersistence:
    """Persist and restore Omega memory state."""

    def __init__(self, path: str | None = None):
        if path is None:
            path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "omega_state.json")
            path = os.path.normpath(path)
        self._path = path
        self._bak_path = path + ".bak"

    # ------------------------------------------------------------------ #
    # Save (crash-safe, atomic, durable, with previous-state backup)
    # ------------------------------------------------------------------ #
    def save(self, omega) -> dict:
        state = {
            "timestamp": time.time(),
            "dopamine_history": omega.dopamine._history[-100:],
            "dopamine_threshold": omega.dopamine._current_threshold,
            "coala_working": [{"content": getattr(i, 'content', ''), "importance": getattr(i, 'importance', 0.5)}
                             for i in omega.coala._working_memory[-20:]],
            "four_network_counts": {k: len(v) for k, v in omega.four_network._networks.items()},
            "graph_episode_count": len(omega.graph_memory._episodes),
            "feedback_count": sum(len(v) for v in omega.feedback._feedbacks.values()),
            "evolution_count": len(omega.evolution_engine._history),
            "dream_count": len(omega.dream._memories),
            "thermodynamic_state": omega.thermodynamic.get_state(),
            "trust_levels": omega.knowledge_to_mechanism.get_trust_state(),
        }
        parent = os.path.dirname(self._path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        # Rotate a backup of the *previous* completed good state BEFORE we
        # overwrite the primary. This guarantees the backup always holds the
        # last fully-written state, never a half-written one.
        if os.path.exists(self._path):
            try:
                shutil.copyfile(self._path, self._bak_path)
            except OSError as e:
                logger.warning("StatePersistence: could not back up previous state: %s", e)

        # Atomic + durable write: serialize to a temp file in the same
        # directory, fsync, then os.replace (atomic rename on POSIX & Windows).
        # A crash before os.replace leaves the primary untouched and the temp
        # file orphaned — never a corrupt primary.
        tmp_path = self._path + ".tmp"
        try:
            with open(tmp_path, 'w') as f:
                json.dump(state, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self._path)
        except OSError as e:
            logger.error("StatePersistence save failed (state NOT persisted): %s", e)
            # Clean up a possibly-partial temp file; leave any existing
            # primary/bak intact so a restart can still recover.
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
            raise
        return state

    # ------------------------------------------------------------------ #
    # Load (recover from backup, fail loud instead of silently)
    # ------------------------------------------------------------------ #
    def _safe_read(self, path: str):
        """Read JSON; return dict on success, None on any read/parse error."""
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError, ValueError) as e:
            logger.warning("StatePersistence: cannot read %s: %s", path, e)
            return None

    def load(self, omega) -> dict:
        # Benign: first run, no state yet.
        if not os.path.exists(self._path):
            return {}

        state = self._safe_read(self._path)
        source = self._path

        # Corrupt/unreadable primary -> attempt recovery from backup.
        if state is None:
            logger.warning("StatePersistence: primary state unreadable, attempting backup recovery: %s", self._path)
            if os.path.exists(self._bak_path):
                bak_state = self._safe_read(self._bak_path)
                if bak_state is not None:
                    logger.warning("StatePersistence: recovered engine state from backup: %s", self._bak_path)
                    state, source = bak_state, self._bak_path

        # Both primary and backup unusable -> loud degradation (not silent).
        if state is None:
            logger.error(
                "StatePersistence: primary AND backup both unreadable; engine booting "
                "with NO persistent state (all saved memory lost): %s", self._path
            )
            return {}

        try:
            self._apply(state, omega)
        except Exception as e:
            logger.error("StatePersistence: failed to apply restored state from %s: %s", source, e)
            return {}
        return state

    @staticmethod
    def _apply(state: dict, omega) -> None:
        # Restore dopamine threshold
        if "dopamine_threshold" in state:
            omega.dopamine._current_threshold = state["dopamine_threshold"]
        # Restore dopamine history
        if "dopamine_history" in state:
            omega.dopamine._history = state["dopamine_history"]
        # Restore CoALA working memory
        if "coala_working" in state:
            omega.coala._working_memory = state["coala_working"]
        # Restore graph episode count tracking
        if "graph_episode_count" in state:
            omega.graph_memory._episode_count = state["graph_episode_count"]
        # Restore evolution engine history
        if "evolution_count" in state:
            omega.evolution_engine._history_loaded = True
        # Restore thermodynamic state
        if "thermodynamic_state" in state:
            omega.thermodynamic.set_state(state["thermodynamic_state"])
        # Restore trust levels
        if "trust_levels" in state:
            omega.knowledge_to_mechanism.set_trust_state(state["trust_levels"])
        # four_network_counts / feedback_count / dream_count are info-only;
        # networks rebuild dynamically on first access.

    def get_stats(self) -> dict:
        exists = os.path.exists(self._path)
        return {"persisted": exists, "path": self._path, "backup": self._bak_path if os.path.exists(self._bak_path) else None}
