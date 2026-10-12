"""Import planning: read-only comparison of the payload with what is stored. Used for dry-run too."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .errors import Issue
from .models import MONGO_ID_FIELDS
from .normalization import NormalizedImport
from .ontology import Ontology
from .ports import DocumentStore, GraphStore
from .utils import chunks

MODES = ("insert", "upsert", "replace")


@dataclass
class ImportPlan:
    document_id: str
    mode: str
    document_exists: bool = False
    entities: dict[str, int] = field(default_factory=lambda: {"create": 0, "update": 0, "skip": 0})
    relations: dict[str, int] = field(default_factory=lambda: {"create": 0, "update": 0, "skip": 0})
    mongo: dict[str, int] = field(default_factory=dict)
    conflicts: list[Issue] = field(default_factory=list)  # data already exists / ownership problems
    errors: list[Issue] = field(default_factory=list)  # references that cannot be resolved
    entity_links: dict[str, str] = field(default_factory=dict)  # incoming id -> existing canonical id
    entity_candidates: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # vector suggestions for review

    def to_dict(self) -> dict[str, Any]:
        return {"document_id": self.document_id, "mode": self.mode, "document_exists": self.document_exists,
                "entities": self.entities, "relations": self.relations, "mongo": self.mongo,
                "conflicts": [c.to_dict() for c in self.conflicts], "errors": [e.to_dict() for e in self.errors],
                "entity_links": self.entity_links, "entity_candidates": self.entity_candidates}


def build_plan(norm: NormalizedImport, mode: str, ontology: Ontology, graph: GraphStore, docs: DocumentStore,
               *, batch: int = 1000) -> ImportPlan:
    plan = ImportPlan(document_id=norm.document_id, mode=mode)
    doc_id = norm.document_id
    plan.document_exists = docs.document_exists(doc_id)
    plan.mongo = {c: len(r) for c, r in norm.mongo.items()}

    if mode == "insert":
        if plan.document_exists:
            plan.conflicts.append(Issue("DUPLICATE_DOCUMENT", f"document '{doc_id}' already exists (mode=insert)",
                                        context={"document_id": doc_id}))
        for coll, recs in norm.mongo.items():
            if coll == "documents":
                continue
            field_ = MONGO_ID_FIELDS[coll]
            ids = [r[field_] for r in recs]
            for part in chunks(ids, batch):
                for dup in sorted(docs.existing_ids(coll, doc_id, part)):
                    plan.conflicts.append(Issue("DUPLICATE_MONGO_RECORD", f"{coll} '{dup}' already exists (mode=insert)",
                                                context={"document_id": doc_id, "collection": coll, "id": dup}))

    # entities
    ent_ids = [e["id"] for e in norm.entities]
    existing: dict[str, dict[str, Any]] = {}
    for part in chunks(ent_ids, batch):
        existing.update(graph.get_entities(part))
    types = {e["id"]: e["entity_type"] for e in norm.entities}
    for e in norm.entities:
        cur = existing.get(e["id"])
        if cur is None:
            plan.entities["create"] += 1
        elif mode == "insert":
            plan.conflicts.append(Issue("DUPLICATE_ENTITY", f"entity '{e['id']}' already exists (mode=insert)",
                                        context={"entity_id": e["id"]}))
        elif cur.get("content_hash") == e["content_hash"] and cur.get("entity_type") == e["entity_type"]:
            plan.entities["skip"] += 1
        else:
            plan.entities["update"] += 1

    # endpoints not in the payload must already exist in the graph, with a type the ontology accepts
    external = sorted({x for r in norm.relations for x in (r["source_id"], r["target_id"]) if x not in types})
    ext: dict[str, dict[str, Any]] = {}
    for part in chunks(external, batch):
        ext.update(graph.get_entities(part))
    for ref in external:
        if ref not in ext:
            plan.errors.append(Issue("ENTITY_NOT_FOUND", f"entity '{ref}' is referenced by a relation but exists neither in "
                                     "the payload nor in the graph", context={"entity_id": ref}))
        else:
            types[ref] = ext[ref].get("entity_type")
    for r in norm.relations:
        s, t = types.get(r["source_id"]), types.get(r["target_id"])
        if s and t and (r["source_id"] in ext or r["target_id"] in ext):  # in-payload pairs were checked by validate()
            msg = ontology.domain_range_error(r["relation_type"], s, t)
            if msg:
                plan.errors.append(Issue("ONTOLOGY_DOMAIN_RANGE_VIOLATION", msg, context={"relation_id": r["id"]}))

    # relations
    rel_existing: dict[str, dict[str, Any]] = {}
    for part in chunks([r["id"] for r in norm.relations], batch):
        rel_existing.update(graph.get_relations(part))
    for r in norm.relations:
        cur = rel_existing.get(r["id"])
        if cur is None:
            plan.relations["create"] += 1
            continue
        if mode == "insert":
            plan.conflicts.append(Issue("DUPLICATE_RELATION", f"relation '{r['id']}' already exists (mode=insert)",
                                        context={"relation_id": r["id"]}))
        elif (cur["type"], cur["source_id"], cur["target_id"]) != (r["relation_type"], r["source_id"], r["target_id"]):
            plan.conflicts.append(Issue("RELATION_IDENTITY_CONFLICT",
                                        f"relation '{r['id']}' exists with a different type/source/target; use a new relation id",
                                        context={"relation_id": r["id"]}))
        elif cur.get("source_document_id") != doc_id:
            plan.conflicts.append(Issue("RELATION_OWNED_BY_OTHER_DOCUMENT",
                                        f"relation '{r['id']}' belongs to document '{cur.get('source_document_id')}'",
                                        context={"relation_id": r["id"], "document_id": doc_id}))
        elif cur.get("content_hash") == r["content_hash"]:
            plan.relations["skip"] += 1
        else:
            plan.relations["update"] += 1
    return plan
