import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.modules.rag.core import Input,DemoEncoder,ChunkConfig,build_records,validate_refs
from app.modules.rag.storage import DemoStore
from app.modules.rag.service import Service
from app.modules.rag.main import create_app
ROOT=Path(__file__).resolve().parents[3]
@pytest.fixture
def raw():
    return {'schema_version':'1.0','document':{'document_id':'D1','title':'Hướng dẫn hô hấp','document_type':'clinical_guideline','language':'vi','sections':[
      {'section_id':'S1','title':'Triệu chứng','paragraphs':[{'paragraph_id':'P1','sentences':[
        {'sentence_id':'T1','text':'  COPD có triệu chứng khó thở. Ho kéo dài.  '},{'sentence_id':'T2','text':'Đánh giá triệu chứng và tiền sử.'}]}]},
      {'section_id':'S2','title':'Chẩn đoán','paragraphs':[{'paragraph_id':'P2','sentences':[{'sentence_id':'T3','text':'Đo chức năng hô hấp để đánh giá.'}]}]}]},
      'entities':[{'id':'E1','type':'Disease','canonical_name':'COPD'},{'id':'E2','type':'Symptom','canonical_name':'Khó thở'}],
      'relations':[{'id':'R1','type':'HAS_SYMPTOM','source':'E1','target':'E2','proposition_ids':['PROP1']}],
      'propositions':[{'id':'PROP1','text':'COPD có triệu chứng khó thở.','evidence':[{'sentence_id':'T1'}]}]}
@pytest.fixture
def service(tmp_path):
    s=Service(DemoStore(str(tmp_path/'db.sqlite')),DemoEncoder(),ChunkConfig(32,8),'demo')
    yield s
    s.store.close()
def test_refs(raw):
    raw['propositions'][0]['evidence'][0]['sentence_id']='missing'
    assert not validate_refs(Input.model_validate(raw))['valid']
    raw['entities'][1]['id']='E1'
    assert any('ID trùng' in e for e in validate_refs(Input.model_validate(raw))['errors'])
def test_chunk_bounds_and_lossless_offsets(raw):
    original='  '+' '.join(f'từ{i}' for i in range(1000))+'  '
    raw['document']['sections'][0]['paragraphs'][0]['sentences'][0]['text']=original
    encoder=DemoEncoder();rows=build_records(Input.model_validate(raw),encoder,ChunkConfig(40,10));covered=set()
    for row in rows:
        assert row['token_count']<=encoder.max_length
        if row['kind']!='chunk':continue
        for span in row['source_spans']:
            if span['sentence_id']=='T1':
                covered.update(range(span['start_char'],span['end_char']))
                assert original[span['start_char']:span['end_char']] in row['text']
        if row['section_id']=='S2':assert 'T1' not in row['sentence_ids']
    assert covered==set(range(len(original)))
def test_idempotent_update_reindex_delete(raw,service):
    assert service.import_data(raw,dry_run=True)['status']=='dry_run';assert not service.store.documents()
    assert service.import_data(raw)['actions']['insert']==3
    old=service.store.get('D1')['active_revision']
    assert service.import_data(raw)['status']=='skipped';assert service.store.get('D1')['active_revision']==old
    raw['document']['sections'].pop()
    assert service.import_data(raw)['actions']['delete']==1;assert not service.store.records(old)
    assert service.import_data(raw,force=True)['vectors_written']==2
    hits=service.search('khó thở','proposition',{'entity_ids':'E2'},5)['results']
    assert len(hits)==1 and hits[0]['evidence_sentence_ids']==['T1']
    assert not service.search('khó thở',None,{'document_id':'other'},5)['results']
    service.delete('D1');assert not service.store.documents();assert not service.search('khó thở',None,{},5)['results']
def test_failed_stage_keeps_active_revision(raw,service,monkeypatch):
    service.import_data(raw);old=service.store.get('D1')['active_revision'];stage=service.store.stage
    def fail(*args):stage(*args);raise RuntimeError('injected stage failure')
    monkeypatch.setattr(service.store,'stage',fail);raw['document']['title']='Phiên bản cập nhật'
    with pytest.raises(RuntimeError):service.import_data(raw)
    assert service.store.get('D1')['active_revision']==old
    assert all(r['revision']==old for r in service.search('COPD',None,{},5)['results'])
    monkeypatch.setattr(service.store,'stage',stage)
    assert service.import_data(raw)['status']=='completed';assert not service.store.records(old)
def test_model_change_requires_reindex(raw,service):
    service.import_data(raw);service.encoder.fingerprint='changed'
    with pytest.raises(ValueError,match='Reindex'):service.search('COPD',None,{},5)
    service.import_data(raw,force=True);assert service.search('COPD',None,{},5)['results']
def test_api(raw,service):
    client=TestClient(create_app(service))
    assert client.get('/').status_code==200
    assert client.post('/api/v1/rag/validate',json={}).status_code==422
    assert client.post('/api/v1/rag/validate',content='{').status_code==400
    assert client.post('/api/v1/rag/import-json?mode=bad',json=raw).status_code==422
    assert client.post('/api/v1/rag/import-json',json=raw).status_code==200
    assert client.get('/api/v1/rag/stats').json()['documents']==1
    assert client.get('/api/v1/rag/documents/D1/chunks?limit=1').json()['total']==2
    e=client.get('/api/v1/rag/documents/D1/evidence/T1').json()
    assert e['text'].startswith('  ') and len(e['chunk_ids'])==1
    assert client.get('/api/v1/rag/documents/D1/evidence/missing').status_code==404
    assert client.post('/api/v1/rag/search',json={'query':'COPD','filters':{'bad':'x'}}).status_code==422
    assert client.post('/api/v1/rag/search',json={'query':'   '}).status_code==422
    assert client.post('/api/v1/rag/search',json={'query':'COPD'}).json()['results']
    assert client.post('/api/v1/rag/documents/D1/reindex').status_code==200
    assert client.delete('/api/v1/rag/documents/D1').status_code==200
    assert client.get('/api/v1/rag/documents/D1').status_code==404
def test_provided_file(service):
    raw=json.loads((ROOT/'examples/rag/DOC_000001.json').read_text(encoding='utf-8'))
    assert service.validate(raw)['valid'];assert service.import_data(raw)['propositions']==128
    assert service.import_data(raw)['status']=='skipped'
    hits=service.search('COPD có triệu chứng khó thở','proposition',{},5)['results']
    assert hits[0]['proposition_id']=='DOC_000001_PROP_000001'

@pytest.mark.parametrize('metadata_value',['missing',None,'','   '])
def test_optional_document_metadata_import(raw,service,metadata_value):
    for key in ['document_type','language']:
        if metadata_value=='missing': raw['document'].pop(key)
        else: raw['document'][key]=metadata_value
    client=TestClient(create_app(service))
    checked=client.post('/api/v1/rag/validate',json=raw)
    assert checked.status_code==200 and checked.json()['valid']
    assert len(checked.json()['warnings'])==2
    preview=client.post('/api/v1/rag/import-json?mode=dry_run',json=raw)
    assert preview.status_code==200 and not service.store.documents()
    imported=client.post('/api/v1/rag/import-json',json=raw)
    assert imported.status_code==200 and imported.json()['status']=='completed'
    source=client.get('/api/v1/rag/documents/D1/source').json()['document']
    assert source['document_type']=='unknown' and source['language']=='und'
    hits=client.post('/api/v1/rag/search',json={'query':'COPD','filters':{'language':'und'}}).json()['results']
    assert hits and all(r['document_type']=='unknown' for r in hits)
    assert client.post('/api/v1/rag/import-json',json=raw).json()['status']=='skipped'
    assert client.post('/api/v1/rag/documents/D1/reindex').status_code==200
    assert client.get('/api/v1/rag/health').json()['version']=='1.0.1'

def test_provided_metadata_preserved_and_wrong_types_rejected(raw,service):
    data=Input.model_validate(raw)
    assert data.document.document_type=='clinical_guideline' and data.document.language=='vi'
    assert not validate_refs(data)['warnings']
    client=TestClient(create_app(service))
    for key in ['document_type','language']:
        original=raw['document'][key]
        raw['document'][key]=123
        assert client.post('/api/v1/rag/validate',json=raw).status_code==422
        raw['document'][key]=original
