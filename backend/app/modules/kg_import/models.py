"""Input model + structural (schema) parsing.

Parsing collects ALL structural problems instead of failing on the first one.
Nothing is guessed or auto-corrected here; wrong shapes are reported.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .errors import Issue

# Mongo collection -> name of its id field. Fixed allowlist: user input never picks a collection.
MONGO_ID_FIELDS: dict[str, str] = {
    "documents": "document_id",
    "sections": "section_id",
    "paragraphs": "paragraph_id",
    "sentences": "sentence_id",
    "propositions": "proposition_id",
    "evidence": "evidence_id",
}


@dataclass(frozen=True)
class SentenceIn:
    sentence_id: str
    text: str
    paragraph_id: str
    section_id: str
    order: int


@dataclass(frozen=True)
class ParagraphIn:
    paragraph_id: str
    section_id: str
    order: int
    sentences: tuple[SentenceIn, ...]


@dataclass(frozen=True)
class SectionIn:
    section_id: str
    title: str | None
    order: int
    paragraphs: tuple[ParagraphIn, ...]


@dataclass(frozen=True)
class DocumentIn:
    document_id: str
    title: str
    document_type: str | None
    language: str | None
    metadata: dict[str, Any]
    sections: tuple[SectionIn, ...]


@dataclass(frozen=True)
class EntityIn:
    id: str
    type: str
    canonical_name: str
    aliases: tuple[str, ...]
    properties: dict[str, Any]
    index: int


@dataclass(frozen=True)
class RelationIn:
    id: str
    type: str
    source: str
    target: str
    properties: dict[str, Any]
    confidence: float | None
    proposition_ids: tuple[str, ...]
    index: int


@dataclass(frozen=True)
class EvidenceIn:
    evidence_id: str | None
    sentence_id: str | None
    text: str | None
    location: dict[str, Any]


@dataclass(frozen=True)
class PropositionIn:
    id: str
    text: str
    evidence: tuple[EvidenceIn, ...]
    entity_ids: tuple[str, ...]
    relation_ids: tuple[str, ...]
    index: int


@dataclass(frozen=True)
class KGImport:
    schema_version: str
    document: DocumentIn
    entities: tuple[EntityIn, ...]
    relations: tuple[RelationIn, ...]
    propositions: tuple[PropositionIn, ...]


class _Parser:
    def __init__(self) -> None:
        self.issues: list[Issue] = []

    def err(self, code: str, message: str, path: str, **ctx: Any) -> None:
        self.issues.append(Issue(code, message, path, ctx))

    def obj(self, value: Any, path: str) -> dict | None:
        if isinstance(value, dict):
            return value
        self.err("SCHEMA_INVALID_TYPE", "expected an object", path)
        return None

    def arr(self, value: Any, path: str, required: bool = False) -> list:
        if value is None:
            if required:
                self.err("SCHEMA_REQUIRED_FIELD", "field is required", path)
            return []
        if not isinstance(value, list):
            self.err("SCHEMA_INVALID_TYPE", "expected an array", path)
            return []
        return value

    def s(self, d: dict, key: str, path: str, required: bool = True, **ctx: Any) -> str | None:
        v = d.get(key)
        p = f"{path}.{key}"
        if v is None:
            if required:
                self.err("SCHEMA_REQUIRED_FIELD", f"'{key}' is required", p, **ctx)
            return None
        if not isinstance(v, str):
            self.err("SCHEMA_INVALID_TYPE", f"'{key}' must be a string", p, **ctx)
            return None
        if not v.strip():
            if required:
                self.err("SCHEMA_EMPTY_FIELD", f"'{key}' must not be empty", p, **ctx)
            return None
        return v

    def str_list(self, d: dict, key: str, path: str) -> tuple[str, ...]:
        raw = self.arr(d.get(key), f"{path}.{key}")
        out: list[str] = []
        for i, v in enumerate(raw):
            if isinstance(v, str) and v.strip():
                out.append(v)
            else:
                self.err("SCHEMA_INVALID_TYPE", "expected a non-empty string", f"{path}.{key}[{i}]")
        return tuple(out)

    def props(self, d: dict, key: str, path: str) -> dict[str, Any]:
        v = d.get(key)
        if v is None:
            return {}
        if not isinstance(v, dict):
            self.err("SCHEMA_INVALID_TYPE", f"'{key}' must be an object", f"{path}.{key}")
            return {}
        try:
            json.dumps(v)
        except (TypeError, ValueError):
            self.err("SCHEMA_INVALID_TYPE", f"'{key}' must be JSON-serializable", f"{path}.{key}")
            return {}
        return v


def parse_import(payload: Any) -> tuple[KGImport | None, list[Issue]]:
    """Return (KGImport, issues). If issues is non-empty the KGImport must not be used."""
    p = _Parser()
    root = p.obj(payload, "$")
    if root is None:
        return None, p.issues

    version = p.s(root, "schema_version", "$")
    doc_raw = p.obj(root.get("document"), "$.document") if root.get("document") is not None else None
    if doc_raw is None and root.get("document") is None:
        p.err("SCHEMA_REQUIRED_FIELD", "'document' is required", "$.document")

    document: DocumentIn | None = None
    if doc_raw is not None:
        doc_id = p.s(doc_raw, "document_id", "$.document")
        title = p.s(doc_raw, "title", "$.document")
        sections: list[SectionIn] = []
        for si, sraw in enumerate(p.arr(doc_raw.get("sections"), "$.document.sections")):
            sp = f"$.document.sections[{si}]"
            sd = p.obj(sraw, sp)
            if sd is None:
                continue
            sec_id = p.s(sd, "section_id", sp)
            paragraphs: list[ParagraphIn] = []
            for pi, praw in enumerate(p.arr(sd.get("paragraphs"), f"{sp}.paragraphs")):
                pp = f"{sp}.paragraphs[{pi}]"
                pd = p.obj(praw, pp)
                if pd is None:
                    continue
                par_id = p.s(pd, "paragraph_id", pp)
                sentences: list[SentenceIn] = []
                for ni, nraw in enumerate(p.arr(pd.get("sentences"), f"{pp}.sentences")):
                    np_ = f"{pp}.sentences[{ni}]"
                    nd = p.obj(nraw, np_)
                    if nd is None:
                        continue
                    sid, stext = p.s(nd, "sentence_id", np_), p.s(nd, "text", np_)
                    if sid and stext and par_id and sec_id:
                        sentences.append(SentenceIn(sid, stext, par_id, sec_id, ni))
                if par_id and sec_id:
                    paragraphs.append(ParagraphIn(par_id, sec_id, pi, tuple(sentences)))
            if sec_id:
                sections.append(SectionIn(sec_id, p.s(sd, "title", sp, required=False), si, tuple(paragraphs)))
        if doc_id and title:
            document = DocumentIn(
                doc_id,
                title,
                p.s(doc_raw, "document_type", "$.document", required=False),
                p.s(doc_raw, "language", "$.document", required=False),
                p.props(doc_raw, "metadata", "$.document"),
                tuple(sections),
            )

    entities: list[EntityIn] = []
    for i, raw in enumerate(p.arr(root.get("entities"), "$.entities", required=True)):
        path = f"$.entities[{i}]"
        d = p.obj(raw, path)
        if d is None:
            continue
        eid = p.s(d, "id", path)
        etype = p.s(d, "type", path, entity_id=eid)
        name = p.s(d, "canonical_name", path, entity_id=eid)
        aliases = p.str_list(d, "aliases", path)
        props = p.props(d, "properties", path)
        if eid and etype and name:
            entities.append(EntityIn(eid, etype, name, aliases, props, i))

    relations: list[RelationIn] = []
    for i, raw in enumerate(p.arr(root.get("relations"), "$.relations")):
        path = f"$.relations[{i}]"
        d = p.obj(raw, path)
        if d is None:
            continue
        rid = p.s(d, "id", path)
        rtype = p.s(d, "type", path, relation_id=rid)
        src = p.s(d, "source", path, relation_id=rid)
        tgt = p.s(d, "target", path, relation_id=rid)
        conf = d.get("confidence")
        if conf is not None and (isinstance(conf, bool) or not isinstance(conf, (int, float)) or not 0 <= conf <= 1):
            p.err("SCHEMA_INVALID_VALUE", "'confidence' must be a number in [0, 1]", f"{path}.confidence", relation_id=rid)
            conf = None
        pids = p.str_list(d, "proposition_ids", path)
        props = p.props(d, "properties", path)
        if rid and rtype and src and tgt:
            relations.append(RelationIn(rid, rtype, src, tgt, props, float(conf) if conf is not None else None, pids, i))

    propositions: list[PropositionIn] = []
    for i, raw in enumerate(p.arr(root.get("propositions"), "$.propositions")):
        path = f"$.propositions[{i}]"
        d = p.obj(raw, path)
        if d is None:
            continue
        pid = p.s(d, "id", path)
        text = p.s(d, "text", path, proposition_id=pid)
        ev: list[EvidenceIn] = []
        for j, eraw in enumerate(p.arr(d.get("evidence"), f"{path}.evidence")):
            ep = f"{path}.evidence[{j}]"
            ed = p.obj(eraw, ep)
            if ed is None:
                continue
            ev.append(
                EvidenceIn(
                    p.s(ed, "evidence_id", ep, required=False),
                    p.s(ed, "sentence_id", ep, required=False),
                    p.s(ed, "text", ep, required=False),
                    p.props(ed, "location", ep),
                )
            )
        eids, rids = p.str_list(d, "entity_ids", path), p.str_list(d, "relation_ids", path)
        if pid and text:
            propositions.append(PropositionIn(pid, text, tuple(ev), eids, rids, i))

    if p.issues or document is None or version is None:
        return None, p.issues
    return KGImport(version, document, tuple(entities), tuple(relations), tuple(propositions)), []
