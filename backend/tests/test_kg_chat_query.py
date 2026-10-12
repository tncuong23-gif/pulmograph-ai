"""Synthetic graph tests: these edges are test data, not medical assertions."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient

from app.modules.kg_import.ontology import Ontology
from app.modules.kg_import.utils import fold
from app.modules.kg_query.entity_lookup import EntityLookup, CATALOG_QUERY, get_lookup
from app.modules.kg_query.question_analysis import detect_intents
from app.modules.kg_query.question_analysis import uses_context
from app.modules.kg_query.retrieval_api import QueryRequest, create_app, retrieve
from app.modules.kg_query.service import KGQueryService
from app.services.orchestrator import Orchestrator
from tests.upstream.kg.fake_neo4j import FakeDriver, FakeEvidenceStore, ROOT


def fixture_service():
    graph = SimpleNamespace(entities={}, rels=[], evidence={})
    def entity(eid, name, kind, aliases=()):
        graph.entities[eid] = {'id': eid, 'canonical_name': name, 'normalized_name': fold(name),
                               'entity_type': kind, 'aliases': list(aliases)}
    entity('D1', 'COPD', 'Disease', ['Bệnh phổi tắc nghẽn mạn tính'])
    entity('D2', 'Viêm phổi', 'Disease')
    entity('D3', 'COVID-19', 'Disease')
    entity('D4', 'Bệnh A thử nghiệm', 'Disease', ['ABC'])
    entity('D5', 'Bệnh B thử nghiệm', 'Disease', ['ABC'])
    entity('G1', 'Nhóm thuốc thử', 'DrugClass')
    entity('M1', 'Thuốc A', 'Medication')
    entity('M2', 'Thuốc B', 'Medication')
    entity('M3', 'Thuốc C', 'Medication')
    entity('S1', 'Ho', 'Symptom')
    entity('A1', 'Phản ứng A', 'AdverseEffect')
    entity('C1', 'Điều kiện A', 'Disease')
    def relation(src, rel, dst, properties=None):
        rid = f'R{len(graph.rels)+1}'
        eid = f'E{len(graph.rels)+1}'
        graph.rels.append({'id': rid, 'source': src, 'target': dst, 'type': rel,
                           'doc': 'SYNTHETIC_TEST', 'evidence_ids': [eid], 'props': ['P'+rid],
                           'confidence': .9, 'properties_json': json.dumps(properties or {})})
        graph.evidence[('SYNTHETIC_TEST', eid)] = {'evidence_id': eid, 'text': f'Bằng chứng giả lập {rid}.',
                                                'sentence_id': 'S'+rid, 'section_id': 'SEC1'}
    relation('D1', 'HAS_SYMPTOM', 'S1')
    relation('D2', 'HAS_SYMPTOM', 'S1')
    relation('D1', 'TREATED_BY', 'G1')
    relation('G1', 'HAS_MEMBER', 'M1')
    relation('D1', 'TREATED_BY', 'M2')
    relation('M1', 'HAS_ADVERSE_EFFECT', 'A1', {'negated': True, 'population': 'fixture'})
    relation('M2', 'HAS_ADVERSE_EFFECT', 'A1')
    relation('G1', 'HAS_MEMBER', 'M3')  # A dead end for adverse effects.
    relation('M1', 'HAS_CONTRAINDICATION', 'C1')
    service = KGQueryService(FakeDriver(graph), Ontology.load(ROOT/'examples/kg/kg_ontology.example.json'),
                             evidence_store=FakeEvidenceStore(graph))
    return service


@pytest.fixture
def service():
    return fixture_service()


def query(service, question, **kwargs):
    return retrieve(service, QueryRequest(question=question, **kwargs)).model_dump()


@pytest.mark.parametrize(('question', 'intent'), [
    ('COPD có triệu chứng gì?', 'symptom'),
    ('COPD được điều trị thế nào?', 'treatment'),
    ('Nhóm thuốc thử gồm những thuốc nào?', 'membership'),
    ('Thuốc A thuộc nhóm nào?', 'drug_class'),
    ('Liều dùng của Thuốc A?', 'dosage'),
    ('Tác dụng phụ của Thuốc A?', 'adverse_effect'),
    ('Chống chỉ định của Thuốc A?', 'contraindication'),
    ('Thuốc A có tương tác gì?', 'interaction'),
    ('Yếu tố nguy cơ của COPD?', 'risk_factor'),
    ('Nguyên nhân COPD?', 'cause'),
    ('Phòng ngừa COPD?', 'prevention'),
    ('Xét nghiệm chẩn đoán COPD?', 'diagnosis'),
    ('Chẩn đoán phân biệt COPD?', 'differential'),
    ('Đánh giá COPD bằng thang điểm nào?', 'assessment'),
    ('COPD có các giai đoạn nào?', 'classification'),
    ('COPD có biến chứng nào?', 'comorbidity'),
    ('Cần theo dõi COPD thế nào?', 'monitoring'),
    ('Tiên lượng COPD?', 'prognosis'),
    ('Khuyến cáo cho COPD?', 'recommendation'),
    ('Viêm phổi lây thế nào?', 'transmission'),
    ('Kháng thuốc ở COPD?', 'resistance'),
    ('Bài tập phục hồi chức năng COPD?', 'rehabilitation'),
    ('Thuốc A áp dụng cho đối tượng nào?', 'population'),
    ('Cơ chế tác động của Thuốc A?', 'mechanism'),
    ('COPD ảnh hưởng cơ quan nào?', 'anatomy'),
])
def test_all_intent_families(question, intent):
    assert intent in detect_intents(question, ('COPD', 'Thuốc A', 'Nhóm thuốc thử', 'Viêm phổi'))


def test_specific_intent_and_entity_name_do_not_trigger_broader_intent():
    assert detect_intents('Chẩn đoán phân biệt COPD?', ['COPD']) == ['differential']
    assert detect_intents('Chống chỉ định của Thuốc A?', ['Thuốc A']) == ['contraindication']
    assert detect_intents('Lao kháng thuốc có triệu chứng gì?', ['Lao kháng thuốc']) == ['symptom']
    assert not uses_context('Chấn thương do nổ có triệu chứng gì?')


def test_one_hop_accents_aliases_and_sources(service):
    result = query(service, 'Benh phoi tac nghen man tinh co trieu chung gi?')
    assert result['status'] == 'ok'
    assert result['query']['mode'] == 'one_hop'
    assert {f['predicate'] for f in result['llm_context']['facts']} == {'HAS_SYMPTOM'}
    assert result['llm_context']['sources'][0]['doc_id'] == 'SYNTHETIC_TEST'
    assert result['retrieval']['complete'] is False


def test_digit_boundary_and_current_entities_outrank_context(service):
    result = query(service, 'COVID19 có dấu hiệu gì?', context_mentions=['COPD'])
    assert result['status'] == 'no_facts'
    assert list(result['retrieval']['anchors'].values())[0][0]['id'] == 'D3'
    result = query(service, 'Mối liên hệ giữa COPD và Viêm phổi?', context_mentions=['COVID-19'])
    assert result['query']['mode'] == 'path'
    assert len(result['retrieval']['anchors']) == 2


def test_pronoun_can_use_context_but_unknown_name_cannot(service):
    assert query(service, 'Nó có triệu chứng gì?', context_mentions=['COPD'])['status'] == 'ok'
    unknown = query(service, 'ZZZ là gì?', context_mentions=['COPD'])
    assert unknown['status'] == 'needs_clarification'
    assert not unknown['llm_context']['facts']


@pytest.mark.parametrize('question', ['ABC có triệu chứng gì?', 'Viêm phỗi có triệu chứng gì?'])
def test_ambiguous_and_fuzzy_names_require_confirmation(service, question):
    result = query(service, question)
    assert result['status'] == 'needs_clarification'
    assert result['clarification']['can_confirm']
    assert not result['llm_context']['facts']
    assert all(q == CATALOG_QUERY for q, _ in service.driver.log)


def test_confirmation_ids_resolve_ambiguity_and_removed_ids_fail(service):
    result = query(service, 'ABC có triệu chứng gì?', entity_ids=['D4'])
    assert result['status'] == 'no_facts'
    assert result['retrieval']['anchors']['Bệnh A thử nghiệm'][0]['id'] == 'D4'
    assert query(service, 'ABC?', entity_ids=['MISSING'])['status'] == 'needs_clarification'


def test_explicit_distinct_ids_with_same_name_keep_both_path_endpoints(service):
    service.driver.g.entities['D2']['canonical_name'] = 'COPD'
    result = query(service, 'Tìm đường liên kết giữa hai ID đã chọn', entity_ids=['D1', 'D2'], mode='path')
    assert result['status'] == 'ok'
    assert len(result['retrieval']['anchors']) == 2
    assert [n['id'] for n in result['llm_context']['paths'][0]['nodes']] == ['D1', 'S1', 'D2']


def test_accent_collision_is_not_silently_selected(service):
    service.driver.g.entities['X'] = {'id': 'X', 'canonical_name': 'Viềm phổi',
                                     'normalized_name': 'viềm phổi', 'entity_type': 'Disease', 'aliases': []}
    result = query(service, 'viem phoi co trieu chung gi?')
    assert result['status'] == 'needs_clarification'
    assert len(result['clarification']['groups'][0]['candidates']) == 2


@pytest.mark.parametrize(('question', 'preset'), [
    ('COPD dùng thuốc nào?', 'drugs_for_disease'),
    ('Thuốc điều trị COPD có tác dụng phụ gì?', 'drug_adverse_effects'),
    ('Chống chỉ định của thuốc điều trị COPD?', 'drug_contraindications'),
])
def test_multi_hop_plans_have_connected_complete_evidence(service, question, preset):
    result = query(service, question)
    assert result['query']['mode'] == 'multi_hop'
    assert result['query']['preset'] == preset
    assert result['status'] == 'ok'
    ctx = result['llm_context']
    assert ctx['chains']
    for chain in ctx['chains']:
        facts = [ctx['facts'][i] for i in chain['fact_indices']]
        for left, right in zip(facts, facts[1:]):
            assert {left['subject']['id'], left['object']['id']} & {right['subject']['id'], right['object']['id']}
        assert all(f['evidence'] and f['assertions'] for f in facts)
        if preset != 'drugs_for_disease':
            assert facts[-1]['hop'] == 3
    if preset == 'drugs_for_disease':
        # A directly prescribed drug is kept even when other branches have members.
        assert any(ctx['facts'][c['fact_indices'][-1]]['object']['id'] == 'M2' for c in ctx['chains'])


def test_no_terminal_step_means_no_facts_not_a_partial_answer(service):
    service.driver.g.rels = [r for r in service.driver.g.rels if r['type'] != 'HAS_ADVERSE_EFFECT']
    result = query(service, 'Thuốc điều trị COPD có tác dụng phụ gì?')
    assert result['status'] == 'no_facts'
    assert not result['llm_context']['facts']
    assert not result['llm_context']['chains']


def test_drug_specific_question_stays_one_hop_and_preserves_negation(service):
    result = query(service, 'Thuốc A có tác dụng phụ gì?')
    assert result['query']['mode'] == 'one_hop'
    fact = result['llm_context']['facts'][0]
    assert fact['assertions'][0]['properties']['negated'] is True
    assert fact['confidence_semantics'] == 'source_metadata_not_disease_probability'


def test_paths_are_delivered_as_facts_with_original_direction(service):
    result = query(service, 'Mối liên hệ giữa COPD và Viêm phổi?')
    assert result['status'] == 'ok'
    ctx = result['llm_context']
    path = ctx['paths'][0]
    assert [n['id'] for n in path['nodes']] == ['D1', 'S1', 'D2']
    facts = [ctx['facts'][i] for i in path['fact_indices']]
    assert [f['subject']['id'] for f in facts] == ['D1', 'D2']
    assert len(ctx['sources']) == 2
    assert result['warnings']


def test_path_does_not_fall_back_when_endpoint_missing_and_obeys_depth(service):
    missing = query(service, 'Mối liên hệ giữa COPD và ZZZ?')
    assert missing['status'] == 'needs_clarification'
    assert not missing['llm_context']['facts']
    assert query(service, 'Mối liên hệ giữa COPD và Viêm phổi?', max_hops=1)['status'] == 'no_facts'


def test_small_budget_never_breaks_an_evidence_path(service):
    result = query(service, 'Mối liên hệ giữa COPD và Viêm phổi?', limit=1)
    assert result['status'] == 'no_facts'
    assert result['retrieval']['truncated']
    assert result['llm_context']['facts'] == result['llm_context']['paths'] == []


def test_unspecified_comparison_and_mixed_chain_ask_back(service):
    for question in ('So sánh COPD và Viêm phổi',
                     'Thuốc điều trị COPD có tác dụng phụ và chống chỉ định gì?'):
        result = query(service, question)
        assert result['status'] == 'needs_clarification'
        assert not result['clarification']['can_confirm']


def test_cache_refresh_and_catalog_limit(service):
    query(service, 'COPD có triệu chứng gì?')
    query(service, 'COPD có triệu chứng gì?')
    assert sum(q == CATALOG_QUERY for q, _ in service.driver.log) == 1
    get_lookup(service).expiry = 0
    query(service, 'COPD có triệu chứng gì?')
    assert sum(q == CATALOG_QUERY for q, _ in service.driver.log) == 2
    service._question_entity_lookup = EntityLookup(service, max_entities=1)
    assert query(service, 'COPD?')['clarification']['reason'] == 'dictionary_limit'


def test_generic_entity_names_do_not_swallow_the_intent(service):
    service.driver.g.entities['GENERIC'] = {'id': 'GENERIC', 'canonical_name': 'Triệu chứng',
        'normalized_name': 'triệu chứng', 'entity_type': 'Symptom', 'aliases': []}
    result = query(service, 'COPD co trieu chung gi?')
    assert result['query']['intents'] == ['symptom']
    assert len(result['query']['mentions']) == 1


def test_indistinguishable_duplicate_nodes_request_data_review(service):
    node = service.driver.g.entities['D1']
    service.driver.g.entities['COPY'] = {**node, 'id': 'COPY'}
    result = query(service, 'COPD có triệu chứng gì?')
    assert result['status'] == 'needs_clarification'
    assert result['clarification']['reason'] == 'duplicate_entities'
    assert not result['clarification']['can_confirm']


def test_api_modes_input_validation_and_no_cypher_escape(service):
    with TestClient(create_app(service)) as client:
        meta = client.get('/api/v1/kg/meta').json()
        assert set(meta['query_modes']) == {'one_hop', 'multi_hop', 'path', 'compare', 'common', 'difference'}
        assert len(meta['automatic_intents']) == 25
        for extra in ({'mode': 'invalid'}, {'mode': 'multi_hop'}, {'preset': 'bad'},
                      {'cypher': 'MATCH (n) DELETE n'}, {'max_hops': 5}, {'limit': 0},
                      {'mode': 'path', 'preset': 'drugs_for_disease'}, {'intents': ['bad']},
                      {'entity_ids': ['D1'], 'mentions': ['COPD']}):
            response = client.post('/api/v1/kg/query', json={'question': 'COPD?', **extra})
            assert response.status_code == 422


@pytest.mark.asyncio
async def test_orchestrator_clarification_and_no_facts_do_not_call_llm(service):
    modules = Mock()
    modules.context_resolve = AsyncMock(return_value={'resolution_status': 'resolved', 'active_topic': {'canonical_name': 'COPD'}})
    modules.kg_query = AsyncMock(side_effect=lambda question, mentions, **kw: query(service, question, context_mentions=mentions, **kw))
    llm = AsyncMock()
    classifier = Mock()
    classifier.predict.return_value = {'label': 'RELATIONAL_QUERY'}
    orchestrator = Orchestrator(classifier, modules, llm)
    args = dict(conversation_id='c', message_id='m', timestamp='now', attachments=[])
    result = await orchestrator.answer(question='ABC có triệu chứng gì?', **args)
    assert result['route'] == 'NEEDS_CLARIFICATION'
    assert result['kg_clarification']['can_confirm']
    assert result['kg_route'] == 'RELATIONAL_QUERY'
    modules.rag_search = AsyncMock(return_value={'results': []})
    empty = await orchestrator.answer(question='COVID19 có triệu chứng gì?', **args)
    modules.rag_search.assert_awaited_once()
    assert 'Chưa đủ bằng chứng' in empty['content']
    llm.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_orchestrator_supplies_path_facts_to_llm_and_ui(service):
    from app.services.modules import ModuleClient
    modules = ModuleClient(context_url='http://c', clinical_url='http://ie', kg_url='http://kg', rag_url='http://r',
                           timeout=5, embedded_apps={'http://kg': create_app(service)})
    modules.context_resolve = AsyncMock(return_value={'normalized_question': 'COVID19?', 'resolution_status': 'resolved',
                                                     'active_topic': {'canonical_name': 'COVID-19'}})
    classifier = Mock(); classifier.predict.return_value = {'label': 'RELATIONAL_QUERY'}
    llm = AsyncMock(); llm.generate.return_value = 'Chỉ là phản hồi kiểm thử.'
    result = await Orchestrator(classifier, modules, llm).answer(conversation_id='c', message_id='m', timestamp='now',
             attachments=[], question='Mối liên hệ giữa COPD và Viêm phổi?')
    assert result['kg_query']['mode'] == 'path'
    assert len(result['sources']) == 2
    ctx = llm.generate.call_args.args[1]['module_results']['kg']
    assert ctx['paths'] and len(ctx['facts']) == 2

