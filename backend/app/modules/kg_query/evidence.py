"""Neo4j stores only evidence ids. The text lives in MongoDB `evidence`, unique on (document_id, evidence_id)."""
from __future__ import annotations

from typing import Any, Iterable


class MongoEvidenceStore:
    def __init__(self, db: Any) -> None:
        self.coll = db["evidence"]

    def fetch(self, document_id: str, evidence_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
        cur = self.coll.find({"document_id": document_id, "evidence_id": {"$in": list(evidence_ids)}},
                             {"_id": 0, "evidence_id": 1, "text": 1, "sentence_id": 1, "paragraph_id": 1,
                              "section_id": 1})
        return {d["evidence_id"]: d for d in cur}
