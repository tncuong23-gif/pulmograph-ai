"""Duplicate review API and matching logic without live database services."""
import unittest

from fastapi.testclient import TestClient

from app.modules.kg_import.service import ImportResult
from app.modules.kg_query.duplicate_review import DuplicateReviewService, exact_pairs
from app.modules.kg_query.web_app import create_app


def row(id, name, type="Disease", aliases=()):
    return {"id": id, "canonical_name": name, "entity_type": type,
            "aliases": list(aliases), "source_ids": ["DOC_1"]}


class Graph:
    def __init__(self):
        self.rows = [row("E1", "Bệnh phổi tắc nghẽn mạn tính", aliases=["COPD"]),
                     row("E2", "bệnh phổi tắc nghẽn mạn tính"),
                     row("E3", "Viêm phế quản"), row("E4", "COPD", "Symptom")]

    def list_entities(self, after_id, limit):
        return [e for e in self.rows if e["id"] > after_id][:limit]

    def find_entity_candidates(self, ids, names, types):
        return [e for e in self.rows if e["id"] in ids]

    def get_entity_context(self, entity_id, limit=50):
        return {**next(e for e in self.rows if e["id"] == entity_id), "relations": []} if any(
            e["id"] == entity_id for e in self.rows) else None


class Index:
    def ready(self): return True

    def suggest(self, name, entity_type, *, limit, score_threshold):
        return [{"entity_id": "E3", "matched_name": "Viêm phế quản", "score": .88}] if name.startswith("Bệnh") else []


class PreviewMethods:
    def preview_kg(self, payload, **kwargs):
        return self.import_kg(payload, "upsert", dry_run=True)

    def review_profile(self):
        return "test-profile"


class Importer(PreviewMethods):
    def __init__(self): self.args = None

    def import_kg(self, payload, mode, *, dry_run):
        self.args = (payload, mode, dry_run)
        return ImportResult("IMP_TEST", "dry_run", mode, document_id="DOC_2", plan={"entities": {"create": 1},
                            "entity_links": {}, "entity_candidates": {"NEW": [{"entity_id": "E1", "score": .85}]}})


class ReviewedImporter(PreviewMethods):
    def __init__(self):
        self.calls = []

    def import_kg(self, payload, mode, *, dry_run):
        self.calls.append((payload, mode, dry_run))
        return ImportResult("IMP_OK", "dry_run" if dry_run else "completed", mode,
                            document_id="DOC_2", plan={"entities": {"create": 1}, "relations": {"create": 2},
                                                       "entity_links": {}, "entity_candidates": {}})


class DuplicateReviewTests(unittest.TestCase):
    def test_chronic_spelling_requires_vector_candidate_not_a_special_rule(self):
        rows = [row("E1", "Bệnh phổi tắc nghẽn mãn tính"),
                row("E2", "Bệnh phổi tắc nghẽn mạn tính  ")]
        self.assertEqual(exact_pairs(rows), [])
        graph = Graph()
        graph.rows = rows
        class SemanticIndex:
            def ready(self): return True
            def suggest(self, name, entity_type, *, limit, score_threshold):
                self.last_threshold = score_threshold
                return [{"entity_id": "E2", "matched_name": rows[1]["canonical_name"], "score": .79}] if "mãn" in name else []
        index = SemanticIndex()
        result = DuplicateReviewService(graph, index).scan(min_score=.7)
        self.assertEqual([(p["key"], p["method"]) for p in result["pairs"]], [("E1|E2", "embedding")])
        self.assertEqual(index.last_threshold, .7)

    def test_exact_pair_is_case_insensitive_type_safe_and_deduplicated(self):
        pairs = exact_pairs(Graph().rows)
        self.assertEqual({p["key"] for p in pairs}, {"E1|E2", "E1|E4"})
        self.assertTrue(next(p for p in pairs if p["key"] == "E1|E4")["cross_type"])
        self.assertEqual(pairs[0]["method"], "exact")

    def test_embedding_candidates_and_limit(self):
        service = DuplicateReviewService(Graph(), Index())
        result = service.scan(mode="embedding", max_entities=2)
        self.assertEqual(result["scanned"], 2)
        self.assertEqual({p["key"] for p in result["pairs"]}, {"E1|E2", "E1|E3"})
        self.assertTrue(result["truncated"])

    def test_routes_and_dry_run_only(self):
        importer = Importer()
        client = TestClient(create_app(review_service=DuplicateReviewService(Graph(), Index()), import_service=importer))
        self.assertEqual(client.get("/duplicates").status_code, 200)
        self.assertEqual(client.get("/static/duplicates.js").status_code, 200)
        self.assertEqual(client.get("/static/graph_layout.js").status_code, 200)
        self.assertIn("neo4j_graph.js", client.get("/duplicates").text)
        self.assertEqual(client.get("/api/review/scan").json()["pairs_total"], 3)
        self.assertEqual(client.get("/api/review/entities/E1").json()["canonical_name"], Graph().rows[0]["canonical_name"])
        self.assertEqual(client.get("/api/review/entities/missing").status_code, 404)
        self.assertEqual(client.get("/api/review/scan?mode=bad").status_code, 400)
        self.assertEqual(client.get("/api/review/scan?min_score=0.1").status_code, 400)
        payload = {"document": {"document_id": "DOC_2"}, "entity_link_decisions": {"NEW": "E1"}}
        self.assertEqual(client.post("/api/review/preview", json=payload).json()["status"], "dry_run")
        self.assertEqual(importer.args, (payload, "upsert", True))
        self.assertEqual(client.post("/api/review/preview", json=[]).status_code, 400)

    def test_import_requires_recent_matching_preview_and_token_is_one_use(self):
        importer = ReviewedImporter()
        client = TestClient(create_app(import_service=importer))
        payload = {"document": {"document_id": "DOC_2"}, "entities": []}
        self.assertEqual(client.post("/api/review/import", json={"payload": payload}).status_code, 400)
        preview = client.post("/api/review/preview", json=payload).json()
        token = preview["preview_token"]
        altered = {"document": {"document_id": "DOC_3"}, "entities": []}
        self.assertEqual(client.post("/api/review/import", json={"payload": altered, "preview_token": token}).status_code, 409)
        self.assertEqual(len(importer.calls), 1)
        token = client.post("/api/review/preview", json=payload).json()["preview_token"]
        success = client.post("/api/review/import", json={"payload": payload, "preview_token": token})
        self.assertEqual((success.status_code, success.json()["status"]), (200, "completed"))
        self.assertEqual(importer.calls[-1], (payload, "upsert", False))
        self.assertEqual(client.post("/api/review/import", json={"payload": payload, "preview_token": token}).status_code, 409)

    def test_unreviewed_candidates_cannot_be_imported_from_ui(self):
        client = TestClient(create_app(import_service=Importer()))
        preview = client.post("/api/review/preview", json={"entities": []}).json()
        self.assertNotIn("preview_token", preview)


if __name__ == "__main__":
    unittest.main()
