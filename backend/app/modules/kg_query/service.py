"""Read-only query service over the KG written by kg_import.

    question -> (question analysis) -> QuerySpec -> KGQueryService.run() -> facts + evidence -> answer

Only `execute_read` is ever used. Nothing here writes to Neo4j or Mongo.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable

from app.modules.kg_import.ontology import Ontology
from app.modules.kg_import.utils import clean_text, fold

from . import cypher
from .intents import CATCH_ALL, PRESET_CHAINS, build_intents
from .models import Anchor, EntityRef, Fact, PathResult, QueryResult, QuerySpec, Step, merge_answers

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class QueryLimits:
    max_candidates: int = 5      # entity candidates per mention
    max_anchors: int = 8         # anchors per mention after alias-sibling expansion
    per_query_rows: int = 200    # rows per Cypher call
    max_frontier: int = 50       # nodes carried from one chain step to the next
    max_chains: int = 100
    max_paths: int = 5
    evidence_per_fact: int = 3


class KGQueryService:
    def __init__(self, driver: Any, ontology: Ontology, *, database: str = "neo4j", limits: QueryLimits | None = None,
                 evidence_store: Any | None = None, fulltext_index: str = "entity_names",
                 merge_alias_siblings: bool = True) -> None:
        self.driver, self.ontology, self.database = driver, ontology, database
        self.limits = limits or QueryLimits()
        self.evidence_store = evidence_store
        self.fulltext_index = fulltext_index
        self.merge_alias_siblings = merge_alias_siblings
        self.intents = build_intents(ontology)

    # ------------------------------------------------------------------ plumbing
    def _read(self, query: str, **params: Any) -> list[dict[str, Any]]:
        def work(tx):
            return [dict(r) for r in tx.run(query, **params)]
        with self.driver.session(database=self.database) as session:
            return session.execute_read(work)

    def ping(self) -> None:
        self.driver.verify_connectivity()

    # ------------------------------------------------------------------ entity resolution
    def resolve(self, mention: str, types: Iterable[str] | None = None) -> list[Anchor]:
        q = fold(mention)
        if not q:
            return []
        tlist = [t for t in (types or []) if self.ontology.has_entity_type(t)] or None
        n = self.limits.max_candidates
        base = {"q": q, "types": tlist, "limit": n}
        stages = [("exact_name", cypher.RESOLVE_EXACT, base), ("alias", cypher.RESOLVE_ALIAS, base)]
        stages.append(("fulltext", cypher.RESOLVE_FULLTEXT,
                       {"index": self.fulltext_index, "lucene": cypher.lucene_query(q), "types": tlist, "limit": n}))
        stages.append(("contains", cypher.RESOLVE_CONTAINS, base))

        rows: list[dict[str, Any]] = []
        used = ""
        for name, query, params in stages:
            try:
                rows = self._read(query, **params)
            except Exception as exc:  # noqa: BLE001 - the full-text index may not exist yet; other stages still work
                if name != "fulltext":
                    raise
                log.debug("full-text stage skipped: %s", exc)
                rows = []
            if rows:
                used = name
                break
        if used == "fulltext":  # drop weak hits: keep those within 60% of the best score
            top = max(r["score"] for r in rows)
            rows = [r for r in rows if r["score"] >= 0.6 * top]
        anchors = [Anchor(EntityRef(r["id"], r["name"], r["type"]), used, r.get("score")) for r in rows]

        if anchors and self.merge_alias_siblings:
            ids = [a.entity.id for a in anchors]
            for r in self._read(cypher.ALIAS_SIBLINGS, ids=ids, limit=self.limits.max_anchors):
                anchors.append(Anchor(EntityRef(r["id"], r["name"], r["type"]), "alias_sibling"))
        return anchors[: self.limits.max_anchors]

    # ------------------------------------------------------------------ direction inference from the ontology
    def direction_plan(self, entity_type: str, rel_names: Iterable[str]) -> dict[str, list[str]]:
        """For an anchor of `entity_type`: which relations leave it (out), arrive at it (in), or may do both (any).
        Derived from ontology domain/range; imports are validated against it, so stored edges conform."""
        plan: dict[str, list[str]] = {"out": [], "in": [], "any": []}
        for name in rel_names:
            spec = self.ontology.relations.get(name)
            if spec is None:
                continue  # not in the allowlist -> never reaches Cypher
            as_source = not spec.domain or entity_type in spec.domain
            as_target = not spec.range or entity_type in spec.range
            if as_source and as_target:
                plan["any"].append(name)
            elif as_source:
                plan["out"].append(name)
            elif as_target:
                plan["in"].append(name)
        return plan

    # ------------------------------------------------------------------ 1-hop
    def neighbors(self, anchors: Iterable[EntityRef], rel_names: Iterable[str], *, target_types: Iterable[str] | None = None,
                  limit: int | None = None, hop: int = 1, diagnostics: dict | None = None) -> list[Fact]:
        rel_names = [r for r in rel_names if self.ontology.has_relation(r)]
        types = list(target_types) if target_types else None
        limit = min(limit or self.limits.per_query_rows, self.limits.per_query_rows)
        by_type: dict[str, list[str]] = {}
        for a in anchors:
            by_type.setdefault(a.type, []).append(a.id)
        facts: dict[tuple[str, str, str], Fact] = {}
        for etype, ids in by_type.items():
            for direction, rels in self.direction_plan(etype, rel_names).items():
                if not rels:
                    continue
                rows = self._read(cypher.neighbors(direction, rels), ids=ids, types=types, limit=limit)
                if diagnostics is not None and len(rows) >= limit:
                    diagnostics['query_limited'] = True
                for row in rows:
                    key = (row["source_id"], row["rel"], row["target_id"])
                    fact = facts.get(key)
                    if fact is None:
                        fact = facts[key] = Fact(
                            EntityRef(row["source_id"], row["source_name"], row["source_type"]), row["rel"],
                            EntityRef(row["target_id"], row["target_name"], row["target_type"]),
                            anchor_id=row["anchor_id"], hop=hop)
                    fact.add_row(row)
        return list(facts.values())

    # ------------------------------------------------------------------ multi-hop (chain of intents)
    def chain(self, anchors: Iterable[EntityRef], steps: Iterable[Step]) -> list[Fact]:
        frontier = {a.id: a for a in anchors}
        all_facts: list[Fact] = []
        for hop, step in enumerate(steps, 1):
            intent = self.intents.get(step.intent) or self.intents[CATCH_ALL]
            facts = self.neighbors(frontier.values(), intent.relations, target_types=step.target_types, hop=hop)
            nxt: dict[str, EntityRef] = {}
            for f in facts:
                far = f.far_end
                if far.id not in frontier:
                    nxt[far.id] = far
            if step.include_previous:
                nxt = {**frontier, **nxt}
            all_facts.extend(facts)
            frontier = dict(list(nxt.items())[: self.limits.max_frontier])
            if not frontier:
                break
        return all_facts

    def build_chains(self, facts: list[Fact]) -> list[list[Fact]]:
        """Maximal paths: each fact must start at the far end of the previous one, with increasing hop."""
        by_anchor: dict[str, list[Fact]] = {}
        for f in facts:
            by_anchor.setdefault(f.anchor_id, []).append(f)
        out: list[list[Fact]] = []

        def extend(path: list[Fact]) -> None:
            if len(out) >= self.limits.max_chains:
                return
            last = path[-1]
            nxt = [f for f in by_anchor.get(last.far_end.id, []) if f.hop > last.hop]
            if not nxt:
                out.append(path)
                return
            for f in nxt:
                extend(path + [f])

        first_hop = min((f.hop for f in facts), default=1)
        for f in facts:
            if f.hop == first_hop:
                extend([f])
        return out

    # ------------------------------------------------------------------ paths between two entities
    def paths(self, src: Iterable[EntityRef], dst: Iterable[EntityRef], *, max_hops: int = 3,
              rel_types: Iterable[str] | None = None) -> list[PathResult]:
        rels = [r for r in (rel_types or []) if self.ontology.has_relation(r)] or None
        src_ids, dst_ids = [e.id for e in src], [e.id for e in dst]
        rows = self._read(cypher.shortest_paths(rels, max_hops), src=src_ids, dst=dst_ids,
                          limit=self.limits.max_paths * 10)
        endpoints = set(src_ids) | set(dst_ids)
        # A route that passes through another anchor (e.g. the other spelling of the same disease) is an
        # artefact of duplicate nodes, not a real connection.
        rows = [r for r in rows if not any(n["id"] in endpoints for n in r["nodes"][1:-1])]
        if rows:
            best = min(len(r["rels"]) for r in rows)
            rows = [r for r in rows if len(r["rels"]) == best]
        results: dict[tuple, PathResult] = {}
        for row in rows:
            nodes = [EntityRef(n["id"], n["name"], n["type"]) for n in row["nodes"]]
            by_id = {n.id: n for n in nodes}
            facts = []
            for i, r in enumerate(row["rels"], 1):
                f = Fact(by_id[r["source"]], r["type"], by_id[r["target"]], anchor_id=r["source"], hop=i)
                f.add_row({"rel_id": r["id"], "doc_id": r["doc_id"], "evidence_ids": r["evidence_ids"],
                           "proposition_ids": r["proposition_ids"], "confidence": r["confidence"],
                           "properties_json": r.get("properties_json")})
                facts.append(f)
            key = tuple((f.subject.id, f.predicate, f.object.id) for f in facts)
            if key in results:  # parallel edges (same triple, other document): merge the provenance
                for mine, theirs in zip(results[key].facts, facts):
                    for doc, ids in theirs.evidence.items():
                        bucket = mine.evidence.setdefault(doc, [])
                        bucket += [e for e in ids if e not in bucket]
                    mine.doc_ids += [d for d in theirs.doc_ids if d not in mine.doc_ids]
                    mine.relation_ids += [r for r in theirs.relation_ids if r not in mine.relation_ids]
                    mine.assertions += [a for a in theirs.assertions if a not in mine.assertions]
            else:
                results[key] = PathResult(nodes, facts)
        return list(results.values())[: self.limits.max_paths]

    # ------------------------------------------------------------------ evidence (Neo4j ids -> Mongo text)
    def attach_evidence(self, facts: Iterable[Fact]) -> None:
        if self.evidence_store is None:
            return
        picked: list[tuple[Fact, str, str]] = []
        wanted: dict[str, set[str]] = {}
        for f in facts:
            budget = self.limits.evidence_per_fact
            for doc, ids in f.evidence.items():
                for eid in ids:
                    if budget <= 0:
                        break
                    picked.append((f, doc, eid))
                    wanted.setdefault(doc, set()).add(eid)
                    budget -= 1
        found = {doc: self.evidence_store.fetch(doc, sorted(ids)) for doc, ids in wanted.items()}
        for f, doc, eid in picked:
            rec = found.get(doc, {}).get(eid)
            if rec:
                f.evidence_texts.append({"doc_id": doc, "evidence_id": eid, "text": rec.get("text"),
                                         "sentence_id": rec.get("sentence_id"), "section_id": rec.get("section_id")})

    # ------------------------------------------------------------------ front door
    def check_spec(self, spec: QuerySpec) -> QuerySpec:
        """Drop/repair anything the ontology does not know, and say so in spec.notes."""
        spec.mentions = [clean_text(m) for m in spec.mentions if clean_text(m)][:2]
        bad = [i for i in spec.intents if i not in self.intents]
        if bad:
            spec.notes.append(f"unknown intent(s) {bad} -> using '{CATCH_ALL}'")
        spec.intents = [i for i in spec.intents if i in self.intents] or ([] if spec.chain or spec.path else [CATCH_ALL])
        for step in spec.chain:
            if step.intent not in self.intents:
                spec.notes.append(f"unknown chain intent '{step.intent}' -> using '{CATCH_ALL}'")
        spec.chain = [s if s.intent in self.intents else Step(CATCH_ALL, s.target_types, s.include_previous)
                      for s in spec.chain][:3]
        for attr in ("target_types", "anchor_types"):
            vals = getattr(spec, attr)
            if vals:
                ok = [t for t in vals if self.ontology.has_entity_type(t)]
                if len(ok) != len(vals):
                    spec.notes.append(f"unknown entity type(s) dropped from {attr}: {sorted(set(vals) - set(ok))}")
                setattr(spec, attr, ok or None)
        spec.limit = max(1, min(spec.limit, self.limits.per_query_rows))
        return spec

    def run(self, spec: QuerySpec, *, with_evidence: bool = True,
            resolved_anchors: dict[str, list[Anchor]] | None = None) -> QueryResult:
        spec = self.check_spec(spec)
        result = QueryResult(status="no_entity", notes=list(spec.notes))
        for m in spec.mentions:
            result.anchors[m] = (resolved_anchors.get(m, []) if resolved_anchors is not None
                                 else self.resolve(m, spec.anchor_types))
        found = {m: a for m, a in result.anchors.items() if a}
        if not found:
            return result

        if spec.path and len(found) == 2:
            (a, b) = list(found.values())
            result.paths = self.paths([x.entity for x in a], [x.entity for x in b], max_hops=spec.max_hops,
                                      rel_types=spec.rel_types)
            all_facts = [f for p in result.paths for f in p.facts]
            result.facts = all_facts
        else:
            if spec.path:
                result.notes.append("path needs two resolvable mentions; falling back to neighbourhood")
            anchors = [x.entity for v in found.values() for x in v]
            if spec.chain:
                result.facts = self.chain(anchors, spec.chain)
                result.chains = self.build_chains(result.facts)
                # Optional membership keeps directly linked drugs. Required terminal
                # steps must actually exist; partial chains cannot answer about effects.
                required_hop = max((i for i, step in enumerate(spec.chain, 1)
                                    if not step.include_previous), default=1)
                result.chains = [p for p in result.chains if p[-1].hop >= required_hop]
                used = {id(f) for p in result.chains for f in p}
                result.facts = [f for f in result.facts if id(f) in used]
            else:
                rels = list(dict.fromkeys(r for i in spec.intents for r in self.intents[i].relations))
                result.facts = self.neighbors(anchors, rels, target_types=spec.target_types, limit=spec.limit)
            all_facts = result.facts

        result.status = "ok" if all_facts else "no_facts"
        if with_evidence and all_facts:
            self.attach_evidence(all_facts)
        if result.facts and not spec.chain and not spec.path:
            result.answers = merge_answers(result.facts)
        return result
