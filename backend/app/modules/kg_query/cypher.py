"""Cypher text. Every VALUE is a query parameter. Relationship TYPES cannot be parameterized, so they are
interpolated only through `rel_union()`, which regex-checks them and backtick-quotes them; the service also
checks them against the ontology allowlist before calling here. Nothing else is ever interpolated
(the path depth is an int clamped to 1..4)."""
from __future__ import annotations

import re
from typing import Iterable

from app.modules.kg_import.ontology import RELATION_TYPE_RE

_TYPES_FILTER = "($types IS NULL OR e.entity_type IN $types)"
_ENTITY_COLS = "e.id AS id, e.canonical_name AS name, e.entity_type AS type, coalesce(e.aliases, []) AS aliases"

# ---- entity resolution (stages are tried in order; the first stage with rows wins) -------------------------
RESOLVE_EXACT = f"""
MATCH (e:Entity {{normalized_name: $q}}) WHERE {_TYPES_FILTER}
RETURN {_ENTITY_COLS}
ORDER BY name LIMIT $limit
"""

RESOLVE_ALIAS = f"""
MATCH (e:Entity) WHERE any(a IN coalesce(e.aliases, []) WHERE toLower(a) = $q) AND {_TYPES_FILTER}
RETURN {_ENTITY_COLS}
ORDER BY name LIMIT $limit
"""

# needs the full-text index from scripts/setup_query_indexes.py
RESOLVE_FULLTEXT = f"""
CALL db.index.fulltext.queryNodes($index, $lucene) YIELD node AS e, score
WHERE {_TYPES_FILTER}
RETURN {_ENTITY_COLS}, score
ORDER BY score DESC LIMIT $limit
"""

RESOLVE_CONTAINS = f"""
MATCH (e:Entity)
WHERE (e.normalized_name CONTAINS $q OR any(a IN coalesce(e.aliases, []) WHERE toLower(a) CONTAINS $q))
  AND {_TYPES_FILTER}
RETURN {_ENTITY_COLS}
ORDER BY size(e.normalized_name), name LIMIT $limit
"""

# Same disease imported under two spellings (e.g. "mãn tính" / "mạn tính") = two nodes. Pull in nodes of the
# same type that share the name or any alias with an anchor, so their facts are not lost.
ALIAS_SIBLINGS = """
MATCH (a:Entity) WHERE a.id IN $ids
MATCH (o:Entity {entity_type: a.entity_type})
WHERE NOT (o.id IN $ids)
  AND (o.normalized_name = a.normalized_name
       OR any(x IN coalesce(a.aliases, []) WHERE toLower(trim(x)) = o.normalized_name)
       OR any(x IN coalesce(o.aliases, []) WHERE toLower(trim(x)) = a.normalized_name))
RETURN DISTINCT o.id AS id, o.canonical_name AS name, o.entity_type AS type, coalesce(o.aliases, []) AS aliases
LIMIT $limit
"""

_NEIGHBOR_TAIL = """
WHERE a.id IN $ids AND ($types IS NULL OR b.entity_type IN $types)
RETURN a.id AS anchor_id, r.id AS rel_id, type(r) AS rel,
       startNode(r).id AS source_id, startNode(r).canonical_name AS source_name, startNode(r).entity_type AS source_type,
       endNode(r).id AS target_id, endNode(r).canonical_name AS target_name, endNode(r).entity_type AS target_type,
       r.source_document_id AS doc_id, r.evidence_ids AS evidence_ids,
       r.source_proposition_ids AS proposition_ids, r.confidence AS confidence,
       r.properties_json AS properties_json
ORDER BY rel, target_name, rel_id
LIMIT $limit
"""

_ARROWS = {"out": "(a:Entity)-[r:{rels}]->(b:Entity)",
           "in": "(a:Entity)<-[r:{rels}]-(b:Entity)",
           "any": "(a:Entity)-[r:{rels}]-(b:Entity)"}


def safe_rel(name: str) -> str:
    if not RELATION_TYPE_RE.match(name):
        raise ValueError(f"unsafe relation type rejected: {name!r}")
    return f"`{name}`"


def rel_union(names: Iterable[str]) -> str:
    names = list(names)
    if not names:
        raise ValueError("empty relation list")
    return "|".join(safe_rel(n) for n in names)


def neighbors(direction: str, rel_names: Iterable[str]) -> str:
    """1-hop expansion from $ids. direction is relative to the anchor `a`: out | in | any."""
    return "MATCH " + _ARROWS[direction].format(rels=rel_union(rel_names)) + _NEIGHBOR_TAIL


def shortest_paths(rel_names: Iterable[str] | None, max_hops: int) -> str:
    hops = max(1, min(int(max_hops), 4))
    rels = (":" + rel_union(rel_names)) if rel_names else ""
    return f"""
MATCH (a:Entity), (b:Entity)
WHERE a.id IN $src AND b.id IN $dst AND a <> b
MATCH p = allShortestPaths((a)-[{rels}*..{hops}]-(b))
RETURN [n IN nodes(p) | {{id: n.id, name: n.canonical_name, type: n.entity_type}}] AS nodes,
       [r IN relationships(p) | {{id: r.id, type: type(r), source: startNode(r).id, target: endNode(r).id,
                                 doc_id: r.source_document_id, evidence_ids: r.evidence_ids,
                                 proposition_ids: r.source_proposition_ids, confidence: r.confidence, properties_json: r.properties_json}}] AS rels
LIMIT $limit
"""


_LUCENE_SPECIAL = re.compile(r'(&&|\|\||[+\-!(){}\[\]^"~*?:\\/])')


def lucene_query(folded_text: str) -> str:
    """All words must match. Input is already lower-cased, so no word can be read as AND/OR/NOT."""
    words = [_LUCENE_SPECIAL.sub(r"\\\1", w) for w in folded_text.split()]
    return " AND ".join(words)


FULLTEXT_INDEX_DDL = ("CREATE FULLTEXT INDEX {name} IF NOT EXISTS FOR (e:Entity) ON EACH [e.canonical_name, e.aliases] "
                      "OPTIONS {{indexConfig: {{`fulltext.analyzer`: 'standard-folding'}}}}")
