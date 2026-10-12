"""Exercise the browser API without running MongoDB or Neo4j."""
import unittest

from fastapi.testclient import TestClient

from app.modules.kg_query.models import Anchor, EntityRef, Fact, QueryResult
from app.modules.kg_query.web_app import create_app


class FakeService:
    def ping(self):
        return None

    def run(self, spec):
        a = EntityRef("a", "COPD", "Disease")
        b = EntityRef("b", "Ho", "Symptom")
        f = Fact(a, "HAS_SYMPTOM", b, anchor_id="a")
        f.add_row({"rel_id": "r1", "doc_id": "D001", "evidence_ids": ["ev1"]})
        f.evidence_texts.append({"doc_id": "D001", "evidence_id": "ev1", "text": "COPD có triệu chứng ho."})
        return QueryResult(status="ok", anchors={spec.mentions[0]: [Anchor(a, "exact_name")]}, facts=[f])


class WebAppTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app(FakeService()))

    def test_ui_and_metadata(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertIn("Khám phá tri thức", self.client.get("/").text)
        self.assertEqual(self.client.get("/static/app.js").status_code, 200)
        self.assertEqual(self.client.get("/static/neo4j_graph.js").status_code, 200)
        self.assertIn("symptom", [i["id"] for i in self.client.get("/api/meta").json()["intents"]])
        self.assertEqual(self.client.get("/api/health").json()["status"], "connected")

    def test_query_preserves_direction_and_evidence(self):
        response = self.client.post("/api/query", json={"mentions": ["COPD"], "intents": ["symptom"]})
        self.assertEqual(response.status_code, 200)
        fact = response.json()["facts"][0]
        self.assertEqual((fact["subject"]["name"], fact["predicate"], fact["object"]["name"]),
                         ("COPD", "HAS_SYMPTOM", "Ho"))
        self.assertEqual(fact["evidence"][0]["doc_id"], "D001")

    def test_rejects_invalid_path_and_large_input(self):
        self.assertEqual(self.client.post("/api/query", json={"mentions": ["COPD"], "path": True}).status_code, 400)
        self.assertEqual(self.client.post("/api/query", json={"mentions": ["x" * 161]}).status_code, 400)
        self.assertEqual(self.client.post("/api/query", json={"mentions": ["COPD"], "chain": "unknown"}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
