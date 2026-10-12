import copy
import unittest

from tests.upstream.kg.helpers import ServiceTestCase
from app.modules.kg_import.entity_vector import QdrantEntityIndex
from app.modules.kg_import.config import EntityEmbeddingSettings


class FakeIndex:
    def __init__(self):
        self.entities = {}

    def ready(self):
        return True

    def suggest(self, name, entity_type):
        if name == "Bệnh phổi tắt nghẽn mãn tính" and "ENT_000001" in self.entities:
            return [{"entity_id": "ENT_000001", "canonical_name": "Bệnh phổi tắc nghẽn mạn tính",
                     "matched_name": "Bệnh phổi tắc nghẽn mạn tính", "score": 0.9}]
        return []

    def upsert_entities(self, entities):
        self.entities.update({e["id"]: e for e in entities})
        return len(entities)


class EntityVectorFlowTests(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.index = FakeIndex()
        self.svc.entity_index = self.index

    def payload_with_new_spelling(self):
        p = copy.deepcopy(self.payload)
        p["document"]["document_id"] = "DOC_000002"
        p["entities"][0].update(id="ENT_NEW", canonical_name="Bệnh phổi tắt nghẽn mãn tính", aliases=[])
        for r in p["relations"]:
            if r["source"] == "ENT_000001":
                r["source"] = "ENT_NEW"
            r["id"] = "NEW_" + r["id"]
        p["propositions"][0]["entity_ids"] = ["ENT_NEW"]
        return p

    def test_candidates_are_reviewed_and_explicit_existing_id_rewrites_references(self):
        self.assertEqual(self.svc.import_kg(self.p()).status, "completed")
        p = self.payload_with_new_spelling()
        dry = self.svc.import_kg(p, dry_run=True)
        self.assertEqual(dry.status, "dry_run")
        self.assertEqual(dry.plan["entity_candidates"]["ENT_NEW"][0]["entity_id"], "ENT_000001")
        blocked = self.svc.import_kg(p)
        self.assertEqual(blocked.status, "failed")
        self.assertIn("ENTITY_LINK_REVIEW_REQUIRED", self.codes(blocked))
        self.assertFalse(self.docs.document_exists("DOC_000002"))
        p["entity_link_decisions"] = {"ENT_NEW": "ENT_000001"}
        self.assertEqual(self.svc.import_kg(p).status, "completed")
        self.assertEqual(self.graph.relations["NEW_REL_000001"]["source_id"], "ENT_000001")
        self.assertEqual(self.docs.data["propositions"][("DOC_000002", "PROP_000001")]["entity_ids"], ["ENT_000001"])

    def test_reviewer_can_keep_a_distinct_entity(self):
        self.assertEqual(self.svc.import_kg(self.p()).status, "completed")
        p = self.payload_with_new_spelling()
        p["entity_link_decisions"] = {"ENT_NEW": "new"}
        self.assertEqual(self.svc.import_kg(p).status, "completed")
        self.assertIn("ENT_NEW", self.graph.entities)


class SmallEncoder:
    def get_sentence_embedding_dimension(self):
        return 2

    def encode(self, names, normalize_embeddings=True, **kwargs):
        class Vector(list):
            def tolist(self):
                return list(self)
        return [Vector([1.0, 0.0] if "phổi" in n.lower() else [0.0, 1.0]) for n in names]


class QdrantAdapterTests(unittest.TestCase):
    def test_filtered_vector_candidates_with_local_qdrant(self):
        from qdrant_client import QdrantClient
        index = QdrantEntityIndex(EntityEmbeddingSettings(enabled=True, collection="entities_test", model="fake"),
                                  client=QdrantClient(":memory:"), encoder=SmallEncoder())
        index.upsert_entities([
            {"id": "d1", "entity_type": "Disease", "canonical_name": "Bệnh phổi", "aliases": ["Phổi"]},
            {"id": "s1", "entity_type": "Symptom", "canonical_name": "Đau phổi", "aliases": []},
        ])
        hits = index.suggest("bệnh phổi", "Disease")
        self.assertEqual(hits[0]["entity_id"], "d1")
        self.assertTrue(all(h["entity_id"] != "s1" for h in hits))


if __name__ == "__main__":
    unittest.main()
