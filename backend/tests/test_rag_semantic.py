"""Semantic boundaries driven by controlled vectors, plus source/DB/API contracts.

Fixtures do not download E5 and do not measure Vietnamese retrieval quality.
"""
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.modules.rag.core import ChunkConfig, DemoEncoder, Input, build_records
from app.modules.rag.main import create_app
from app.modules.rag.service import Service
from app.modules.rag.storage import DemoStore


class SemanticEncoder(DemoEncoder):
    supports_semantic = True
    fingerprint = 'semantic-controlled-fixture-v1'
    dimension = 2
    max_length = 128

    def __init__(self, uniform=False):
        self.uniform = uniform
        self.calls = []

    def encode(self, texts, query=False):
        self.calls.append((list(texts), query))
        assert all(self.count(('query: ' if query else 'passage: ') + t) <= self.max_length for t in texts)
        return [[0.0, 1.0] if 'BETA' in t and not self.uniform else [1.0, 0.0] for t in texts]


def document(texts=None):
    texts = texts or ['ALPHA câu một giữ nguyên.', 'ALPHA câu hai cùng chủ đề.',
                      'BETA câu ba chuyển chủ đề.', 'BETA câu bốn cùng chủ đề mới.']
    return {'schema_version': '1.0', 'document': {'document_id': 'D', 'title': 'Nguồn',
        'document_type': 'test_fixture', 'language': 'vi', 'sections': [
            {'section_id': 'S', 'title': 'Mục', 'paragraphs': [
                {'paragraph_id': 'P', 'sentences': [{'sentence_id': f'T{i}', 'text': text} for i, text in enumerate(texts)]}]}]},
        'entities': [{'id': 'E1', 'type': 'Disease', 'canonical_name': 'Nguồn mẫu'},
                     {'id': 'E2', 'type': 'Symptom', 'canonical_name': 'Dữ kiện mẫu'}],
        'propositions': [{'id': 'PROP', 'text': texts[0], 'evidence': [{'sentence_id': 'T0'}]}],
        'relations': [{'id': 'REL', 'type': 'HAS_SYMPTOM', 'source': 'E1', 'target': 'E2', 'proposition_ids': ['PROP']}]}


def config(**kwargs):
    return replace(ChunkConfig(target=100, overlap=0, semantic_min_tokens=2, semantic_window=1), **kwargs)


def chunks(raw, encoder=None, cfg=None):
    return [r for r in build_records(Input.model_validate(raw), encoder or SemanticEncoder(), cfg or config()) if r['kind'] == 'chunk']


def test_topic_change_splits_before_the_size_ceiling_and_homogeneous_text_does_not():
    raw = document()
    rows = chunks(raw)
    assert [r['sentence_ids'] for r in rows] == [['T0', 'T1'], ['T2', 'T3']]
    assert rows[0]['boundary_reason'] == 'semantic' and rows[0]['boundary_distance'] == pytest.approx(1)
    # Same JSON and same token limit, only the embeddings differ.
    uniform = chunks(raw, SemanticEncoder(uniform=True))
    assert len(uniform) == 1 and uniform[0]['boundary_reason'] == 'section_end'
    assert ''.join(r['text'] for r in rows) == uniform[0]['text']


def test_semantic_chunks_preserve_exact_characters_evidence_and_section_isolation():
    raw = document(['  ALPHA không sốt; SpO2 92.5%, liều 0.5 mg.  ', 'ALPHA người thân; tiền sử.\n',
                    '\tBETA câu nguồn chuyển chủ đề. ', 'BETA giữ dấu tiếng Việt: “chưa biết”.'])
    raw['document']['sections'].append({'section_id': 'S2', 'title': 'Mục khác', 'paragraphs': [
        {'paragraph_id': 'P2', 'sentences': [{'sentence_id': 'T4', 'text': 'ALPHA nguồn độc lập.'}]}]})
    encoder = SemanticEncoder()
    rows = build_records(Input.model_validate(raw), encoder, config())
    for section in raw['document']['sections']:
        originals = {s['sentence_id']: s['text'] for p in section['paragraphs'] for s in p['sentences']}
        selected = [r for r in rows if r['kind'] == 'chunk' and r['section_id'] == section['section_id']]
        assert ''.join(r['text'] for r in selected) == '\n'.join(originals.values())
        covered = {sid: set() for sid in originals}
        for r in selected:
            assert set(r['sentence_ids']) <= set(originals)
            assert r['token_count'] <= encoder.max_length
            for span in r['source_spans']:
                text = originals[span['sentence_id']]
                assert text[span['start_char']:span['end_char']] in r['text']
                covered[span['sentence_id']].update(range(span['start_char'], span['end_char']))
        assert all(covered[sid] == set(range(len(text))) for sid, text in originals.items())
    prop = next(r for r in rows if r['kind'] == 'proposition')
    assert prop['evidence_sentence_ids'] == ['T0'] and prop['entity_ids'] == ['E1', 'E2'] and prop['relation_ids'] == ['REL']
    assert next(r for r in rows if 'T0' in r.get('sentence_ids', []))['proposition_ids'] == ['PROP']


def test_oversized_single_sentence_is_split_losslessly_without_oversized_model_input():
    text = '  Không sốt; SpO2 92.5%.\n' + ' '.join(f'từ{i}' for i in range(1000)) + '\t  '
    raw = document([text])
    raw['propositions'] = []
    raw['relations'] = []
    encoder = SemanticEncoder()
    rows = chunks(raw, encoder, config(target=60))
    assert len(rows) > 1 and ''.join(r['text'] for r in rows) == text
    assert set(r['boundary_reason'] for r in rows) <= {'token_limit', 'section_end'}
    assert all(r['token_count'] <= encoder.max_length and len(encoder.offsets(r['text'])) <= 60 for r in rows)
    covered = set()
    for r in rows:
        for span in r['source_spans']:
            covered.update(range(span['start_char'], span['end_char']))
    assert covered == set(range(len(text)))


def test_semantic_scoring_uses_bounded_batches_and_symmetric_query_prefix():
    raw = document([f'ALPHA câu {i}.' for i in range(80)])
    encoder = SemanticEncoder()
    chunks(raw, encoder)
    assert len(encoder.calls) == 3
    assert all(len(texts) <= 32 and query is True for texts, query in encoder.calls)


def test_disabling_semantics_avoids_boundary_embedding_and_demo_reports_token_mode():
    encoder = SemanticEncoder()
    rows = chunks(document(), encoder, config(method='token'))
    assert not encoder.calls and all(r['chunk_method'] == 'token' for r in rows)
    service = Service(None, DemoEncoder(), config(), 'demo')
    assert service.chunking_profile()['method'] == 'token'
    assert service.chunking_profile()['fallback_reason'] == 'encoder_not_semantic'


def test_window_smoothing_and_soft_minimum_avoid_tiny_tail_chunks():
    assert len(chunks(document(), cfg=config(semantic_window=2))) == 2
    assert len(chunks(document(), cfg=config(semantic_min_tokens=100))) == 1
    assert len(chunks(document(), cfg=config(semantic_min_distance=1.5))) == 1


@pytest.mark.parametrize('changes', [
    {'target': 0}, {'overlap': 100}, {'method': 'invalid'},
    {'semantic_percentile': float('nan')}, {'semantic_percentile': 101},
    {'semantic_min_distance': float('inf')}, {'semantic_min_tokens': 0}, {'semantic_window': 0},
])
def test_invalid_configuration_is_rejected(changes):
    with pytest.raises(ValueError):
        config(**changes)


@pytest.mark.parametrize('bad', [[[]], [[float('nan'), 1]], [[0, 0]], []])
def test_invalid_boundary_vectors_fail_instead_of_silently_switching_to_size(bad):
    encoder = SemanticEncoder()
    encoder.encode = lambda texts, query=False: [] if not bad else bad * len(texts)
    with pytest.raises(ValueError):
        chunks(document(), encoder)


def test_preview_commit_idempotence_config_change_reindex_and_search(tmp_path):
    service = Service(DemoStore(str(tmp_path / 'rag.sqlite')), SemanticEncoder(), config(), 'live')
    client = TestClient(create_app(service))
    try:
        raw = document()
        preview = client.post('/api/v1/rag/import-json?mode=dry_run', json=raw).json()
        assert preview['chunking']['method'] == 'semantic' and preview['chunking_summary']['semantic'] == 1
        assert not service.store.documents()
        imported = client.post('/api/v1/rag/import-json', json=raw).json()
        assert imported['chunks'] == 2 and imported['propositions'] == 1
        old = service.store.get('D')['active_revision']
        assert client.post('/api/v1/rag/import-json', json=raw).json()['status'] == 'skipped'
        assert service.store.get('D')['active_revision'] == old
        assert client.get('/api/v1/rag/health').json()['chunking']['method'] == 'semantic'
        assert not client.get('/api/v1/rag/documents/D').json()['needs_reindex']
        service.config = config(semantic_min_distance=1.5)
        assert client.get('/api/v1/rag/stats').json()['needs_reindex'] == 1
        assert client.get('/api/v1/rag/documents').json()['items'][0]['needs_reindex']
        search = client.post('/api/v1/rag/search', json={'query': 'ALPHA', 'kind': 'all'}).json()
        assert search['results'] and search['reindex_required'] == ['D']
        reindexed = client.post('/api/v1/rag/documents/D/reindex').json()
        assert reindexed['chunks'] == 1 and not service.store.records(old)
        assert not client.get('/api/v1/rag/documents/D').json()['needs_reindex']
        assert client.get('/api/v1/rag/documents/D/source').json() == raw
    finally:
        service.store.close()


def test_legacy_document_without_chunking_metadata_is_migrated_without_changing_source(tmp_path):
    service = Service(DemoStore(str(tmp_path / 'rag.sqlite')), SemanticEncoder(), config(method='token'), 'live')
    try:
        raw = document()
        service.import_data(raw)
        old = service.store.get('D')
        old.pop('chunking')
        old['fingerprint'] = 'old-section-offset-v1'
        service.store.activate(old)
        source = service.store.source(old['active_revision'])
        service.config = config()
        assert service.document_status(service.store.get('D'))['needs_reindex']
        assert service.import_data(source)['chunks'] == 2
        assert service.store.source(service.store.get('D')['active_revision']) == raw
    finally:
        service.store.close()


def test_boundary_model_failure_keeps_the_previous_active_revision(tmp_path):
    encoder = SemanticEncoder()
    service = Service(DemoStore(str(tmp_path / 'rag.sqlite')), encoder, config(method='token'), 'live')
    try:
        raw = document()
        service.import_data(raw)
        old = service.store.get('D')['active_revision']
        service.config = config()
        def fail(texts, query=False):
            raise RuntimeError('Boundary encoder unavailable')
        encoder.encode = fail
        with pytest.raises(RuntimeError):
            service.import_data(raw, force=True)
        assert service.store.get('D')['active_revision'] == old
        assert service.store.source(old) == raw
    finally:
        service.store.close()


def test_semantic_metadata_roundtrip_in_mongo_and_real_qdrant_local_mode(monkeypatch):
    mongomock = pytest.importorskip('mongomock')
    qdrant = pytest.importorskip('qdrant_client')
    from qdrant_client import models
    from app.modules.rag.storage import LiveStore
    original = mongomock.collection.BulkOperationBuilder.add_replace
    def compatible(self, *args, sort=None, **kwargs):
        assert sort is None
        return original(self, *args, **kwargs)
    monkeypatch.setattr(mongomock.collection.BulkOperationBuilder, 'add_replace', compatible)
    store = LiveStore.__new__(LiveStore)
    store.models, store.mongo = models, mongomock.MongoClient()
    store.db, store.q = store.mongo['semantic_test'], qdrant.QdrantClient(':memory:')
    # Local Qdrant ignores payload indexes; the upstream adapter test covers
    # those calls. Avoid consuming its process-wide warn-once cache here.
    monkeypatch.setattr(store.q, 'create_payload_index', lambda *args, **kwargs: None)
    store.ensure_indexes(SemanticEncoder())
    service = Service(store, SemanticEncoder(), config(), 'live')
    try:
        assert service.import_data(document())['chunks'] == 2
        assert store.q.count('medical_rag_chunks', exact=True).count == 2
        meta = store.get('D')
        assert not service.document_status(meta)['needs_reindex']
        rows = store.records(meta['active_revision'], 'chunk')
        assert {r['chunk_method'] for r in rows} == {'semantic'}
        assert any(r['boundary_reason'] == 'semantic' for r in rows)
        hits = service.search('ALPHA', None, {}, 5)['results']
        assert hits and any('T0' in r.get('sentence_ids', []) for r in hits)
        service.config = config(semantic_min_distance=1.5)
        service.import_data(store.source(meta['active_revision']), force=True)
        assert store.q.count('medical_rag_chunks', exact=True).count == 1
        assert not store.records(meta['active_revision'])
    finally:
        store.close()


def test_lifespan_defaults_to_semantic_and_reads_token_override(monkeypatch):
    from app.modules.rag import main
    for key in ['RAG_CHUNK_METHOD', 'RAG_CHUNK_TOKENS', 'RAG_CHUNK_OVERLAP', 'RAG_SEMANTIC_PERCENTILE',
                'RAG_SEMANTIC_MIN_DISTANCE', 'RAG_SEMANTIC_MIN_TOKENS', 'RAG_SEMANTIC_WINDOW']:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('RAG_MODE', 'live')
    monkeypatch.setattr(main, 'E5Encoder', lambda *args: SemanticEncoder())
    monkeypatch.setattr(main, 'LiveStore', lambda *args: DemoStore(':memory:'))
    with TestClient(create_app()) as client:
        profile = client.get('/api/v1/rag/health').json()['chunking']
        assert profile['method'] == 'semantic' and profile['config']['target'] == 450
    monkeypatch.setenv('RAG_CHUNK_METHOD', 'token')
    monkeypatch.setenv('RAG_SEMANTIC_PERCENTILE', '75')
    with TestClient(create_app()) as client:
        profile = client.get('/api/v1/rag/health').json()['chunking']
        assert profile['method'] == 'token' and profile['config']['semantic_percentile'] == 75


def test_invalid_env_fails_before_loading_model_or_opening_database(monkeypatch):
    from app.modules.rag import main
    monkeypatch.setenv('RAG_MODE', 'live')
    monkeypatch.setenv('RAG_CHUNK_METHOD', 'misspelled')
    def forbidden(*args):
        pytest.fail('An invalid chunking configuration must fail before model/database setup')
    monkeypatch.setattr(main, 'E5Encoder', forbidden)
    monkeypatch.setattr(main, 'LiveStore', forbidden)
    with pytest.raises(ValueError, match='RAG_CHUNK_METHOD'):
        with TestClient(create_app()):
            pass


def test_e5_adapter_uses_query_prefix_for_boundaries_and_passage_for_indexing(monkeypatch):
    import numpy as np
    from app.services import encoders
    from app.modules.rag.core import E5Encoder
    calls = []
    class Tokenizer:
        is_fast = True
        def __call__(self, text, add_special_tokens=True, return_offsets_mapping=False):
            offsets = DemoEncoder().offsets(text)
            return {'input_ids': [1] * (len(offsets) + (2 if add_special_tokens else 0)), 'offset_mapping': offsets}
    class Model:
        tokenizer = Tokenizer()
        max_seq_length = 128
        def get_sentence_embedding_dimension(self): return 2
        def encode(self, texts, **kwargs):
            assert kwargs['normalize_embeddings'] is True
            calls.extend(texts)
            return np.array([[0., 1.] if 'BETA' in text else [1., 0.] for text in texts])
    monkeypatch.setattr(encoders, 'get_encoder', lambda *args, **kwargs: Model())
    encoder = E5Encoder('intfloat/multilingual-e5-base', 'fixture-revision', 'cpu')
    assert len(chunks(document(), encoder)) == 2
    assert calls and all(text.startswith('query: ') for text in calls)
    calls.clear()
    encoder.encode(['Đoạn nguồn đã chia'])
    assert calls == ['passage: Đoạn nguồn đã chia']
    with pytest.raises(ValueError, match='Vượt giới hạn'):
        encoder.encode(['từ ' * 200], query=True)
