from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from app.modules.kg_query import assessment as a
from app.modules.kg_query.models import Anchor, EntityRef, Fact
from app.modules.kg_query.retrieval_api import create_app


def relation(d='d1', f='s1', name='Ho', properties='{}', doc='doc1', kind='Symptom'):
    return dict(disease_id=d, disease_name=f'Bệnh thử {d}', disease_type='Disease',
                feature_id=f, feature_name=name, feature_type=kind,
                rel_id=f'{doc}:{d}:{f}', rel='HAS_SYMPTOM', doc_id=doc,
                evidence_ids=['ev1'], proposition_ids=['p1'], confidence=.99,
                properties_json=properties)


class Service:
    def __init__(self):
        self.rows = [relation(), relation(f='s2', name='Sốt', properties='{"population":"adult"}'),
                     relation(d='d2'), relation(d='d2', f='s3', name='Khó thở')]
        self.nodes = [dict(id='d1', name='Bệnh thử d1', type='Disease'),
                      dict(id='d2', name='Bệnh thử d2', type='Disease')]
        self.evidence_store = object()
        self.sources = True
        self.intents = {}
        self.calls = []

    def _read(self, q, **p):
        self.calls.append((q, p))
        if q == a.ENTITIES:
            nodes = {n['id']: n for n in self.nodes}
            for r in self.rows:
                nodes[r['feature_id']] = dict(id=r['feature_id'], name=r['feature_name'], type=r['feature_type'])
            return [nodes[i] for i in p['ids'] if i in nodes]
        if q == a.DISEASE_PAGE:
            return [n for n in self.nodes if n['id'] > p['after'] and (p['ids'] is None or n['id'] in p['ids'])][:p['limit']]
        if q == a.COVERAGE:
            return [dict(disease_id=n['id'], relation='HAS_SYMPTOM', edge_count=2, evidence_reference_count=1)
                    for n in self.nodes if n['id'] in p['ids']]
        if q == a.RELATIONS:
            return [r for r in self.rows if (p['feature_ids'] is None or r['feature_id'] in p['feature_ids'])
                    and (p['disease_ids'] is None or r['disease_id'] in p['disease_ids'])][:p['limit']]
        raise AssertionError(q)

    def attach_evidence(self, facts):
        for f in facts:
            if self.sources:
                f.evidence_texts = [dict(doc_id=f.doc_ids[0], evidence_id='ev1', text='Synthetic test evidence; not medical guidance.')]

    def resolve(self, mention):
        return [Anchor(EntityRef('s1', mention, 'Symptom'), 'exact_name')]


def payload():
    return dict(patient_id='patient1', assessment_id='assessment1', facts=[dict(
        fact_id='fact1', kg_entity_id='s1', presence='present', confirmation_status='user_confirmed',
        confirmed_at='2026-09-30T11:00:00+00:00', source_id='message1', timeframe='current')])


def test_sourced_proposals_preserve_properties_and_skip_known():
    svc = Service(); data = a.followups(svc, a.FollowupRequest(**payload()))
    assert data['status'] == 'proposals'
    assert {q['target_entity_id'] for q in data['questions']} == {'s2', 's3'}
    q = next(q for q in data['questions'] if q['target_entity_id'] == 's2')
    assert q['basis'][0]['assertions'][0]['properties'] == {'population': 'adult'}
    assert q['requires_review'] and not data['diagnostic_ready']
    assert 'probability' not in data['candidate_diseases'][0]
    assert all(query.lstrip().startswith('MATCH') for query, _ in svc.calls)


def test_absent_unknown_and_asked_are_not_repeated():
    p = payload()
    p['facts'].append({**p['facts'][0], 'fact_id': 'f2', 'kg_entity_id': 's2', 'presence': 'absent'})
    p['asked_entity_ids'] = ['s3']
    data = a.followups(Service(), a.FollowupRequest(**p))
    assert data['questions'] == []
    assert len(data['candidate_diseases']) == 2


@pytest.mark.parametrize('change,status', [({'presence': 'absent'}, 'no_current_positive_facts'),
    ({'presence': 'unknown'}, 'no_current_positive_facts'),
    ({'timeframe': 'history'}, 'no_current_positive_facts'),
    ({'kg_entity_id': 'not-a-node'}, 'unmapped_facts')])
def test_no_guessing(change, status):
    p = payload(); p['facts'][0].update(change)
    assert a.followups(Service(), a.FollowupRequest(**p))['status'] == status


def test_conflicting_facts_block_proposals():
    p = payload(); p['facts'].append({**p['facts'][0], 'fact_id': 'f2', 'presence': 'absent'})
    assert a.followups(Service(), a.FollowupRequest(**p))['status'] == 'conflicting_facts'


def test_missing_evidence_blocks_proposals():
    svc = Service(); svc.sources = False
    assert a.followups(svc, a.FollowupRequest(**payload()))['questions'] == []


def test_invalid_properties_are_not_silently_used():
    svc = Service(); svc.rows[1]['properties_json'] = 'invalid'
    data = a.followups(svc, a.FollowupRequest(**payload()))
    assert {q['target_entity_id'] for q in data['questions']} == {'s3'}


def test_truncation_requires_narrowing():
    svc = Service(); svc.rows = [relation(d=f'd{i}') for i in range(501)]
    assert a.followups(svc, a.FollowupRequest(**payload()))['status'] == 'needs_narrower_scope'


def test_ambiguous_and_fuzzy_entities_not_auto_selected():
    svc = Service()
    svc.resolve = lambda _: [Anchor(EntityRef('a', 'A', 'Symptom'), 'exact_name'), Anchor(EntityRef('b', 'A', 'Symptom'), 'alias')]
    data = a.map_entities(svc, a.MapRequest(mentions=['A']))['items'][0]
    assert data['status'] == 'needs_confirmation' and data['kg_entity_id'] is None
    svc.resolve = lambda _: [Anchor(EntityRef('a', 'A', 'Symptom'), 'contains')]
    assert a.map_entities(svc, a.MapRequest(mentions=['A']))['items'][0]['kg_entity_id'] is None


def test_coverage_paging_missing_ids_and_reference_only_counts():
    svc = Service(); first = a.coverage(svc, a.CoverageRequest(page_size=1))
    assert first['next_after_id'] == 'd1'
    assert first['items'][0]['groups']['symptoms']['without_evidence_reference'] == 1
    assert not first['evidence_text_checked'] and not first['clinical_completeness_assessed']
    second = a.coverage(svc, a.CoverageRequest(page_size=1, after_id='d1'))
    assert second['items'][0]['disease']['id'] == 'd2' and second['next_after_id'] is None
    assert a.coverage(svc, a.CoverageRequest(disease_ids=['missing', 's1']))['missing_or_non_disease_ids'] == ['missing', 's1']


def test_assertions_from_different_sources_are_kept_separate():
    f = Fact(EntityRef('d','D','Disease'),'HAS_SYMPTOM',EntityRef('s','S','Symptom'),'d')
    f.add_row(dict(rel_id='r1',doc_id='doc1',properties_json='{"population":"adult"}'))
    f.add_row(dict(rel_id='r2',doc_id='doc2',properties_json='{"population":"child"}'))
    assert len(f.to_dict()['assertions']) == 2


def test_api_rejects_unconfirmed_or_unscoped_data():
    client = TestClient(create_app(Service()))
    p = payload(); p['facts'][0]['confirmation_status'] = 'extracted'
    assert client.post('/api/v1/kg/assessment/followups', json=p).status_code == 422
    p = payload(); p['facts'][0]['confirmed_at'] = '2026-09-30T11:00:00'
    assert client.post('/api/v1/kg/assessment/followups', json=p).status_code == 422
    assert client.post('/api/v1/kg/assessment/followups', json=payload()).json()['status'] == 'proposals'
    assert client.post('/api/v1/kg/assessment/coverage', json={}).status_code == 200
    assert client.post('/api/v1/kg/assessment/map', json={'mentions':['Ho']}).json()['items'][0]['status'] == 'resolved'


def test_api_dependency_failure_does_not_leak_secrets():
    svc = Service(); svc._read = Mock(side_effect=RuntimeError('private-password'))
    response = TestClient(create_app(svc)).post('/api/v1/kg/assessment/coverage', json={})
    assert response.status_code == 503 and 'private-password' not in response.text


def test_explicit_negative_relation_is_not_positive_support():
    svc = Service()
    for r in svc.rows:
        if r['feature_id'] == 's1':
            r['properties_json'] = '{"negated": true}'
    assert a.followups(svc, a.FollowupRequest(**payload()))['candidate_diseases'] == []


def test_audit_script_collects_all_pages_and_checks_label_ids(monkeypatch):
    from scripts import audit_kg_assessment as script
    svc = Service()
    def page(base, after):
        return a.coverage(svc, a.CoverageRequest(page_size=1, after_id=after))
    monkeypatch.setattr(script, 'request_page', page)
    report = script.run_audit('http://test', {'LabelA': ['d1'], 'LabelB': [], 'LabelC': ['missing']})
    assert report['disease_count'] == 2
    assert [m['status'] for m in report['model_mapping']] == ['ids_present', 'unmapped', 'missing_ids']
