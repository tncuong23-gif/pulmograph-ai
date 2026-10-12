"""Integration tests against REAL MongoDB and Neo4j. Skipped unless these env vars are set:

    KG_TEST_MONGODB_URI, KG_TEST_NEO4J_URI, KG_TEST_NEO4J_USER, KG_TEST_NEO4J_PASSWORD
The tests use a throw-away Mongo database and DELETE ALL NODES in the target Neo4j database.
Point them at a disposable instance only.
"""
import os
import unittest
import uuid

from app.modules.kg_import.service import KGImportService
from tests.upstream.kg.helpers import load_ontology, load_payload

ENV = ("KG_TEST_MONGODB_URI", "KG_TEST_NEO4J_URI", "KG_TEST_NEO4J_USER", "KG_TEST_NEO4J_PASSWORD")


@unittest.skipUnless(all(os.environ.get(k) for k in ENV), "real MongoDB/Neo4j not configured")
class RealDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from neo4j import GraphDatabase
        from pymongo import MongoClient
        from app.modules.kg_import.adapters.mongo import MongoKGStore
        from app.modules.kg_import.adapters.neo4j import Neo4jKGStore
        cls.mongo = MongoClient(os.environ["KG_TEST_MONGODB_URI"], serverSelectionTimeoutMS=5000)
        cls.dbname = "kg_test_" + uuid.uuid4().hex[:8]
        cls.driver = GraphDatabase.driver(os.environ["KG_TEST_NEO4J_URI"],
                                          auth=(os.environ["KG_TEST_NEO4J_USER"], os.environ["KG_TEST_NEO4J_PASSWORD"]))
        cls.mstore = MongoKGStore(cls.mongo[cls.dbname])
        cls.gstore = Neo4jKGStore(cls.driver, os.environ.get("KG_TEST_NEO4J_DATABASE", "neo4j"))
        cls.ontology = load_ontology()

    @classmethod
    def tearDownClass(cls):
        cls.mongo.drop_database(cls.dbname)
        cls.mongo.close()
        cls.driver.close()

    def setUp(self):
        with self.driver.session(database=self.gstore.database) as s:
            s.run("MATCH (n) DETACH DELETE n").consume()
        for c in self.mongo[self.dbname].list_collection_names():
            self.mongo[self.dbname][c].delete_many({})
        self.mstore.ensure_indexes()
        self.gstore.ensure_constraints(self.ontology.relation_names())
        self.svc = KGImportService(self.ontology, self.mstore, self.gstore, self.mstore)

    def cypher(self, q, **kw):
        with self.driver.session(database=self.gstore.database) as s:
            return [r.data() for r in s.run(q, **kw)]

    def test_constraints_script_is_idempotent(self):
        self.gstore.ensure_constraints(self.ontology.relation_names())
        self.mstore.ensure_indexes()

    def test_import_twice_no_duplicates(self):
        for _ in range(2):
            r = self.svc.import_kg(load_payload(), "upsert")
            self.assertEqual(r.status, "completed", r.errors)
        self.assertEqual(self.cypher("MATCH (e:Entity) RETURN count(e) AS n")[0]["n"], 4)
        self.assertEqual(self.cypher("MATCH ()-[r]->() RETURN count(r) AS n")[0]["n"], 3)
        self.assertEqual(self.cypher("MATCH (e:Entity) WITH e.id AS id, count(*) AS c WHERE c > 1 RETURN id")[0:1], [])
        db = self.mongo[self.dbname]
        self.assertEqual((db.documents.count_documents({}), db.propositions.count_documents({}), db.evidence.count_documents({})), (1, 2, 2))

    def test_relation_provenance_stored_in_graph(self):
        self.svc.import_kg(load_payload(), "upsert")
        row = self.cypher("MATCH ()-[r {id:'REL_000001'}]->() RETURN type(r) AS t, r.source_document_id AS d, "
                          "r.source_proposition_ids AS p, r.evidence_ids AS e")[0]
        self.assertEqual((row["t"], row["d"], row["p"]), ("HAS_SYMPTOM", "DOC_000001", ["PROP_000001"]))
        self.assertEqual(self.mongo[self.dbname].evidence.find_one({"evidence_id": row["e"][0]})["sentence_id"], "SENT_000001")

    def test_insert_conflict_and_replace(self):
        self.assertEqual(self.svc.import_kg(load_payload(), "insert").status, "completed")
        self.assertEqual(self.svc.import_kg(load_payload(), "insert").http_status, 409)
        p = load_payload(); p["relations"].pop(); p["propositions"].pop(); p["entities"].pop()
        p["document"]["sections"][0]["paragraphs"][0]["sentences"].pop()
        self.assertEqual(self.svc.import_kg(p, "replace").status, "completed")
        self.assertEqual(self.cypher("MATCH ()-[r]->() RETURN count(r) AS n")[0]["n"], 2)
        self.assertEqual(self.mongo[self.dbname].propositions.count_documents({}), 1)

    def test_unique_constraint_blocks_duplicate_entity_ids(self):
        with self.driver.session(database=self.gstore.database) as s:
            s.run("CREATE (:Entity {id:'X'})").consume()
            with self.assertRaises(Exception):
                s.run("CREATE (:Entity {id:'X'})").consume()

    def test_injection_string_never_reaches_cypher(self):
        p = load_payload(); p["relations"][0]["type"] = "HAS_SYMPTOM`]->() DETACH DELETE n //"
        self.assertEqual(self.svc.import_kg(p, "upsert").http_status, 422)
