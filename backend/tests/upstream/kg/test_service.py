from app.modules.kg_import.service import Status
from tests.upstream.kg.helpers import ServiceTestCase


class ImportFlowTests(ServiceTestCase):
    def counts(self):
        return (len(self.graph.entities), len(self.graph.relations), self.docs.count("documents"),
                self.docs.count("propositions"), self.docs.count("evidence"), self.docs.count("sentences"))

    def test_first_import(self):
        r = self.svc.import_kg(self.p(), "upsert")
        self.assertEqual(r.status, "completed", r.errors)
        self.assertEqual(r.http_status, 200)
        st = r.statistics
        self.assertEqual((st["entities_created"], st["entities_updated"], st["relations_created"]), (4, 0, 3))
        self.assertEqual(self.counts(), (4, 3, 1, 2, 2, 2))
        self.assertEqual(self.jobs.get_job(r.import_id)["status"], "completed")

    def test_second_import_is_idempotent(self):
        self.svc.import_kg(self.p(), "upsert")
        before = self.counts()
        r = self.svc.import_kg(self.p(), "upsert")
        self.assertEqual(r.status, "completed")
        self.assertEqual(self.counts(), before)
        self.assertEqual(r.statistics["entities_created"], 0)
        self.assertEqual(r.statistics["entities_skipped"], 4)
        self.assertEqual(r.statistics["relations_skipped"], 3)
        self.assertEqual(self.graph.entities["ENT_000001"]["source_ids"], ["DOC_000001"])

    def test_upsert_updates_changed_entity_and_adds_new_one(self):
        self.svc.import_kg(self.p(), "upsert")
        p = self.p()
        p["entities"][1]["canonical_name"] = "Ho mạn tính"
        p["entities"].append({"id": "ENT_000005", "type": "Symptom", "canonical_name": "Khạc đờm"})
        r = self.svc.import_kg(p, "upsert")
        self.assertEqual((r.statistics["entities_created"], r.statistics["entities_updated"]), (1, 1))
        self.assertEqual(self.graph.entities["ENT_000002"]["canonical_name"], "Ho mạn tính")

    def test_insert_mode_conflicts(self):
        self.assertEqual(self.svc.import_kg(self.p(), "insert").status, "completed")
        r = self.svc.import_kg(self.p(), "insert")
        self.assertEqual((r.status, r.http_status, r.stage), ("failed", 409, "planning"))
        self.assertTrue({"DUPLICATE_DOCUMENT", "DUPLICATE_ENTITY", "DUPLICATE_RELATION"} <= self.codes(r))

    def test_insert_mode_conflict_writes_nothing(self):
        self.svc.import_kg(self.p(), "upsert")
        self.docs.fail_on_write = True  # would blow up if anything were written
        r = self.svc.import_kg(self.p(), "insert")
        self.assertEqual(r.http_status, 409)

    def test_relation_to_missing_entity(self):
        p = self.p(); p["relations"][0]["target"] = "ENT_MISSING"
        r = self.svc.import_kg(p, "upsert")
        self.assertEqual((r.status, r.http_status), ("failed", 422))
        self.assertIn("ENTITY_NOT_FOUND", self.codes(r))
        self.assertEqual(self.counts(), (0, 0, 0, 0, 0, 0))

    def test_relation_to_entity_in_graph_from_other_document(self):
        self.svc.import_kg(self.p(), "upsert")
        p = self.p()
        p["document"]["document_id"] = "DOC_000002"
        p["entities"] = [{"id": "ENT_000009", "type": "Symptom", "canonical_name": "Sốt"}]
        p["relations"] = [{"id": "REL_000009", "type": "HAS_SYMPTOM", "source": "ENT_000001", "target": "ENT_000009",
                           "proposition_ids": ["PROP_000001"]}]
        p["propositions"] = [p["propositions"][0]]
        r = self.svc.import_kg(p, "upsert")
        self.assertEqual(r.status, "completed", r.errors)
        self.assertEqual(sorted(self.graph.entities["ENT_000001"]["source_ids"]), ["DOC_000001"])  # untouched
        self.assertEqual(self.graph.relations["REL_000009"]["source_document_id"], "DOC_000002")

    def test_external_ref_domain_range_checked_against_graph_types(self):
        self.svc.import_kg(self.p(), "upsert")
        p = self.p()
        p["document"]["document_id"] = "DOC_000002"
        p["entities"] = [{"id": "ENT_000009", "type": "Symptom", "canonical_name": "Sốt"}]
        p["relations"] = [{"id": "REL_000009", "type": "HAS_SYMPTOM", "source": "ENT_000002", "target": "ENT_000009",
                           "proposition_ids": ["PROP_000001"]}]  # source is a Symptom in the graph -> violates domain
        r = self.svc.import_kg(p, "upsert")
        self.assertIn("ONTOLOGY_DOMAIN_RANGE_VIOLATION", self.codes(r))

    def test_relation_id_reused_by_other_document_is_rejected(self):
        self.svc.import_kg(self.p(), "upsert")
        p = self.p(); p["document"]["document_id"] = "DOC_000002"
        r = self.svc.import_kg(p, "upsert")
        self.assertIn("RELATION_OWNED_BY_OTHER_DOCUMENT", self.codes(r))

    def test_relation_identity_change_is_rejected(self):
        self.svc.import_kg(self.p(), "upsert")
        p = self.p(); p["relations"][0]["target"] = "ENT_000003"
        r = self.svc.import_kg(p, "upsert")
        self.assertIn("RELATION_IDENTITY_CONFLICT", self.codes(r))

    def test_invalid_payload_and_invalid_mode(self):
        r = self.svc.import_kg({"nope": 1}, "upsert")
        self.assertEqual((r.status, r.http_status, r.stage), ("failed", 422, "validation"))
        self.assertEqual(self.svc.import_kg(self.p(), "delete-all").http_status, 422)
        self.assertEqual(self.counts(), (0, 0, 0, 0, 0, 0))

    def test_dry_run_writes_nothing_and_reports_plan(self):
        r = self.svc.import_kg(self.p(), "upsert", dry_run=True)
        self.assertEqual((r.status, r.http_status), ("dry_run", 200))
        self.assertEqual(r.plan["entities"], {"create": 4, "update": 0, "skip": 0})
        self.assertEqual(r.plan["mongo"]["evidence"], 2)
        self.assertEqual(self.counts(), (0, 0, 0, 0, 0, 0))
        self.assertEqual(self.jobs.jobs, {})
        self.svc.import_kg(self.p(), "upsert")
        r2 = self.svc.import_kg(self.p(), "upsert", dry_run=True)
        self.assertEqual(r2.plan["entities"], {"create": 0, "update": 0, "skip": 4})

    def test_failed_validation_is_recorded_in_job(self):
        r = self.svc.import_kg({"schema_version": "1.0"}, "upsert")
        job = self.jobs.get_job(r.import_id)
        self.assertEqual((job["status"], job["stage"]), ("failed", "validation"))

    def test_result_never_leaks_internals(self):
        self.graph.fail_on_write = True
        r = self.svc.import_kg(self.p(), "upsert")
        self.assertNotIn("injected", str(r.to_dict()))


class ReplaceTests(ServiceTestCase):
    def test_replace_removes_only_this_documents_stale_data(self):
        self.svc.import_kg(self.p(), "upsert")
        other = self.p()
        other["document"]["document_id"] = "DOC_OTHER"
        other["entities"] = [{"id": "ENT_OTHER", "type": "Disease", "canonical_name": "Bệnh khác"}]
        other["relations"] = []
        other["propositions"] = []
        self.assertEqual(self.svc.import_kg(other, "upsert").status, "completed")

        p = self.p()  # new version of DOC_000001 without the smoking risk factor
        p["entities"] = [e for e in p["entities"] if e["id"] != "ENT_000004"]
        p["relations"] = [r for r in p["relations"] if r["id"] != "REL_000003"]
        p["propositions"] = [p["propositions"][0]]
        p["document"]["sections"][0]["paragraphs"][0]["sentences"].pop()
        r = self.svc.import_kg(p, "replace")
        self.assertEqual(r.status, "completed", r.errors)
        self.assertEqual(set(self.graph.relations), {"REL_000001", "REL_000002"})
        self.assertNotIn("ENT_000004", self.graph.entities)
        self.assertIn("ENT_OTHER", self.graph.entities)  # other document untouched
        self.assertEqual(self.docs.count("propositions"), 1)
        mine = [k for k in self.docs.data["sentences"] if k[0] == "DOC_000001"]
        self.assertEqual(len(mine), 1)
        self.assertEqual(len([k for k in self.docs.data["sentences"] if k[0] == "DOC_OTHER"]), 2)  # other doc untouched
        self.assertEqual(r.statistics["relations_deleted"], 1)

    def test_replace_keeps_entity_shared_with_other_document(self):
        self.svc.import_kg(self.p(), "upsert")
        shared = self.p()
        shared["document"]["document_id"] = "DOC_2"
        shared["entities"] = [self.p()["entities"][3]]  # ENT_000004 too
        shared["relations"], shared["propositions"] = [], []
        self.svc.import_kg(shared, "upsert")
        p = self.p()
        p["entities"] = p["entities"][:3]
        p["relations"] = p["relations"][:2]
        self.svc.import_kg(p, "replace")
        self.assertEqual(self.graph.entities["ENT_000004"]["source_ids"], ["DOC_2"])


class FailureHandlingTests(ServiceTestCase):
    def test_neo4j_failure_on_new_document_compensates_mongo(self):
        self.graph.fail_on_write = True
        r = self.svc.import_kg(self.p(), "upsert")
        self.assertEqual((r.status, r.stage, r.http_status), ("failed", "neo4j", 500))
        self.assertTrue(r.compensated and r.retryable)
        self.assertEqual(self.docs.count("documents"), 0)
        self.assertEqual(self.docs.count("evidence"), 0)
        self.assertEqual(len(self.graph.entities), 0)
        self.assertIn("NEO4J_IMPORT_ERROR", self.codes(r))

    def test_retry_after_neo4j_failure_completes(self):
        self.graph.fail_on_write = True
        r = self.svc.import_kg(self.p(), "insert")
        self.graph.fail_on_write = False
        r2 = self.svc.retry(r.import_id, self.p())
        self.assertEqual(r2.status, "completed", r2.errors)
        self.assertEqual((len(self.graph.entities), self.docs.count("documents")), (4, 1))
        self.assertEqual(self.jobs.get_job(r.import_id)["retry_count"], 1)

    def test_mongo_failure(self):
        self.docs.fail_on_write = True
        r = self.svc.import_kg(self.p(), "upsert")
        self.assertEqual((r.status, r.stage), ("failed", "mongodb"))
        self.assertIn("MONGO_IMPORT_ERROR", self.codes(r))
        self.assertEqual(len(self.graph.entities), 0)  # Neo4j never touched

    def test_neo4j_failure_on_existing_document_is_partial(self):
        self.svc.import_kg(self.p(), "upsert")
        p = self.p(); p["entities"][0]["canonical_name"] = "Tên mới"
        self.graph.fail_on_write = True
        r = self.svc.import_kg(p, "upsert")
        self.assertEqual((r.status, r.compensated, r.retryable), ("partial", False, True))
        self.assertEqual(self.docs.count("documents"), 1)  # old data must not be deleted
        self.graph.fail_on_write = False
        r2 = self.svc.retry(r.import_id, p)
        self.assertEqual(r2.status, "completed", r2.errors)
        self.assertEqual(self.graph.entities["ENT_000001"]["canonical_name"], "Tên mới")

    def test_compensation_failure_reports_partial(self):
        self.graph.fail_on_write = True
        self.docs.fail_on_delete = True
        r = self.svc.import_kg(self.p(), "upsert")
        self.assertEqual(r.status, "partial")
        self.assertIn("COMPENSATION_FAILED", self.codes(r))
        self.docs.fail_on_delete = False
        self.graph.fail_on_write = False
        self.assertEqual(self.svc.retry(r.import_id, self.p()).status, "completed")

    def test_retry_rejects_different_payload_and_non_retryable(self):
        self.graph.fail_on_write = True
        r = self.svc.import_kg(self.p(), "upsert")
        p = self.p(); p["entities"][0]["canonical_name"] = "Đổi"
        self.assertEqual(self.svc.retry(r.import_id, p).http_status, 409)
        bad = self.svc.import_kg({"x": 1}, "upsert")
        self.assertEqual(self.svc.retry(bad.import_id, {"x": 1}).http_status, 409)
        self.assertEqual(self.svc.retry("IMP_NOPE", {}).http_status, 409)

    def test_get_status(self):
        r = self.svc.import_kg(self.p(), "upsert")
        self.assertEqual(self.svc.get_status(r.import_id)["status"], "completed")
