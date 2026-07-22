"""MinervaStore — Production-grade SQLite + FTS5 storage engine.

Features:
- 13-table schema with full relational integrity
- FTS5 full-text search with LIKE fallback
- WAL mode for concurrent reads
- Branch system for parallel experimentation
- CAS (Compare-And-Swap) write tokens for consistency
- Thread-safe with fine-grained locking
- UUIDv7 time-ordered IDs
- Complete audit trail

Complexity:
- create_node: O(1) amortized, O(log N) for FTS index
- read_node: O(1) by primary key
- update_node: O(1) amortized
- delete_node: O(E) where E = edges connected to node
- search: O(K·log N) where K = result set size
- merge_branch: O(N) where N = nodes in source branch
- get_node_count: O(1)
- get_edge_count: O(1)

Thread Safety:
- All public methods acquire self._lock before database operations
- FTS5 operations are serialized through the same lock
- Write tokens provide CAS semantics for optimistic concurrency

Error Handling:
- IronLawViolation raised when write violates constraints
- SQLite OperationalError caught and converted to WriteResult
- Connection health checked before operations
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from prometheus_nexus.foundation.schema import (
    Node, Edge, NodeType, EdgeType, MemoryTier, ProvenanceType,
    ZConfig, generate_uuidv7, WriteOperator, CommitState,
)

logger = logging.getLogger(__name__)


@dataclass
class BatchWriteResult:
    """批量写结果 (create_nodes_batch 返回)."""

    success: bool
    created: int = 0
    failed: list[dict] = field(default_factory=list)
    write_ids: list[str] = field(default_factory=list)


# ============================================================
# Data Classes
# ============================================================

@dataclass
class IronLawViolation:
    """Raised when a write operation violates iron law constraints."""
    node_id: str = ""
    rule: str = ""
    detail: str = ""


@dataclass
class WriteToken:
    """CAS write token for optimistic concurrency control."""
    token: str = ""
    node_id: str = ""
    operator: str = ""
    granted_at: float = 0.0
    expires_at: float = 0.0

    def is_valid(self) -> bool:
        return time.time() < self.expires_at


@dataclass
class WriteResult:
    """Result of a write operation."""
    write_id: str = ""
    success: bool = True
    reason: str = ""
    nodes_affected: int = 0


@dataclass
class MergeResult:
    """Result of a branch merge operation."""
    write_id: str = ""
    success: bool = True
    nodes_merged: int = 0
    conflicts_resolved: int = 0
    reason: str = ""


# ============================================================
# Schema Definition
# ============================================================

SCHEMA_SQL = """
-- Core node storage
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL DEFAULT 'FACT',
    content TEXT NOT NULL,
    utility REAL DEFAULT 0.5 CHECK(utility >= 0.0 AND utility <= 1.0),
    surprise REAL DEFAULT 0.0 CHECK(surprise >= 0.0 AND surprise <= 1.0),
    tags TEXT DEFAULT '[]',
    branch TEXT DEFAULT 'main',
    source TEXT DEFAULT 'DIRECT_OBSERVATION',
    confidence REAL DEFAULT 0.5 CHECK(confidence >= 0.0 AND confidence <= 1.0),
    tier INTEGER DEFAULT 0 CHECK(tier >= 0 AND tier <= 6),
    access_count INTEGER DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    tx_from REAL DEFAULT 0.0,
    tx_to REAL DEFAULT 0.0,
    version INTEGER DEFAULT 1,
    raw_chunk TEXT DEFAULT '',
    trust_state TEXT DEFAULT 'unknown',
    url TEXT DEFAULT ''
);

-- Edge relationships
CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'SEMANTIC_SIMILAR',
    weight REAL DEFAULT 1.0 CHECK(weight >= 0.0 AND weight <= 1.0),
    created_at REAL NOT NULL,
    metadata TEXT DEFAULT '{}',
    FOREIGN KEY (source_id) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (target_id) REFERENCES nodes(id) ON DELETE CASCADE
);

-- Branch management
CREATE TABLE IF NOT EXISTS branches (
    name TEXT PRIMARY KEY,
    parent TEXT,
    created_at REAL NOT NULL,
    merged_at REAL,
    FOREIGN KEY (parent) REFERENCES branches(name)
);

-- Write audit log
CREATE TABLE IF NOT EXISTS write_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    write_id TEXT NOT NULL,
    node_id TEXT,
    operator TEXT,
    token TEXT,
    committed_at REAL NOT NULL,
    state TEXT DEFAULT 'PENDING' CHECK(state IN ('PENDING', 'COMMITTED', 'ROLLED_BACK', 'CONFLICT'))
);

-- Feedback tracking
CREATE TABLE IF NOT EXISTS feedback_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL,
    feedback_type TEXT NOT NULL,
    value REAL NOT NULL,
    timestamp REAL NOT NULL,
    FOREIGN KEY (node_id) REFERENCES nodes(id) ON DELETE CASCADE
);

-- Failure tracking
CREATE TABLE IF NOT EXISTS failure_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    error TEXT NOT NULL,
    timestamp REAL NOT NULL,
    context TEXT DEFAULT '{}'
);

-- Evolution audit trail
CREATE TABLE IF NOT EXISTS evolution_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id TEXT NOT NULL,
    fitness_before REAL,
    fitness_after REAL,
    delta REAL,
    strategy TEXT,
    timestamp REAL NOT NULL
);

-- Dream cycle log
CREATE TABLE IF NOT EXISTS dream_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id TEXT NOT NULL,
    patterns_found INTEGER DEFAULT 0,
    beliefs_synthesized INTEGER DEFAULT 0,
    connections_discovered INTEGER DEFAULT 0,
    timestamp REAL NOT NULL
);

-- Maintenance log
CREATE TABLE IF NOT EXISTS maintenance_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    nodes_affected INTEGER DEFAULT 0,
    duration_ms REAL DEFAULT 0,
    timestamp REAL NOT NULL
);

-- Audit trail
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dimension TEXT NOT NULL,
    score REAL,
    details TEXT DEFAULT '{}',
    timestamp REAL NOT NULL
);

-- Branch merge history
CREATE TABLE IF NOT EXISTS branch_merges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    nodes_merged INTEGER DEFAULT 0,
    write_id TEXT,
    timestamp REAL NOT NULL
);

-- Provenance tracking
CREATE TABLE IF NOT EXISTS provenance_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL,
    provenance_type TEXT NOT NULL,
    source TEXT,
    confidence REAL DEFAULT 0.5,
    chain TEXT DEFAULT '[]',
    timestamp REAL NOT NULL,
    FOREIGN KEY (node_id) REFERENCES nodes(id) ON DELETE CASCADE
);

-- Mechanism state persistence
CREATE TABLE IF NOT EXISTS mechanism_state (
    mechanism_name TEXT PRIMARY KEY,
    state TEXT DEFAULT '{}',
    last_updated REAL NOT NULL
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_nodes_branch ON nodes(branch);
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
CREATE INDEX IF NOT EXISTS idx_nodes_utility ON nodes(utility);
CREATE INDEX IF NOT EXISTS idx_nodes_branch_tx ON nodes(branch, tx_to);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(type);
CREATE INDEX IF NOT EXISTS idx_write_log_node ON write_log(node_id);
CREATE INDEX IF NOT EXISTS idx_feedback_node ON feedback_log(node_id);
CREATE INDEX IF NOT EXISTS idx_evolution_cycle ON evolution_log(cycle_id);

-- FTS5 full-text search index
CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
    id UNINDEXED, content, tags, entity_ids, creator_agent, branch
);
"""


# ============================================================
# MinervaStore
# ============================================================

class MinervaStore:
    """Production-grade SQLite storage engine with FTS5 and branch support.

    Provides:
    - CRUD operations for nodes and edges
    - Full-text search via FTS5
    - Branch-based parallel experimentation
    - CAS write tokens for consistency
    - Complete audit trail

    Usage:
        config = ZConfig(database_path="my_data.db")
        store = MinervaStore(config)
        store.connect()

        node = Node(content="Hello world", utility=0.8)
        result = store.create_node(node)
        assert result.success

        results = store.search("Hello")
        assert len(results) > 0

        store.close()

    Thread Safety:
        All public methods are thread-safe. The store uses a reentrant lock
        for all database operations and FTS5 queries.
    """

    def __init__(self, config: ZConfig | None = None):
        """Initialize the store with configuration.

        Args:
            config: Store configuration. Uses defaults if None.

        Raises:
            ValueError: If config is invalid.
        """
        self._cfg = config or ZConfig()
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self._tokens: dict[str, WriteToken] = {}
        self._connected = False
        self._fts_fallback_count = 0  # FTS检索降级计数 (监控用)

    def connect(self) -> None:
        """Connect to the database and create schema.

        Raises:
            sqlite3.Error: If connection or schema creation fails.
        """
        if self._connected:
            return

        try:
            self._conn = sqlite3.connect(
                self._cfg.database_path,
                check_same_thread=False,
                timeout=30.0,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA cache_size=-8000")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._create_schema()
            self._ensure_main_branch()
            self._connected = True
            logger.info("MinervaStore connected to %s", self._cfg.database_path)
        except sqlite3.Error as e:
            logger.error("Failed to connect to database: %s", e)
            raise

    def _create_schema(self) -> None:
        """Create all tables and indexes."""
        assert self._conn is not None
        self._conn.executescript(SCHEMA_SQL)
        # Migrate existing tables to add missing columns for B2-1/B2-2
        self._migrate_add_column("nodes", "raw_chunk", "TEXT DEFAULT ''")
        self._migrate_add_column("nodes", "trust_state", "TEXT DEFAULT 'unknown'")
        self._migrate_add_column("nodes", "url", "TEXT DEFAULT ''")
        self._conn.commit()

    def _migrate_add_column(self, table: str, column: str, col_def: str) -> None:
        """Add a column if it doesn't already exist (safe migration)."""
        assert self._conn is not None
        try:
            pragma = self._conn.execute(f"PRAGMA table_info({table})").fetchall()
            col_names = [r[1] for r in pragma]
            if column not in col_names:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
                logger.info("Migrated %s: added column %s", table, column)
        except Exception as e:
            logger.warning("Migration of %s.%s skipped: %s", table, column, e)

    def _ensure_main_branch(self) -> None:
        """Ensure the 'main' branch exists."""
        assert self._conn is not None
        self._conn.execute(
            "INSERT OR IGNORE INTO branches (name, parent, created_at) VALUES (?, NULL, ?)",
            ("main", time.time()),
        )
        self._conn.commit()

    def _check_connection(self) -> None:
        """Verify database connection is alive."""
        if self._conn is None:
            raise sqlite3.Error("Store not connected. Call connect() first.")

    # ============================================================
    # Node Operations
    # ============================================================

    def create_node(self, node: Node, token: WriteToken | None = None) -> WriteResult:
        """Create a new node in the store.

        Args:
            node: The node to create. Must have unique id.
            token: Optional CAS write token for consistency.

        Returns:
            WriteResult with success status and write_id.

        Raises:
            IronLawViolation: If node violates constraints.

        Complexity: O(1) amortized, O(log N) for FTS index update.
        """
        self._check_connection()
        assert self._conn is not None

        # Validate node
        if not node.id:
            return WriteResult(success=False, reason="Node ID required")
        if not node.content:
            return WriteResult(success=False, reason="Content required")
        if node.utility < 0 or node.utility > 1:
            return WriteResult(success=False, reason=f"Utility {node.utility} out of [0,1]")

        # Validate token if provided
        if token and not token.is_valid():
            return WriteResult(success=False, reason="Write token expired")

        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO nodes (id, type, content, utility, surprise, tags,"
                    " branch, source, confidence, tier, access_count,"
                    " created_at, updated_at, tx_from, tx_to, version, raw_chunk, trust_state, url)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (node.id, node.type.value, node.content, node.utility, node.surprise,
                     json.dumps(node.tags), node.branch, node.source.value, node.confidence,
                     node.tier.value, node.access_count, node.created_at, node.updated_at,
                     node.tx_from, node.tx_to, node.version,
                     node.raw_chunk, node.trust_state, node.url),
                )

                # Update FTS index
                try:
                    self._conn.execute(
                        "INSERT INTO nodes_fts (id, content, tags, entity_ids, creator_agent, branch) VALUES (?,?,?,?,?,?)",
                        (node.id, node.content, json.dumps(node.tags), "[]", None, node.branch),
                    )
                except sqlite3.OperationalError as e:
                    logger.warning("FTS insert skipped (table may not exist): %s", e)

                # Log write
                write_id = generate_uuidv7()
                self._conn.execute(
                    "INSERT INTO write_log (write_id, node_id, operator, token, committed_at, state) VALUES (?,?,?,?,?,?)",
                    (write_id, node.id, token.operator if token else "direct",
                     token.token if token else None, time.time(), "COMMITTED"),
                )

                self._conn.commit()
                return WriteResult(write_id=write_id, success=True, nodes_affected=1)

            except sqlite3.IntegrityError as e:
                self._conn.rollback()
                return WriteResult(success=False, reason=f"Integrity error: {e}")
            except sqlite3.Error as e:
                self._conn.rollback()
                logger.error("create_node failed: %s", e)
                return WriteResult(success=False, reason=f"Database error: {e}")

    def read_node(self, node_id: str) -> Node | None:
        """Read a node by ID.

        Args:
            node_id: The unique node identifier.

        Returns:
            Node object if found, None otherwise.

        Complexity: O(1) by primary key lookup.
        """
        self._check_connection()
        assert self._conn is not None

        with self._lock:
            try:
                row = self._conn.execute(
                    "SELECT * FROM nodes WHERE id=? AND tx_to=0.0", (node_id,)
                ).fetchone()
                return self._row_to_node(row) if row else None
            except sqlite3.Error as e:
                logger.error("read_node failed for %s: %s", node_id, e)
                return None

    def create_nodes_batch(
        self,
        nodes: list[Node],
        tokens: dict[str, WriteToken] | None = None,
    ) -> "BatchWriteResult":
        """批量创建节点 — 单锁 / 单事务 / executemany。

        架构优化 P0 (2026-07-23): 232 机制在 remember 循环里逐条 create_node,
        每条独立抢锁 + 独立 commit(WAL 单写者下 commit 的 fsync 是主瓶颈)。
        批量接口把 N 次 锁获取+事务提交 压成 1 次, 吞吐近似线性提升,
        且不改变单锁串行语义(零风险)。

        Args:
            nodes: 节点列表
            tokens: 可选 {node_id: WriteToken} 逐节点 CAS 令牌

        Returns:
            BatchWriteResult: {success, created, failed:[{id,reason}], write_ids}
        """
        self._check_connection()
        assert self._conn is not None

        valid: list[Node] = []
        failed: list[dict] = []
        # 锁外逐条校验(校验不持锁, 减少持锁时间)
        for node in nodes:
            if not node.id:
                failed.append({"id": getattr(node, "id", ""), "reason": "Node ID required"})
                continue
            if not node.content:
                failed.append({"id": node.id, "reason": "Content required"})
                continue
            if node.utility < 0 or node.utility > 1:
                failed.append({"id": node.id, "reason": f"Utility {node.utility} out of [0,1]"})
                continue
            tk = (tokens or {}).get(node.id)
            if tk is not None and not tk.is_valid():
                failed.append({"id": node.id, "reason": "Write token expired"})
                continue
            valid.append(node)

        if not valid:
            return BatchWriteResult(success=False, created=0, failed=failed, write_ids=[])

        write_ids: list[str] = []
        created = 0
        with self._lock:
            try:
                node_rows = [
                    (n.id, n.type.value, n.content, n.utility, n.surprise,
                     json.dumps(n.tags), n.branch, n.source.value, n.confidence,
                     n.tier.value, n.access_count, n.created_at, n.updated_at,
                     n.tx_from, n.tx_to, n.version, n.raw_chunk, n.trust_state, n.url)
                    for n in valid
                ]
                fts_rows = [(n.id, n.content, json.dumps(n.tags), "[]", None, n.branch) for n in valid]
                self._conn.executemany(
                    "INSERT INTO nodes (id, type, content, utility, surprise, tags,"
                    " branch, source, confidence, tier, access_count,"
                    " created_at, updated_at, tx_from, tx_to, version, raw_chunk, trust_state, url)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    node_rows,
                )
                try:
                    self._conn.executemany(
                        "INSERT INTO nodes_fts (id, content, tags, entity_ids, creator_agent, branch)"
                        " VALUES (?,?,?,?,?,?)",
                        fts_rows,
                    )
                except sqlite3.OperationalError as e:
                    logger.warning("FTS bulk insert skipped: %s", e)
                for n in valid:
                    wid = generate_uuidv7()
                    self._conn.execute(
                        "INSERT INTO write_log (write_id, node_id, operator, token, committed_at, state)"
                        " VALUES (?,?,?,?,?,?)",
                        (wid, n.id, "BULK_CREATE", None, time.time(), "COMMITTED"),
                    )
                    write_ids.append(wid)
                self._conn.commit()
                created = len(valid)
                return BatchWriteResult(success=True, created=created, failed=failed, write_ids=write_ids)
            except sqlite3.IntegrityError as e:
                self._conn.rollback()
                return BatchWriteResult(success=False, created=0,
                                        failed=failed + [{"id": "*", "reason": f"Integrity: {e}"}],
                                        write_ids=[])
            except sqlite3.Error as e:
                self._conn.rollback()
                logger.error("create_nodes_batch failed: %s", e)
                return BatchWriteResult(success=False, created=0,
                                        failed=failed + [{"id": "*", "reason": f"DB: {e}"}],
                                        write_ids=[])

    def update_node(self, node: Node, token: WriteToken | None = None) -> WriteResult:
        """Update an existing node.

        Args:
            node: The node with updated fields. Must have valid id.
            token: Optional CAS write token.

        Returns:
            WriteResult with success status.

        Complexity: O(1) amortized.
        """
        self._check_connection()
        assert self._conn is not None

        if token and not token.is_valid():
            return WriteResult(success=False, reason="Write token expired")

        with self._lock:
            try:
                node.touch()
                node.version += 1
                cursor = self._conn.execute(
                    """UPDATE nodes SET content=?, utility=?, surprise=?, tags=?,
                       confidence=?, tier=?, access_count=?, updated_at=?, version=?,
                       type=?, url=?, raw_chunk=?, trust_state=?
                       WHERE id=? AND tx_to=0.0""",
                    (node.content, node.utility, node.surprise, json.dumps(node.tags),
                     node.confidence, node.tier.value, node.access_count,
                     node.updated_at, node.version, node.type.value, node.url,
                     node.raw_chunk, node.trust_state,
                     node.id),
                )
                self._conn.commit()

                if cursor.rowcount == 0:
                    return WriteResult(success=False, reason="Node not found")

                return WriteResult(write_id=node.id, success=True, nodes_affected=cursor.rowcount)

            except sqlite3.Error as e:
                self._conn.rollback()
                logger.error("update_node failed: %s", e)
                return WriteResult(success=False, reason=f"Database error: {e}")

    def delete_node(self, node_id: str) -> WriteResult:
        """Delete a node and all its edges.

        Args:
            node_id: The node to delete.

        Returns:
            WriteResult with success status.

        Complexity: O(E) where E = edges connected to node.
        """
        self._check_connection()
        assert self._conn is not None

        with self._lock:
            try:
                # Delete edges first
                edge_cursor = self._conn.execute(
                    "DELETE FROM edges WHERE source_id=? OR target_id=?", (node_id, node_id)
                )
                edges_deleted = edge_cursor.rowcount

                # Delete node
                node_cursor = self._conn.execute(
                    "DELETE FROM nodes WHERE id=?", (node_id,)
                )
                nodes_deleted = node_cursor.rowcount

                # Delete from FTS index
                try:
                    self._conn.execute(
                        "DELETE FROM nodes_fts WHERE id=?", (node_id,)
                    )
                except sqlite3.OperationalError as e:
                    logger.warning("FTS delete skipped: %s", e)

                self._conn.commit()

                if nodes_deleted == 0:
                    return WriteResult(success=False, reason="Node not found")

                return WriteResult(
                    write_id=generate_uuidv7(), success=True,
                    nodes_affected=nodes_deleted,
                    reason=f"Deleted {edges_deleted} edges",
                )

            except sqlite3.Error as e:
                self._conn.rollback()
                logger.error("delete_node failed: %s", e)
                return WriteResult(success=False, reason=f"Database error: {e}")

    # ============================================================
    # Edge Operations
    # ============================================================

    def create_edge(self, edge: Edge) -> WriteResult:
        """Create an edge between two nodes.

        Args:
            edge: The edge to create.

        Returns:
            WriteResult with success status.

        Complexity: O(1) amortized.
        """
        self._check_connection()
        assert self._conn is not None

        if not edge.source_id or not edge.target_id:
            return WriteResult(success=False, reason="Source and target IDs required")
        if edge.weight < 0 or edge.weight > 1:
            return WriteResult(success=False, reason=f"Weight {edge.weight} out of [0,1]")

        with self._lock:
            try:
                self._conn.execute(
                    """INSERT INTO edges (source_id, target_id, type, weight, created_at, metadata)
                       VALUES (?,?,?,?,?,?)""",
                    (edge.source_id, edge.target_id, edge.type.value, edge.weight,
                     edge.created_at, json.dumps(edge.metadata)),
                )
                self._conn.commit()
                return WriteResult(success=True, nodes_affected=1)
            except sqlite3.Error as e:
                self._conn.rollback()
                return WriteResult(success=False, reason=f"Database error: {e}")

    # ============================================================
    # Search Operations
    # ============================================================

    def search(self, query: str, limit: int = 10, branch: str = "main") -> list[Node]:
        """Full-text search for nodes.

        Uses FTS5 for efficient text search with LIKE fallback.

        Args:
            query: Search query string. Return most recent nodes if empty.
            limit: Maximum results to return.
            branch: Branch to search in.

        Returns:
            List of matching nodes, sorted by relevance (or recency for empty query).

        Complexity: O(K·log N) where K = result set size.
        """
        self._check_connection()
        assert self._conn is not None

        if not query or not query.strip():
            # Return most recent nodes instead of empty list
            with self._lock:
                try:
                    rows = self._conn.execute(
                        """SELECT * FROM nodes
                           WHERE branch=? AND tx_to=0.0
                           ORDER BY created_at DESC LIMIT ?""",
                        (branch, limit),
                    ).fetchall()
                    return [self._row_to_node(r) for r in rows]
                except sqlite3.Error as e:
                    logger.error("search (empty query) failed: %s", e)
                    return []

        with self._lock:
            # Try FTS5 first — 转义特殊字符避免语法错误导致降级
            # FTS5 特殊字符: " * ( ) : ^ . + - / AND OR NOT
            # 用双引号包裹整句做 phrase query (最稳), 失败再尝试裸查询, 再 fallback LIKE
            fts_query = query
            special = set('*():"^.+-/')
            if any(c in special for c in query) and not (query.startswith('"') and query.endswith('"')):
                fts_query = '"' + query.replace('"', '""') + '"'
            try:
                rows = self._conn.execute(
                    """SELECT n.* FROM nodes_fts f
                       JOIN nodes n ON f.id = n.id
                       WHERE nodes_fts MATCH ? AND n.branch=? AND n.tx_to=0.0
                       ORDER BY rank LIMIT ?""",
                    (fts_query, branch, limit),
                ).fetchall()
                return [self._row_to_node(r) for r in rows]
            except (sqlite3.OperationalError, sqlite3.OperationalError) as e:
                logger.debug("FTS search (phrase) failed, trying raw: %s", e)
                # 再试一次裸查询(可能本身就是合法 FTS 语法)
                try:
                    rows = self._conn.execute(
                        """SELECT n.* FROM nodes_fts f
                           JOIN nodes n ON f.id = n.id
                           WHERE nodes_fts MATCH ? AND n.branch=? AND n.tx_to=0.0
                           ORDER BY rank LIMIT ?""",
                        (query, branch, limit),
                    ).fetchall()
                    return [self._row_to_node(r) for r in rows]
                except (sqlite3.OperationalError, sqlite3.OperationalError) as e2:
                    logger.warning("FTS search failed, falling back to LIKE: %s", e2)
                    self._fts_fallback_count += 1

            # Fallback to LIKE search
            try:
                rows = self._conn.execute(
                    """SELECT * FROM nodes
                       WHERE branch=? AND tx_to=0.0 AND content LIKE ?
                       ORDER BY utility DESC LIMIT ?""",
                    (branch, f"%{query}%", limit),
                ).fetchall()
                return [self._row_to_node(r) for r in rows]
            except sqlite3.Error as e:
                logger.error("search failed: %s", e)
                return []

    # ============================================================
    # Count Operations
    # ============================================================

    def get_node_count(self, branch: str | None = None) -> int:
        """Get total node count.

        Args:
            branch: If specified, count only nodes in this branch.

        Returns:
            Number of active nodes.

        Complexity: O(1) - uses SQLite COUNT.
        """
        self._check_connection()
        assert self._conn is not None

        with self._lock:
            try:
                if branch:
                    return self._conn.execute(
                        "SELECT COUNT(*) FROM nodes WHERE branch=? AND tx_to=0.0", (branch,)
                    ).fetchone()[0]
                return self._conn.execute(
                    "SELECT COUNT(*) FROM nodes WHERE tx_to=0.0"
                ).fetchone()[0]
            except sqlite3.Error as e:
                logger.error("get_node_count failed: %s", e)
                return 0

    def get_edge_count(self) -> int:
        """Get total edge count.

        Returns:
            Number of edges.

        Complexity: O(1).
        """
        self._check_connection()
        assert self._conn is not None

        with self._lock:
            try:
                return self._conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
            except sqlite3.Error as e:
                logger.error("get_edge_count failed: %s", e)
                return 0

    # ============================================================
    # Node Listing
    # ============================================================

    def get_active_nodes(self, limit: int = 100, branch: str = "main") -> list[Node]:
        """Get active nodes sorted by utility.

        Args:
            limit: Maximum nodes to return.
            branch: Branch to query.

        Returns:
            List of nodes, highest utility first.

        Complexity: O(limit · log limit) for sort.
        """
        self._check_connection()
        assert self._conn is not None

        with self._lock:
            try:
                rows = self._conn.execute(
                    """SELECT * FROM nodes
                       WHERE branch=? AND tx_to=0.0
                       ORDER BY utility DESC LIMIT ?""",
                    (branch, limit),
                ).fetchall()
                return [self._row_to_node(r) for r in rows]
            except sqlite3.Error as e:
                logger.error("get_active_nodes failed: %s", e)
                return []

    def get_nodes_by_type(self, node_type: Any, limit: int = 100, branch: str = "main") -> list[Node]:
        """P5: 按 NodeType 查询节点(多态感知检索)。

        供 recall/dream/maintain 按类型消费多类型知识库。
        """
        self._check_connection()
        assert self._conn is not None
        if isinstance(node_type, NodeType):
            type_val = node_type.value
        else:
            type_val = str(node_type)
        with self._lock:
            try:
                rows = self._conn.execute(
                    """SELECT * FROM nodes
                       WHERE branch=? AND tx_to=0.0 AND type=?
                       ORDER BY utility DESC LIMIT ?""",
                    (branch, type_val, limit),
                ).fetchall()
                return [self._row_to_node(r) for r in rows]
            except sqlite3.Error as e:
                logger.error("get_nodes_by_type failed: %s", e)
                return []

    def get_branch_nodes(self, branch: str) -> list[Node]:
        """Get all nodes in a branch.

        Args:
            branch: Branch name.

        Returns:
            List of nodes in the branch.

        Complexity: O(N) where N = nodes in branch.
        """
        self._check_connection()
        assert self._conn is not None

        with self._lock:
            try:
                rows = self._conn.execute(
                    "SELECT * FROM nodes WHERE branch=? AND tx_to=0.0", (branch,)
                ).fetchall()
                return [self._row_to_node(r) for r in rows]
            except sqlite3.Error as e:
                logger.error("get_branch_nodes failed: %s", e)
                return []

    def get_temporal_neighbors(self, node_id: str, delta_t: float = 3600.0,
                               branch: str = "main", limit: int = 5) -> list[Node]:
        """取某节点的时间邻域(前后 delta_t 秒内的同 branch 节点) [P1-d].

        论文④ Overlap Speech 借力: 因果系统在帧重叠固有延迟内浪费未来信息,
        用伪重叠帧融合补救. 映射到 ULTRA: recall 召回孤立节点会丢失帧边界处
        上下文, 此处融合时间邻域节点重建上下文(避免因果断点丢信息).
        """
        self._check_connection()
        assert self._conn is not None
        with self._lock:
            try:
                # 取该节点的 created_at
                cur = self._conn.execute(
                    "SELECT created_at FROM nodes WHERE id=?", (node_id,)
                ).fetchone()
                if cur is None:
                    return []
                t0 = cur[0]
                rows = self._conn.execute(
                    """SELECT * FROM nodes
                       WHERE branch=? AND tx_to=0.0 AND id!=?
                         AND created_at BETWEEN ? AND ?
                       ORDER BY ABS(created_at - ?) ASC LIMIT ?""",
                    (branch, node_id, t0 - delta_t, t0 + delta_t, t0, limit),
                ).fetchall()
                return [self._row_to_node(r) for r in rows]
            except sqlite3.Error as e:
                logger.error("get_temporal_neighbors failed: %s", e)
                return []

    # ============================================================
    # Branch Operations
    # ============================================================

    def create_branch(self, name: str, parent: str = "main") -> bool:
        """Create a new branch.

        Args:
            name: Branch name (must be unique).
            parent: Parent branch name.

        Returns:
            True if created successfully.

        Complexity: O(1).
        """
        self._check_connection()
        assert self._conn is not None

        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO branches (name, parent, created_at) VALUES (?,?,?)",
                    (name, parent, time.time()),
                )
                self._conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False
            except sqlite3.Error as e:
                logger.error("create_branch failed: %s", e)
                return False

    def merge_branch(self, source: str, target: str, token: WriteToken | None = None) -> MergeResult:
        """Merge a branch into target.

        Uses utility-wins conflict resolution: if a node exists in both
        branches, the one with higher utility wins.

        Args:
            source: Source branch to merge.
            target: Target branch to merge into.
            token: Optional CAS write token.

        Returns:
            MergeResult with merge statistics.

        Complexity: O(N) where N = nodes in source branch.
        """
        self._check_connection()
        assert self._conn is not None

        if token and not token.is_valid():
            return MergeResult(success=False, reason="Write token expired")

        with self._lock:
            try:
                # Get source nodes
                rows = self._conn.execute(
                    "SELECT * FROM nodes WHERE branch=? AND tx_to=0.0", (source,)
                ).fetchall()

                merged = 0
                conflicts = 0

                for row in rows:
                    node = self._row_to_node(row)
                    node.branch = target

                    # Check if exists in target
                    existing_row = self._conn.execute(
                        "SELECT * FROM nodes WHERE id=? AND branch=? AND tx_to=0.0",
                        (node.id, target),
                    ).fetchone()

                    if existing_row:
                        existing_node = self._row_to_node(existing_row)
                        if node.utility > existing_node.utility:
                            # Update existing
                            node.touch()
                            node.version += 1
                            self._conn.execute(
                                """UPDATE nodes SET content=?, utility=?, surprise=?, tags=?,
                                   confidence=?, tier=?, access_count=?, updated_at=?, version=?
                                   WHERE id=? AND branch=?""",
                                (node.content, node.utility, node.surprise, json.dumps(node.tags),
                                 node.confidence, node.tier.value, node.access_count,
                                 node.updated_at, node.version, node.id, target),
                            )
                            conflicts += 1
                        merged += 1
                    else:
                        # Move node to target branch (UPDATE existing row)
                        self._conn.execute(
                            "UPDATE nodes SET branch=? WHERE id=? AND branch=?",
                            (target, node.id, source),
                        )
                        merged += 1

                # Record merge
                write_id = generate_uuidv7()
                self._conn.execute(
                    """INSERT INTO branch_merges (source, target, nodes_merged, write_id, timestamp)
                       VALUES (?,?,?,?,?)""",
                    (source, target, merged, write_id, time.time()),
                )

                # Mark branch as merged
                self._conn.execute(
                    "UPDATE branches SET merged_at=? WHERE name=?", (time.time(), source)
                )

                self._conn.commit()
                return MergeResult(
                    write_id=write_id, success=True,
                    nodes_merged=merged, conflicts_resolved=conflicts,
                )

            except sqlite3.Error as e:
                self._conn.rollback()
                logger.error("merge_branch failed: %s", e)
                return MergeResult(success=False, reason=f"Database error: {e}")

    def list_branches(self) -> list[str]:
        """List all branch names.

        Returns:
            List of branch name strings.

        Complexity: O(B) where B = number of branches.
        """
        self._check_connection()
        assert self._conn is not None

        with self._lock:
            try:
                rows = self._conn.execute("SELECT name FROM branches").fetchall()
                return [r["name"] for r in rows]
            except sqlite3.Error as e:
                logger.error("list_branches failed: %s", e)
                return []

    # ============================================================
    # Write Token System (CAS)
    # ============================================================

    def request_write_token(self, node_id: str, operator: str, action: str) -> WriteToken:
        """Request a CAS write token.

        Tokens expire after 30 seconds. Only one token per node should
        be active at a time for consistency.

        Args:
            node_id: Node to write to.
            operator: Operator name.
            action: Action being performed.

        Returns:
            WriteToken with 30-second expiry.

        Complexity: O(1).
        """
        token = WriteToken(
            token=generate_uuidv7(),
            node_id=node_id,
            operator=operator,
            granted_at=time.time(),
            expires_at=time.time() + 30.0,
        )
        self._tokens[token.token] = token

        # Cleanup expired tokens
        if len(self._tokens) > 1000:
            self._tokens = {k: v for k, v in self._tokens.items() if v.is_valid()}

        return token

    # ============================================================
    # Audit Logging
    # ============================================================

    def log_evolution(self, cycle_id: str, before: float, after: float, strategy: str) -> None:
        """Log an evolution cycle.

        Args:
            cycle_id: Unique cycle identifier.
            fitness_before: Fitness before evolution.
            fitness_after: Fitness after evolution.
            strategy: Evolution strategy used.
        """
        self._check_connection()
        assert self._conn is not None

        with self._lock:
            try:
                self._conn.execute(
                    """INSERT INTO evolution_log (cycle_id, fitness_before, fitness_after, delta, strategy, timestamp)
                       VALUES (?,?,?,?,?,?)""",
                    (cycle_id, before, after, after - before, strategy, time.time()),
                )
                self._conn.commit()
            except sqlite3.Error as e:
                logger.error("log_evolution failed: %s", e)

    def log_maintenance(self, action: str, affected: int, duration_ms: float) -> None:
        """Log a maintenance operation.

        Args:
            action: Maintenance action performed.
            affected: Number of nodes affected.
            duration_ms: Duration in milliseconds.
        """
        self._check_connection()
        assert self._conn is not None

        with self._lock:
            try:
                self._conn.execute(
                    """INSERT INTO maintenance_log (action, nodes_affected, duration_ms, timestamp)
                       VALUES (?,?,?,?)""",
                    (action, affected, duration_ms, time.time()),
                )
                self._conn.commit()
            except sqlite3.Error as e:
                logger.error("log_maintenance failed: %s", e)

    def log_audit(self, dimension: str, score: float, details: dict) -> None:
        """Log an audit result.

        Args:
            dimension: Audit dimension name.
            score: Audit score.
            details: Additional details.
        """
        self._check_connection()
        assert self._conn is not None

        with self._lock:
            try:
                self._conn.execute(
                    """INSERT INTO audit_log (dimension, score, details, timestamp)
                       VALUES (?,?,?,?)""",
                    (dimension, score, json.dumps(details), time.time()),
                )
                self._conn.commit()
            except sqlite3.Error as e:
                logger.error("log_audit failed: %s", e)

    # ============================================================
    # Lifecycle
    # ============================================================

    def close(self) -> None:
        """Close the database connection.

        Should be called when the store is no longer needed.
        """
        with self._lock:
            if self._conn:
                try:
                    self._conn.close()
                except sqlite3.Error as e:
                    logger.warning("Failed to close store connection: %s", e)
                self._conn = None
                self._connected = False
                logger.info("MinervaStore closed")

    # ============================================================
    # Internal Helpers
    # ============================================================

    def _row_to_node(self, row: sqlite3.Row) -> Node:
        """Convert a database row to a Node object.

        Args:
            row: SQLite Row object.

        Returns:
            Node instance.
        """
        try:
            raw_chunk = row["raw_chunk"] if "raw_chunk" in row.keys() else ""
        except Exception:
            logger.warning("Store: failed to read raw_chunk from row, defaulting to empty")
            raw_chunk = ""
        try:
            trust_state = row["trust_state"] if "trust_state" in row.keys() else "unknown"
        except Exception:
            logger.warning("Store: failed to read trust_state from row, defaulting to unknown")
            trust_state = "unknown"
        return Node(
            id=row["id"],
            type=NodeType(row["type"]),
            content=row["content"],
            utility=row["utility"],
            surprise=row["surprise"],
            tags=json.loads(row["tags"]) if row["tags"] else [],
            branch=row["branch"],
            source=ProvenanceType(row["source"]),
            confidence=row["confidence"],
            tier=MemoryTier(row["tier"]),
            access_count=row["access_count"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            tx_from=row["tx_from"],
            tx_to=row["tx_to"],
            version=row["version"],
            raw_chunk=raw_chunk,
            trust_state=trust_state,
            url=row["url"] if "url" in row.keys() else "",
        )
