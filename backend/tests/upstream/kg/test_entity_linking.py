"""Entity identity and provenance must stay consistent across document imports."""
import copy
import unittest

from tests.upstream.kg.helpers import ServiceTestCase


class EntityLinkingTests(ServiceTestCase):
    def second_document(self):
        p = copy.deepcopy(self.payload)
        p["document"]["document_id"] = "DOC_000002"
        entity_map = {e["id"]: "SECOND_" + e["id"] for e in p["entities"]}
        for e in p["entities"]:
            e["id"] = entity_map[e["id"]]
        p["entities"][0]["canonical_name"] = "COPD"  # alias of the existing disease
        p["entities"][0]["aliases"] = ["Bệnh phổi tắc nghẽn mạn tính"]
        for r in p["relations"]:
            r["id"] = "SECOND_" + r["id"]
            r["source"] = entity_map[r["source"]]
            r["target"] = entity_map[r["target"]]
        for prop in p["propositions"]:
            prop["entity_ids"] = [entity_map["ENT_000001"], entity_map["ENT_000002"]]
        return p, entity_map

    def test_second_document_reuses_entities_and_rewrites_provenance(self):
        self.assertEqual(self.svc.import_kg(self.p()).status, "completed")
        p, mapping = self.second_document()
        before = len(self.graph.entities)
        dry = self.svc.import_kg(p, dry_run=True)
        self.assertEqual(dry.status, "dry_run")
        self.assertEqual(dry.plan["entity_links"][mapping["ENT_000001"]], "ENT_000001")
        self.assertEqual(len(self.graph.entities), before)
        self.assertEqual(self.svc.import_kg(p).status, "completed")
        self.assertEqual(len(self.graph.entities), before)
        self.assertEqual(self.graph.relations["SECOND_REL_000001"]["source_id"], "ENT_000001")
        self.assertEqual(self.graph.relations["SECOND_REL_000001"]["target_id"], "ENT_000002")
        prop = self.docs.data["propositions"][("DOC_000002", "PROP_000001")]
        self.assertEqual(prop["entity_ids"], ["ENT_000001", "ENT_000002"])
        self.assertIn("COPD", self.graph.entities["ENT_000001"]["aliases"])
        self.assertIn("DOC_000002", self.graph.entities["ENT_000001"]["source_ids"])

    def test_ambiguous_alias_stops_before_writes(self):
        self.assertEqual(self.svc.import_kg(self.p()).status, "completed")
        other = copy.deepcopy(self.graph.entities["ENT_000001"])
        other.update(id="ENT_OTHER", canonical_name="Bệnh khác", normalized_name="bệnh khác",
                     aliases=["COPD"])
        self.graph.entities["ENT_OTHER"] = other
        p, _ = self.second_document()
        result = self.svc.import_kg(p, dry_run=True)
        self.assertEqual(result.status, "failed")
        self.assertIn("ENTITY_LINK_AMBIGUOUS", self.codes(result))
        self.assertFalse(self.docs.document_exists("DOC_000002"))

    def test_duplicate_names_inside_one_payload_share_id(self):
        p = self.p()
        p["entities"].append({"id": "ENT_EXTRA", "type": "Disease", "canonical_name": "COPD"})
        p["relations"][0]["source"] = "ENT_EXTRA"
        p["propositions"][0]["entity_ids"] = ["ENT_EXTRA"]
        result = self.svc.import_kg(p, dry_run=True)
        self.assertEqual(result.status, "dry_run")
        self.assertEqual(result.plan["entity_links"], {"ENT_EXTRA": "ENT_000001"})
        self.assertEqual(result.plan["entities"]["create"], 4)
        self.assertEqual(self.svc.import_kg(p).status, "completed")
        self.assertEqual(self.graph.relations["REL_000001"]["source_id"], "ENT_000001")


if __name__ == "__main__":
    unittest.main()
