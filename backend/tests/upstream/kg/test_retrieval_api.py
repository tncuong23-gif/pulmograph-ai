import unittest
from unittest.mock import Mock
from fastapi.testclient import TestClient
from app.modules.kg_query.retrieval_api import create_app, detect_mentions
from app.modules.kg_query.models import QueryResult, Fact, EntityRef
from app.modules.kg_query.intents import build_intents
from app.modules.kg_import.ontology import Ontology
from pathlib import Path

class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.service = Mock()
        self.service.intents = build_intents(Ontology.load(Path(__file__).parents[3] / 'examples/kg/kg_ontology.example.json'))
        self.service._read.return_value = [
            {'id': 'D1', 'name': 'COPD', 'type': 'Disease', 'aliases': []},
            {'id': 'D2', 'name': 'Viêm phổi', 'type': 'Disease', 'aliases': []}]
        fact = Fact(EntityRef('D1', 'COPD', 'Disease'), 'HAS_SYMPTOM', EntityRef('S1', 'Ho', 'Symptom'), 'D1', doc_ids=['DOC1'])
        fact.evidence_texts = [{'doc_id': 'DOC1', 'evidence_id': 'E1', 'text': 'Fixture evidence.'}]
        self.service.run.return_value = QueryResult(status='ok', facts=[fact])
        self.client = TestClient(create_app(self.service))
    def test_question_and_sources(self):
        r = self.client.post('/api/v1/kg/query', json={'question': 'COPD có triệu chứng gì?'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['query']['intents'], ['symptom'])
        self.assertEqual(r.json()['llm_context']['sources'][0]['evidence_id'], 'E1')
        self.assertNotIn('answer', r.json())
    def test_upstream(self):
        r = self.client.post('/api/v1/kg/query', json={'question': 'Nó có triệu chứng gì?', 'mentions': ['Viêm phổi'], 'intents': ['symptom'], 'include_evidence': False})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.service.run.call_args.kwargs['resolved_anchors']['Viêm phổi'][0].entity.id, 'D2')
        self.assertFalse(self.service.run.call_args.kwargs['with_evidence'])
    def test_pronoun(self):
        self.service._read.return_value = []
        r = self.client.post('/api/v1/kg/query', json={'question': 'Nó có triệu chứng gì?'})
        self.assertEqual(r.json()['status'], 'needs_clarification')
        self.service.run.assert_not_called()
    def test_longest(self):
        self.service._read.return_value = [
            {'id': 'D1', 'name': 'Viêm phổi', 'type': 'Disease'},
            {'id': 'D2', 'name': 'Viêm phổi cộng đồng', 'type': 'Disease'}]
        self.assertEqual(detect_mentions(self.service, 'Viêm phổi cộng đồng là gì?'), ['viêm phổi cộng đồng'])
        self.assertEqual(self.service._read.call_count, 1)
    def test_validation(self):
        for p in ({'question':' '}, {'question':'x','limit':201}, {'question':'x','intents':['bad']}, {'question':'x','cypher':'x'}):
            self.assertEqual(self.client.post('/api/v1/kg/query', json=p).status_code, 422)
    def test_failure(self):
        self.service.run.side_effect = RuntimeError('secret')
        with self.assertLogs('app.modules.kg_query.retrieval_api', level='ERROR'):
            r = self.client.post('/api/v1/kg/query', json={'question':'COPD?'})
        self.assertEqual(r.status_code, 503)
        self.assertNotIn('secret', r.text)
    def test_empty(self):
        self.service.run.return_value = QueryResult(status='no_facts')
        r = self.client.post('/api/v1/kg/query', json={'question':'COPD?'}).json()
        self.assertTrue(r['retrieval']['fallback_recommended'])
        self.assertEqual(r['llm_context']['facts'], [])
    def test_openapi(self):
        self.assertIn('/api/v1/kg/query', self.client.get('/openapi.json').json()['paths'])
