"""Plain dataclasses (no third-party deps). `QuerySpec` is what the question-analysis step should emit."""
from __future__ import annotations

import json

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class EntityRef:
    id: str
    name: str
    type: str


@dataclass
class Anchor:
    entity: EntityRef
    matched_by: str  # exact_name | alias | fulltext | contains | alias_sibling
    score: float | None = None


@dataclass
class Fact:
    """One (subject, predicate, object) triple, merged across documents (same triple in 2 docs = 1 Fact)."""
    subject: EntityRef
    predicate: str
    object: EntityRef
    anchor_id: str  # the endpoint the query started from
    hop: int = 1
    relation_ids: list[str] = field(default_factory=list)
    doc_ids: list[str] = field(default_factory=list)
    evidence: dict[str, list[str]] = field(default_factory=dict)  # doc_id -> evidence_ids
    proposition_ids: list[str] = field(default_factory=list)
    confidence: float | None = None
    evidence_texts: list[dict[str, Any]] = field(default_factory=list)  # filled by attach_evidence()

    assertions: list[dict[str, Any]] = field(default_factory=list)

    @property
    def far_end(self) -> EntityRef:
        """The endpoint that is not the anchor (the 'answer' side)."""
        return self.object if self.subject.id == self.anchor_id else self.subject

    def add_row(self, row: Mapping[str, Any]) -> None:
        raw = row.get("properties_json")
        try:
            properties = json.loads(raw) if isinstance(raw, str) else (raw or {})
            valid = isinstance(properties, dict)
        except (ValueError, TypeError):
            properties, valid = {}, False
        assertion = {
            "relation_id": row.get("rel_id"), "document_id": row.get("doc_id"),
            "proposition_ids": list(row.get("proposition_ids") or []),
            "evidence_ids": list(row.get("evidence_ids") or []),
            "properties": properties if valid else {}, "properties_valid": valid,
            "confidence": row.get("confidence"),
        }
        if assertion not in self.assertions:
            self.assertions.append(assertion)
        _add(self.relation_ids, row.get("rel_id"))
        doc = row.get("doc_id")
        _add(self.doc_ids, doc)
        for ev in row.get("evidence_ids") or []:
            _add(self.evidence.setdefault(doc, []), ev)
        for pid in row.get("proposition_ids") or []:
            _add(self.proposition_ids, pid)
        if self.confidence is None:
            self.confidence = row.get("confidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": vars(self.subject), "predicate": self.predicate, "object": vars(self.object),
            "hop": self.hop, "relation_ids": self.relation_ids, "doc_ids": self.doc_ids,
            "proposition_ids": self.proposition_ids,
            "evidence_ids": self.evidence, "evidence": self.evidence_texts, "confidence": self.confidence,
            "assertions": self.assertions,
            "confidence_semantics": "source_metadata_not_disease_probability",
        }


def _add(lst: list, value: Any) -> None:
    if value is not None and value not in lst:
        lst.append(value)


@dataclass
class Answer:
    """Answer-level view of 1-hop facts: (predicate, far entity) merged across anchors and documents.
    Needed because one disease can exist as several nodes (spelling variants) that assert the same fact."""
    predicate: str
    entity: EntityRef
    asserted_by: list[str] = field(default_factory=list)  # names of the anchor nodes that state it
    doc_ids: list[str] = field(default_factory=list)
    relation_ids: list[str] = field(default_factory=list)
    evidence: dict[str, list[str]] = field(default_factory=dict)
    evidence_texts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"predicate": self.predicate, "entity": vars(self.entity), "asserted_by": self.asserted_by,
                "doc_ids": self.doc_ids, "relation_ids": self.relation_ids, "evidence_ids": self.evidence,
                "evidence": self.evidence_texts}


def merge_answers(facts: list["Fact"]) -> list[Answer]:
    out: dict[tuple[str, str], Answer] = {}
    for f in facts:
        far = f.far_end
        a = out.setdefault((f.predicate, far.id), Answer(f.predicate, far))
        anchor = f.subject if f.subject.id == f.anchor_id else f.object
        _add(a.asserted_by, anchor.name)
        for d in f.doc_ids:
            _add(a.doc_ids, d)
        for r in f.relation_ids:
            _add(a.relation_ids, r)
        for doc, ids in f.evidence.items():
            for e in ids:
                _add(a.evidence.setdefault(doc, []), e)
        seen = {(t["doc_id"], t["evidence_id"]) for t in a.evidence_texts}
        a.evidence_texts += [t for t in f.evidence_texts if (t["doc_id"], t["evidence_id"]) not in seen]
    return list(out.values())


@dataclass(frozen=True)
class Step:
    intent: str
    target_types: tuple[str, ...] | None = None
    include_previous: bool = False


@dataclass
class QuerySpec:
    mentions: list[str]
    intents: list[str] = field(default_factory=list)      # 1-hop: union of these intents (default: related)
    chain: list[Step] = field(default_factory=list)       # multi-hop: one step per hop
    path: bool = False                                    # connect mentions[0] and mentions[1]
    target_types: list[str] | None = None                 # filter the answer side (1-hop)
    anchor_types: list[str] | None = None                 # restrict entity resolution (e.g. ["Disease"])
    rel_types: list[str] | None = None                    # path mode only: restrict relation types
    max_hops: int = 3                                     # path mode only
    limit: int = 100
    notes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], presets: Mapping[str, tuple[Step, ...]] | None = None) -> "QuerySpec":
        """Structural parsing only (semantic checks against the ontology happen in the service)."""
        mentions = [str(m) for m in (data.get("mentions") or []) if str(m).strip()]
        chain_raw = data.get("chain") or []
        notes: list[str] = []
        if isinstance(chain_raw, str):
            if presets and chain_raw in presets:
                chain = list(presets[chain_raw])
            else:
                chain, notes = [], [f"unknown chain preset '{chain_raw}' ignored"]
        else:
            chain = [Step(s["intent"], tuple(s["target_types"]) if s.get("target_types") else None,
                          bool(s.get("include_previous", False))) for s in chain_raw]
        intents = data.get("intents") or ([data["intent"]] if data.get("intent") else [])
        return cls(
            mentions=mentions, intents=[str(i) for i in intents], chain=chain, path=bool(data.get("path", False)),
            target_types=data.get("target_types") or None, anchor_types=data.get("anchor_types") or None,
            rel_types=data.get("rel_types") or None, max_hops=int(data.get("max_hops", 3)),
            limit=int(data.get("limit", 100)), notes=notes,
        )


@dataclass
class PathResult:
    nodes: list[EntityRef]
    facts: list[Fact]  # one per edge, subject/object in the real edge direction


@dataclass
class QueryResult:
    status: str  # ok | no_entity | no_facts   (no_* -> caller should fall back to vector/hybrid search)
    anchors: dict[str, list[Anchor]] = field(default_factory=dict)
    facts: list[Fact] = field(default_factory=list)
    answers: list[Answer] = field(default_factory=list)  # 1-hop only: `facts` merged per (predicate, answer entity)
    chains: list[list[Fact]] = field(default_factory=list)
    paths: list[PathResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status, "notes": self.notes,
            "anchors": {m: [{**vars(a.entity), "matched_by": a.matched_by, "score": a.score} for a in v]
                        for m, v in self.anchors.items()},
            "facts": [f.to_dict() for f in self.facts],
            "answers": [a.to_dict() for a in self.answers],
            "chains": [[f.to_dict() for f in c] for c in self.chains],
            "paths": [{"nodes": [vars(n) for n in p.nodes], "facts": [f.to_dict() for f in p.facts]} for p in self.paths],
        }
