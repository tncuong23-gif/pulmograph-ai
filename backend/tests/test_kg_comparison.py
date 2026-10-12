"""Synthetic facts only; tests validate retrieval semantics, not clinical accuracy."""
import json
from dataclasses import replace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient

from app.modules.kg_import.utils import fold
from app.modules.kg_query.question_analysis import comparison_mode
from app.modules.kg_query.retrieval_api import create_app
from app.services.kg_chat import no_facts_text
from app.services.orchestrator import Orchestrator
from tests.test_kg_chat_query import fixture_service, query


@pytest.fixture
def service():
    return fixture_service()


def add_entity(service, eid, name, kind='Symptom'):
    service.driver.g.entities[eid] = {'id': eid, 'canonical_name': name, 'normalized_name': fold(name),
                                     'entity_type': kind, 'aliases': []}


def add_relation(service, src, dst, rel='HAS_SYMPTOM', properties=None, doc='SECOND_TEST'):
    graph = service.driver.g
    rid = 'EXTRA' + str(len(graph.rels))
    graph.rels.append({'id': rid, 'source': src, 'target': dst, 'type': rel, 'doc': doc,
                      'evidence_ids': [rid], 'props': ['P'+rid], 'confidence': .7,
                      'properties_json': json.dumps(properties or {})})
    graph.evidence[(doc, rid)] = {'text': 'Nguồn giả lập ' + rid, 'evidence_id': rid}


@pytest.mark.parametrize(('text', 'mode'), [
    ('So sánh COPD và Viêm phổi về triệu chứng', 'compare'),
    ('Doi chieu COPD va viem phoi ve dau hieu', 'compare'),
    ('COPD và Viêm phổi có triệu chứng nào giống nhau?', 'common'),
    ('Điểm chung về nguy cơ của COPD và Viêm phổi?', 'common'),
    ('COPD và Viêm phổi có triệu chứng khác gì?', 'difference'),
    ('Tác dụng phụ của Thuốc A và Thuốc B khác nhau như thế nào?', 'difference'),
    ('Điểm chung và khác biệt về triệu chứng giữa COPD và Viêm phổi?', 'compare'),
    ('Chẩn đoán phân biệt COPD?', None),
])
def test_comparison_question_modes(text, mode):
    assert comparison_mode(text) == mode


def test_common_matches_ids_and_has_independent_side_sources(service):
    result = query(service, 'COPD và Viêm phổi có triệu chứng nào giống nhau?')
    assert result['schema_version'] == '1.2'
    assert result['status'] == 'ok'
    ctx = result['llm_context']
    row = ctx['comparison']['rows'][0]
    assert row['classification'] == 'common'
    assert row['feature']['id'] == 'S1'
    for cell, entity in zip(row['cells'], ('D1', 'D2')):
        assert cell['entity_id'] == entity
        fact = ctx['facts'][cell['fact_indices'][0]]
        assert fact['subject']['id'] == entity
        assert fact['evidence'] and fact['assertions']
    assert len(ctx['sources']) == 2
    assert ctx['comparison']['complete'] is False


def test_only_one_side_is_unknown_not_negated(service):
    add_entity(service, 'S2', 'Dấu hiệu thử')
    add_relation(service, 'D1', 'S2')
    result = query(service, 'So sánh triệu chứng COPD và Viêm phổi')
    row = next(r for r in result['llm_context']['comparison']['rows'] if r['feature']['id'] == 'S2')
    assert row['classification'] == 'left_only'
    assert row['cells'][1] == {'entity_id': 'D2', 'status': 'not_found_in_retrieved_data', 'fact_indices': []}
    assert 'không có nghĩa' in result['llm_context']['comparison']['notice']


def test_differences_filter_does_not_include_common_rows(service):
    add_entity(service, 'S2', 'Dấu hiệu thử')
    add_relation(service, 'D2', 'S2')
    result = query(service, 'COPD và Viêm phổi khác nhau về triệu chứng?')
    rows = result['llm_context']['comparison']['rows']
    assert [r['classification'] for r in rows] == ['right_only']
    assert [f['subject']['id'] for f in result['llm_context']['facts']] == ['D2']


def test_same_display_name_different_ids_not_common(service):
    add_entity(service, 'S_COPY', 'Ho')
    service.driver.g.rels[1]['target'] = 'S_COPY'
    result = query(service, 'COPD và Viêm phổi có triệu chứng giống nhau?')
    assert result['status'] == 'no_facts'
    assert result['llm_context']['comparison']['no_result_reason'] == 'no_matching_rows'
    assert 'không khẳng định' in no_facts_text(result)


@pytest.mark.parametrize('properties', [{'negated': True}, {'population': 'trẻ em'}, {'condition': 'khi gắng sức'}])
def test_negation_and_population_or_conditions_are_not_dropped(service, properties):
    service.driver.g.rels[1]['properties_json'] = json.dumps(properties)
    result = query(service, 'So sánh COPD và Viêm phổi về triệu chứng')
    assert result['llm_context']['comparison']['rows'][0]['classification'] == 'assertion_difference'
    assert result['llm_context']['facts'][1]['assertions'][0]['properties'] == properties
    assert query(service, 'COPD và Viêm phổi có triệu chứng giống nhau?')['status'] == 'no_facts'


def test_matching_negative_assertions_stay_negative_with_evidence(service):
    for rel in service.driver.g.rels[:2]:
        rel['properties_json'] = '{"negated": true}'
    result = query(service, 'COPD và Viêm phổi có triệu chứng giống nhau?')
    assert result['llm_context']['comparison']['rows'][0]['classification'] == 'common'
    assert all(f['assertions'][0]['properties']['negated'] for f in result['llm_context']['facts'])


@pytest.mark.parametrize('bad', ['{broken', '[]', '"wrong"'])
def test_invalid_assertions_require_review_and_cannot_be_common(service, bad):
    service.driver.g.rels[1]['properties_json'] = bad
    result = query(service, 'So sánh triệu chứng COPD và Viêm phổi')
    assert result['llm_context']['comparison']['rows'][0]['classification'] == 'needs_review'
    assert query(service, 'COPD và Viêm phổi có triệu chứng giống nhau?')['status'] == 'no_facts'


def test_conflicting_sources_on_one_side_not_reduced_to_overlap(service):
    add_relation(service, 'D1', 'S1', properties={'negated': True})
    result = query(service, 'So sánh triệu chứng COPD và Viêm phổi')
    assert result['llm_context']['comparison']['rows'][0]['classification'] == 'assertion_difference'
    assert len(result['llm_context']['facts'][0]['assertions']) == 2


def test_duplicate_sources_do_not_create_duplicate_rows(service):
    add_relation(service, 'D1', 'S1')
    result = query(service, 'So sánh triệu chứng COPD và Viêm phổi')
    assert len(result['llm_context']['comparison']['rows']) == 1
    assert len(result['llm_context']['facts'][0]['assertions']) == 2
    assert len(result['llm_context']['sources']) == 3


def test_distinct_predicates_are_not_assumed_equivalent(service):
    service.driver.g.rels[1]['type'] = 'HAS_MANIFESTATION'
    result = query(service, 'So sánh triệu chứng COPD và Viêm phổi')
    assert not any(r['classification'] == 'common' for r in result['llm_context']['comparison']['rows'])


def test_inverse_direction_is_kept_and_not_merged(service):
    add_relation(service, 'M1', 'M2', rel='INTERACTS_WITH')
    result = query(service, 'So sánh tương tác của Thuốc A và Thuốc B')
    assert {r['direction'] for r in result['llm_context']['comparison']['rows']} == {'out', 'in'}
    assert len(result['llm_context']['facts']) == 1  # shared original triple, no inverted invented edge


def test_each_side_has_own_retrieval_budget_and_atomic_result_budget(service):
    result = query(service, 'So sánh triệu chứng COPD và Viêm phổi', limit=1)
    assert result['status'] == 'no_facts'
    assert result['retrieval']['truncated']
    assert not result['llm_context']['facts']
    assert result['llm_context']['comparison']['no_result_reason'] == 'result_limit'
    assert 'đối chiếu đầy đủ' in no_facts_text(result)
    service.limits = replace(service.limits, per_query_rows=1)
    result = query(service, 'So sánh triệu chứng COPD và Viêm phổi', limit=2)
    assert result['status'] == 'ok'
    assert len(result['llm_context']['facts']) == 2
    assert result['retrieval']['truncated']
    assert all(c['query_limited'] for c in result['llm_context']['comparison']['coverage'])


def test_common_is_found_before_output_budget_not_lost_behind_left_only(service):
    for i in range(8):
        add_entity(service, f'S{i+10}', f'A dấu hiệu {i}')
        add_relation(service, 'D1', f'S{i+10}')
    result = query(service, 'COPD và Viêm phổi có triệu chứng giống nhau?', limit=2)
    assert result['status'] == 'ok'
    assert result['llm_context']['comparison']['rows'][0]['classification'] == 'common'


@pytest.mark.parametrize('question', [
    'So sánh COPD và Viêm phổi', 'So sánh triệu chứng COPD',
    'So sánh triệu chứng COPD và Thuốc A',
    'So sánh triệu chứng COPD và Viêm phổi và COVID19',
    'So sánh tác dụng phụ của thuốc điều trị COPD và Viêm phổi',
    'COPD và Bệnh phổi tắc nghẽn mạn tính có triệu chứng giống nhau?',
])
def test_missing_criteria_wrong_types_or_number_of_entities_ask_back(service, question):
    result = query(service, question)
    assert result['status'] == 'needs_clarification'
    assert not result['llm_context']['facts']


def test_ambiguous_entity_can_be_confirmed_without_changing_original_query(service):
    result = query(service, 'So sánh triệu chứng ABC và COPD')
    assert result['status'] == 'needs_clarification'
    assert result['clarification']['can_confirm']
    result = query(service, 'So sánh triệu chứng ABC và COPD', entity_ids=['D4', 'D1'])
    assert result['query']['mode'] == 'compare'
    assert result['query']['entity_resolution'] == 'user_confirmed'
    assert [e['id'] for e in result['llm_context']['comparison']['entities']] == ['D4', 'D1']


def test_explicit_mode_intents_multicriteria_and_no_evidence(service):
    result = query(service, 'Đối chiếu hai thực thể', mode='compare', entity_ids=['D1','D2'],
                   intents=['symptom','treatment'], include_evidence=False)
    assert result['status'] == 'ok'
    assert {r['criterion'] for r in result['llm_context']['comparison']['rows']} == {'symptom','treatment'}
    assert all(not f['evidence'] for f in result['llm_context']['facts'])
    assert not result['llm_context']['sources']
    assert query(service, 'COPD và Viêm phổi giống nhau?', intents=['symptom'])['query']['mode'] == 'common'


def test_api_validates_mode_criteria_and_presets(service):
    with TestClient(create_app(service)) as client:
        for extra in ({'mode':'compare','preset':'drugs_for_disease'}, {'mode':'common','intents':['injected']},
                      {'mode':'difference','cypher':'MATCH (n) DELETE n'}):
            assert client.post('/api/v1/kg/query', json={'question':'COPD?', **extra}).status_code == 422
        result = client.post('/api/v1/kg/query', json={'question':'So sánh triệu chứng COPD và Viêm phổi'}).json()
        assert result['status'] == 'ok'
        assert result['llm_context']['comparison']['rows']
        assert client.get('/api/v1/kg/meta').json()['comparison']['requires_criterion']


def orchestration(service, label):
    modules = Mock()
    modules.context_resolve = AsyncMock(return_value={'resolution_status':'resolved', 'normalized_question':'COVID19?',
        'active_topic': {'canonical_name':'COVID-19'}})
    modules.kg_query = AsyncMock(side_effect=lambda q, mentions, **kw: query(service, q, context_mentions=mentions, **kw))
    modules.rag_search = AsyncMock(return_value={'results':[{'document_id':'RAG_TEST','text':'Nguồn khác'}]})
    classifier = Mock(); classifier.predict.return_value = {'label':label, 'confidence':.8}
    llm = AsyncMock(); llm.generate.return_value = 'Tóm tắt thử nghiệm.'
    return Orchestrator(classifier, modules, llm), modules, llm


ARGS = dict(conversation_id='c', message_id='m', timestamp='now', attachments=[])


@pytest.mark.asyncio
async def test_general_comparison_routes_to_kg_with_auditable_model_prediction(service):
    orchestrator, modules, llm = orchestration(service, 'GENERAL_MEDICAL_QUERY')
    result = await orchestrator.answer(question='So sánh triệu chứng COPD và Viêm phổi', **ARGS)
    assert result['route'] == 'RELATIONAL_QUERY'
    assert result['classifier']['original_label'] == 'GENERAL_MEDICAL_QUERY'
    assert result['kg_comparison']['rows']
    assert len(result['sources']) == 2
    assert llm.generate.call_args.args[1]['module_results']['kg']['comparison']['mode'] == 'compare'
    modules.rag_search.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('label', ['DIAGNOSTIC_ASSESSMENT','OUT_OF_SCOPE'])
async def test_comparison_does_not_override_diagnostic_or_out_of_scope_gates(service, label):
    orchestrator, modules, llm = orchestration(service, label)
    result = await orchestrator.answer(question='So sánh triệu chứng COPD và Viêm phổi', **ARGS)
    assert result['route'] == label
    modules.kg_query.assert_not_awaited()
    llm.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_common_rows_fall_back_to_rag_without_fabricated_kg_comparison(service):
    orchestrator, modules, llm = orchestration(service, 'CLINICAL_EXPLANATION_MANAGEMENT')
    result = await orchestrator.answer(question='COPD và COVID19 có triệu chứng giống nhau?', **ARGS)
    assert result['route'] == 'GENERAL_MEDICAL_QUERY'
    assert result['kg_comparison'] is None
    assert set(llm.generate.call_args.args[1]['module_results']) == {'rag'}
    modules.rag_search.assert_awaited_once()
