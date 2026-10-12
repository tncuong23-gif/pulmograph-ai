"""SQLite demo and MongoDB/Qdrant adapters, with isolated staged snapshots."""
import json,sqlite3
from pathlib import Path
COLLECTIONS={'chunk':'medical_rag_chunks','proposition':'medical_rag_propositions'}
FILTER_FIELDS=['document_id','section_id','language','document_type','entity_ids','relation_ids','sentence_ids','evidence_sentence_ids','proposition_id']
def matches(row,filters):
    return all(value in row.get(key,[]) if isinstance(row.get(key),list) else row.get(key)==value for key,value in filters.items() if value is not None)
class DemoStore:
    def __init__(self,path):
        Path(path).parent.mkdir(parents=True,exist_ok=True);self.db=sqlite3.connect(path,check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sources(revision TEXT PRIMARY KEY,document_id TEXT,body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS records(revision TEXT,logical_id TEXT,document_id TEXT,kind TEXT,body TEXT NOT NULL,PRIMARY KEY(revision,logical_id));
        CREATE INDEX IF NOT EXISTS records_doc_kind ON records(document_id,kind);
        CREATE INDEX IF NOT EXISTS sources_doc ON sources(document_id);''')
    def documents(self):return [json.loads(r[0]) for r in self.db.execute('SELECT body FROM documents ORDER BY id')]
    def get(self,doc_id):
        row=self.db.execute('SELECT body FROM documents WHERE id=?',(doc_id,)).fetchone();return json.loads(row[0]) if row else None
    def source(self,revision):
        row=self.db.execute('SELECT body FROM sources WHERE revision=?',(revision,)).fetchone();return json.loads(row[0]) if row else None
    def records(self,revision,kind=None):
        sql='SELECT body FROM records WHERE revision=?';params=[revision]
        if kind:sql+=' AND kind=?';params.append(kind)
        return [json.loads(r[0]) for r in self.db.execute(sql,params)]
    def stage(self,meta,source,records):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO sources VALUES(?,?,?)',(meta['active_revision'],meta['document_id'],json.dumps(source,ensure_ascii=False)))
            self.db.executemany('INSERT OR REPLACE INTO records VALUES(?,?,?,?,?)',[(meta['active_revision'],r['logical_id'],meta['document_id'],r['kind'],json.dumps(r,ensure_ascii=False)) for r in records])
    def activate(self,meta):
        with self.db:self.db.execute('INSERT OR REPLACE INTO documents VALUES(?,?)',(meta['document_id'],json.dumps(meta,ensure_ascii=False)))
    def cleanup(self,doc_id,keep=None):
        with self.db:
            for table in ['sources','records']:
                if keep:self.db.execute(f'DELETE FROM {table} WHERE document_id=? AND revision<>?',(doc_id,keep))
                else:self.db.execute(f'DELETE FROM {table} WHERE document_id=?',(doc_id,))
    def deactivate(self,doc_id):
        with self.db:self.db.execute('DELETE FROM documents WHERE id=?',(doc_id,))
    def search(self,vector,revisions,kind,filters,limit):
        rows=[]
        for rev in revisions:
            for r in self.records(rev,kind):
                if matches(r,filters):
                    score=sum(a*b for a,b in zip(vector,r['vector']))
                    if score>0:rows.append({**r,'score':score})
        return sorted(rows,key=lambda r:r['score'],reverse=True)[:limit]
    def chunk_page(self,revision,offset,limit,sentence_id=None):
        rows=sorted(self.records(revision,'chunk'),key=lambda r:r['chunk_index'])
        if sentence_id:rows=[r for r in rows if sentence_id in r['sentence_ids']]
        return len(rows),rows[offset:offset+limit]
    def sentence(self,revision,sentence_id):
        source=self.source(revision)
        if not source:return None
        for section in source['document']['sections']:
            for paragraph in section['paragraphs']:
                for sentence in paragraph['sentences']:
                    if sentence['sentence_id']==sentence_id:
                        return {'document_id':source['document']['document_id'],'section_id':section['section_id'],
                                'section_title':section['title'],'paragraph_id':paragraph['paragraph_id'],**sentence}
        return None
    def health(self):self.db.execute('SELECT 1');return {'sqlite':'ok','search':'lexical demo'}
    def close(self):self.db.close()

class LiveStore:
    def __init__(self,uri,db_name,qdrant_url,api_key,encoder):
        from pymongo import MongoClient
        from qdrant_client import QdrantClient,models
        self.models=models;self.mongo=MongoClient(uri,serverSelectionTimeoutMS=5000);self.db=self.mongo[db_name]
        self.q=QdrantClient(url=qdrant_url,api_key=api_key or None,timeout=60);self.ensure_indexes(encoder)
    def ensure_indexes(self,encoder):
        m=self.models
        self.db.rag_documents.create_index('document_id',unique=True)
        self.db.rag_sources.create_index('revision',unique=True);self.db.rag_sources.create_index('document_id')
        self.db.rag_sentences.create_index([('revision',1),('sentence_id',1)],unique=True)
        self.db.rag_sentences.create_index([('document_id',1),('revision',1)])
        for kind,name in COLLECTIONS.items():
            c=self.db[name];c.create_index([('revision',1),('logical_id',1)],unique=True);c.create_index([('document_id',1),('revision',1)])
            if kind=='chunk':c.create_index([('revision',1),('chunk_index',1)])
            fields=['section_id','sentence_ids','proposition_ids'] if kind=='chunk' else ['proposition_id','evidence_sentence_ids','entity_ids','relation_ids']
            for field in fields:c.create_index(field)
            if not self.q.collection_exists(name):self.q.create_collection(name,vectors_config=m.VectorParams(size=encoder.dimension,distance=m.Distance.COSINE))
            info=self.q.get_collection(name);vp=info.config.params.vectors
            if not isinstance(vp,m.VectorParams) or vp.size!=encoder.dimension or vp.distance!=m.Distance.COSINE:
                raise ValueError(f'Collection {name}: sai cấu hình vector; dùng collection mới.')
            for field in ['revision','document_id','language','document_type']+fields:
                if field not in info.payload_schema:self.q.create_payload_index(name,field_name=field,field_schema=m.PayloadSchemaType.KEYWORD,wait=True)
    def documents(self):return list(self.db.rag_documents.find({},{'_id':0}).sort('document_id',1))
    def get(self,doc_id):return self.db.rag_documents.find_one({'document_id':doc_id},{'_id':0})
    def source(self,revision):
        row=self.db.rag_sources.find_one({'revision':revision},{'_id':0});return row['source'] if row else None
    def records(self,revision,kind=None):
        rows=[]
        for k,name in COLLECTIONS.items():
            if not kind or k==kind:rows.extend(self.db[name].find({'revision':revision},{'_id':0}))
        return rows
    def stage(self,meta,source,records):
        from bson import BSON
        from pymongo import ReplaceOne
        m=self.models;row={'revision':meta['active_revision'],'document_id':meta['document_id'],'source':source}
        if len(BSON.encode(row))>15*1024*1024:raise ValueError('Source vượt giới hạn BSON; hãy tách tài liệu.')
        self.db.rag_sources.replace_one({'revision':row['revision']},row,upsert=True)
        sentences=[]
        for section in source['document']['sections']:
            for paragraph in section['paragraphs']:
                for sentence in paragraph['sentences']:
                    record={**sentence,'revision':row['revision'],'document_id':row['document_id'],'section_id':section['section_id'],'section_title':section['title'],'paragraph_id':paragraph['paragraph_id']}
                    sentences.append(ReplaceOne({'revision':row['revision'],'sentence_id':sentence['sentence_id']},record,upsert=True))
        if sentences:self.db.rag_sentences.bulk_write(sentences)
        for kind,name in COLLECTIONS.items():
            subset=[r for r in records if r['kind']==kind]
            for i in range(0,len(subset),64):
                batch=subset[i:i+64]
                self.db[name].bulk_write([ReplaceOne({'revision':r['revision'],'logical_id':r['logical_id']},{k:v for k,v in r.items() if k!='vector'},upsert=True) for r in batch])
                self.q.upsert(name,points=[m.PointStruct(id=r['point_id'],vector=r['vector'],payload={k:v for k,v in r.items() if k not in ('vector','embedding_text')}) for r in batch],wait=True)
    def activate(self,meta):self.db.rag_documents.replace_one({'document_id':meta['document_id']},meta,upsert=True)
    def cleanup(self,doc_id,keep=None):
        m=self.models;criteria={'document_id':doc_id}
        if keep:criteria['revision']={'$ne':keep}
        for name in COLLECTIONS.values():
            flt=m.Filter(must=[m.FieldCondition(key='document_id',match=m.MatchValue(value=doc_id))],must_not=[m.FieldCondition(key='revision',match=m.MatchValue(value=keep))] if keep else None)
            self.q.delete(name,points_selector=m.FilterSelector(filter=flt),wait=True);self.db[name].delete_many(criteria)
        self.db.rag_sources.delete_many(criteria);self.db.rag_sentences.delete_many(criteria)
    def deactivate(self,doc_id):self.db.rag_documents.delete_one({'document_id':doc_id})
    def search(self,vector,revisions,kind,filters,limit):
        if not revisions:return []
        m=self.models;conditions=[m.FieldCondition(key='revision',match=m.MatchAny(any=revisions))]
        conditions += [m.FieldCondition(key=k,match=m.MatchValue(value=v)) for k,v in filters.items() if v is not None]
        results=[]
        for k,name in COLLECTIONS.items():
            if kind and k!=kind:continue
            hits=self.q.query_points(name,query=vector,query_filter=m.Filter(must=conditions),limit=limit,with_payload=True).points
            results.extend({**hit.payload,'score':hit.score} for hit in hits)
        return sorted(results,key=lambda r:r['score'],reverse=True)[:limit]
    def chunk_page(self,revision,offset,limit,sentence_id=None):
        criteria={'revision':revision}
        if sentence_id:criteria['sentence_ids']=sentence_id
        c=self.db.medical_rag_chunks
        return c.count_documents(criteria),list(c.find(criteria,{'_id':0}).sort('chunk_index',1).skip(offset).limit(limit))
    def sentence(self,revision,sentence_id):return self.db.rag_sentences.find_one({'revision':revision,'sentence_id':sentence_id},{'_id':0})
    def health(self):self.mongo.admin.command('ping');self.q.get_collections();return {'mongodb':'ok','qdrant':'ok'}
    def close(self):self.mongo.close();self.q.close()
