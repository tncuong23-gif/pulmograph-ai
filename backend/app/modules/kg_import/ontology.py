"""Ontology port.

The ontology is the allowlist for entity types and relation types (and optional domain/range).
Relation names are interpolated into Cypher (Cypher cannot parameterize relationship types), so
they are regex-checked here AND must be present in the allowlist before they ever reach a query.

Wire this to your project's existing source of truth with `Ontology.from_dict(...)`.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .errors import OntologyConfigError

ENTITY_TYPE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
RELATION_TYPE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


@dataclass(frozen=True)
class RelationSpec:
    name: str
    domain: frozenset[str] = field(default_factory=frozenset)  # empty = any
    range: frozenset[str] = field(default_factory=frozenset)  # empty = any


@dataclass(frozen=True)
class Ontology:
    entity_types: frozenset[str]
    relations: Mapping[str, RelationSpec]

    def has_entity_type(self, name: str) -> bool:
        return name in self.entity_types

    def has_relation(self, name: str) -> bool:
        return name in self.relations

    def relation_names(self) -> list[str]:
        return sorted(self.relations)

    def domain_range_error(self, relation: str, source_type: str, target_type: str) -> str | None:
        spec = self.relations.get(relation)
        if spec is None:
            return None
        if spec.domain and source_type not in spec.domain:
            return f"{relation} does not allow source type '{source_type}' (allowed: {sorted(spec.domain)})"
        if spec.range and target_type not in spec.range:
            return f"{relation} does not allow target type '{target_type}' (allowed: {sorted(spec.range)})"
        return None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Ontology":
        types = data.get("entity_types")
        rels = data.get("relation_types")
        if not isinstance(types, list) or not types:
            raise OntologyConfigError("ontology.entity_types must be a non-empty list")
        if not isinstance(rels, dict) or not rels:
            raise OntologyConfigError("ontology.relation_types must be a non-empty object")
        for t in types:
            if not isinstance(t, str) or not ENTITY_TYPE_RE.match(t):
                raise OntologyConfigError(f"invalid entity type name: {t!r}")
        tset = frozenset(types)
        specs: dict[str, RelationSpec] = {}
        for name, spec in rels.items():
            if not RELATION_TYPE_RE.match(name):
                raise OntologyConfigError(f"invalid relation type name: {name!r}")
            spec = spec or {}
            dom, rng = frozenset(spec.get("domain", [])), frozenset(spec.get("range", []))
            unknown = (dom | rng) - tset
            if unknown:
                raise OntologyConfigError(f"relation {name} references unknown entity types {sorted(unknown)}")
            specs[name] = RelationSpec(name, dom, rng)
        return cls(tset, specs)

    @classmethod
    def load(cls, path: str | Path) -> "Ontology":
        with open(path, "r", encoding="utf-8-sig") as fh:
            return cls.from_dict(json.load(fh))
