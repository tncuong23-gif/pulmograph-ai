import copy
import json
import unittest
from pathlib import Path

from app.modules.kg_import.adapters.memory import MemoryDocumentStore, MemoryGraphStore, MemoryJobStore
from app.modules.kg_import.config import Limits
from app.modules.kg_import.ontology import Ontology
from app.modules.kg_import.service import KGImportService

ROOT = Path(__file__).resolve().parents[3]


def load_payload() -> dict:
    return json.loads((ROOT / "examples/kg" / "kg_import.json").read_text(encoding="utf-8"))


def load_ontology() -> Ontology:
    return Ontology.load(ROOT / "examples/kg" / "kg_ontology.example.json")


class ServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.docs, self.graph, self.jobs = MemoryDocumentStore(), MemoryGraphStore(), MemoryJobStore()
        self.svc = KGImportService(load_ontology(), self.docs, self.graph, self.jobs, Limits())
        self.payload = load_payload()

    def p(self):
        return copy.deepcopy(self.payload)

    def codes(self, result):
        return {e["code"] for e in result.errors}
