"""Read-only candidate audit over Neo4j :Entity and the optional Qdrant name index."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.modules.kg_import.utils import fold


def _view(row: dict[str, Any]) -> dict[str, Any]:
    return {"id": row["id"], "name": row.get("canonical_name") or "", "type": row.get("entity_type") or "",
            "aliases": row.get("aliases") or [], "source_ids": row.get("source_ids") or []}


def _pair(a: dict, b: dict, method: str, reason: str, score: float | None = None) -> dict:
    if a["id"] > b["id"]:
        a, b = b, a
    return {"key": f"{a['id']}|{b['id']}", "a": _view(a), "b": _view(b),
            "method": method, "reason": ("Khác loại — cần rà soát: " + reason if a["entity_type"] != b["entity_type"] else reason),
            "cross_type": a["entity_type"] != b["entity_type"], "score": score}


def exact_pairs(rows: list[dict]) -> list[dict]:
    by_name: dict[str, list[dict]] = defaultdict(list)
    by_alias: dict[str, list[dict]] = defaultdict(list)
    for e in rows:
        by_name[fold(e["canonical_name"])].append(e)
        for alias in e.get("aliases") or []:
            by_alias[fold(alias)].append(e)
    pairs: dict[str, dict] = {}
    for key, named in by_name.items():
        for i, a in enumerate(named):
            for b in named[i + 1:]:
                p = _pair(a, b, "exact", "Tên chuẩn trùng nhau")
                pairs[p["key"]] = p
        for a in named:
            for b in by_alias.get(key, []):
                if a["id"] != b["id"]:
                    p = _pair(a, b, "exact", "Tên chuẩn khớp alias")
                    pairs.setdefault(p["key"], p)
    return sorted(pairs.values(), key=lambda p: (p["a"]["type"], p["a"]["name"], p["b"]["name"]))


class DuplicateReviewService:
    def __init__(self, graph, entity_index=None):
        self.graph, self.entity_index = graph, entity_index

    def scan(self, *, mode: str = "embedding", max_entities: int = 500, entity_type: str = "",
             min_score: float = 0.70) -> dict:
        max_entities = max(1, min(max_entities, 500 if mode == "embedding" else 5000))
        rows: list[dict] = []
        after = ""
        while len(rows) <= max_entities:
            page = self.graph.list_entities(after, min(250, max_entities + 1 - len(rows)))
            if not page:
                break
            rows.extend(page)
            after = page[-1]["id"]
        truncated = len(rows) > max_entities
        rows = rows[:max_entities]
        if entity_type:
            rows = [r for r in rows if r["entity_type"] == entity_type]
        pairs = {p["key"]: p for p in exact_pairs(rows)}

        if mode == "embedding":
            if self.entity_index is None or not self.entity_index.ready():
                raise ValueError("Chưa bật embedding hoặc chưa lập chỉ mục Qdrant cho thực thể.")
            by_id = {e["id"]: e for e in rows}
            queries = [(e['canonical_name'], None) for e in rows]
            many = getattr(self.entity_index, 'suggest_many', None)
            groups = (many(queries, limit=8, score_threshold=min_score) if many else
                      [self.entity_index.suggest(*q, limit=8, score_threshold=min_score) for q in queries])
            suggestions = [(e, s) for e, group in zip(rows, groups) for s in group if s['entity_id'] != e['id']]
            missing = list({s["entity_id"] for _, s in suggestions} - set(by_id))
            if missing:
                by_id.update({r["id"]: r for r in self.graph.find_entity_candidates(missing, [], [])})
            for a, hit in suggestions:
                b = by_id.get(hit["entity_id"])
                if not b:
                    continue
                p = _pair(a, b, "embedding", f"Tên gần với “{hit['matched_name']}”", hit["score"])
                if p["key"] not in pairs or (pairs[p["key"]]["method"] != "exact" and (pairs[p["key"]]["score"] or 0) < (p["score"] or 0)):
                    pairs[p["key"]] = p

        result = sorted(pairs.values(), key=lambda p: (p["method"] != "exact", -(p["score"] or 0), p["key"]))
        return {"pairs": result[:300], "pairs_total": len(result), "scanned": len(rows),
                "truncated": truncated or len(result) > 300, "mode": mode, "min_score": min_score}

    def detail(self, entity_id: str) -> dict | None:
        return self.graph.get_entity_context(entity_id, limit=50)
