"""Storage ports. Real adapters: adapters/mongo.py, adapters/neo4j.py. Test doubles: adapters/memory.py.

If your project already has Mongo/Neo4j repositories, implement these Protocols as thin wrappers
over them instead of using the bundled adapters (no second database layer needed).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class GraphWriteResult:
    entities_created: int = 0
    relations_created: int = 0
    relations_deleted: int = 0
    entities_unlinked: int = 0
    entities_deleted: int = 0


class DocumentStore(Protocol):
    def ensure_indexes(self) -> None: ...
    def ping(self) -> None: ...
    def document_exists(self, document_id: str) -> bool: ...
    def existing_ids(self, collection: str, document_id: str, ids: list[str]) -> set[str]: ...
    def write(self, records: dict[str, list[dict[str, Any]]], *, mode: str, import_id: str, now: str) -> dict[str, int]:
        """mode 'insert' fails on duplicates; 'upsert' is idempotent. Every record is tagged with import_id."""
    def delete_stale(self, document_id: str, keep_import_id: str) -> dict[str, int]:
        """Delete this document's records whose import_id != keep_import_id (replace mode finalize)."""
    def delete_by_import(self, document_id: str, import_id: str) -> dict[str, int]:
        """Compensation: delete this document's records written by import_id."""


class GraphStore(Protocol):
    def ensure_constraints(self, relation_types: list[str]) -> list[str]: ...
    def ping(self) -> None: ...
    def get_entities(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        """id -> {entity_type, content_hash}"""
    def find_entity_candidates(self, ids: list[str], names: list[str], types: list[str]) -> list[dict[str, Any]]:
        """Existing entities matching an id or an exact normalized name/alias; include names and aliases."""
    def list_entities(self, after_id: str, limit: int) -> list[dict[str, Any]]:
        """Page through stored entities for the vector index bootstrap."""
    def get_relations(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        """id -> {type, source_id, target_id, content_hash, source_document_id}"""
    def write(self, entities: list[dict], relations: list[dict], *, document_id: str, import_id: str,
              now: str, replace: bool) -> GraphWriteResult:
        """ONE atomic transaction. In replace mode also drops this document's stale relations/links."""


class JobStore(Protocol):
    def create_job(self, job: dict[str, Any]) -> None: ...
    def update_job(self, import_id: str, fields: dict[str, Any]) -> None: ...
    def get_job(self, import_id: str) -> dict[str, Any] | None: ...
