from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.data_workspace import api
from app.modules.context.config import Settings
from app.modules.context.container import ApplicationContainer
from app.modules.context.domain.models import ClinicalFact, HistoryTurn


def app_for(**modules):
    app = FastAPI()
    app.state.embedded_apps = modules
    app.state.import_batches = {}
    app.include_router(api.create_router(['http://localhost:5173', '*']))
    return app


def test_serves_shared_workspace_and_only_public_assets():
    with TestClient(app_for()) as client:
        for path in ['/data', '/data/']:
            response = client.get(path)
            assert response.status_code == 200
            assert 'moduleCards' in response.text
            assert response.headers['cache-control'] == 'no-store'
        for name in ['app.js', 'style.css', 'embed.js', 'embed.css', 'logo.png']:
            assert client.get('/data-assets/' + name).status_code == 200
        assert client.get('/data-assets/api.py').status_code == 422
        assert client.get('/api/v1/data/config').json() == {'frontend_origins': ['http://localhost:5173']}


def test_overview_isolates_failed_source_sanitizes_error_and_caches(monkeypatch):
    rag = AsyncMock(return_value={'state': 'ready', 'stats': {'documents': 3}})
    kg = AsyncMock(side_effect=RuntimeError('password=SECRET'))
    context = AsyncMock(return_value={'state': 'ready', 'mode': 'memory', 'stats': {'facts': 1}})
    monkeypatch.setattr(api, 'rag_summary', rag)
    monkeypatch.setattr(api, 'kg_summary', kg)
    monkeypatch.setattr(api, 'context_summary', context)
    with TestClient(app_for()) as client:
        response = client.get('/api/v1/data/overview')
        assert response.status_code == 200
        data = response.json()
        assert data['modules']['rag']['stats']['documents'] == 3
        assert data['modules']['kg']['state'] == 'unavailable'
        assert data['modules']['context']['mode'] == 'memory'
        assert 'SECRET' not in response.text
        assert client.get('/api/v1/data/overview').json() == data
    rag.assert_awaited_once()
    kg.assert_awaited_once()
    context.assert_awaited_once()


@pytest.mark.asyncio
async def test_context_memory_counts_without_embedding_or_clinical_text(monkeypatch):
    container = ApplicationContainer.build(Settings(graph_backend='memory', nlp_backend='rule', embedding_backend='hash', terminology_mode='off'))
    await container.history_repository.add_turn(HistoryTurn(patient_id='P', session_id='S', message_id='M', role='user', original_text='PRIVATE', created_at='2026-10-10T00:00:00Z'))
    await container.patient_repository.upsert_facts(patient_id='P', facts=[ClinicalFact(fact_type='symptom', display='PRIVATE', recorded_at='2026-10-10T00:00:00Z', source_message_id='M')])
    embed = AsyncMock(side_effect=AssertionError('Overview must not embed'))
    monkeypatch.setattr(container.history_repository.embedding_service, 'embed', embed)
    monkeypatch.setattr(container.patient_repository.embedding_service, 'embed', embed)
    result = await api.context_summary(app_for(context=NS(state=NS(available=True, container=container))))
    assert result['stats'] == {'patients': 1, 'sessions': 1, 'turns': 1, 'facts': 1}
    assert result['mode'] == 'memory'
    assert 'PRIVATE' not in str(result)
    embed.assert_not_called()


def test_kg_overview_uses_read_service_and_count_queries_only():
    service = MagicMock()
    service.database = 'medical_kg'
    session = service.driver.session.return_value.__enter__.return_value
    session.run.return_value.single.return_value = {'entities': 10, 'relations': 12}
    db = service.evidence_store.coll.database
    db.__getitem__.return_value.count_documents.return_value = 3
    getter = MagicMock(return_value=service)
    app = app_for(kg_explorer=NS(state=NS(available=True, get_query_service=getter)))
    result = api.kg_graph_summary(app)
    assert result['stats'] == {'entities': 10, 'relations': 12, 'documents': 3}
    assert result['mongodb']['state'] == 'ready'
    service.driver.session.assert_called_once_with(database='medical_kg', default_access_mode='READ')
    query = session.run.call_args.args[0]
    assert query.timeout == 3
    assert all(word not in query.text.upper() for word in ['MERGE', 'CREATE', 'DELETE', ' SET '])
    db.command.assert_called_once_with('ping')


@pytest.mark.asyncio
async def test_disabled_kg_vector_never_contacts_qdrant_or_initializes_encoder(monkeypatch):
    monkeypatch.setenv('KG_ENTITY_EMBEDDING_ENABLED', '0')
    client = MagicMock(side_effect=AssertionError('No network when disabled'))
    monkeypatch.setattr(api.httpx, 'AsyncClient', client)
    assert (await api.kg_vector_summary())['state'] == 'disabled'
    client.assert_not_called()


def test_merged_jobs_keep_module_identity_but_omit_sources_and_failed_module(monkeypatch):
    job = {'job_id': 'SAME', 'mode': 'commit', 'status': 'completed', 'started_at': '2026-10-10T00:00:00Z', 'total': 2, 'processed': 2, 'completed': 1, 'failed': 0, 'items': [{'text': 'PRIVATE'}], 'source': '/PRIVATE/path'}
    get = AsyncMock(return_value={'items': [job], 'active_job_id': None})
    monkeypatch.setattr(api, 'internal_get', get)
    def manager(request, module):
        if module == 'context':
            raise RuntimeError('password=SECRET')
        return NS(list=lambda: {'items': [{**job, 'partial': 1}], 'active_job_id': None})
    monkeypatch.setattr(api, 'manager', manager)
    with TestClient(app_for()) as client:
        response = client.get('/api/v1/data/jobs')
        assert response.status_code == 200
        data = response.json()
        assert {item['module'] for item in data['items']} == {'rag', 'kg'}
        assert data['items'][1]['partial'] == 1
        assert data['per_module_limit'] == 30
        assert set(data['errors']) == {'context'}
        assert all('items' not in item and 'source' not in item for item in data['items'])
        assert 'PRIVATE' not in response.text and 'SECRET' not in response.text
    assert get.call_args.args[1].endswith('?limit=30')


@pytest.mark.asyncio
async def test_context_neo4j_uses_counts_without_retrieving_patient_records():
    counts = {'patients': 2, 'sessions': 3, 'turns': 8, 'facts': 4}
    result = NS(single=AsyncMock(return_value=counts))
    session = NS(run=AsyncMock(return_value=result))
    driver = MagicMock()
    driver.session.return_value.__aenter__ = AsyncMock(return_value=session)
    driver.session.return_value.__aexit__ = AsyncMock(return_value=False)
    container = NS(driver=driver, settings=NS(neo4j_database='context', graph_backend='neo4j'))
    value = await api.context_summary(app_for(context=NS(state=NS(available=True, container=container))))
    assert value['stats'] == counts
    driver.session.assert_called_once_with(database='context', default_access_mode='READ')
    query = session.run.call_args.args[0]
    assert query.timeout == 3 and 'original_text' not in query.text


@pytest.mark.asyncio
async def test_busy_rag_does_not_wait_for_embedding_lock(monkeypatch):
    get = AsyncMock(side_effect=AssertionError('Busy RAG must not request stats'))
    monkeypatch.setattr(api, 'internal_get', get)
    result = await api.rag_summary(app_for(rag=NS(state=NS(available=True, batch=NS(active='RUNNING')))))
    assert result['state'] == 'busy'
    assert 'stats' not in result
    get.assert_not_called()
