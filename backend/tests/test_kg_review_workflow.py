import copy
from unittest.mock import Mock
import numpy as np
import pytest
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from app.bulk_import.kg import KGAdapter
from app.bulk_import.manager import BatchManager
from app.modules.kg_import.config import EntityEmbeddingSettings, Settings, MEDICAL_MODEL, MEDICAL_REVISION
from app.modules.kg_import.entity_vector import QdrantEntityIndex
from app.modules.kg_import.review_store import DocumentReviewStore
from tests.test_bulk_import import kg_service, save, finish
from tests.upstream.kg.helpers import load_payload
from tests.upstream.kg.test_entity_vector import FakeIndex, SmallEncoder


def incoming():
    raw = load_payload()
    raw['document']['document_id'] = 'DOC_NEW'
    raw['entities'][0].update(id='ENT_NEW', canonical_name='Bệnh phổi tắt nghẽn mãn tính', aliases=[])
    for rel in raw['relations']:
        if rel['source'] == 'ENT_000001': rel['source'] = 'ENT_NEW'
        rel['id'] = 'NEW_' + rel['id']
    raw['propositions'][0]['entity_ids'] = ['ENT_NEW']
    return raw


def seeded():
    svc = kg_service(FakeIndex())
    assert svc.import_kg(load_payload()).status == 'completed'
    return svc


@pytest.mark.asyncio
async def test_saved_document_can_commit_without_repreview_and_receipt_survives_restart(tmp_path):
    svc = seeded()
    m = BatchManager('kg', KGAdapter(lambda: svc), tmp_path/'in', tmp_path/'out')
    save(m, 'one.json', incoming())
    job = await finish(m)
    assert job['needs_review'] == 1
    result = await m.decisions(job['job_id'], 0, {'ENT_NEW': 'new'})
    assert result['item']['review_status'] == 'reviewed'
    assert result['item']['reviewed_at']
    assert m.get(job['job_id'])['completed'] == 1
    committed = await finish(m, mode='commit', previous_job_id=job['job_id'], confirmed=True)
    assert committed['completed'] == 1
    assert svc.graph.relations['NEW_REL_000001']['source_id'] == 'ENT_NEW'
    await m.close()
    m = BatchManager('kg', KGAdapter(lambda: svc), tmp_path/'in', tmp_path/'out')
    raw, _ = m.read('one.json')
    assert m.reviews.status(raw, svc.review_profile())['review_status'] == 'reviewed'
    raw['document']['title'] += ' changed'
    assert m.reviews.status(raw, svc.review_profile())['review_status'] == 'needs_review'
    save(m, 'one.json', raw)
    stale = await finish(m, mode='commit', previous_job_id=job['job_id'], confirmed=True)
    assert stale['failed'] == 1
    await m.close()


@pytest.mark.asyncio
async def test_incomplete_or_invalid_decisions_never_mark_reviewed(tmp_path):
    svc = seeded(); m = BatchManager('kg', KGAdapter(lambda: svc), tmp_path/'in', tmp_path/'out')
    save(m, 'one.json', incoming()); job = await finish(m)
    for choices in ({}, {'ENT_NEW': 'MISSING'}, {'ENT_NEW': 42}, {'UNKNOWN': 'new'}):
        with pytest.raises(ValueError): await m.decisions(job['job_id'], 0, choices)
    raw, _ = m.read('one.json')
    assert m.reviews.status(raw, svc.review_profile())['review_status'] == 'unreviewed'
    del svc.graph.entities['ENT_000001']
    with pytest.raises(ValueError): await m.decisions(job['job_id'], 0, {'ENT_NEW': 'ENT_000001'})
    assert 'entity_link_decisions' not in m.read('one.json')[0]
    await m.close()


def test_review_receipt_bound_to_content_profile_and_new_candidates(tmp_path):
    store = DocumentReviewStore(tmp_path); raw = incoming()
    store.mark(raw, 'model-a')
    assert store.status(raw, 'model-a')['review_status'] == 'reviewed'
    assert store.status(raw, 'model-b')['review_status'] == 'needs_review'
    assert store.status(raw, 'model-a', needs_review=True)['review_status'] == 'needs_review'
    store.close()


def test_preview_cache_is_read_only_and_actual_import_revalidates():
    svc = seeded(); raw = incoming()
    original = svc.entity_index.suggest
    svc.entity_index.suggest = Mock(side_effect=original)
    first = svc.preview_kg(raw); calls = svc.entity_index.suggest.call_count
    first.plan['entity_candidates'].clear()
    assert svc.preview_kg(raw).plan['entity_candidates']
    assert svc.entity_index.suggest.call_count == calls
    assert svc.import_kg(raw).status == 'failed'
    assert svc.entity_index.suggest.call_count > calls
    raw['entity_link_decisions'] = {'ENT_NEW': 'new'}
    assert svc.import_kg(raw).status == 'completed'
    assert not svc._previews


def test_keep_new_does_not_duplicate_exact_name():
    svc = seeded(); raw = incoming()
    raw['entities'][0]['canonical_name'] = load_payload()['entities'][0]['canonical_name']
    raw['entity_link_decisions'] = {'ENT_NEW': 'new'}
    assert svc.import_kg(raw).status == 'completed'
    assert 'ENT_NEW' not in svc.graph.entities and 'ENT_000001' in svc.graph.entities
    assert svc.graph.relations['NEW_REL_000001']['source_id'] == 'ENT_000001'


def index(**kwargs):
    enc = SmallEncoder(); enc.encode = Mock(wraps=enc.encode)
    settings = EntityEmbeddingSettings(model='fake', revision=None, trust_remote_code=False, collection='test', **kwargs)
    return QdrantEntityIndex(settings, client=QdrantClient(':memory:'), encoder=enc)


def test_vector_batching_filters_types_and_reuses_cached_embeddings():
    idx = index()
    idx.upsert_entities([{'id':'D','entity_type':'Disease','canonical_name':'Bệnh phổi'},
                         {'id':'S','entity_type':'Symptom','canonical_name':'Đau phổi'}])
    idx.client.query_batch_points = Mock(wraps=idx.client.query_batch_points)
    queries = [(f'phổi {i}', 'Disease') for i in range(145)]
    hits = idx.suggest_many(queries)
    assert all([h['entity_id'] for h in group] == ['D'] for group in hits)
    assert idx.client.query_batch_points.call_count == 3
    enc_calls = idx.encoder.encode.call_count
    idx.suggest_many(queries)
    assert idx.encoder.encode.call_count == enc_calls
    assert idx.client.query_batch_points.call_count == 6
    idx.close()


def test_interrupted_build_and_incompatible_collection_are_not_ready():
    idx = index(); idx.begin_build()
    assert not idx.ready()
    idx.finish_build(); assert idx.ready()
    other = QdrantEntityIndex(EntityEmbeddingSettings(model='other', collection='test'), client=idx.client, encoder=SmallEncoder())
    with pytest.raises(ValueError): other.ready()
    idx.close()

    idx = index(); idx.client.create_collection('test', vectors_config=VectorParams(size=2, distance=Distance.COSINE))
    idx.client.upsert('test', [PointStruct(id=1, vector=[1.,0.], payload={'entity_id':'OLD'})])
    with pytest.raises(ValueError): idx.ensure_collection()
    idx.close()


def test_semantic_review_can_find_candidates_across_types():
    idx=index()
    try:
        idx.upsert_entities([{'id':'D','entity_type':'Disease','canonical_name':'Tên bệnh'},
                             {'id':'S','entity_type':'Symptom','canonical_name':'Tên triệu chứng'}])
        hits=idx.suggest_many([('khái niệm cần rà soát',None)])[0]
        assert {h['entity_id'] for h in hits}=={'D','S'}
    finally:
        idx.close()


def test_embedding_cache_bounded_and_invalid_vectors_rejected():
    idx = index(cache_size=2)
    idx._encode(['one','two','three']); assert len(idx._vectors) == 2
    idx.encoder.encode = lambda *a, **k: np.array([[float('nan'),0.]])
    with pytest.raises(ValueError, match='Invalid'): idx._encode(['bad'])
    idx.close()


def test_model_defaults_and_nonmedical_environment_do_not_inherit_remote_code(monkeypatch):
    for key in ('KG_ENTITY_MODEL','KG_ENTITY_MODEL_REVISION','KG_ENTITY_TRUST_REMOTE_CODE'):
        monkeypatch.delenv(key, raising=False)
    cfg = Settings.from_env().entity_embedding
    assert (cfg.model, cfg.revision, cfg.trust_remote_code) == (MEDICAL_MODEL, MEDICAL_REVISION, True)
    monkeypatch.setenv('KG_ENTITY_MODEL','another/repo')
    cfg = Settings.from_env().entity_embedding
    assert cfg.revision is None and cfg.trust_remote_code is False


def test_single_file_review_uses_shared_receipt_and_content_bound_import_token(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.modules.kg_query.web_app import create_app
    monkeypatch.setenv('BATCH_DATA_ROOT', str(tmp_path))
    svc = seeded(); raw = incoming()
    with TestClient(create_app(import_service=svc)) as client:
        preview = client.post('/api/review/preview', json=raw).json()
        assert 'preview_token' not in preview
        saved = client.post('/api/review/decisions', json={'payload':raw,'choices':{'ENT_NEW':'new'}})
        assert saved.status_code == 200
        saved = saved.json(); assert saved['review_status'] == 'reviewed'
        store = DocumentReviewStore(tmp_path/'import_reports'/'kg')
        assert store.status(saved['payload'], svc.review_profile())['review_status'] == 'reviewed'
        store.close()
        result = client.post('/api/review/import', json={'payload':saved['payload'],'preview_token':saved['preview_token']})
        assert result.status_code == 200 and result.json()['status'] == 'completed'
        reused = client.post('/api/review/import', json={'payload':saved['payload'],'preview_token':saved['preview_token']})
        assert reused.status_code != 200
    with TestClient(create_app(import_service=svc)) as client:
        assert client.post('/api/review/preview', json=saved['payload']).json()['review_status'] == 'reviewed'
