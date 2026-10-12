"""Batched, model-bound KG name index. Vectors propose candidates, never auto-merge."""
from __future__ import annotations
import logging
import uuid
from collections import OrderedDict
from threading import RLock
from typing import Any
import numpy as np
from .config import EntityEmbeddingSettings
from .utils import fold, sha256_of

log = logging.getLogger('kg_import')
PROFILE_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, 'medical-ai:kg-embedding-profile:v1'))


class QdrantEntityIndex:
    def __init__(self, settings: EntityEmbeddingSettings, *, client=None, encoder=None):
        self.settings = settings
        if client is None:
            from qdrant_client import QdrantClient
            client = QdrantClient(url=settings.qdrant_url, timeout=30)
        self.client, self._encoder = client, encoder
        self._lock = RLock()
        self._vectors = OrderedDict()
        self.profile = sha256_of({'model': settings.model, 'revision': settings.revision,
                                  'max_seq_length': settings.max_seq_length, 'normalize': True})

    def close(self):
        close = getattr(self.client, 'close', None)
        if close: close()

    @property
    def encoder(self):
        with self._lock:
            if self._encoder is None:
                from sentence_transformers import SentenceTransformer
                log.info('kg.embedding.loading model=%s revision=%s', self.settings.model, self.settings.revision)
                self._encoder = SentenceTransformer(self.settings.model, revision=self.settings.revision,
                    trust_remote_code=self.settings.trust_remote_code,
                    device=None if self.settings.device == 'auto' else self.settings.device,
                    cache_folder=self.settings.cache_dir)
                self._encoder.max_seq_length = self.settings.max_seq_length
                log.info('kg.embedding.ready dimension=%s device=%s',
                         self._encoder.get_sentence_embedding_dimension(), self._encoder.device)
            return self._encoder

    def _marker(self):
        rows = self.client.retrieve(self.settings.collection, [PROFILE_ID], with_payload=True)
        return rows[0].payload if rows else None

    def _check_marker(self, marker):
        if not marker or marker.get('embedding_profile') != self.profile:
            raise ValueError('Chỉ mục KG thuộc model/cấu hình khác hoặc là chỉ mục cũ. '
                             'Đặt KG_ENTITY_COLLECTION mới rồi chạy python -m scripts.kg.index_entities.')

    def ready(self):
        if not self.client.collection_exists(self.settings.collection): return False
        marker = self._marker()
        self._check_marker(marker)
        return marker.get('state') == 'ready'

    def _write_marker(self, state, size):
        from qdrant_client.models import PointStruct
        self.client.upsert(collection_name=self.settings.collection, wait=True, points=[
            PointStruct(id=PROFILE_ID, vector=[0.0] * size,
                payload={'record_type': 'kg_embedding_profile', 'embedding_profile': self.profile,
                         'model_id': self.settings.model, 'revision': self.settings.revision,
                         'state': state, 'dimension': size})])

    def ensure_collection(self, *, initial_state='ready'):
        from qdrant_client.models import Distance, VectorParams
        with self._lock:
            size = int(self.encoder.get_sentence_embedding_dimension())
            if not self.client.collection_exists(self.settings.collection):
                self.client.create_collection(self.settings.collection,
                    vectors_config=VectorParams(size=size, distance=Distance.COSINE))
                self._write_marker(initial_state, size)
                return
            info = self.client.get_collection(self.settings.collection)
            vectors = info.config.params.vectors
            if getattr(vectors, 'size', None) != size or getattr(vectors, 'distance', None) != Distance.COSINE:
                raise ValueError('Chiều vector/khoảng cách Qdrant không khớp model; dùng collection KG mới.')
            marker = self._marker()
            if marker is None and info.points_count == 0: self._write_marker(initial_state, size)
            else: self._check_marker(marker)

    def begin_build(self):
        self.ensure_collection(initial_state='building')
        self._write_marker('building', int(self.encoder.get_sentence_embedding_dimension()))

    def finish_build(self):
        self._write_marker('ready', int(self.encoder.get_sentence_embedding_dimension()))

    def _encode(self, names):
        with self._lock:
            values = {name: self._vectors[name] for name in names if name in self._vectors}
            missing = list(dict.fromkeys(name for name in names if name not in values))
            if missing:
                encoded = self.encoder.encode(missing, normalize_embeddings=True,
                    batch_size=self.settings.batch_size, show_progress_bar=False)
                if len(encoded) != len(missing): raise ValueError('Embedding output count differs from entity names')
                for name, vector in zip(missing, encoded):
                    value = np.asarray(vector, dtype=np.float32)
                    if value.shape != (int(self.encoder.get_sentence_embedding_dimension()),) or not np.isfinite(value).all():
                        raise ValueError('Invalid entity embedding vector')
                    values[name] = value
            for name in names:
                if self.settings.cache_size:
                    self._vectors[name] = values[name]
                    self._vectors.move_to_end(name)
                    while len(self._vectors) > self.settings.cache_size: self._vectors.popitem(last=False)
            return [values[name] for name in names]

    def upsert_entities(self, entities: list[dict[str, Any]]):
        from qdrant_client.models import PointStruct
        self.ensure_collection()
        entries = []
        for entity in entities:
            seen = set()
            for name in [entity['canonical_name'], *(entity.get('aliases') or [])]:
                key = fold(name)
                if key and key not in seen:
                    seen.add(key); entries.append((name, entity))
        count = 0
        for offset in range(0, len(entries), 128):
            batch = entries[offset:offset + 128]
            vectors = self._encode([name for name, _ in batch])
            points = []
            for (name, e), vector in zip(batch, vectors):
                key = f"{self.profile}|{e['id']}|{fold(name)}"
                points.append(PointStruct(id=str(uuid.uuid5(uuid.NAMESPACE_URL, key)), vector=vector.tolist(),
                    payload={'entity_id': e['id'], 'entity_type': e['entity_type'], 'name': name,
                             'canonical_name': e['canonical_name'], 'model_id': self.settings.model,
                             'embedding_profile': self.profile}))
            if points:
                self.client.upsert(collection_name=self.settings.collection, points=points, wait=True)
                count += len(points)
        return count

    @staticmethod
    def _candidates(points, limit):
        by_id = {}
        for hit in points:
            payload = hit.payload or {}; eid = payload.get('entity_id')
            if eid and (eid not in by_id or hit.score > by_id[eid]['score']):
                by_id[eid] = {'entity_id': eid, 'canonical_name': payload.get('canonical_name'),
                             'matched_name': payload.get('name'), 'score': round(float(hit.score), 4)}
        return sorted(by_id.values(), key=lambda x: x['score'], reverse=True)[:limit]

    def suggest_many(self, queries, *, limit=5, score_threshold=None):
        from qdrant_client.models import FieldCondition, Filter, MatchValue, QueryRequest
        if not queries: return []
        if not self.ready():
            raise ValueError('Chỉ mục KG chưa sẵn sàng; chạy python -m scripts.kg.index_entities trước.')
        out = []
        for offset in range(0, len(queries), self.settings.query_batch_size):
            batch = queries[offset:offset + self.settings.query_batch_size]
            vectors = self._encode([name for name, _ in batch])
            requests = [QueryRequest(query=vector.tolist(), filter=Filter(must=[
                FieldCondition(key='embedding_profile', match=MatchValue(value=self.profile)),
                *([FieldCondition(key='entity_type', match=MatchValue(value=kind))] if kind else [])]),
                score_threshold=self.settings.candidate_score if score_threshold is None else score_threshold,
                limit=max(limit * 3, limit), with_payload=True) for (_, kind), vector in zip(batch, vectors)]
            results = self.client.query_batch_points(collection_name=self.settings.collection, requests=requests)
            if len(results) != len(batch): raise ValueError('Qdrant output count differs from entity queries')
            out.extend(self._candidates(result.points, limit) for result in results)
        return out

    def suggest(self, name, entity_type, *, limit=5, score_threshold=None):
        return self.suggest_many([(name, entity_type)], limit=limit, score_threshold=score_threshold)[0]
