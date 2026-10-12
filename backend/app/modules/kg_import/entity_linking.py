"""Conservative, exact entity linking before import normalization and provenance writes.

No fuzzy matching: a name/alias must match exactly after the project's existing fold().
Ambiguous matches stop the import so different medical concepts are never silently combined.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import replace
from typing import Any

from .errors import Issue, ValidationError
from .models import KGImport
from .ports import GraphStore
from .utils import clean_text, fold


def _strong_match(incoming: dict[str, Any], candidate: dict[str, Any]) -> bool:
    # A shared generic alias alone is not enough to assert medical concept identity.
    a, b = fold(incoming["canonical_name"]), fold(candidate["canonical_name"])
    return a == b or a in {fold(x) for x in candidate.get("aliases") or []} or \
        b in {fold(x) for x in incoming.get("aliases") or []}


def _aliases(values: list[str], canonical: str) -> tuple[str, ...]:
    seen = {fold(canonical)}
    out = []
    for value in values:
        name = clean_text(value)
        key = fold(name)
        if key and key not in seen:
            seen.add(key)
            out.append(name)
    return tuple(out)


def link_entities(kg: KGImport, graph: GraphStore, decisions: dict[str, str] | None = None) -> tuple[KGImport, dict[str, str]]:
    """Return a copy of the payload with globally resolved ids and all references rewritten."""
    decisions = decisions or {}
    ids = [e.id for e in kg.entities]
    ids += [i for i in decisions.values() if i != "new"]
    names = sorted({fold(x) for e in kg.entities for x in (e.canonical_name, *e.aliases)})
    types = sorted({e.type for e in kg.entities})
    existing = graph.find_entity_candidates(ids, names, types) if ids else []
    by_id = {r["id"]: r for r in existing}
    issues: list[Issue] = []
    mapping: dict[str, str] = {}
    targets: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    canonical_ids, alias_ids = defaultdict(set), defaultdict(set)
    def index_names(row):
        kind, eid = row['entity_type'], row['id']
        canonical_ids[(kind, fold(row['canonical_name']))].add(eid)
        for alias in row.get('aliases') or []: alias_ids[(kind, fold(alias))].add(eid)
    for row in existing: index_names(row)

    unknown = set(decisions) - {e.id for e in kg.entities}
    for key in sorted(unknown):
        issues.append(Issue("ENTITY_LINK_DECISION_INVALID", f"decision refers to unknown input id '{key}'"))

    for e in kg.entities:
        incoming = {"id": e.id, "entity_type": e.type, "canonical_name": clean_text(e.canonical_name),
                    "aliases": list(e.aliases), "properties": e.properties}
        same_id = by_id.get(e.id)
        forced_id = decisions.get(e.id)
        forced = by_id.get(forced_id) if forced_id and forced_id != "new" else None
        if same_id and forced and forced_id != e.id:
            issues.append(Issue("ENTITY_LINK_DECISION_INVALID", "an existing input id cannot be redirected to another id",
                                f"$.entity_link_decisions.{e.id}"))
            continue
        if forced_id and forced_id != "new" and forced is None:
            issues.append(Issue("ENTITY_LINK_DECISION_INVALID", f"chosen entity '{forced_id}' does not exist",
                                f"$.entity_link_decisions.{e.id}"))
            continue
        if forced and forced["entity_type"] != e.type:
            issues.append(Issue("ENTITY_TYPE_CONFLICT", f"chosen entity '{forced_id}' has a different type",
                                f"$.entity_link_decisions.{e.id}"))
            continue
        if same_id and same_id["entity_type"] != e.type:
            issues.append(Issue("ENTITY_TYPE_CONFLICT", f"entity '{e.id}' already has type '{same_id['entity_type']}'",
                                f"$.entities[{e.index}].type"))
            continue

        # Prefer an explicitly reused id. For new ids, all exact name/alias matches must agree.
        ids_matching = set()
        # 'new' may reject a semantic/alias proposal, but cannot duplicate an exact canonical name.
        ids_matching.update(canonical_ids[(e.type, fold(e.canonical_name))])
        if forced_id != 'new':
            name_key = (e.type, fold(e.canonical_name))
            ids_matching.update(canonical_ids[name_key]); ids_matching.update(alias_ids[name_key])
            for alias in e.aliases: ids_matching.update(canonical_ids[(e.type, fold(alias))])
        matches = {i: targets.get(i) or by_id[i] for i in sorted(ids_matching)}
        if same_id:
            matches[e.id] = same_id
        if len(matches) > 1 and not forced:
            issues.append(Issue("ENTITY_LINK_AMBIGUOUS",
                                f"entity '{e.id}' matches multiple existing entities: {sorted(matches)}",
                                f"$.entities[{e.index}]", {"candidate_ids": sorted(matches)}))
            continue
        target_id = forced_id if forced else (e.id if same_id else next(iter(matches), e.id))
        mapping[e.id] = target_id
        base = targets.get(target_id) or by_id.get(target_id)
        if base is None:
            targets[target_id] = incoming
            order.append(target_id)
        else:
            if base["entity_type"] != e.type:
                issues.append(Issue("ENTITY_TYPE_CONFLICT", f"entity '{e.id}' resolves to a different type",
                                    f"$.entities[{e.index}].type"))
                continue
            # An explicitly reused id retains the module's normal upsert behavior: its new
            # canonical name may be an intentional edit. A newly linked id keeps the stored name.
            explicit_update = same_id is not None and e.id == target_id
            canonical = clean_text(e.canonical_name) if explicit_update else base["canonical_name"]
            combined = [base["canonical_name"], *(base.get("aliases") or []), e.canonical_name, *e.aliases]
            props = base.get("properties")
            if props is None:
                try:
                    props = json.loads(base.get("properties_json") or "{}")
                except (ValueError, TypeError):
                    props = {}
            if not explicit_update and e.properties and props and e.properties != props:
                issues.append(Issue("ENTITY_PROPERTY_CONFLICT", "Tên khớp nhưng thuộc tính khác nhau; cần rà soát khái niệm trước khi liên kết.", f"$.entities[{e.index}]"))
                continue
            targets[target_id] = {"id": target_id, "entity_type": e.type, "canonical_name": canonical,
                                  "aliases": list(_aliases(combined, canonical)),
                                  "properties": e.properties or props}
            if target_id not in order:
                order.append(target_id)

        index_names(targets[target_id])

    if issues:
        raise ValidationError("entity linking requires review", issues=issues)

    # Keep one entity definition per resolved id and rewrite both graph and Mongo provenance references.
    representative = {mapping[e.id]: e for e in kg.entities if e.id in mapping}
    entities = tuple(replace(representative[i], id=i, canonical_name=targets[i]["canonical_name"],
                             aliases=_aliases(targets[i]["aliases"], targets[i]["canonical_name"]),
                             properties=targets[i]["properties"]) for i in order)
    relations = tuple(replace(r, source=mapping.get(r.source, r.source), target=mapping.get(r.target, r.target))
                      for r in kg.relations)
    propositions = tuple(replace(p, entity_ids=tuple(dict.fromkeys(mapping.get(i, i) for i in p.entity_ids)))
                         for p in kg.propositions)
    return replace(kg, entities=entities, relations=relations, propositions=propositions), \
        {source: dest for source, dest in mapping.items() if source != dest}
