"""In-memory stores implementing the ports with the SAME semantics as the real adapters.

Used for unit tests and dry local runs. Failure injection: set `fail_on_write` / `fail_on_delete`.
"""
from __future__ import annotations

import copy
from typing import Any

from ..models import MONGO_ID_FIELDS
from ..ports import GraphWriteResult
from ..utils import fold


class MemoryDocumentStore:
    def __init__(self) -> None:
        self.data: dict[str, dict[tuple[str, str], dict[str, Any]]] = {c: {} for c in MONGO_ID_FIELDS}
        self.fail_on_write = False
        self.fail_on_delete = False

    def ensure_indexes(self) -> None: ...

    def ping(self) -> None: ...

    def _key(self, coll: str, rec: dict) -> tuple[str, str]:
        return rec["document_id"], rec[MONGO_ID_FIELDS[coll]]

    def document_exists(self, document_id: str) -> bool:
        return any(k[0] == document_id for k in self.data["documents"])

    def existing_ids(self, collection: str, document_id: str, ids: list[str]) -> set[str]:
        return {k[1] for k in self.data[collection] if k[0] == document_id and k[1] in set(ids)}

    def write(self, records, *, mode, import_id, now):
        if self.fail_on_write:
            raise RuntimeError("injected mongo failure")
        if mode == "insert":
            for coll, recs in records.items():
                for r in recs:
                    if self._key(coll, r) in self.data[coll]:
                        raise RuntimeError(f"duplicate key in {coll}")
        counts = {}
        for coll, recs in records.items():
            for r in recs:
                key = self._key(coll, r)
                created = self.data[coll].get(key, {}).get("created_at", now)
                self.data[coll][key] = {**copy.deepcopy(r), "import_id": import_id, "created_at": created, "updated_at": now}
            counts[coll] = len(recs)
        return counts

    def delete_stale(self, document_id, keep_import_id):
        if self.fail_on_delete:
            raise RuntimeError("injected mongo delete failure")
        out = {}
        for coll, d in self.data.items():
            stale = [k for k, v in d.items() if k[0] == document_id and v["import_id"] != keep_import_id]
            for k in stale:
                del d[k]
            out[coll] = len(stale)
        return out

    def delete_by_import(self, document_id, import_id):
        if self.fail_on_delete:
            raise RuntimeError("injected mongo delete failure")
        out = {}
        for coll, d in self.data.items():
            gone = [k for k, v in d.items() if k[0] == document_id and v["import_id"] == import_id]
            for k in gone:
                del d[k]
            out[coll] = len(gone)
        return out

    def count(self, coll: str) -> int:
        return len(self.data[coll])


class MemoryJobStore:
    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, Any]] = {}

    def create_job(self, job): self.jobs[job["import_id"]] = copy.deepcopy(job)

    def update_job(self, import_id, fields): self.jobs[import_id].update(copy.deepcopy(fields))

    def get_job(self, import_id): return copy.deepcopy(self.jobs.get(import_id))


class MemoryGraphStore:
    def __init__(self) -> None:
        self.entities: dict[str, dict[str, Any]] = {}
        self.relations: dict[str, dict[str, Any]] = {}
        self.fail_on_write = False

    def ensure_constraints(self, relation_types): return ["entity_id_unique (memory)"]

    def ping(self) -> None: ...

    def get_entities(self, ids):
        return {i: {"entity_type": self.entities[i]["entity_type"], "content_hash": self.entities[i]["content_hash"]}
                for i in ids if i in self.entities}

    def find_entity_candidates(self, ids, names, types):
        wanted_ids, wanted_names, wanted_types = set(ids), set(names), set(types)
        return [copy.deepcopy(e) for e in self.entities.values()
                if e["id"] in wanted_ids or
                ((not wanted_types or e["entity_type"] in wanted_types) and
                 (e["normalized_name"] in wanted_names or any(fold(a) in wanted_names for a in e.get("aliases", []))))]

    def list_entities(self, after_id, limit):
        return [copy.deepcopy(self.entities[k]) for k in sorted(self.entities) if k > after_id][:limit]

    def get_entity_context(self, entity_id, limit=50):
        if entity_id not in self.entities:
            return None
        e = copy.deepcopy(self.entities[entity_id])
        e["relations"] = [{"id": r["id"], "predicate": r["type"], "source_id": r["source_id"],
                           "target_id": r["target_id"], "other_id": (r["target_id"] if r["source_id"] == entity_id
                                                                 else r["source_id"]),
                           "other_name": self.entities[(r["target_id"] if r["source_id"] == entity_id else
                                                         r["source_id"])]["canonical_name"],
                           "document_id": r.get("source_document_id"),
                           "proposition_ids": r.get("proposition_ids", []),
                           "evidence_ids": r.get("evidence_ids", [])}
                          for r in self.relations.values() if entity_id in (r["source_id"], r["target_id"])][:limit]
        return e

    def get_relations(self, ids):
        keys = ("type", "source_id", "target_id", "content_hash", "source_document_id")
        return {i: {k: self.relations[i][k] for k in keys} for i in ids if i in self.relations}

    def write(self, entities, relations, *, document_id, import_id, now, replace):
        if self.fail_on_write:
            raise RuntimeError("injected neo4j failure")
        ents, rels = copy.deepcopy(self.entities), copy.deepcopy(self.relations)  # atomic: commit only on success
        res = GraphWriteResult()
        for e in entities:
            cur = ents.get(e["id"])
            if cur is None:
                res.entities_created += 1
                cur = {"created_at": now, "source_ids": []}
                ents[e["id"]] = cur
            cur.update({k: v for k, v in e.items()}, updated_at=now, import_id=import_id)
            if document_id not in cur["source_ids"]:
                cur["source_ids"].append(document_id)
        for r in relations:
            if r["source_id"] not in ents or r["target_id"] not in ents:
                raise RuntimeError(f"relation {r['id']} endpoint missing")
            if r["id"] not in rels:
                res.relations_created += 1
            rels[r["id"]] = {"type": r["relation_type"], **{k: v for k, v in r.items() if k != "relation_type"},
                             "source_document_id": document_id, "import_id": import_id}
        if replace:
            stale_r = [i for i, r in rels.items() if r["source_document_id"] == document_id and r["import_id"] != import_id]
            for i in stale_r:
                del rels[i]
            res.relations_deleted = len(stale_r)
            for i, e in list(ents.items()):
                if document_id in e["source_ids"] and e["import_id"] != import_id:
                    e["source_ids"].remove(document_id)
                    res.entities_unlinked += 1
                    connected = any(i in (r["source_id"], r["target_id"]) for r in rels.values())
                    if not e["source_ids"] and not connected:
                        del ents[i]
                        res.entities_deleted += 1
        self.entities, self.relations = ents, rels
        return res
