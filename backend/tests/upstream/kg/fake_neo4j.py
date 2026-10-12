"""A tiny in-memory stand-in for the Neo4j driver that understands ONLY the query templates in kg_query.cypher.
It lets the Python logic (resolution, direction, merging, chains, evidence) be tested on the real example data
without a database. It does NOT validate Cypher syntax: run scripts/query_kg.py against a real Neo4j for that."""
from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from pathlib import Path

from app.modules.kg_import.utils import fold

ROOT = Path(__file__).resolve().parents[3]
DOC_FILES = [ROOT / "examples/kg" / f"DOC_00000{i}_kg_import_global_ids.json" for i in (1, 2, 3)]


def docs_available() -> bool:
    return all(p.exists() for p in DOC_FILES)


class FakeGraph:
    def __init__(self) -> None:
        self.entities: dict[str, dict] = {}
        self.rels: list[dict] = []
        self.evidence: dict[tuple[str, str], dict] = {}
        for path in DOC_FILES:
            d = json.loads(path.read_text(encoding="utf-8"))
            doc = d["document"]["document_id"]
            sent = {s["sentence_id"]: s["text"] for sec in d["document"]["sections"]
                    for p in sec["paragraphs"] for s in p["sentences"]}
            for e in d["entities"]:  # upsert: later documents overwrite name/aliases like the real MERGE ... SET
                self.entities[e["id"]] = {"id": e["id"], "canonical_name": e["canonical_name"], "entity_type": e["type"],
                                          "normalized_name": fold(e["canonical_name"]), "aliases": e.get("aliases") or []}
            props = {p["id"]: p for p in d["propositions"]}
            for p in d["propositions"]:
                for ev in p["evidence"]:
                    eid = f"EVD_{p['id']}_{ev['sentence_id']}"
                    self.evidence[(doc, eid)] = {"evidence_id": eid, "text": sent[ev["sentence_id"]],
                                                 "sentence_id": ev["sentence_id"], "section_id": None}
            for r in d["relations"]:
                evs = [f"EVD_{pid}_{ev['sentence_id']}" for pid in r["proposition_ids"] for ev in props[pid]["evidence"]]
                self.rels.append({"id": r["id"], "type": r["type"], "source": r["source"], "target": r["target"],
                                  "doc": doc, "evidence_ids": evs, "props": r["proposition_ids"], "confidence": None})


class FakeEvidenceStore:
    def __init__(self, graph: FakeGraph) -> None:
        self.g = graph

    def fetch(self, document_id, evidence_ids):
        return {e: self.g.evidence[(document_id, e)] for e in evidence_ids if (document_id, e) in self.g.evidence}


class _Tx:
    def __init__(self, g: FakeGraph, log: list) -> None:
        self.g, self.log = g, log

    def run(self, query, **p):
        from app.modules.kg_query.entity_lookup import CATALOG_QUERY, IDS_QUERY
        self.log.append((query, p))
        g = self.g
        types = p.get("types")
        ok_type = lambda t: types is None or t in types  # noqa: E731
        ent = lambda e: {"id": e["id"], "name": e["canonical_name"], "type": e["entity_type"], "aliases": e["aliases"]}  # noqa: E731

        if query == CATALOG_QUERY:
            rows = [ent(e) for e in sorted(g.entities.values(), key=lambda e: e['id'])]
        elif query == IDS_QUERY:
            rows = [ent(e) for e in g.entities.values() if e['id'] in p['ids']]
        elif "normalized_name: $q}" in query:
            rows = [ent(e) for e in g.entities.values() if e["normalized_name"] == p["q"] and ok_type(e["entity_type"])]
        elif "toLower(a) = $q" in query:
            rows = [ent(e) for e in g.entities.values()
                    if any(a.lower() == p["q"] for a in e["aliases"]) and ok_type(e["entity_type"])]
        elif "db.index.fulltext.queryNodes" in query:
            raise RuntimeError("no such index")  # emulate 'index not created yet'
        elif "CONTAINS $q" in query:
            rows = [ent(e) for e in g.entities.values() if ok_type(e["entity_type"]) and
                    (p["q"] in e["normalized_name"] or any(p["q"] in a.lower() for a in e["aliases"]))]
        elif "MATCH (o:Entity {entity_type: a.entity_type})" in query:
            rows, seen = [], set()
            for a in (g.entities[i] for i in p["ids"]):
                for o in g.entities.values():
                    if o["id"] in p["ids"] or o["id"] in seen or o["entity_type"] != a["entity_type"]:
                        continue
                    if o["normalized_name"] == a["normalized_name"] or any(
                            x in o["aliases"] or x.lower() == o["normalized_name"] for x in a["aliases"]):
                        seen.add(o["id"]); rows.append(ent(o))
        elif "allShortestPaths" in query:
            rows = self._paths(query, p)
        elif query.lstrip().startswith("MATCH (a:Entity)"):
            rows = self._neighbors(query, p)
        else:
            raise AssertionError(f"fake does not understand query:\n{query}")
        return [r for r in rows[: p.get("limit", len(rows))]]

    def _neighbors(self, q, p):
        names = set(re.findall(r"`([A-Z0-9_]+)`", q.split("WHERE")[0]))
        head = q.split("WHERE")[0]
        direction = "in" if "<-[r" in head else "out" if "]->" in head else "any"
        g, ids, types = self.g, set(p["ids"]), p.get("types")
        rows = []
        for r in g.rels:
            if r["type"] not in names:
                continue
            for a_id, b_id in ((r["source"], r["target"]), (r["target"], r["source"])):
                is_forward = a_id == r["source"]
                if direction == "out" and not is_forward or direction == "in" and is_forward:
                    continue
                if a_id in ids and (types is None or g.entities[b_id]["entity_type"] in types):
                    s, t = g.entities[r["source"]], g.entities[r["target"]]
                    rows.append({"anchor_id": a_id, "rel_id": r["id"], "rel": r["type"],
                                 "source_id": s["id"], "source_name": s["canonical_name"], "source_type": s["entity_type"],
                                 "target_id": t["id"], "target_name": t["canonical_name"], "target_type": t["entity_type"],
                                 "doc_id": r["doc"], "evidence_ids": r["evidence_ids"], "proposition_ids": r["props"],
                                 "confidence": r["confidence"], "properties_json": r.get('properties_json')})
        rows.sort(key=lambda x: (x["rel"], x["target_name"], x["rel_id"]))
        return rows

    def _paths(self, q, p):
        g = self.g
        m = re.search(r"\[(?::([`A-Z0-9_|]+))?\*\.\.(\d)\]", q)
        allowed = set(re.findall(r"`([A-Z0-9_]+)`", m.group(1))) if m.group(1) else None
        k = int(m.group(2))
        adj = defaultdict(list)
        for r in g.rels:
            if allowed is None or r["type"] in allowed:
                adj[r["source"]].append((r["target"], r))
                adj[r["target"]].append((r["source"], r))
        rows = []
        for a in p["src"]:
            dist, parents, dq = {a: 0}, defaultdict(list), deque([a])
            while dq:
                u = dq.popleft()
                if dist[u] >= k:
                    continue
                for v, r in adj[u]:
                    if v not in dist:
                        dist[v] = dist[u] + 1; dq.append(v)
                    if dist[v] == dist[u] + 1:
                        parents[v].append((u, r))
            for b in p["dst"]:
                if b == a or b not in dist:
                    continue
                stack = [(b, [])]
                while stack:
                    node, acc = stack.pop()
                    if node == a:
                        edges = list(reversed(acc))
                        nodes, cur = [a], a
                        for e in edges:
                            cur = e["target"] if cur == e["source"] else e["source"]
                            nodes.append(cur)
                        rows.append({"nodes": [{"id": n, "name": g.entities[n]["canonical_name"],
                                                "type": g.entities[n]["entity_type"]} for n in nodes],
                                     "rels": [{"id": e["id"], "type": e["type"], "source": e["source"], "target": e["target"],
                                               "doc_id": e["doc"], "evidence_ids": e["evidence_ids"],
                                               "proposition_ids": e["props"], "confidence": None,
                                               "properties_json": e.get('properties_json')} for e in edges]})
                        continue
                    for u, r in parents[node]:
                        stack.append((u, acc + [r]))
        return rows


class _Session:
    def __init__(self, g, log): self.g, self.log = g, log
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute_read(self, fn): return fn(_Tx(self.g, self.log))
    # no execute_write on purpose: any write attempt raises AttributeError


class FakeDriver:
    def __init__(self, graph: FakeGraph) -> None:
        self.g, self.log = graph, []

    def session(self, database=None): return _Session(self.g, self.log)
    def verify_connectivity(self): ...
    def close(self): ...
