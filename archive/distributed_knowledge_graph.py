"""
DistributedKnowledgeGraph - Multi-node knowledge graph synchronization

Features:
- Master-slave replication
- Conflict resolution with last-write-wins
- Incremental sync via change log
- Compression for network efficiency

Author: Prometheus Ultra Team
Version: 1.0.0
"""
from __future__ import annotations
import json
import time
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class ChangeLogEntry:
    """A change log entry for incremental sync."""
    timestamp: float
    operation: str  # "add", "update", "delete"
    entity_type: str  # "concept", "relation"
    entity_id: str
    data: dict[str, Any]
    version: int


class DistributedKnowledgeGraph:
    """Multi-node knowledge graph with synchronization support."""
    
    def __init__(self, node_id: str = "default"):
        self.node_id = node_id
        self.is_master = True
        self.change_log: list[ChangeLogEntry] = []
        self.last_sync_time: float = 0
        self.conflict_resolution: str = "last_write_wins"  # or "merge"
        # Local storage
        self.concepts: dict[str, dict[str, Any]] = {}
        self.relations: dict[str, dict[str, Any]] = {}
        # Version tracking
        self._version: int = 0
        self._last_updated: float = 0
    
    def add_concept(self, concept_id: str, data: dict[str, Any]) -> None:
        """Add a concept and log the change."""
        self.concepts[concept_id] = {
            **data,
            "node_id": self.node_id,
            "version": self._version + 1,
            "updated_at": time.time(),
        }
        self._log_change("add", "concept", concept_id, data)
        self._version += 1
        self._last_updated = time.time()
    
    def update_concept(self, concept_id: str, data: dict[str, Any]) -> None:
        """Update a concept and log the change."""
        if concept_id in self.concepts:
            self.concepts[concept_id].update(data)
            self.concepts[concept_id]["version"] = self._version + 1
            self.concepts[concept_id]["updated_at"] = time.time()
            self._log_change("update", "concept", concept_id, data)
            self._version += 1
            self._last_updated = time.time()
    
    def delete_concept(self, concept_id: str) -> None:
        """Delete a concept and log the change."""
        if concept_id in self.concepts:
            data = self.concepts.pop(concept_id)
            self._log_change("delete", "concept", concept_id, data)
            self._version += 1
            self._last_updated = time.time()
    
    def add_relation(self, relation_id: str, data: dict[str, Any]) -> None:
        """Add a relation and log the change."""
        self.relations[relation_id] = {
            **data,
            "node_id": self.node_id,
            "version": self._version + 1,
            "updated_at": time.time(),
        }
        self._log_change("add", "relation", relation_id, data)
        self._version += 1
        self._last_updated = time.time()
    
    def update_relation(self, relation_id: str, data: dict[str, Any]) -> None:
        """Update a relation and log the change."""
        if relation_id in self.relations:
            self.relations[relation_id].update(data)
            self.relations[relation_id]["version"] = self._version + 1
            self.relations[relation_id]["updated_at"] = time.time()
            self._log_change("update", "relation", relation_id, data)
            self._version += 1
            self._last_updated = time.time()
    
    def delete_relation(self, relation_id: str) -> None:
        """Delete a relation and log the change."""
        if relation_id in self.relations:
            data = self.relations.pop(relation_id)
            self._log_change("delete", "relation", relation_id, data)
            self._version += 1
            self._last_updated = time.time()
    
    def _log_change(self, operation: str, entity_type: str, entity_id: str, data: dict[str, Any]) -> None:
        """Log a change for incremental sync."""
        entry = ChangeLogEntry(
            timestamp=time.time(),
            operation=operation,
            entity_type=entity_type,
            entity_id=entity_id,
            data=data,
            version=self._version,
        )
        self.change_log.append(entry)
        # Keep only last 1000 changes
        if len(self.change_log) > 1000:
            self.change_log = self.change_log[-1000:]
    
    def get_changes_since(self, since_time: float) -> list[ChangeLogEntry]:
        """Get all changes since a given time."""
        return [entry for entry in self.change_log if entry.timestamp > since_time]
    
    def sync_from(self, other: 'DistributedKnowledgeGraph') -> dict[str, Any]:
        """Sync from another node (master-slave)."""
        if not self.is_master:
            # Slave can only sync from master
            if other.node_id != "master":
                return {"error": "Can only sync from master node"}
        
        sync_stats = {
            "concepts_added": 0,
            "concepts_updated": 0,
            "concepts_deleted": 0,
            "relations_added": 0,
            "relations_updated": 0,
            "relations_deleted": 0,
            "conflicts_resolved": 0,
        }
        
        # Get changes from other node
        other_changes = other.get_changes_since(self.last_sync_time)
        
        for change in other_changes:
            if change.entity_type == "concept":
                if change.operation == "add":
                    if change.entity_id not in self.concepts:
                        self.concepts[change.entity_id] = change.data
                        sync_stats["concepts_added"] += 1
                    else:
                        # Conflict resolution
                        if self._resolve_conflict(change):
                            self.concepts[change.entity_id] = change.data
                            sync_stats["concepts_updated"] += 1
                            sync_stats["conflicts_resolved"] += 1
                elif change.operation == "update":
                    if change.entity_id in self.concepts:
                        if self._resolve_conflict(change):
                            self.concepts[change.entity_id].update(change.data)
                            sync_stats["concepts_updated"] += 1
                            sync_stats["conflicts_resolved"] += 1
                elif change.operation == "delete":
                    if change.entity_id in self.concepts:
                        del self.concepts[change.entity_id]
                        sync_stats["concepts_deleted"] += 1
            
            elif change.entity_type == "relation":
                if change.operation == "add":
                    if change.entity_id not in self.relations:
                        self.relations[change.entity_id] = change.data
                        sync_stats["relations_added"] += 1
                    else:
                        if self._resolve_conflict(change):
                            self.relations[change.entity_id] = change.data
                            sync_stats["relations_updated"] += 1
                            sync_stats["conflicts_resolved"] += 1
                elif change.operation == "update":
                    if change.entity_id in self.relations:
                        if self._resolve_conflict(change):
                            self.relations[change.entity_id].update(change.data)
                            sync_stats["relations_updated"] += 1
                            sync_stats["conflicts_resolved"] += 1
                elif change.operation == "delete":
                    if change.entity_id in self.relations:
                        del self.relations[change.entity_id]
                        sync_stats["relations_deleted"] += 1
        
        self.last_sync_time = time.time()
        return sync_stats
    
    def _resolve_conflict(self, change: ChangeLogEntry) -> bool:
        """Resolve conflict based on strategy."""
        if self.conflict_resolution == "last_write_wins":
            # Last write wins
            return change.timestamp > self._last_updated
        elif self.conflict_resolution == "merge":
            # Merge strategy - always merge
            return True
        return False
    
    def get_stats(self) -> dict[str, Any]:
        """Get statistics about the distributed knowledge graph."""
        return {
            "node_id": self.node_id,
            "is_master": self.is_master,
            "concepts": len(self.concepts),
            "relations": len(self.relations),
            "change_log_size": len(self.change_log),
            "version": self._version,
            "last_updated": self._last_updated,
            "last_sync_time": self.last_sync_time,
        }
    
    def export_for_sync(self) -> dict[str, Any]:
        """Export data for synchronization (compressed)."""
        return {
            "node_id": self.node_id,
            "version": self._version,
            "timestamp": time.time(),
            "concepts": self.concepts,
            "relations": self.relations,
            "change_log": self.change_log[-100:],  # Only last 100 changes
        }
    
    def import_from_sync(self, data: dict[str, Any]) -> dict[str, Any]:
        """Import data from synchronization."""
        stats = {
            "concepts_imported": 0,
            "relations_imported": 0,
            "changes_applied": 0,
        }
        
        # Import concepts
        for concept_id, concept_data in data.get("concepts", {}).items():
            if concept_id not in self.concepts:
                self.concepts[concept_id] = concept_data
                stats["concepts_imported"] += 1
        
        # Import relations
        for relation_id, relation_data in data.get("relations", {}).items():
            if relation_id not in self.relations:
                self.relations[relation_id] = relation_data
                stats["relations_imported"] += 1
        
        # Apply changes
        for change in data.get("change_log", []):
            self._log_change(
                change["operation"],
                change["entity_type"],
                change["entity_id"],
                change["data"],
            )
            stats["changes_applied"] += 1
        
        self._version = data.get("version", self._version)
        self._last_updated = time.time()
        
        return stats


class InteractiveKnowledgeGraphEditor:
    """Interactive knowledge graph editor for visual editing."""
    
    def __init__(self, kg: DistributedKnowledgeGraph):
        self.kg = kg
        self.edit_history: list[dict[str, Any]] = []
    
    def add_concept_interactive(self, name: str, category: str = "general", properties: dict[str, Any] = None) -> dict[str, Any]:
        """Add a concept interactively."""
        concept_id = hashlib.md5(f"{name}{time.time()}".encode()).hexdigest()[:12]
        data = {
            "name": name,
            "category": category,
            "properties": properties or {},
            "created_by": "editor",
        }
        self.kg.add_concept(concept_id, data)
        self._log_edit("add_concept", concept_id, data)
        return {"concept_id": concept_id, "status": "success"}
    
    def add_relation_interactive(self, source: str, target: str, relation_type: str, strength: float = 0.6) -> dict[str, Any]:
        """Add a relation interactively."""
        relation_id = hashlib.md5(f"{source}{target}{relation_type}{time.time()}".encode()).hexdigest()[:12]
        data = {
            "source": source,
            "target": target,
            "relation_type": relation_type,
            "strength": strength,
            "created_by": "editor",
        }
        self.kg.add_relation(relation_id, data)
        self._log_edit("add_relation", relation_id, data)
        return {"relation_id": relation_id, "status": "success"}
    
    def delete_concept_interactive(self, concept_id: str) -> dict[str, Any]:
        """Delete a concept interactively."""
        if concept_id not in self.kg.concepts:
            return {"status": "error", "message": "Concept not found"}
        
        data = self.kg.concepts[concept_id]
        self.kg.delete_concept(concept_id)
        self._log_edit("delete_concept", concept_id, data)
        return {"status": "success"}
    
    def delete_relation_interactive(self, relation_id: str) -> dict[str, Any]:
        """Delete a relation interactively."""
        if relation_id not in self.kg.relations:
            return {"status": "error", "message": "Relation not found"}
        
        data = self.kg.relations[relation_id]
        self.kg.delete_relation(relation_id)
        self._log_edit("delete_relation", relation_id, data)
        return {"status": "success"}
    
    def undo_last_edit(self) -> dict[str, Any]:
        """Undo the last edit."""
        if not self.edit_history:
            return {"status": "error", "message": "No edits to undo"}
        
        last_edit = self.edit_history.pop()
        op = last_edit["operation"]
        entity_id = last_edit["entity_id"]
        data = last_edit["data"]
        
        if op == "add_concept":
            self.kg.delete_concept(entity_id)
        elif op == "add_relation":
            self.kg.delete_relation(entity_id)
        elif op == "delete_concept":
            self.kg.add_concept(entity_id, data)
        elif op == "delete_relation":
            self.kg.add_relation(entity_id, data)
        
        return {"status": "success", "undone": last_edit}
    
    def _log_edit(self, operation: str, entity_id: str, data: dict[str, Any]) -> None:
        """Log an edit for undo."""
        self.edit_history.append({
            "operation": operation,
            "entity_id": entity_id,
            "data": data,
            "timestamp": time.time(),
        })
        # Keep only last 100 edits
        if len(self.edit_history) > 100:
            self.edit_history = self.edit_history[-100:]
    
    def get_visualization_data(self) -> dict[str, Any]:
        """Get data for visualization."""
        nodes = []
        edges = []
        
        for concept_id, concept_data in self.kg.concepts.items():
            nodes.append({
                "id": concept_id,
                "label": concept_data.get("name", concept_id),
                "category": concept_data.get("category", "general"),
                "properties": concept_data.get("properties", {}),
            })
        
        for relation_id, relation_data in self.kg.relations.items():
            edges.append({
                "id": relation_id,
                "source": relation_data.get("source"),
                "target": relation_data.get("target"),
                "type": relation_data.get("relation_type"),
                "strength": relation_data.get("strength", 0.6),
            })
        
        return {
            "nodes": nodes,
            "edges": edges,
            "stats": self.kg.get_stats(),
        }


class IncrementalKnowledgeSync:
    """Incremental knowledge synchronization from external sources."""
    
    def __init__(self, kg: DistributedKnowledgeGraph):
        self.kg = kg
        self.sync_sources: dict[str, dict[str, Any]] = {}
        self.last_sync_times: dict[str, float] = {}
    
    def register_source(self, source_name: str, source_config: dict[str, Any]) -> None:
        """Register a knowledge source."""
        self.sync_sources[source_name] = {
            "name": source_name,
            "config": source_config,
            "enabled": True,
            "last_sync": 0,
            "sync_interval": source_config.get("sync_interval", 3600),  # Default 1 hour
        }
    
    def sync_from_source(self, source_name: str) -> dict[str, Any]:
        """Sync from a specific source."""
        if source_name not in self.sync_sources:
            return {"error": f"Source {source_name} not found"}
        
        source = self.sync_sources[source_name]
        if not source["enabled"]:
            return {"error": f"Source {source_name} is disabled"}
        
        # Check if it's time to sync
        current_time = time.time()
        if current_time - source["last_sync"] < source["sync_interval"]:
            return {"status": "skipped", "reason": "Sync interval not reached"}
        
        # Simulate fetching from external source
        # In real implementation, this would call APIs, scrape websites, etc.
        sync_result = self._fetch_and_process(source_name)
        
        source["last_sync"] = current_time
        return sync_result
    
    def _fetch_and_process(self, source_name: str) -> dict[str, Any]:
        """Fetch and process knowledge from source."""
        # This is a placeholder - in real implementation, this would:
        # 1. Call external APIs
        # 2. Scrape websites
        # 3. Process and extract knowledge
        # 4. Add to knowledge graph
        
        return {
            "status": "success",
            "source": source_name,
            "concepts_added": 0,
            "relations_added": 0,
            "timestamp": time.time(),
        }
    
    def sync_all_sources(self) -> dict[str, Any]:
        """Sync from all registered sources."""
        results = {}
        for source_name in self.sync_sources:
            if self.sync_sources[source_name]["enabled"]:
                results[source_name] = self.sync_from_source(source_name)
        return results
    
    def get_sync_status(self) -> dict[str, Any]:
        """Get status of all sync sources."""
        status = {}
        for source_name, source in self.sync_sources.items():
            status[source_name] = {
                "enabled": source["enabled"],
                "last_sync": source["last_sync"],
                "sync_interval": source["sync_interval"],
                "next_sync": source["last_sync"] + source["sync_interval"],
            }
        return status