import unittest

from app.modules.kg_import.ontology import Ontology
from app.modules.kg_query import cypher
from app.modules.kg_query.intents import PRESET_CHAINS, build_intents, uncovered_relations, unknown_relation_names
from app.modules.kg_query.models import QuerySpec, Step
from app.modules.kg_query.service import KGQueryService
from tests.upstream.kg.fake_neo4j import FakeDriver, FakeEvidenceStore, FakeGraph, ROOT, docs_available

ONTOLOGY = Ontology.load(ROOT / "examples/kg" / "kg_ontology.example.json")


class IntentTests(unittest.TestCase):
    def test_every_name_in_every_intent_exists_in_the_ontology(self):
        self.assertEqual(unknown_relation_names(ONTOLOGY), {})

    def test_catch_all_reaches_everything(self):
        self.assertEqual(set(build_intents(ONTOLOGY)["related"].relations), set(ONTOLOGY.relations))

    def test_uncovered_are_reported_not_hidden(self):
        self.assertIsInstance(uncovered_relations(ONTOLOGY), list)

    def test_presets_reference_known_intents_and_types(self):
        intents = build_intents(ONTOLOGY)
        for steps in PRESET_CHAINS.values():
            for s in steps:
                self.assertIn(s.intent, intents)
                for t in s.target_types or ():
                    self.assertTrue(ONTOLOGY.has_entity_type(t), t)


class CypherSafetyTests(unittest.TestCase):
    def test_relation_type_injection_is_rejected(self):
        for bad in ("X`) DETACH DELETE n //", "lower", "A B", "", "HAS-SYMPTOM"):
            with self.assertRaises(ValueError):
                cypher.rel_union([bad])

    def test_values_are_parameters_and_types_backticked(self):
        q = cypher.neighbors("out", ["HAS_SYMPTOM", "TREATED_BY"])
        self.assertIn("[r:`HAS_SYMPTOM`|`TREATED_BY`]", q)
        self.assertIn("$ids", q)
        self.assertNotIn("DELETE", q)

    def test_path_depth_is_clamped(self):
        self.assertIn("*..4]", cypher.shortest_paths(None, 99))
        self.assertIn("*..1]", cypher.shortest_paths(None, -5))

    def test_lucene_escaping(self):
        self.assertEqual(cypher.lucene_query("copd (mạn) a+b"), "copd AND \\(mạn\\) AND a\\+b")


@unittest.skipUnless(docs_available(), "examples/DOC_00000{1,2,3}_kg_import_global_ids.json not found")
class ServiceOnRealExamplesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = FakeGraph()

    def setUp(self):
        self.driver = FakeDriver(self.graph)
        self.svc = KGQueryService(self.driver, ONTOLOGY, evidence_store=FakeEvidenceStore(self.graph))

    # -- resolution
    def test_alias_finds_both_spellings_of_the_same_disease(self):
        anchors = self.svc.resolve("COPD")
        names = {a.entity.name for a in anchors}
        self.assertIn("Bệnh phổi tắc nghẽn mãn tính", names)
        self.assertIn("Bệnh phổi tắc nghẽn mạn tính", names)

    def test_exact_name_then_alias_sibling_recovers_the_other_node(self):
        anchors = self.svc.resolve("Bệnh phổi tắc nghẽn mạn tính")
        by = {a.entity.name: a.matched_by for a in anchors}
        self.assertEqual(by["Bệnh phổi tắc nghẽn mạn tính"], "exact_name")
        self.assertEqual(by["Bệnh phổi tắc nghẽn mãn tính"], "alias_sibling")

    def test_fulltext_missing_index_does_not_break_resolution(self):
        self.assertTrue(self.svc.resolve("phổi tắc nghẽn"))  # falls through to CONTAINS

    def test_unknown_mention(self):
        self.assertEqual(self.svc.resolve("zzzz không tồn tại"), [])

    # -- direction inference
    def test_direction_plan_for_disease(self):
        plan = self.svc.direction_plan("Disease", ["TREATED_BY", "TREATS", "HAS_COMORBIDITY", "HAS_RISK_FACTOR",
                                                   "RISK_FACTOR_FOR", "HAS_SYMPTOM", "NOT_IN_ONTOLOGY"])
        self.assertEqual(sorted(plan["out"]), ["HAS_RISK_FACTOR", "HAS_SYMPTOM", "TREATED_BY"])
        self.assertEqual(sorted(plan["in"]), ["RISK_FACTOR_FOR", "TREATS"])
        self.assertEqual(plan["any"], ["HAS_COMORBIDITY"])

    # -- 1-hop
    def _run(self, **kw):
        return self.svc.run(QuerySpec(**kw))

    def test_symptom_question(self):
        res = self._run(mentions=["COPD"], intents=["symptom"])
        self.assertEqual(res.status, "ok")
        self.assertTrue(res.facts)
        self.assertTrue(all(f.predicate in build_intents(ONTOLOGY)["symptom"].relations for f in res.facts))
        self.assertTrue(all(f.far_end.type == "Symptom" for f in res.facts))

    def test_same_triple_from_two_documents_becomes_one_fact_with_both_sources(self):
        res = self._run(mentions=["COPD"], intents=["treatment"])
        self.assertTrue(any(len(f.doc_ids) > 1 for f in res.facts))
        keys = [(f.subject.id, f.predicate, f.object.id) for f in res.facts]
        self.assertEqual(len(keys), len(set(keys)))

    def test_answers_merge_spelling_variants_of_the_same_disease(self):
        res = self._run(mentions=["COPD"], intents=["symptom"])
        keys = [(a.predicate, a.entity.id) for a in res.answers]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertLess(len(res.answers), len(res.facts))          # 2 COPD nodes state the same symptoms
        dyspnea = next(a for a in res.answers if a.entity.name == "Khó thở")
        self.assertEqual(len(dyspnea.asserted_by), 2)
        self.assertEqual(set(dyspnea.doc_ids), {"DOC_000001", "DOC_000002", "DOC_000003"})

    def test_target_type_filter(self):
        res = self._run(mentions=["COPD"], intents=["treatment"], target_types=["Medication"])
        self.assertTrue(res.facts)
        self.assertTrue(all(f.far_end.type == "Medication" for f in res.facts))

    def test_risk_factor_question_uses_both_directions(self):
        res = self._run(mentions=["COPD"], intents=["risk_factor"])
        self.assertTrue(res.facts)
        self.assertTrue(all(f.far_end.id != f.anchor_id for f in res.facts))

    def test_evidence_text_is_attached_from_mongo_store(self):
        res = self._run(mentions=["COPD"], intents=["symptom"])
        self.assertTrue(all(f.evidence_texts for f in res.facts))
        self.assertTrue(all(len(f.evidence_texts) <= self.svc.limits.evidence_per_fact for f in res.facts))
        res2 = self.svc.run(QuerySpec(["COPD"], intents=["symptom"]), with_evidence=False)
        self.assertTrue(all(not f.evidence_texts for f in res2.facts))

    # -- multi-hop
    def test_chain_drug_adverse_effects(self):
        res = self._run(mentions=["COPD"], chain=list(PRESET_CHAINS["drug_adverse_effects"]))
        self.assertEqual(res.status, "ok")
        self.assertTrue(res.chains)
        anchor_ids = {a.entity.id for v in res.anchors.values() for a in v}
        for path in res.chains:
            self.assertIn(path[0].anchor_id, anchor_ids)
            self.assertEqual([f.hop for f in path], sorted({f.hop for f in path}))
            for prev, nxt in zip(path, path[1:]):
                self.assertEqual(nxt.anchor_id, prev.far_end.id)
        self.assertTrue(all(p[-1].hop == 3 for p in res.chains))          # dead ends are dropped
        self.assertTrue(all(p[-1].far_end.type == "AdverseEffect" for p in res.chains))

    def test_chain_is_capped_at_three_steps(self):
        spec = self.svc.check_spec(QuerySpec(["COPD"], chain=[Step("symptom")] * 6))
        self.assertEqual(len(spec.chain), 3)

    # -- paths
    def test_path_between_two_entities(self):
        res = self._run(mentions=["COPD", "Ung thư phổi"], path=True)
        self.assertEqual(res.status, "ok")
        self.assertTrue(res.paths)
        for p in res.paths:
            self.assertEqual(len(p.nodes), len(p.facts) + 1)
            self.assertLessEqual(len(p.facts), 3)
        self.assertEqual(len({len(p.facts) for p in res.paths}), 1)      # shortest only

    def test_path_does_not_detour_through_the_other_spelling_of_an_endpoint(self):
        res = self._run(mentions=["COPD", "Thiếu máu"], path=True)
        endpoints = {a.entity.id for v in res.anchors.values() for a in v}
        self.assertTrue(res.paths)
        for p in res.paths:
            self.assertFalse(any(n.id in endpoints for n in p.nodes[1:-1]))

    # -- fallbacks and hygiene
    def test_no_entity_status_lets_the_caller_fall_back(self):
        res = self._run(mentions=["zzzz không tồn tại"], intents=["symptom"])
        self.assertEqual(res.status, "no_entity")
        self.assertEqual(res.facts, [])

    def test_unknown_intent_and_types_are_repaired_not_fatal(self):
        spec = QuerySpec.from_dict({"mentions": ["COPD"], "intents": ["giá_thuốc"], "target_types": ["Nope", "Symptom"]})
        res = self.svc.run(spec)
        self.assertEqual(res.status, "ok")
        self.assertTrue(any("unknown intent" in n for n in res.notes))
        self.assertEqual(spec.target_types, ["Symptom"])

    def test_only_read_transactions_are_used(self):
        self._run(mentions=["COPD"], intents=["symptom"])  # FakeSession has no execute_write: would raise
        self.assertTrue(self.driver.log)

    def test_from_dict_chain_preset_name(self):
        spec = QuerySpec.from_dict({"mentions": ["COPD"], "chain": "drug_adverse_effects"}, PRESET_CHAINS)
        self.assertEqual([s.intent for s in spec.chain], ["treatment", "membership", "adverse_effect"])


if __name__ == "__main__":
    unittest.main()
