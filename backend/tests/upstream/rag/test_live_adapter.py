"""Client integration: mongomock + real Qdrant local mode, not a live server benchmark."""
import pytest
mongomock=pytest.importorskip('mongomock');qdrant=pytest.importorskip('qdrant_client')
from qdrant_client import models
from app.modules.rag.storage import LiveStore
from app.modules.rag.core import DemoEncoder,ChunkConfig
from app.modules.rag.service import Service
from .test_pipeline import raw

def test_live_adapter_indexes_stage_search_delete(raw,monkeypatch):
    # mongomock 4.3 predates the optional PyMongo sort argument. Adapter never uses sort.
    original=mongomock.collection.BulkOperationBuilder.add_replace
    def compatible(self,*args,sort=None,**kwargs):
        assert sort is None
        return original(self,*args,**kwargs)
    monkeypatch.setattr(mongomock.collection.BulkOperationBuilder,'add_replace',compatible)
    store=LiveStore.__new__(LiveStore);store.models=models;store.mongo=mongomock.MongoClient();store.db=store.mongo['test'];store.q=qdrant.QdrantClient(':memory:')
    with pytest.warns(UserWarning,match='Payload indexes'):store.ensure_indexes(DemoEncoder())
    service=Service(store,DemoEncoder(),ChunkConfig(32,8),'live')
    try:
        assert service.import_data(raw)['status']=='completed'
        revision=store.get('D1')['active_revision']
        assert store.sentence(revision,'T1')['text'].startswith('  ')
        assert store.chunk_page(revision,0,10,'T1')[0]==1
        assert service.search('khó thở','proposition',{'entity_ids':'E2'},5)['results'][0]['logical_id']=='PROP1'
        assert service.import_data(raw)['status']=='skipped'
        raw['document']['sections'].pop();service.import_data(raw)
        assert store.q.count('medical_rag_chunks',exact=True).count==1
        assert store.db.medical_rag_chunks.count_documents({})==1
        assert store.db.rag_sentences.count_documents({})==2
        service.delete('D1')
        assert store.q.count('medical_rag_chunks',exact=True).count==0
        assert store.q.count('medical_rag_propositions',exact=True).count==0
        assert store.db.rag_sources.count_documents({})==0
    finally:store.close()
