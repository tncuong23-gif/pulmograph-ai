"""Semantic validation. Pure function: no I/O, runs before any mutation.

References to entities that are NOT in the payload are not errors here: they may already exist
in the graph (from another document). The planner resolves those against Neo4j.
"""
from __future__ import annotations

import re
from collections import Counter

from .config import Limits
from .errors import Issue
from .models import KGImport
from .ontology import Ontology

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-]{0,127}$")


def find_external_refs(kg: KGImport) -> set[str]:
    known = {e.id for e in kg.entities}
    return {ref for r in kg.relations for ref in (r.source, r.target) if ref not in known}


def _dups(values: list[str], code: str, label: str, path: str) -> list[Issue]:
    return [
        Issue(code, f"duplicate {label} id '{v}' appears {n} times in the payload", path, {f"{label}_id": v})
        for v, n in Counter(values).items()
        if n > 1
    ]


def validate(kg: KGImport, ontology: Ontology, limits: Limits) -> list[Issue]:
    out: list[Issue] = []
    doc_id = kg.document.document_id

    if kg.schema_version not in limits.supported_schema_versions:
        out.append(Issue("SCHEMA_VERSION_UNSUPPORTED",
                         f"schema_version '{kg.schema_version}' not supported (supported: {list(limits.supported_schema_versions)})",
                         "$.schema_version"))
    if not ID_RE.match(doc_id):
        out.append(Issue("ID_INVALID", "document_id has an invalid format", "$.document.document_id", {"document_id": doc_id}))

    n_sent = sum(len(p.sentences) for s in kg.document.sections for p in s.paragraphs)
    for name, n, cap in (("entities", len(kg.entities), limits.max_entities),
                         ("relations", len(kg.relations), limits.max_relations),
                         ("propositions", len(kg.propositions), limits.max_propositions),
                         ("sentences", n_sent, limits.max_sentences)):
        if n > cap:
            out.append(Issue("IMPORT_TOO_LARGE", f"{n} {name} exceeds the limit of {cap}", f"$.{name}"))

    # ---- document structure -------------------------------------------------------------
    secs = [s.section_id for s in kg.document.sections]
    pars = [p.paragraph_id for s in kg.document.sections for p in s.paragraphs]
    sents = [n.sentence_id for s in kg.document.sections for p in s.paragraphs for n in p.sentences]
    out += _dups(secs, "DUPLICATE_SECTION", "section", "$.document.sections")
    out += _dups(pars, "DUPLICATE_PARAGRAPH", "paragraph", "$.document.sections")
    out += _dups(sents, "DUPLICATE_SENTENCE", "sentence", "$.document.sections")
    for label, ids in (("section", secs), ("paragraph", pars), ("sentence", sents)):
        for v in ids:
            if not ID_RE.match(v):
                out.append(Issue("ID_INVALID", f"{label} id '{v}' has an invalid format", "$.document", {f"{label}_id": v}))
    sentence_ids = set(sents)

    # ---- entities -----------------------------------------------------------------------
    out += _dups([e.id for e in kg.entities], "DUPLICATE_ENTITY", "entity", "$.entities")
    ent_type: dict[str, str] = {}
    for e in kg.entities:
        path = f"$.entities[{e.index}]"
        if not ID_RE.match(e.id):
            out.append(Issue("ID_INVALID", "entity id has an invalid format", path, {"entity_id": e.id}))
        if not e.canonical_name.strip():
            out.append(Issue("ENTITY_NAME_EMPTY", "canonical_name must not be empty", path, {"entity_id": e.id}))
        if not ontology.has_entity_type(e.type):
            out.append(Issue("ONTOLOGY_UNKNOWN_ENTITY_TYPE", f"entity type '{e.type}' is not in the ontology",
                             f"{path}.type", {"entity_id": e.id, "entity_type": e.type}))
        else:
            ent_type[e.id] = e.type

    # ---- propositions / evidence --------------------------------------------------------
    out += _dups([p.id for p in kg.propositions], "DUPLICATE_PROPOSITION", "proposition", "$.propositions")
    prop_ids = {p.id for p in kg.propositions}
    all_entity_ids = {e.id for e in kg.entities}
    rel_ids = {r.id for r in kg.relations}
    ev_ids: list[str] = []
    for p in kg.propositions:
        path = f"$.propositions[{p.index}]"
        if not ID_RE.match(p.id):
            out.append(Issue("ID_INVALID", "proposition id has an invalid format", path, {"proposition_id": p.id}))
        if limits.require_provenance and not p.evidence:
            out.append(Issue("PROVENANCE_MISSING", "proposition has no evidence", path, {"proposition_id": p.id}))
        for j, ev in enumerate(p.evidence):
            ep = f"{path}.evidence[{j}]"
            if ev.evidence_id:
                ev_ids.append(ev.evidence_id)
                if not ID_RE.match(ev.evidence_id):
                    out.append(Issue("ID_INVALID", "evidence_id has an invalid format", ep, {"evidence_id": ev.evidence_id}))
            if ev.sentence_id:
                if sentence_ids and ev.sentence_id not in sentence_ids:
                    out.append(Issue("EVIDENCE_SENTENCE_NOT_FOUND",
                                     f"sentence '{ev.sentence_id}' is not defined in document.sections",
                                     ep, {"proposition_id": p.id, "sentence_id": ev.sentence_id}))
                elif not sentence_ids and not ev.text:
                    out.append(Issue("EVIDENCE_UNVERIFIABLE",
                                     "document defines no sentences, so evidence must carry its own 'text'",
                                     ep, {"proposition_id": p.id, "sentence_id": ev.sentence_id}))
            elif not ev.text:
                out.append(Issue("EVIDENCE_EMPTY", "evidence needs a sentence_id or text", ep, {"proposition_id": p.id}))
        for ref in p.entity_ids:
            if ref not in all_entity_ids:
                out.append(Issue("PROPOSITION_ENTITY_NOT_FOUND", f"entity '{ref}' is not in the payload",
                                 f"{path}.entity_ids", {"proposition_id": p.id, "entity_id": ref}))
        for ref in p.relation_ids:
            if ref not in rel_ids:
                out.append(Issue("PROPOSITION_RELATION_NOT_FOUND", f"relation '{ref}' is not in the payload",
                                 f"{path}.relation_ids", {"proposition_id": p.id, "relation_id": ref}))
    out += _dups(ev_ids, "DUPLICATE_EVIDENCE", "evidence", "$.propositions")

    # ---- relations ----------------------------------------------------------------------
    out += _dups([r.id for r in kg.relations], "DUPLICATE_RELATION", "relation", "$.relations")
    evidence_by_prop = {p.id: len(p.evidence) for p in kg.propositions}
    for r in kg.relations:
        path = f"$.relations[{r.index}]"
        if not ID_RE.match(r.id):
            out.append(Issue("ID_INVALID", "relation id has an invalid format", path, {"relation_id": r.id}))
        if not ontology.has_relation(r.type):
            out.append(Issue("ONTOLOGY_UNKNOWN_RELATION_TYPE", f"relation type '{r.type}' is not in the ontology",
                             f"{path}.type", {"relation_id": r.id, "relation_type": r.type}))
        elif r.source in ent_type and r.target in ent_type:
            msg = ontology.domain_range_error(r.type, ent_type[r.source], ent_type[r.target])
            if msg:
                out.append(Issue("ONTOLOGY_DOMAIN_RANGE_VIOLATION", msg, path, {"relation_id": r.id}))
        if limits.require_provenance and not r.proposition_ids:
            out.append(Issue("PROVENANCE_MISSING", "relation must reference at least one proposition", path, {"relation_id": r.id}))
        for pid in r.proposition_ids:
            if pid not in prop_ids:
                out.append(Issue("RELATION_PROPOSITION_NOT_FOUND", f"proposition '{pid}' is not in the payload",
                                 f"{path}.proposition_ids", {"relation_id": r.id, "proposition_id": pid}))
            elif limits.require_provenance and evidence_by_prop.get(pid, 0) == 0:
                out.append(Issue("PROVENANCE_MISSING", f"proposition '{pid}' has no evidence", path,
                                 {"relation_id": r.id, "proposition_id": pid}))
    return out
