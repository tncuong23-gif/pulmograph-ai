import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.bulk_import.api import create_router
from app.bulk_import.context import ContextAdapter, ContextFile
from app.bulk_import.kg import KGAdapter
from app.bulk_import.manager import BatchManager, ImportBusy, MAX_BYTES
from app.modules.context.config import Settings
from app.modules.context.container import ApplicationContainer
from app.modules.context.infrastructure.neo4j.history_repository import Neo4jHistoryRepository
from app.modules.context.infrastructure.neo4j.patient_repository import Neo4jPatientRepository
from app.modules.kg_import.adapters.memory import MemoryDocumentStore, MemoryGraphStore, MemoryJobStore
from app.modules.kg_import.service import KGImportService
from tests.upstream.kg.helpers import load_ontology, load_payload


def context_file(patient='P_1', session='S_1', message='M_1'):
    return {'schema_version':'1.0', 'patient_id':patient, 'session_id':session,
            'history':[{'patient_id':patient, 'session_id':session, 'message_id':message,
                        'role':'user', 'original_text':'Tôi bị ho.', 'created_at':'2026-10-10T10:00:00+07:00'}],
            'facts':[{'fact_type':'symptom','display':'ho','source_text':'Tôi bị ho.',
                      'source_message_id':message,'recorded_at':'2026-10-10T10:00:00+07:00'}]}


def context_container():
    return ApplicationContainer.build(Settings(graph_backend='memory', nlp_backend='rule',
                                               embedding_backend='hash', terminology_mode='off'))


def save(manager, name, raw):
    manager.upload(name, json.dumps(raw,ensure_ascii=False).encode())


async def finish(manager, **kwargs):
    job = manager.start(**kwargs)
    await asyncio.wait_for(manager.task, 5)
    return manager.get(job['job_id'])


@pytest.mark.asyncio
async def test_context_preview_commit_and_rerun_keep_consent_negation_and_certainty(tmp_path):
    container = context_container()
    manager = BatchManager('context', ContextAdapter(lambda:container),tmp_path/'input',tmp_path/'reports')
    raw=context_file();raw['facts'][0].update(negated=True,certainty='possible')
    save(manager,'one.json',raw)
    preview=await finish(manager)
    assert preview['completed']==1 and not container.patient_repository._facts
    assert (await manager.review(preview['job_id'],0))['facts'][0]['negated'] is True
    with pytest.raises(ValueError,match='xác nhận'):
        manager.start(mode='commit',previous_job_id=preview['job_id'])
    with pytest.raises(ValueError):
        manager.start(mode='commit',previous_job_id=preview['job_id'],confirmed=True,files=[])
    committed=await finish(manager,mode='commit',previous_job_id=preview['job_id'],confirmed=True)
    assert committed['completed']==1
    fact=container.patient_repository._facts['P_1'][0]
    assert fact.negated and fact.certainty=='possible' and fact.attributes['confirmation_status']=='user_confirmed'
    repeat=await finish(manager,mode='commit',previous_job_id=preview['job_id'],confirmed=True)
    assert repeat['skipped']==1 and len(container.patient_repository._facts['P_1'])==1
    await manager.close()


@pytest.mark.asyncio
async def test_mixed_files_continue_and_reports_do_not_contain_clinical_text(tmp_path):
    container=context_container()
    m=BatchManager('context',ContextAdapter(lambda:container),tmp_path/'input',tmp_path/'reports')
    save(m,'good.json',context_file())
    m.upload('bad.json',b'{')
    save(m,'nested/SECOND.JSON',context_file('P_2','S_2','M_2'))
    preview=await finish(m)
    assert preview['total']==3 and preview['failed']==1 and preview['completed']==2
    commit=await finish(m,mode='commit',previous_job_id=preview['job_id'],confirmed=True)
    assert commit['completed']==2 and set(container.patient_repository._facts)=={'P_1','P_2'}
    report=m.report(preview['job_id'],'errors').read_bytes()
    assert report.startswith(b'\xef\xbb\xbf') and b'bad.json' in report and b'good.json' not in report
    assert 'Tôi bị ho' not in m.report(commit['job_id'],'json').read_text()
    save(m,'bad.json',context_file('P_3','S_3','M_3'))
    repaired=await finish(m,source='files',files=['bad.json'])
    assert repaired['total']==repaired['completed']==1
    await m.close()


@pytest.mark.asyncio
async def test_hash_pin_conflicts_and_patient_isolation(tmp_path):
    container=context_container();m=BatchManager('context',ContextAdapter(lambda:container),tmp_path/'in',tmp_path/'out')
    save(m,'first.json',context_file());preview=await finish(m)
    changed=context_file();changed['facts'][0]['display']='khó thở';save(m,'first.json',changed)
    result=await finish(m,mode='commit',previous_job_id=preview['job_id'],confirmed=True)
    assert result['failed']==1 and 'thay đổi' in result['items'][0]['error']
    assert not container.history_repository._turns
    save(m,'first.json',context_file());preview=await finish(m)
    await finish(m,mode='commit',previous_job_id=preview['job_id'],confirmed=True)
    save(m,'other.json',context_file('P_OTHER','S_OTHER','M_1'))
    other=await finish(m,source='files',files=['other.json'])
    assert other['failed']==1 and 'Không ghi đè' in other['items'][0]['error']
    assert ('P_OTHER','S_OTHER') not in container.history_repository._turns
    await m.close()


@pytest.mark.parametrize('mutation',[
    lambda p:p['history'][0].update(patient_id='WRONG'),
    lambda p:p['history'][0].update(role='system'),
    lambda p:p['history'][0].update(created_at='2026-10-10T10:00:00'),
    lambda p:p['facts'][0].update(source_message_id='MISSING'),
    lambda p:p['facts'][0].update(source_text='Câu không có trong nguồn'),
    lambda p:p['facts'][0].update(assertion='inferred'),
    lambda p:p['facts'][0].update(statement_type='question'),
    lambda p:p['facts'].append(copy.deepcopy(p['facts'][0])),
    lambda p:p.update(patient_id='A:B'),
])
def test_invalid_context_rejected(mutation):
    raw=context_file();mutation(raw)
    with pytest.raises(ValueError):ContextFile.model_validate(raw)


@pytest.mark.asyncio
async def test_upload_errors_never_import_previous_file_and_duplicate_ids_stop_overwrite(tmp_path):
    m=BatchManager('context',ContextAdapter(context_container),tmp_path/'in',tmp_path/'out')
    save(m,'a.json',context_file());save(m,'b.json',context_file())
    duplicate=await finish(m)
    assert duplicate['completed']==1 and duplicate['failed']==1
    failed=await finish(m,source='files',files=['a.json'],file_errors={'a.json':'Upload rejected'})
    assert failed['failed']==1 and failed['items'][0]['stage']=='upload'
    assert 'sha256' not in failed['items'][0]
    await m.close()


@pytest.mark.asyncio
async def test_path_limits_worker_lock_and_recovery(tmp_path):
    entered=asyncio.Event();release=asyncio.Event()
    class Slow:
        def identity(self,raw):return 'ID'
        async def process(self,*a,**k):entered.set();await release.wait();return {'status':'completed'}
    m=BatchManager('kg',Slow(),tmp_path/'in',tmp_path/'out')
    for bad in ['../a.json','/a.json','NUL.json','a\\b.json','a.txt']:
        with pytest.raises(ValueError):m.upload(bad,b'{}')
    with pytest.raises(ValueError):m.upload('big.json',b' '*(MAX_BYTES+1))
    (tmp_path/'outside.json').write_text('{}');(m.input_dir/'link.json').symlink_to(tmp_path/'outside.json')
    with pytest.raises(ValueError):m.read('link.json')
    save(m,'a.json',{})
    job=m.start(source='files',files=['a.json']);await entered.wait()
    with pytest.raises(ImportBusy):m.start()
    with pytest.raises(ImportBusy):m.upload('a.json',b'{}')
    m.task.cancel()
    with pytest.raises(asyncio.CancelledError):await m.task
    m.db.close()
    recovered=BatchManager('kg',Slow(),tmp_path/'in',tmp_path/'out')
    assert recovered.active is None and recovered.get(job['job_id'])['status']=='interrupted'
    assert recovered.get(job['job_id'])['failed']==1
    await recovered.close()


class Index:
    def __init__(self):self.fail=False;self.exists=True;self.rows={}
    def ready(self):return self.exists
    def ensure_collection(self):self.exists=True
    def suggest(self,*args):return []
    def upsert_entities(self,rows):
        if self.fail:raise RuntimeError('injected qdrant outage')
        self.rows.update({e['id']:e for e in rows});return len(rows)


def kg_service(index=None):
    return KGImportService(load_ontology(),MemoryDocumentStore(),MemoryGraphStore(),MemoryJobStore(),entity_index=index)


@pytest.mark.asyncio
async def test_disabled_vector_is_explicit_and_bootstrap_indexes_existing_graph(tmp_path):
    svc=kg_service()
    m=BatchManager('kg',KGAdapter(lambda:svc),tmp_path/'in',tmp_path/'out')
    save(m,'a.json',load_payload())
    preview=await finish(m)
    assert 'đang tắt' in preview['items'][0]['warning']
    await finish(m,mode='commit',previous_job_id=preview['job_id'],confirmed=True)
    index=Index();index.exists=False;svc.entity_index=index
    boot=await finish(m,mode='index')
    assert boot['completed']==1 and set(index.rows)==set(svc.graph.entities)
    await m.close()


@pytest.mark.asyncio
async def test_kg_vector_failure_retry_does_not_rewrite_mongo_or_neo4j(tmp_path):
    index=Index();svc=kg_service(index)
    m=BatchManager('kg',KGAdapter(lambda:svc),tmp_path/'in',tmp_path/'out')
    save(m,'doc.json',load_payload());preview=await finish(m)
    index.fail=True
    first=await finish(m,mode='commit',previous_job_id=preview['job_id'],confirmed=True)
    assert first['partial']==1 and first['items'][0]['stage']=='vector'
    original=svc.get_status(first['items'][0]['import_id'])
    assert original['mongo_done'] and original['neo4j_done'] and original['finalize_done']
    assert svc.docs.document_exists(load_payload()['document']['document_id'])
    index.fail=False;svc.docs.fail_on_write=True;svc.graph.fail_on_write=True
    retry=await finish(m,mode='retry',previous_job_id=first['job_id'],confirmed=True)
    assert retry['completed']==1 and index.rows
    assert retry['items'][0]['import_id']==first['items'][0]['import_id']
    assert 'entity_index_warning' not in retry['items'][0]['statistics']
    await m.close()


@pytest.mark.asyncio
async def test_kg_initial_index_is_explicit_and_semantic_candidates_require_decision(tmp_path):
    from tests.upstream.kg.test_entity_vector import FakeIndex
    index=Index();index.exists=False;svc=kg_service(index)
    m=BatchManager('kg',KGAdapter(lambda:svc),tmp_path/'in',tmp_path/'out')
    save(m,'a.json',load_payload());preview=await finish(m)
    assert preview['failed']==1 and not index.exists
    bootstrap=await finish(m,mode='index');assert bootstrap['completed']==1 and index.exists
    svc.entity_index=FakeIndex();svc.import_kg(load_payload())
    raw=load_payload();raw['document']['document_id']='DOC_000002'
    raw['entities'][0].update(id='ENT_NEW',canonical_name='Bệnh phổi tắt nghẽn mãn tính',aliases=[])
    for r in raw['relations']:
        if r['source']=='ENT_000001':r['source']='ENT_NEW'
        r['id']='NEW_'+r['id']
    raw['propositions'][0]['entity_ids']=['ENT_NEW']
    save(m,'review.json',raw)
    preview=await finish(m,source='files',files=['review.json']);assert preview['needs_review']==1
    with pytest.raises(ValueError):m.start(mode='commit',previous_job_id=preview['job_id'],confirmed=True)
    with pytest.raises(ValueError):await m.decisions(preview['job_id'],0,{'ENT_NEW':'NOT_A_CANDIDATE'})
    await m.decisions(preview['job_id'],0,{'ENT_NEW':'ENT_000001'})
    revised=await finish(m,source='files',files=['review.json']);assert revised['completed']==1
    committed=await finish(m,mode='commit',previous_job_id=revised['job_id'],confirmed=True)
    assert committed['completed']==1 and svc.graph.relations['NEW_REL_000001']['source_id']=='ENT_000001'
    await m.close()


def test_api_serves_workspace_and_requires_review_confirmation(tmp_path):
    container=context_container()
    m=BatchManager('context',ContextAdapter(lambda:container),tmp_path/'in',tmp_path/'out')
    app=FastAPI();app.state.import_batches={'context':m};app.include_router(create_router())
    with TestClient(app) as client:
        assert client.get('/imports').status_code==200
        assert 'Patient Graph' in client.get('/imports-assets/app.js').text
        assert client.get('/api/v1/imports/unknown/jobs').status_code==422
        assert client.put('/api/v1/imports/context/uploads/a.json',content=json.dumps(context_file())).status_code==200
        assert client.post('/api/v1/imports/context/jobs',json={'mode':'commit'}).status_code==422
        response=client.post('/api/v1/imports/context/jobs',json={'mode':'preview'})
        assert response.status_code==202
        jid=response.json()['job_id']
        import time
        for _ in range(100):
            job=client.get('/api/v1/imports/context/jobs/'+jid).json()
            if job['status']=='completed':break
            time.sleep(.01)
        assert job['completed']==1
        assert client.get(f'/api/v1/imports/context/jobs/{jid}/items/-1/preview').status_code==404
        assert client.get(f'/api/v1/imports/context/jobs/{jid}/report?kind=csv').content.startswith(b'\xef\xbb\xbf')
        assert not container.patient_repository._facts
    m.db.close()


class Result:
    def __init__(self,rows=()):self.rows=list(rows)
    async def data(self):return self.rows
    async def single(self):return self.rows[0] if self.rows else None
    async def consume(self):return None


class Transaction:
    def __init__(self,driver,state):self.driver,self.state=driver,state
    async def run(self,query,**p):
        if query.startswith('MATCH (i:ContextImport'):
            return Result([{'key':p['key']}] if p['key'] in self.state['markers'] else [])
        if query.startswith('UNWIND $ids'):
            return Result([{'t':self.state['turns'][i]} for i in p['ids'] if i in self.state['turns']])
        if 'MERGE (s:Session' in query:
            self.state['turns'][p['message_id']]={**p,'id':p['message_id']};return Result()
        if 'MERGE (p:Patient' in query:
            if self.driver.fail:raise RuntimeError('injected transaction failure after history')
            self.state['facts'][p['statement_id']]=p;return Result([{'id':p['statement_id']}])
        if 'MERGE (i:ContextImport' in query:
            self.state['markers'].add(p['key']);return Result()
        raise AssertionError(query)


class Session:
    def __init__(self,driver):self.driver=driver
    async def __aenter__(self):return self
    async def __aexit__(self,*args):return False
    async def execute_read(self,fn):return await fn(Transaction(self.driver,self.driver.state))
    async def execute_write(self,fn):
        state=copy.deepcopy(self.driver.state)
        result=await fn(Transaction(self.driver,state))
        self.driver.state=state
        return result


class Driver:
    def __init__(self):self.state={'turns':{},'facts':{},'markers':set()};self.fail=False
    def session(self,**kwargs):return Session(self)


@pytest.mark.asyncio
async def test_context_neo4j_batch_binds_existing_repositories_to_one_transaction(tmp_path):
    container=context_container();driver=Driver();container.driver=driver
    embedding=container.history_repository.embedding_service
    container.history_repository=Neo4jHistoryRepository(driver,embedding_service=embedding)
    container.patient_repository=Neo4jPatientRepository(driver,embedding_service=embedding)
    container.settings.graph_backend='neo4j'
    m=BatchManager('context',ContextAdapter(lambda:container),tmp_path/'in',tmp_path/'out')
    save(m,'a.json',context_file());preview=await finish(m)
    driver.fail=True
    bad=await finish(m,mode='commit',previous_job_id=preview['job_id'],confirmed=True)
    assert bad['failed']==1 and not driver.state['turns'] and not driver.state['facts']
    driver.fail=False
    good=await finish(m,mode='retry',previous_job_id=bad['job_id'],confirmed=True)
    assert good['completed']==1 and len(driver.state['turns'])==len(driver.state['facts'])==1
    assert json.loads(next(iter(driver.state['facts'].values()))['attributes_json'])['confirmation_status']=='user_confirmed'
    again=await finish(m,mode='commit',previous_job_id=preview['job_id'],confirmed=True)
    assert again['skipped']==1
    await m.close()
