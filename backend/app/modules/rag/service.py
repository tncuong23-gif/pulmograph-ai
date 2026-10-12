import logging
from datetime import datetime,timezone
from threading import RLock
from uuid import uuid4
from .core import Input,build_records,digest,point_id,validate_refs
from .chunking import profile
log=logging.getLogger(__name__)
class Service:
    def __init__(self,store,encoder,config,mode):
        self.store=store;self.encoder=encoder;self.config=config;self.mode=mode;self.lock=RLock()
    def validate(self,raw):return validate_refs(Input.model_validate(raw))
    def chunking_profile(self):return profile(self.encoder,self.config)
    def document_status(self,row):
        return {**row,'needs_reindex':row.get('chunking')!=self.chunking_profile() or row.get('encoder')!=self.encoder.fingerprint}
    def import_data(self,raw,dry_run=False,force=False):
        data=Input.model_validate(raw);report=validate_refs(data)
        if not report['valid']:return {**report,'ok':False,'status':'invalid'}
        chunking=self.chunking_profile()
        normalized=data.model_dump()
        fingerprint=digest({'input':normalized,'encoder':self.encoder.fingerprint,'chunking':chunking})
        with self.lock:
            old=self.store.get(data.document.document_id)
            if old and old['fingerprint']==fingerprint and not force:
                warnings=list(report['warnings'])
                if not dry_run:
                    try:self.store.cleanup(old['document_id'],old['active_revision'])
                    except Exception:log.exception('Cleanup failed');warnings.append('Dọn phiên bản cũ thất bại; import lại để thử tiếp.')
                return {**report,'warnings':warnings,'ok':True,'status':'dry_run' if dry_run else 'skipped',
                        'document_id':data.document.document_id,'chunks':old['chunks'],'propositions':old['propositions'],'chunking':chunking,'chunking_summary':old.get('chunking_summary',{}),
                        'actions':{'insert':0,'update':0,'skip':old['chunks']+old['propositions'],'delete':0}}
            rows=build_records(data,self.encoder,self.config)
            previous={r['logical_id']:r for r in self.store.records(old['active_revision'])} if old else {}
            current={r['logical_id']:r for r in rows}
            actions={'insert':sum(k not in previous for k in current),
                'update':sum(k in previous and (current[k]['content_hash']!=previous[k]['content_hash'] or old['encoder']!=self.encoder.fingerprint or force) for k in current),
                'skip':sum(k in previous and current[k]['content_hash']==previous[k]['content_hash'] and old['encoder']==self.encoder.fingerprint and not force for k in current),
                'delete':len(previous.keys()-current.keys())}
            counts={k:sum(r['kind']==kind for r in rows) for k,kind in [('chunks','chunk'),('propositions','proposition')]}
            summary={reason:sum(r.get('boundary_reason')==reason for r in rows if r['kind']=='chunk') for reason in ['semantic','token_limit','section_end']}
            result={**report,'ok':True,'document_id':data.document.document_id,**counts,'actions':actions,
                    'status':'dry_run' if dry_run else 'completed','encoder':self.encoder.fingerprint,'chunking':chunking,'chunking_summary':summary,
                    'preview':[{k:v for k,v in r.items() if k!='embedding_text'} for r in rows[:3]]}
            if dry_run:return result
            revision=str(uuid4())
            # Independent snapshots: changed imports regenerate all vectors, then activate once.
            for i in range(0,len(rows),32):
                vectors=self.encoder.encode([r['embedding_text'] for r in rows[i:i+32]])
                for r,vector in zip(rows[i:i+32],vectors):r.update(vector=vector,revision=revision,point_id=point_id(revision,r['logical_id']))
            meta={'document_id':data.document.document_id,'title':data.document.title,'active_revision':revision,
                  'fingerprint':fingerprint,'encoder':self.encoder.fingerprint,'chunking':chunking,'chunking_summary':summary,'updated_at':datetime.now(timezone.utc).isoformat(),**counts,'source_counts':report['source']}
            self.store.stage(meta,normalized,rows);self.store.activate(meta)
            try:self.store.cleanup(meta['document_id'],revision)
            except Exception:log.exception('Cleanup failed');result['warnings'].append('Bản mới đã hoạt động; chưa dọn hết bản cũ. Import lại để thử dọn.')
            result['vectors_written']=len(rows);return result
    def search(self,query,kind,filters,top_k):
        with self.lock:
            docs=[d for d in self.store.documents() if not filters.get('document_id') or d['document_id']==filters['document_id']]
            if any(d['encoder']!=self.encoder.fingerprint for d in docs):raise ValueError('Embedding đã đổi. Reindex tài liệu trước khi tìm kiếm.')
            if self.encoder.count('query: '+query)>self.encoder.max_length:raise ValueError('Câu truy vấn quá dài.')
            vector=self.encoder.encode([query],query=True)[0]
            hits=self.store.search(vector,[d['active_revision'] for d in docs],kind,filters,top_k)
            return {'mode':self.mode,'search_type':'lexical_demo' if self.mode=='demo' else 'semantic','query':query,
                    'chunking':self.chunking_profile(),'reindex_required':[d['document_id'] for d in docs if self.document_status(d)['needs_reindex']],
                    'results':[{k:v for k,v in hit.items() if k not in ('vector','embedding_text')} for hit in hits]}
    def delete(self,doc_id):
        with self.lock:self.store.deactivate(doc_id);self.store.cleanup(doc_id);return {'ok':True,'document_id':doc_id}
