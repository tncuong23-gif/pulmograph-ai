import json,logging,os
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock
from typing import Literal
from dotenv import load_dotenv
from fastapi import FastAPI,HTTPException,Query,Request
from fastapi.responses import FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,ConfigDict,Field,ValidationError
from starlette.concurrency import run_in_threadpool
from .core import ChunkConfig,DemoEncoder,E5Encoder
from .storage import DemoStore,LiveStore,FILTER_FIELDS
from .service import Service
from .batch import BatchImporter,BatchBusy
ROOT=Path(__file__).resolve().parent
DATA_ROOT=Path(__file__).resolve().parents[3] / 'data'
log=logging.getLogger(__name__)
class SearchRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    query:str=Field(min_length=1,max_length=4000)
    kind:Literal['chunk','proposition','all']='chunk'
    top_k:int=Field(default=5,ge=1,le=50)
    filters:dict[str,str]=Field(default_factory=dict)
class BatchFile(BaseModel):
    model_config=ConfigDict(extra='forbid')
    filename:str=Field(min_length=1,max_length=1024)
    upload_error:str|None=Field(default=None,max_length=4000)
class BatchRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    source:Literal['directory','files']='directory'
    files:list[BatchFile]=Field(default_factory=list,max_length=10000)
    mode:Literal['commit','dry_run','validate']='commit'
@asynccontextmanager
async def lifespan(app):
    owned = app.state.service is None
    if owned:
        mode=os.getenv('RAG_MODE','live')
        if mode not in ('demo','live'):raise ValueError('RAG_MODE phải là demo hoặc live.')
        config=ChunkConfig(target=int(os.getenv('RAG_CHUNK_TOKENS','450')),overlap=int(os.getenv('RAG_CHUNK_OVERLAP','80')),
            method=os.getenv('RAG_CHUNK_METHOD','semantic'),semantic_percentile=float(os.getenv('RAG_SEMANTIC_PERCENTILE','90')),
            semantic_min_distance=float(os.getenv('RAG_SEMANTIC_MIN_DISTANCE','0.05')),semantic_min_tokens=int(os.getenv('RAG_SEMANTIC_MIN_TOKENS','80')),
            semantic_window=int(os.getenv('RAG_SEMANTIC_WINDOW','2')))
        if mode=='demo':
            encoder=DemoEncoder();store=DemoStore(os.getenv('RAG_DEMO_DB',str(DATA_ROOT/'rag-demo.sqlite3')))
        else:
            encoder=E5Encoder(os.getenv('RAG_EMBEDDING_MODEL','intfloat/multilingual-e5-base'),os.getenv('RAG_EMBEDDING_REVISION','d13f1b27baf31030b7fd040960d60d909913633f'),os.getenv('RAG_EMBEDDING_DEVICE','cpu'))
            store=LiveStore(os.getenv('RAG_MONGO_URI','mongodb://localhost:27017'),os.getenv('RAG_MONGO_DB','medical_rag'),os.getenv('RAG_QDRANT_URL','http://localhost:6333'),os.getenv('RAG_QDRANT_API_KEY'),encoder)
        app.state.service=Service(store,encoder,config,mode)
    try:
        yield
    finally:
        if app.state.batch is not None:
            await run_in_threadpool(app.state.batch.close)
            app.state.batch=None
        app.state.service.store.close()
        if owned:
            app.state.service = None
def create_app(service=None,batch_input_dir=None,batch_report_dir=None):
    app=FastAPI(title='Medical RAG Import',version='1.0.1',lifespan=lifespan);app.state.service=service
    app.state.batch=None
    batch_lock=Lock()
    def batch():
        with batch_lock:
            if app.state.batch is None:
                app.state.batch=BatchImporter(app.state.service,batch_input_dir or DATA_ROOT/'import/rag',batch_report_dir or DATA_ROOT/'import_reports/rag')
            return app.state.batch
    app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')
    @app.exception_handler(ValidationError)
    async def validation_error(request,exc):return JSONResponse(status_code=422,content={'detail':exc.errors(include_url=False,include_context=False,include_input=False)})
    @app.exception_handler(ValueError)
    async def value_error(request,exc):return JSONResponse(status_code=422,content={'detail':str(exc)})
    @app.exception_handler(BatchBusy)
    async def batch_busy(request,exc):return JSONResponse(status_code=409,content={'detail':str(exc)})
    @app.exception_handler(Exception)
    async def backend_error(request,exc):
        log.exception('Backend error');return JSONResponse(status_code=503,content={'detail':'Thao tác thất bại. Kiểm tra log server/kết nối cơ sở dữ liệu rồi thử lại.'})
    async def raw_body(request):
        raw=bytearray()
        async for part in request.stream():
            raw.extend(part)
            if len(raw)>8*1024*1024:raise HTTPException(413,'JSON tối đa 8 MiB.')
        return bytes(raw)
    async def body(request):
        try:return json.loads(await raw_body(request))
        except (ValueError,UnicodeError):raise HTTPException(400,'JSON không hợp lệ.')
    def svc():return app.state.service
    @app.get('/',include_in_schema=False)
    def home():return FileResponse(ROOT/'static/index.html')
    @app.get('/api/v1/rag/health')
    def health():
        s=svc()
        with s.lock:return {'ok':True,'version':'1.0.1','mode':s.mode,'encoder':s.encoder.fingerprint,'chunking':s.chunking_profile(),**s.store.health()}
    @app.post('/api/v1/rag/validate')
    async def validate(request:Request):return await run_in_threadpool(svc().validate,await body(request))
    @app.post('/api/v1/rag/import-json')
    async def import_json(request:Request,mode:Literal['commit','dry_run']='commit'):
        result=await run_in_threadpool(svc().import_data,await body(request),mode=='dry_run')
        return result if result['ok'] else JSONResponse(status_code=422,content=result)
    @app.put('/api/v1/rag/batch/uploads/{filename}')
    async def batch_upload(filename:str,request:Request):
        return await run_in_threadpool(batch().save_upload,filename,await raw_body(request))
    @app.post('/api/v1/rag/batch/jobs',status_code=202)
    def batch_start(payload:BatchRequest):
        return batch().start(payload.source,[item.model_dump(exclude_none=True) for item in payload.files],payload.mode)
    @app.get('/api/v1/rag/batch/jobs')
    def batch_list(limit:int=Query(20,ge=1,le=100)):
        return batch().list(limit)
    def require_job(job_id):
        try:return batch().get(job_id)
        except KeyError:raise HTTPException(404,'Không tìm thấy tác vụ nạp RAG.')
    @app.get('/api/v1/rag/batch/jobs/{job_id}')
    def batch_progress(job_id:str):return require_job(job_id)
    @app.get('/api/v1/rag/batch/jobs/{job_id}/report')
    def batch_report(job_id:str,kind:Literal['json','csv','errors']='json'):
        require_job(job_id)
        path=batch().report(job_id,kind)
        return FileResponse(path,media_type='application/json' if kind=='json' else 'text/csv',filename='rag-'+path.name)
    @app.get('/api/v1/rag/documents')
    def documents(offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=200)):
        s=svc()
        with s.lock:
            rows=s.store.documents();return {'total':len(rows),'items':[s.document_status(row) for row in rows[offset:offset+limit]]}
    @app.get('/api/v1/rag/stats')
    def stats():
        s=svc()
        with s.lock:
            rows=s.store.documents();return {'mode':s.mode,'chunking':s.chunking_profile(),'needs_reindex':sum(s.document_status(d)['needs_reindex'] for d in rows),
                'documents':len(rows),'chunks':sum(d['chunks'] for d in rows),'propositions':sum(d['propositions'] for d in rows),'vectors':sum(d['chunks']+d['propositions'] for d in rows)}
    def require_doc(s,doc_id):
        row=s.store.get(doc_id)
        if not row:raise HTTPException(404,'Không tìm thấy tài liệu.')
        return row
    @app.get('/api/v1/rag/documents/{doc_id}')
    def document(doc_id:str):
        s=svc()
        with s.lock:return s.document_status(require_doc(s,doc_id))
    @app.get('/api/v1/rag/documents/{doc_id}/source')
    def source(doc_id:str):
        s=svc()
        with s.lock:return s.store.source(require_doc(s,doc_id)['active_revision'])
    @app.get('/api/v1/rag/documents/{doc_id}/chunks')
    def chunks(doc_id:str,offset:int=Query(0,ge=0),limit:int=Query(20,ge=1,le=200),sentence_id:str|None=None):
        s=svc()
        with s.lock:
            total,rows=s.store.chunk_page(require_doc(s,doc_id)['active_revision'],offset,limit,sentence_id)
            return {'total':total,'items':[{k:v for k,v in r.items() if k not in ('vector','embedding_text')} for r in rows]}
    @app.get('/api/v1/rag/documents/{doc_id}/evidence/{sentence_id}')
    def evidence(doc_id:str,sentence_id:str):
        s=svc()
        with s.lock:
            rev=require_doc(s,doc_id)['active_revision'];sentence=s.store.sentence(rev,sentence_id)
            if not sentence:raise HTTPException(404,'Không tìm thấy câu nguồn.')
            total,related=s.store.chunk_page(rev,0,200,sentence_id)
            return {**sentence,'chunk_ids':[r['chunk_id'] for r in related],'chunks_total':total}
    @app.delete('/api/v1/rag/documents/{doc_id}')
    def delete(doc_id:str):return svc().delete(doc_id)
    @app.post('/api/v1/rag/documents/{doc_id}/reindex')
    def reindex(doc_id:str):
        s=svc()
        with s.lock:return s.import_data(s.store.source(require_doc(s,doc_id)['active_revision']),force=True)
    @app.post('/api/v1/rag/search')
    def search(payload:SearchRequest):
        if not payload.query.strip():raise HTTPException(422,'Truy vấn không được trống.')
        unknown=set(payload.filters)-set(FILTER_FIELDS)
        if unknown:raise HTTPException(422,f'Filter không hỗ trợ: {sorted(unknown)}')
        return svc().search(payload.query,None if payload.kind=='all' else payload.kind,payload.filters,payload.top_k)
    return app
app=create_app()
