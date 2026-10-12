"""MongoDB adapter (pymongo). Collection names come from a fixed allowlist; user input never selects one."""
from __future__ import annotations

from typing import Any

from pymongo import ASCENDING, InsertOne, UpdateOne
from pymongo.database import Database

from ..models import MONGO_ID_FIELDS
from ..utils import chunks

IMPORTS = "imports"


class MongoKGStore:
    """Implements DocumentStore and JobStore on one pymongo Database (client pool is owned by the caller)."""

    def __init__(self, db: Database, batch_size: int = 1000) -> None:
        self.db, self.batch = db, batch_size

    def ensure_indexes(self) -> None:
        """Idempotent: create_index is a no-op when an identical index exists."""
        self.db["documents"].create_index([("document_id", ASCENDING)], unique=True, name="uq_document_id")
        for coll, id_field in MONGO_ID_FIELDS.items():
            if coll != "documents":
                self.db[coll].create_index([("document_id", ASCENDING), (id_field, ASCENDING)], unique=True,
                                           name=f"uq_document_{id_field}")
            self.db[coll].create_index([("import_id", ASCENDING)], name="ix_import_id")
        self.db[IMPORTS].create_index([("import_id", ASCENDING)], unique=True, name="uq_import_id")
        self.db[IMPORTS].create_index([("document_id", ASCENDING)], name="ix_import_document")

    def ping(self) -> None:
        self.db.client.admin.command("ping")

    # ---- DocumentStore
    def document_exists(self, document_id: str) -> bool:
        return self.db["documents"].count_documents({"document_id": document_id}, limit=1) > 0

    def existing_ids(self, collection: str, document_id: str, ids: list[str]) -> set[str]:
        f = MONGO_ID_FIELDS[collection]
        cur = self.db[collection].find({"document_id": document_id, f: {"$in": ids}}, {f: 1, "_id": 0})
        return {d[f] for d in cur}

    def write(self, records: dict[str, list[dict[str, Any]]], *, mode: str, import_id: str, now: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for coll, recs in records.items():
            id_field = MONGO_ID_FIELDS[coll]  # KeyError for anything outside the allowlist
            ops: list = []
            for r in recs:
                doc = {**r, "import_id": import_id, "updated_at": now}
                if mode == "insert":
                    ops.append(InsertOne({**doc, "created_at": now}))
                else:
                    flt = {"document_id": r["document_id"]} if coll == "documents" else \
                          {"document_id": r["document_id"], id_field: r[id_field]}
                    ops.append(UpdateOne(flt, {"$set": doc, "$setOnInsert": {"created_at": now}}, upsert=True))
            for part in chunks(ops, self.batch):
                self.db[coll].bulk_write(part, ordered=False)
            counts[coll] = len(recs)
        return counts

    def delete_stale(self, document_id: str, keep_import_id: str) -> dict[str, int]:
        return {c: self.db[c].delete_many({"document_id": document_id, "import_id": {"$ne": keep_import_id}}).deleted_count
                for c in MONGO_ID_FIELDS}

    def delete_by_import(self, document_id: str, import_id: str) -> dict[str, int]:
        return {c: self.db[c].delete_many({"document_id": document_id, "import_id": import_id}).deleted_count
                for c in MONGO_ID_FIELDS}

    # ---- JobStore
    def create_job(self, job: dict[str, Any]) -> None:
        self.db[IMPORTS].insert_one(dict(job))

    def update_job(self, import_id: str, fields: dict[str, Any]) -> None:
        self.db[IMPORTS].update_one({"import_id": import_id}, {"$set": fields})

    def get_job(self, import_id: str) -> dict[str, Any] | None:
        return self.db[IMPORTS].find_one({"import_id": import_id}, {"_id": 0})
