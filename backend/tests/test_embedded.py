from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock
import pytest
from fastapi.testclient import TestClient
from app import main
from app.modules.context.domain.models import ClinicalFact, FactType, ProcessRequest
from app.modules.kg_query.retrieval_api import create_app as create_kg
from app.modules.kg_query.intents import build_intents
from app.modules.kg_import.ontology import Ontology
from app.modules.kg_import.config import Settings as KGSettings
from app.modules.context.config import Settings as ContextSettings


def chat(client, question, conversation='integration', mid='message-1'):
    return client.post('/api/v1/chat/message', json={'conversationId': conversation,
        'message': {'id': mid, 'role': 'user', 'content': question, 'attachments': []}})


@pytest.fixture
def integrated():
    with TestClient(main.app) as client:
        classifier = Mock()
        classifier.predict.return_value = {'label': 'GENERAL_MEDICAL_QUERY', 'class_id': '2'}
        main.app.state.orchestrator.classifier = classifier
        main.app.state.orchestrator.llm = AsyncMock()
        main.app.state.orchestrator.llm.generate.return_value = 'Phản hồi từ dữ liệu kiểm thử.'
        yield client, classifier


def test_real_context_rag_chat_and_both_history_turns(integrated):
    client, classifier = integrated
    fixture = {'schema_version': '1.0', 'document': {'document_id': 'TEST_COVID',
        'title': 'Tài liệu COVID19 kiểm thử', 'document_type': 'test', 'language': 'vi',
        'sections': [{'section_id': 'S1', 'title': 'Dấu hiệu', 'paragraphs': [
            {'paragraph_id': 'P1', 'sentences': [{'sentence_id': 'SENT1',
             'text': 'Đoạn giả lập cho câu hỏi các dấu hiệu của COVID19.'}]}]}]}}
    assert client.post('/modules/rag/api/v1/rag/import-json', json=fixture).status_code == 200
    response = chat(client, 'Các dấu hiệu của covid19')
    assert response.status_code == 200, response.text
    metadata = response.json()['message']['metadata']
    assert metadata['resolved_question'] == 'Các dấu hiệu của covid19'
    assert any(o.get('document_id') == 'TEST_COVID' for x in metadata['sources'] for o in x['origins'])
    classifier.predict.assert_called_once_with('Các dấu hiệu của covid19')
    llm = main.app.state.orchestrator.llm
    assert llm.generate.call_args.args[0] == 'Các dấu hiệu của covid19'
    assert llm.generate.call_args.args[1]['module_results']['rag']['evidence'][0]['source_refs'] == [1]
    history = client.get('/modules/context/v1/history', params={'patient_id': 'integration', 'session_id': 'integration'}).json()['items']
    assert {x['role'] for x in history} == {'user', 'assistant'}
    user = next(x for x in history if x['role'] == 'user')
    assert {m['canonical_name'] for m in user['mentions']} == {'covid19'}
    assert not client.get('/modules/context/v1/patients/integration/context').json()['facts']
    client.delete('/modules/rag/api/v1/rag/documents/TEST_COVID')


@pytest.mark.asyncio
async def test_hallucinated_extractor_candidates_cannot_pollute_history():
    from app.modules.context.container import ApplicationContainer
    container = ApplicationContainer.build(ContextSettings(graph_backend='memory', nlp_backend='rule'))
    await container.initialize()
    service = container.service
    now = datetime.now(timezone.utc)
    service.clinical_extractor.extract = AsyncMock(return_value=[
        ClinicalFact(fact_type=FactType.SYMPTOM, display=name, recorded_at=now,
                     source_message_id='test-unknown', source_text='Các dấu hiệu của covid19: '+name)
        for name in ['ho', 'sốt', 'mất khứu giác']])
    result = await service.process(ProcessRequest(patient_id='p', session_id='s', message_id='test-unknown',
                               question='Các dấu hiệu của covid19', timestamp=now))
    turns = await container.history_repository.get_recent_turns(patient_id='p',session_id='s',limit=10)
    assert result.stored_fact_count == 0
    assert {m.canonical_name for m in turns[0].mentions} == {'covid19'}
    m = turns[0].mentions[0]
    assert turns[0].original_text[m.start:m.end] == m.text == 'covid19'
    await container.close()


@pytest.mark.parametrize('label', ['RELATIONAL_QUERY','CLINICAL_EXPLANATION_MANAGEMENT'])
def test_kg_uses_embedded_api_contract(integrated, label):
    client, classifier = integrated
    classifier.predict.return_value = {'label': label}
    service = Mock()
    service.intents = build_intents(Ontology.load(KGSettings.from_env().ontology_path))
    service._read.return_value = [{'id': 'COVID', 'name': 'COVID19', 'type': 'Disease', 'aliases': []}]
    service.run.return_value.to_dict.return_value = {'status': 'ok', 'anchors': {}, 'notes': [],
        'facts': [{'subject': {'id': 'COVID'}, 'predicate': 'HAS_SYMPTOM', 'object': {'id': 'S1'},
                   'evidence': [{'doc_id': 'KG_TEST', 'evidence_id': 'E1', 'text': 'Bằng chứng kiểm thử'}]}]}
    main.app.state.modules.embedded_apps['http://kg.internal'] = create_kg(service)
    response = chat(client, 'COVID19 có triệu chứng gì?', conversation=label)
    assert response.status_code == 200, response.text
    assert response.json()['message']['metadata']['route'] == label
    service.run.assert_called_once()
    assert service.run.call_args.args[0].mentions == ['covid 19']
    assert 'kg' in main.app.state.orchestrator.llm.generate.call_args.args[1]['module_results']


def test_empty_rag_does_not_generate_unfounded_answer(integrated):
    client, _ = integrated
    main.app.state.orchestrator.modules.rag_search = AsyncMock(return_value={'results': []})
    r = chat(client, 'Câu hỏi kiểm thử không có bằng chứng', conversation='empty')
    assert r.status_code == 200
    assert 'Chưa đủ bằng chứng' in r.json()['message']['content']
    main.app.state.orchestrator.llm.generate.assert_not_awaited()


def test_mounts_docs_and_static_assets(integrated):
    client, _ = integrated
    for path in ['/', '/docs', '/modules/context/ui', '/modules/context/docs',
                 '/modules/context/openapi.json', '/modules/rag/docs', '/modules/rag/openapi.json',
                 '/modules/kg/docs', '/modules/kg/openapi.json', '/modules/kg-explorer/',
                 '/modules/kg-explorer/duplicates', '/modules/kg-explorer/static/app.js',
                 '/modules/rag/static/style.css']:
        assert client.get(path).status_code == 200, path
    assert '/modules/context/v1/context/resolve' in client.get('/modules/context/ui').text
    assert '/modules/rag/api/v1/rag' in client.get('/modules/rag/static/app.js').text


def test_module_config_isolation(monkeypatch):
    monkeypatch.setenv('CONTEXT_NEO4J_URI', 'bolt://context:7687')
    monkeypatch.setenv('KG_NEO4J_URI', 'bolt://kg:7687')
    monkeypatch.setenv('NEO4J_URI', 'bolt://unrelated:7687')
    assert ContextSettings().neo4j_uri == 'bolt://context:7687'
    assert KGSettings.from_env().neo4j_uri == 'bolt://kg:7687'


def test_failed_context_startup_returns_503_and_closes_driver(monkeypatch):
    from app.modules.context.container import ApplicationContainer
    failed = Mock(initialize=AsyncMock(side_effect=RuntimeError('offline')), close=AsyncMock())
    monkeypatch.setattr(ApplicationContainer, 'build', lambda _: failed)
    with TestClient(main.app) as client:
        assert client.get('/health/live').status_code == 200
        assert client.get('/modules/context/health').status_code == 503
        assert client.get('/modules/rag/api/v1/rag/health').status_code == 200
    failed.close.assert_awaited_once()


def test_kg_import_and_validation_api():
    from tests.upstream.kg.helpers import ServiceTestCase
    case = ServiceTestCase()
    case.setUp()
    with TestClient(create_kg(service=Mock(), import_service=case.svc)) as client:
        validated = client.post('/api/v1/kg/validate', json=case.payload)
        assert validated.status_code == 200 and validated.json()['valid']
        invalid = client.post('/api/v1/kg/validate', json={'bad': True})
        assert not invalid.json()['valid']
        result = client.post('/api/v1/kg/import-json?mode=upsert', json=case.payload)
        assert result.status_code == 200, result.text
        assert result.json()['status'] == 'completed'


def test_bundled_classifier_is_compatible_with_installed_sklearn():
    import joblib
    import numpy as np
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        model = joblib.load(main.settings.classifier_path)
    assert model.n_features_in_ == 768
    assert list(model.classes_) == [0, 1, 2, 3, 4]
    assert int(model.predict(np.zeros((1,768)))[0]) in range(5)
