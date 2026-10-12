"""Neo4j 5.x adapter.

Cypher safety: every VALUE is a query parameter. Relationship TYPES cannot be parameterized, so they are
interpolated only after passing the ontology allowlist (checked by validate()) AND `_safe_rel()` (regex),
and are always backtick-quoted.
"""
from __future__ import annotations

from typing import Any

from neo4j import Driver

from ..ontology import RELATION_TYPE_RE
from ..ports import GraphWriteResult
from ..utils import chunks


def _safe_rel(name: str) -> str:
    if not RELATION_TYPE_RE.match(name):
        raise ValueError(f"unsafe relation type rejected: {name!r}")
    return f"`{name}`"


_UPSERT_ENTITIES = """
UNWIND $rows AS row
MERGE (e:Entity {id: row.id})
ON CREATE SET e.created_at = row.now
SET e.canonical_name = row.canonical_name, e.entity_type = row.entity_type, e.normalized_name = row.normalized_name,
    e.aliases = row.aliases, e.properties_json = row.properties_json, e.content_hash = row.content_hash,
    e.updated_at = row.now, e.import_id = row.import_id,
    e.source_ids = CASE WHEN row.document_id IN coalesce(e.source_ids, []) THEN e.source_ids
                        ELSE coalesce(e.source_ids, []) + row.document_id END
"""

_UPSERT_RELATIONS = """
UNWIND $rows AS row
MATCH (s:Entity {{id: row.source_id}})
MATCH (t:Entity {{id: row.target_id}})
MERGE (s)-[r:{rel} {{id: row.id}}]->(t)
ON CREATE SET r.created_at = row.now
SET r.properties_json = row.properties_json, r.confidence = row.confidence,
    r.source_document_id = row.document_id, r.source_proposition_ids = row.proposition_ids,
    r.evidence_ids = row.evidence_ids, r.content_hash = row.content_hash,
    r.updated_at = row.now, r.import_id = row.import_id
RETURN count(r) AS n
"""

_DROP_STALE_RELATIONS = """
MATCH ()-[r]->() WHERE r.source_document_id = $doc AND r.import_id <> $import_id
DELETE r
"""

_UNLINK_STALE_ENTITIES = """
MATCH (e:Entity) WHERE $doc IN coalesce(e.source_ids, []) AND e.import_id <> $import_id
SET e.source_ids = [x IN e.source_ids WHERE x <> $doc]
WITH e WHERE size(e.source_ids) = 0 AND NOT (e)--()
DELETE e
"""


class Neo4jKGStore:
    """Implements GraphStore. The Driver (connection pool) is created once by the application."""

    def __init__(self, driver: Driver, database: str = "neo4j", batch_size: int = 1000) -> None:
        self.driver, self.database, self.batch = driver, database, batch_size

    def ping(self) -> None:
        self.driver.verify_connectivity()

    def ensure_constraints(self, relation_types: list[str]) -> list[str]:
        """Idempotent (IF NOT EXISTS). Requires Neo4j 5.7+ for relationship-property uniqueness."""
        stmts = {
            "entity_id_unique": "CREATE CONSTRAINT entity_id_unique IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE",
            "entity_normalized_name": "CREATE INDEX entity_normalized_name IF NOT EXISTS FOR (e:Entity) ON (e.normalized_name)",
            "entity_type_idx": "CREATE INDEX entity_type_idx IF NOT EXISTS FOR (e:Entity) ON (e.entity_type)",
        }
        for rel in relation_types:
            q = _safe_rel(rel)
            stmts[f"rel_id_unique_{rel}"] = (
                f"CREATE CONSTRAINT rel_id_unique_{rel.lower()} IF NOT EXISTS FOR ()-[r:{q}]-() REQUIRE r.id IS UNIQUE")
        with self.driver.session(database=self.database) as s:
            for cypher in stmts.values():
                s.run(cypher).consume()
        return sorted(stmts)

    def get_entities(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        q = "UNWIND $ids AS id MATCH (e:Entity {id: id}) RETURN e.id AS id, e.entity_type AS entity_type, e.content_hash AS content_hash"
        with self.driver.session(database=self.database) as s:
            return {r["id"]: {"entity_type": r["entity_type"], "content_hash": r["content_hash"]}
                    for r in s.execute_read(lambda tx: list(tx.run(q, ids=ids)))}

    def find_entity_candidates(self, ids: list[str], names: list[str], types: list[str]) -> list[dict[str, Any]]:
        # Exact names use the normalized-name index; the alias branch also covers nodes imported before this feature.
        q = """MATCH (e:Entity)
               WHERE e.id IN $ids OR ((size($types) = 0 OR e.entity_type IN $types) AND
                    (e.normalized_name IN $names OR
                     any(a IN coalesce(e.aliases, []) WHERE toLower(trim(a)) IN $names)))
               RETURN e.id AS id, e.entity_type AS entity_type, e.canonical_name AS canonical_name,
                      e.normalized_name AS normalized_name, e.aliases AS aliases,
                      e.properties_json AS properties_json"""
        with self.driver.session(database=self.database) as s:
            return [dict(r) for r in s.execute_read(lambda tx: list(tx.run(q, ids=ids, names=names, types=types)))]

    def list_entities(self, after_id: str, limit: int) -> list[dict[str, Any]]:
        q = """MATCH (e:Entity) WHERE e.id > $after
               RETURN e.id AS id, e.entity_type AS entity_type, e.canonical_name AS canonical_name,
                      e.aliases AS aliases, e.source_ids AS source_ids ORDER BY e.id LIMIT $limit"""
        with self.driver.session(database=self.database) as s:
            return [dict(r) for r in s.execute_read(lambda tx: list(tx.run(q, after=after_id, limit=limit)))]

    def get_entity_context(self, entity_id: str, limit: int = 50) -> dict[str, Any] | None:
        q = """MATCH (e:Entity {id: $id})
               RETURN e.id AS id, e.entity_type AS entity_type, e.canonical_name AS canonical_name,
                      e.aliases AS aliases, e.source_ids AS source_ids, e.properties_json AS properties_json"""
        edges = """MATCH (e:Entity {id: $id})-[r]-(other:Entity)
                   RETURN r.id AS id, type(r) AS predicate, startNode(r).id AS source_id,
                          endNode(r).id AS target_id, other.id AS other_id,
                          other.canonical_name AS other_name, r.source_document_id AS document_id,
                          r.source_proposition_ids AS proposition_ids, r.evidence_ids AS evidence_ids
                   ORDER BY predicate, other_name LIMIT $limit"""
        with self.driver.session(database=self.database) as s:
            def work(tx):
                row = tx.run(q, id=entity_id).single()
                if row is None:
                    return None
                entity = dict(row)
                entity["relations"] = [dict(r) for r in tx.run(edges, id=entity_id, limit=limit)]
                return entity
            return s.execute_read(work)

    def get_relations(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        q = ("MATCH (s:Entity)-[r]->(t:Entity) WHERE r.id IN $ids RETURN r.id AS id, type(r) AS type, s.id AS source_id, "
             "t.id AS target_id, r.content_hash AS content_hash, r.source_document_id AS source_document_id")
        with self.driver.session(database=self.database) as s:
            return {r["id"]: dict(r) for r in s.execute_read(lambda tx: list(tx.run(q, ids=ids)))}

    def write(self, entities: list[dict], relations: list[dict], *, document_id: str, import_id: str, now: str,
              replace: bool) -> GraphWriteResult:
        def work(tx) -> GraphWriteResult:
            res = GraphWriteResult()
            base = {"document_id": document_id, "import_id": import_id, "now": now}
            for part in chunks(entities, self.batch):
                c = tx.run(_UPSERT_ENTITIES, rows=[{**e, **base} for e in part]).consume().counters
                res.entities_created += c.nodes_created
            by_type: dict[str, list[dict]] = {}
            for r in relations:
                by_type.setdefault(r["relation_type"], []).append({**r, **base})
            for rel_type, rows in by_type.items():
                cypher = _UPSERT_RELATIONS.format(rel=_safe_rel(rel_type))
                for part in chunks(rows, self.batch):
                    result = tx.run(cypher, rows=part)
                    matched = result.single()["n"]
                    if matched != len(part):  # MATCH dropped rows -> an endpoint is missing; abort the whole tx
                        raise RuntimeError(f"{len(part) - matched} relation(s) of type {rel_type} had a missing endpoint")
                    res.relations_created += result.consume().counters.relationships_created
            if replace:
                c = tx.run(_DROP_STALE_RELATIONS, doc=document_id, import_id=import_id).consume().counters
                res.relations_deleted = c.relationships_deleted
                c = tx.run(_UNLINK_STALE_ENTITIES, doc=document_id, import_id=import_id).consume().counters
                res.entities_deleted = c.nodes_deleted
            return res

        with self.driver.session(database=self.database) as session:
            return session.execute_write(work)
