"""Normalization with explicit, documented rules only:

* strings: Unicode NFC, trimmed, internal whitespace collapsed
* normalized_name: case-folded canonical_name (accents are NOT stripped)
* aliases: cleaned, empty removed, de-duplicated (order preserved)
* evidence_id (when absent): deterministic  EVD_<proposition_id>_<sentence_id|index>
* relation.evidence_ids: derived from the propositions the relation references
Nothing else is inferred. Types/ids are never "fixed up"; wrong values were rejected by validation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .models import KGImport
from .utils import clean_text, fold, sha256_of


@dataclass
class NormalizedImport:
    document_id: str
    entities: list[dict[str, Any]] = field(default_factory=list)
    relations: list[dict[str, Any]] = field(default_factory=list)
    mongo: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


def normalize(kg: KGImport) -> NormalizedImport:
    doc = kg.document
    out = NormalizedImport(document_id=doc.document_id)

    for e in kg.entities:
        aliases = list(dict.fromkeys(a for a in (clean_text(a) for a in e.aliases) if a))
        name = clean_text(e.canonical_name)
        core = {"entity_type": e.type, "canonical_name": name, "aliases": aliases, "properties": e.properties}
        out.entities.append({
            "id": e.id, "entity_type": e.type, "canonical_name": name, "normalized_name": fold(name),
            "aliases": aliases, "properties_json": json.dumps(e.properties, ensure_ascii=False, sort_keys=True),
            "content_hash": sha256_of(core),
        })

    sentence_text = {n.sentence_id: n for s in doc.sections for p in s.paragraphs for n in p.sentences}
    evidence_recs: list[dict[str, Any]] = []
    prop_recs: list[dict[str, Any]] = []
    prop_evidence: dict[str, list[str]] = {}
    for p in kg.propositions:
        ev_ids: list[str] = []
        sent_ids: list[str] = []
        for j, ev in enumerate(p.evidence):
            eid = ev.evidence_id or f"EVD_{p.id}_{ev.sentence_id or j}"
            sent = sentence_text.get(ev.sentence_id) if ev.sentence_id else None
            ev_ids.append(eid)
            if ev.sentence_id:
                sent_ids.append(ev.sentence_id)
            evidence_recs.append({
                "document_id": doc.document_id, "evidence_id": eid, "proposition_id": p.id,
                "sentence_id": ev.sentence_id,
                "paragraph_id": sent.paragraph_id if sent else None,
                "section_id": sent.section_id if sent else None,
                "text": clean_text(ev.text) if ev.text else (sent.text if sent else None),
                "location": ev.location,
                "source": {"document_id": doc.document_id, "title": doc.title},
            })
        prop_evidence[p.id] = ev_ids
        prop_recs.append({
            "document_id": doc.document_id, "proposition_id": p.id, "text": clean_text(p.text),
            "sentence_ids": sent_ids, "evidence_ids": ev_ids,
            "entity_ids": list(p.entity_ids), "relation_ids": list(p.relation_ids),
        })

    rel_by_prop: dict[str, list[str]] = {}
    for r in kg.relations:
        pids = list(dict.fromkeys(r.proposition_ids))
        evs = list(dict.fromkeys(x for pid in pids for x in prop_evidence.get(pid, [])))
        for pid in pids:
            rel_by_prop.setdefault(pid, []).append(r.id)
        core = {"type": r.type, "source": r.source, "target": r.target, "confidence": r.confidence,
                "properties": r.properties, "propositions": pids, "evidence": evs}
        out.relations.append({
            "id": r.id, "relation_type": r.type, "source_id": r.source, "target_id": r.target,
            "confidence": r.confidence, "properties_json": json.dumps(r.properties, ensure_ascii=False, sort_keys=True),
            "proposition_ids": pids, "evidence_ids": evs, "content_hash": sha256_of(core),
        })
    for rec in prop_recs:  # relations that cite a proposition are linked back to it
        rec["relation_ids"] = list(dict.fromkeys(rec["relation_ids"] + rel_by_prop.get(rec["proposition_id"], [])))

    out.mongo = {
        "documents": [{
            "document_id": doc.document_id, "schema_version": kg.schema_version, "title": clean_text(doc.title),
            "document_type": doc.document_type, "language": doc.language, "metadata": doc.metadata,
        }],
        "sections": [{"document_id": doc.document_id, "section_id": s.section_id, "title": s.title, "order": s.order}
                     for s in doc.sections],
        "paragraphs": [{"document_id": doc.document_id, "paragraph_id": p.paragraph_id, "section_id": s.section_id,
                        "order": p.order} for s in doc.sections for p in s.paragraphs],
        "sentences": [{"document_id": doc.document_id, "sentence_id": n.sentence_id, "paragraph_id": n.paragraph_id,
                       "section_id": n.section_id, "order": n.order, "text": n.text}
                      for s in doc.sections for p in s.paragraphs for n in p.sentences],
        "propositions": prop_recs,
        "evidence": evidence_recs,
    }
    return out
