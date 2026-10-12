"""Fake inference; real multipart transport, validation and SQLite persistence."""
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
import pytest
from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.clinical_routes import create_router
from app.services.modules import ModuleClient
from app.storage import ConversationStore
from clinical_service.app import create_app
from clinical_service.runtime import ClinicalRuntime


def png():
    out=BytesIO(); Image.new('RGB',(12,12)).save(out,format='PNG'); return out.getvalue()


def output(modality):
    return {'ok':True,'data':{'modality':modality,'top5':[{'rank':1,'label':'Viemphoi','calibrated_score':-1.2345}],
        'extracted_facts':{'entities':[]},'warnings':[]}}


class Runtime:
    def __init__(self): self.calls=[]; self.paths=[]
    def inventory(self): return []
    def analyze(self, **kw):
        self.calls.append(kw)
        if kw['image_path']:
            assert kw['image_path'].read_bytes()==png(); self.paths.append(kw['image_path'])
        return output('text_xray' if kw['text'] is not None and kw['image_path'] else 'text' if kw['text'] is not None else 'xray')


@pytest.mark.parametrize('kind',['text','txt','xray','text_xray','txt_xray'])
def test_adapter_modalities_temp_cleanup_and_original_text(kind):
    runtime=Runtime(); data={}; files={}
    if kind in {'text','text_xray'}: data['text']='Ho, không sốt.'
    if kind in {'txt','txt_xray'}: files['file']=('record.txt','\ufeffHo, không sốt.'.encode(),'text/plain')
    if 'xray' in kind: files['image']=('scan.png',png(),'image/png')
    if '_' in kind:data['same_case']='true'
    with TestClient(create_app(runtime)) as client:
        response=client.post('/api/v1/analyze',data=data,files=files)
    assert response.status_code==200, response.text
    assert response.json()['data']['modality']==kind.replace('txt','text')
    assert len(runtime.calls)==1
    assert all(not p.exists() for p in runtime.paths)
    if kind!='xray': assert runtime.calls[0]['text']=='Ho, không sốt.'


@pytest.mark.parametrize('data,files,status',[
    ({},{},422),
    ({'text':'ho'},{'image':('x.png',png(),'image/png')},422),
    ({},{'image':('x.png',b'not image','image/png')},422),
    ({},{'file':('r.txt',b'\xff','text/plain')},422),
    ({},{'file':('r.txt',b'','text/plain')},422),
    ({},{'file':('r.pdf',b'fake','application/pdf')},415),
    ({'text':'ho'},{'file':('r.txt',b'txt','text/plain')},422),
    ({'text':'x'*100001},{},422),
])
def test_adapter_rejects_inputs_before_inference(data,files,status):
    runtime=Runtime()
    with TestClient(create_app(runtime)) as client:
        assert client.post('/api/v1/analyze',data=data,files=files).status_code==status
    assert not runtime.calls


def test_missing_weights_explicit_and_no_fallback(monkeypatch):
    runtime=ClinicalRuntime()
    monkeypatch.setattr(runtime,'inventory',lambda:['ie/joint/final_model/model.safetensors','ie/simplifier/final_model/model.safetensors'])
    assert set(runtime.inventory())=={'ie/joint/final_model/model.safetensors','ie/simplifier/final_model/model.safetensors'}
    with TestClient(create_app(runtime)) as client:
        health=client.get('/health')
        assert health.status_code==503
        assert health.json()['capabilities']=={'text':False,'text_xray':False,'xray':True}
        r=client.post('/api/v1/analyze-text',json={'text':'Ho nhiều'})
        assert r.status_code==503
        assert 'model.safetensors' in r.json()['detail']
    assert runtime.assistant is None


@pytest.mark.asyncio
async def test_real_module_client_contract_for_three_modalities_and_legacy_text():
    runtime=Runtime(); app=create_app(runtime)
    async with app.router.lifespan_context(app):
        modules=ModuleClient(context_url='http://context', clinical_url='http://clinical',
            kg_url='http://kg',rag_url='http://rag',timeout=1,clinical_timeout=5,embedded_apps={'http://clinical':app})
        for text,image,same,expected in [('Ho',None,False,'text'),(None,png(),False,'xray'),('Ho',png(),True,'text_xray')]:
            result=await modules.clinical_analyze(text=text,image=image,same_case=same)
            assert result['data']['modality']==expected
        await modules.clinical_query('Ho')
        assert runtime.calls[-1]['symptom_query'] is True


@pytest.fixture
def backend(tmp_path):
    settings=SimpleNamespace(upload_dir=tmp_path/'uploads',max_upload_bytes=20*1024*1024)
    settings.upload_dir.mkdir()
    app=FastAPI();app.include_router(create_router(settings))
    app.state.store=ConversationStore(tmp_path/'db.sqlite')
    app.state.modules=AsyncMock()
    app.state.llm=AsyncMock()
    app.state.llm.generate.return_value='Xếp hạng hỗ trợ: điểm -1.2345. [1]'
    async def analyze(**kw):return output('text_xray' if kw['text'] is not None and kw['image'] is not None else 'text' if kw['text'] is not None else 'xray')
    app.state.modules.clinical_analyze.side_effect=analyze
    with TestClient(app) as client:yield client,app


@pytest.mark.parametrize('kind',['text','txt','xray','text_xray','txt_xray'])
def test_backend_jobs_history_idempotency_and_conflict(backend,kind):
    client,app=backend; data={'conversationId':'c','clientId':'m'};files={}
    if kind in {'text','text_xray'}:data['text']='Ho'
    if kind in {'txt','txt_xray'}:files['file']=('r.txt',b'Ho','text/plain')
    if 'xray' in kind:files['image']=('x.png',png(),'image/png')
    r=client.post('/api/v1/clinical/analyze',data=data,files=files)
    assert r.status_code==202,r.text
    job_id=r.json()['id']; result=client.get('/api/v1/clinical/jobs/'+job_id).json()
    assert result['status']=='processed',result
    assert result['result']['data']['modality']==kind.replace('txt','text')
    assert '-1.2345' in result['analysisAnswer']
    second=client.post('/api/v1/clinical/analyze',data=data,files=files)
    assert second.json()['status']=='processed'
    app.state.modules.clinical_analyze.assert_awaited_once()
    app.state.modules.context_resolve.assert_not_called()
    app.state.modules.clinical_query.assert_not_called()
    store=ConversationStore(app.state.store.path)
    messages=store.get_conversation('c')['messages']
    assert len(messages)==2
    assert messages[1]['metadata']['route']=='CLINICAL_ANALYSIS'
    assert not messages[0]['attachments']
    changed=client.post('/api/v1/clinical/analyze',data={'conversationId':'c','clientId':'m','text':'new content'})
    assert changed.status_code==409


def test_failed_job_retries_same_id_and_does_not_save_false_answer(backend):
    client,app=backend
    app.state.modules.clinical_analyze.side_effect=httpx.ReadTimeout('timeout')
    data={'conversationId':'c','clientId':'m','text':'Ho'}
    job=client.post('/api/v1/clinical/analyze',data=data).json()['id']
    result=client.get('/api/v1/clinical/jobs/'+job).json()
    assert result['status']=='error' and 'thời gian' in result['error']
    assert app.state.store.get_conversation('c') is None
    app.state.modules.clinical_analyze.side_effect=None
    app.state.modules.clinical_analyze.return_value=output('text')
    assert client.post('/api/v1/clinical/analyze',data=data).json()['id']==job
    assert client.get('/api/v1/clinical/jobs/'+job).json()['status']=='processed'
    assert len(app.state.store.get_conversation('c')['messages'])==2


def test_backend_infers_combined_without_confirmation(backend):
    client,app=backend
    r=client.post('/api/v1/clinical/analyze',data={'conversationId':'c','clientId':'m','text':'Ho'},files={'image':('x.png',png(),'image/png')})
    assert r.status_code==202, r.text
    assert r.json()['modality']=='text_xray'
    app.state.modules.clinical_analyze.assert_awaited_once()
    assert app.state.modules.clinical_analyze.await_args.kwargs['same_case'] is True


@pytest.mark.asyncio
async def test_adapter_busy_does_not_start_second_inference():
    runtime=Runtime();app=create_app(runtime)
    async with app.router.lifespan_context(app):
        await app.state.gate.acquire()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://clinical') as c:
            response=await c.post('/api/v1/analyze',data={'text':'Ho'})
        app.state.gate.release()
        assert response.status_code==409
        assert not runtime.calls


def test_runtime_routes_image_without_loading_nlp_and_combined_with_image(monkeypatch,tmp_path):
    import sys
    from unittest.mock import Mock
    monkeypatch.setitem(sys.modules,'clinical_ie.api',SimpleNamespace(RESEARCH_DISCLAIMER='Research only'))
    runtime=ClinicalRuntime()
    classifier=Mock()
    classifier.predict.return_value=SimpleNamespace(status='fallback_image_only',top5=[],all_scores={},all_probabilities={},warnings=[])
    assistant=Mock();assistant.analyze_text.return_value.to_dict.return_value={'top5':[]}
    runtime._classifier=Mock(return_value=classifier)
    runtime._assistant=Mock(return_value=assistant)
    path=tmp_path/'x.png';path.write_bytes(png())
    image=runtime.analyze(image_path=path,document_id='d')['data']
    runtime._assistant.assert_not_called()
    classifier.predict.assert_called_once_with(image_path=path)
    assert image['graph'] is None and image['extracted_facts']['entities']==[]
    combined=runtime.analyze(text='Ho',image_path=path,document_id='d')['data']
    assistant.analyze_text.assert_called_once_with('Ho',document_id='d',namespace='clinical_case',image_path=path)
    assert combined['modality']=='text_xray'


def test_wrong_modality_from_upstream_is_failed_not_saved(backend):
    client,app=backend
    app.state.modules.clinical_analyze.side_effect=None
    app.state.modules.clinical_analyze.return_value=output('xray')
    r=client.post('/api/v1/clinical/analyze',data={'conversationId':'c','clientId':'m','text':'Ho'})
    assert client.get('/api/v1/clinical/jobs/'+r.json()['id']).json()['status']=='error'
    assert app.state.store.get_conversation('c') is None


@pytest.mark.parametrize('with_image',[False,True])
def test_llm_failure_keeps_clinical_result_and_retry_does_not_repeat_inference(backend,with_image):
    import json
    from pathlib import Path
    client,app=backend
    app.state.llm.generate.side_effect=RuntimeError('Ollama unavailable')
    data={'conversationId':'cache-case','clientId':'msg','text':'Ho'}
    files={'image':('scan.png',png(),'image/png')} if with_image else {}
    if with_image:app.state.modules.clinical_analyze.return_value=output('text_xray')
    response=client.post('/api/v1/clinical/analyze',data=data,files=files)
    job=response.json()['id']
    assert client.get('/api/v1/clinical/jobs/'+job).json()['status']=='error'
    assert app.state.store.get_attachment(job)['analysis_json']
    if with_image:
        payload=json.loads(app.state.store.get_attachment(job)['clinical_input'])
        Path(payload['image_path']).unlink()
    app.state.llm.generate.side_effect=None
    response=client.post('/api/v1/clinical/analyze',data=data,files=files)
    done=client.get('/api/v1/clinical/jobs/'+job).json()
    assert done['status']=='processed' and done['sources'][0]['kind']=='model'
    app.state.modules.clinical_analyze.assert_awaited_once()
    assert app.state.llm.generate.await_count==2
    assert app.state.store.get_conversation('cache-case')['messages'][1]['metadata']['sources']==done['sources']
