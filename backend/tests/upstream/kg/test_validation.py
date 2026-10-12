from app.modules.kg_import.config import Limits
from app.modules.kg_import.models import parse_import
from app.modules.kg_import.normalization import normalize
from app.modules.kg_import.validation import find_external_refs, validate
from tests.upstream.kg.helpers import ServiceTestCase, load_ontology, load_payload


class ValidationTests(ServiceTestCase):
    def issues(self, payload, limits=None):
        kg, iss = parse_import(payload)
        return iss if kg is None else validate(kg, load_ontology(), limits or Limits())

    def codes_of(self, payload, **kw):
        return {i.code for i in self.issues(payload, **kw)}

    def test_valid_example(self):
        self.assertEqual(self.issues(self.p()), [])

    def test_not_an_object(self):
        self.assertIn("SCHEMA_INVALID_TYPE", self.codes_of([1, 2]))

    def test_missing_required_fields_are_all_reported(self):
        p = self.p()
        del p["schema_version"]
        del p["entities"][0]["canonical_name"]
        codes = self.codes_of(p)
        self.assertEqual(codes, {"SCHEMA_REQUIRED_FIELD"})
        self.assertEqual(len(self.issues(p)), 2)

    def test_bad_schema_version(self):
        p = self.p(); p["schema_version"] = "9.9"
        self.assertIn("SCHEMA_VERSION_UNSUPPORTED", self.codes_of(p))

    def test_duplicate_entity_and_relation(self):
        p = self.p()
        p["entities"].append(dict(p["entities"][0]))
        p["relations"].append(dict(p["relations"][0]))
        self.assertTrue({"DUPLICATE_ENTITY", "DUPLICATE_RELATION"} <= self.codes_of(p))

    def test_unknown_entity_type_is_rejected_not_fixed(self):
        p = self.p(); p["entities"][0]["type"] = "disease"  # wrong case must NOT be auto-corrected
        self.assertIn("ONTOLOGY_UNKNOWN_ENTITY_TYPE", self.codes_of(p))

    def test_unknown_relation_type_and_injection_attempt(self):
        p = self.p(); p["relations"][0]["type"] = "HAS_SYMPTOM`]->() DETACH DELETE n //"
        self.assertIn("ONTOLOGY_UNKNOWN_RELATION_TYPE", self.codes_of(p))

    def test_domain_range_violation(self):
        p = self.p(); p["relations"][0]["target"] = "ENT_000004"  # RiskFactor is not a Symptom
        self.assertIn("ONTOLOGY_DOMAIN_RANGE_VIOLATION", self.codes_of(p))

    def test_empty_canonical_name(self):
        p = self.p(); p["entities"][0]["canonical_name"] = "   "
        self.assertIn("SCHEMA_EMPTY_FIELD", self.codes_of(p))

    def test_evidence_sentence_must_exist(self):
        p = self.p(); p["propositions"][0]["evidence"] = [{"sentence_id": "SENT_999"}]
        self.assertIn("EVIDENCE_SENTENCE_NOT_FOUND", self.codes_of(p))

    def test_relation_needs_provenance(self):
        p = self.p(); p["relations"][0]["proposition_ids"] = []
        self.assertIn("PROVENANCE_MISSING", self.codes_of(p))
        self.assertNotIn("PROVENANCE_MISSING", self.codes_of(p, limits=Limits(require_provenance=False)))

    def test_relation_references_unknown_proposition(self):
        p = self.p(); p["relations"][0]["proposition_ids"] = ["PROP_404"]
        self.assertIn("RELATION_PROPOSITION_NOT_FOUND", self.codes_of(p))

    def test_id_format(self):
        p = self.p(); p["entities"][0]["id"] = "bad id;"
        self.assertIn("ID_INVALID", self.codes_of(p))

    def test_size_limit(self):
        self.assertIn("IMPORT_TOO_LARGE", self.codes_of(self.p(), limits=Limits(max_entities=1)))

    def test_external_refs_are_not_validation_errors(self):
        p = self.p(); p["relations"][0]["target"] = "ENT_EXTERNAL"
        kg, _ = parse_import(p)
        self.assertEqual(find_external_refs(kg), {"ENT_EXTERNAL"})
        self.assertEqual(self.issues(p), [])


class NormalizationTests(ServiceTestCase):
    def test_rules(self):
        p = self.p()
        p["entities"][0]["canonical_name"] = "  Bệnh   phổi  "
        p["entities"][0]["aliases"] = ["COPD", " COPD "]
        kg, _ = parse_import(p)
        e = normalize(kg).entities[0]
        self.assertEqual(e["canonical_name"], "Bệnh phổi")
        self.assertEqual(e["normalized_name"], "bệnh phổi")
        self.assertEqual(e["aliases"], ["COPD"])

    def test_provenance_chain(self):
        kg, _ = parse_import(self.p())
        n = normalize(kg)
        rel = n.relations[0]
        self.assertEqual(rel["proposition_ids"], ["PROP_000001"])
        self.assertEqual(rel["evidence_ids"], ["EVD_PROP_000001_SENT_000001"])
        ev = n.mongo["evidence"][0]
        self.assertEqual((ev["sentence_id"], ev["paragraph_id"], ev["section_id"]), ("SENT_000001", "PAR_000001", "SEC_000001"))
        self.assertIn("ho và khó thở", ev["text"])
        prop = n.mongo["propositions"][0]
        self.assertEqual(set(prop["relation_ids"]), {"REL_000001", "REL_000002"})

    def test_hash_is_stable_and_content_sensitive(self):
        kg1, _ = parse_import(self.p()); kg2, _ = parse_import(self.p())
        self.assertEqual(normalize(kg1).entities[0]["content_hash"], normalize(kg2).entities[0]["content_hash"])
        p = self.p(); p["entities"][0]["canonical_name"] = "Khác"
        kg3, _ = parse_import(p)
        self.assertNotEqual(normalize(kg1).entities[0]["content_hash"], normalize(kg3).entities[0]["content_hash"])
