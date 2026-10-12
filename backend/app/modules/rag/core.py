"""Schema, references, embedding adapters and source-preserving chunking."""
import hashlib,json,math,re
from .chunking import ChunkConfig, profile, semantic_ranges, token_ranges
from typing import Annotated,Literal
from uuid import UUID,uuid5
from pydantic import BaseModel,ConfigDict,Field,StringConstraints,field_validator
NonEmpty=Annotated[str,StringConstraints(strip_whitespace=True,min_length=1)]
SourceText=Annotated[str,StringConstraints(min_length=1,pattern=r'\S')]
class Model(BaseModel):
    model_config=ConfigDict(extra='allow',strict=True)
class Sentence(Model):
    sentence_id:NonEmpty
    text:SourceText
class Paragraph(Model):
    paragraph_id:NonEmpty
    sentences:list[Sentence]
class Section(Model):
    section_id:NonEmpty
    title:str
    paragraphs:list[Paragraph]
class Document(Model):
    document_id:NonEmpty
    title:NonEmpty
    document_type:NonEmpty='unknown'
    language:NonEmpty='und'
    sections:list[Section]

    @field_validator('document_type','language',mode='before')
    @classmethod
    def normalize_optional_metadata(cls,value,info):
        if value is None or (isinstance(value,str) and not value.strip()):
            return 'unknown' if info.field_name=='document_type' else 'und'
        return value
class Entity(Model):
    id:NonEmpty
    type:NonEmpty
    canonical_name:NonEmpty
class Evidence(Model):
    sentence_id:NonEmpty
class Proposition(Model):
    id:NonEmpty
    text:SourceText
    evidence:list[Evidence]=Field(min_length=1)
class Relation(Model):
    id:NonEmpty
    type:NonEmpty
    source:NonEmpty
    target:NonEmpty
    proposition_ids:list[NonEmpty]
class Input(Model):
    schema_version:Literal['1.0']
    document:Document
    entities:list[Entity]=Field(default_factory=list)
    relations:list[Relation]=Field(default_factory=list)
    propositions:list[Proposition]=Field(default_factory=list)

def digest(obj):
    return hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def validate_refs(data):
    errors,warnings,seen=[],[],{data.document.document_id}
    if data.document.document_type=='unknown':
        warnings.append('document.document_type chưa được cung cấp; dùng unknown (chưa xác định loại tài liệu).')
    if data.document.language=='und':
        warnings.append('document.language chưa được cung cấp; dùng und (chưa xác định ngôn ngữ).')
    groups={'sections':[],'paragraphs':[],'sentences':[],'entities':data.entities,'relations':data.relations,'propositions':data.propositions}
    for s in data.document.sections:
        groups['sections'].append(s)
        if not s.paragraphs:warnings.append(f'Mục rỗng: {s.section_id}')
        for p in s.paragraphs:
            groups['paragraphs'].append(p);groups['sentences'].extend(p.sentences)
    keys={'sections':'section_id','paragraphs':'paragraph_id','sentences':'sentence_id'};ids={}
    for group,items in groups.items():
        ids[group]=set()
        for item in items:
            key=getattr(item,keys.get(group,'id'))
            if key in seen:errors.append(f'ID trùng: {key}')
            seen.add(key);ids[group].add(key)
    for p in data.propositions:
        for e in p.evidence:
            if e.sentence_id not in ids['sentences']:errors.append(f'{p.id}: evidence không tồn tại: {e.sentence_id}')
    for r in data.relations:
        for e in [r.source,r.target]:
            if e not in ids['entities']:errors.append(f'{r.id}: entity không tồn tại: {e}')
        for p in r.proposition_ids:
            if p not in ids['propositions']:errors.append(f'{r.id}: proposition không tồn tại: {p}')
    if not groups['sentences']:errors.append('Tài liệu không có nội dung câu nguồn.')
    return {'valid':not errors,'errors':errors,'warnings':warnings,'source':{k:len(v) for k,v in groups.items()}}

class DemoEncoder:
    """Lexical hashing only, not a semantic model."""
    fingerprint='demo-lexical-sha256-v1';dimension=512;max_length=512;supports_semantic=False
    def offsets(self,text):return [(m.start(),m.end()) for m in re.finditer(r'\S+',text)]
    def count(self,text):return len(self.offsets(text))+2
    def encode(self,texts,query=False):
        results=[]
        for text in texts:
            vector=[0.0]*self.dimension
            for term in re.findall(r'\w+',text.lower()):
                index=int(hashlib.sha256(term.encode()).hexdigest()[:8],16)%self.dimension
                vector[index]+=1
            norm=math.sqrt(sum(x*x for x in vector)) or 1
            results.append([x/norm for x in vector])
        return results
class E5Encoder:
    supports_semantic=True
    def __init__(self,model,revision,device):
        from app.services.encoders import get_encoder
        self.model=get_encoder(model,revision=revision,device=device)
        self.tokenizer=self.model.tokenizer
        if not self.tokenizer.is_fast:raise ValueError('Cần fast tokenizer để giữ offsets.')
        self.dimension=self.model.get_sentence_embedding_dimension();self.max_length=min(self.model.max_seq_length,512)
        self.fingerprint=f'e5:{model}@{revision}:{self.dimension}:prefix-v1'
    def offsets(self,text):return self.tokenizer(text,add_special_tokens=False,return_offsets_mapping=True)['offset_mapping']
    def count(self,text):return len(self.tokenizer(text,add_special_tokens=True)['input_ids'])
    def encode(self,texts,query=False):
        prefix='query: ' if query else 'passage: '
        if any(self.count(prefix+t)>self.max_length for t in texts):raise ValueError('Vượt giới hạn embedding; không tự cắt nội dung.')
        return self.model.encode([prefix+t for t in texts],batch_size=16,normalize_embeddings=True,show_progress_bar=False).tolist()
NAMESPACE=UUID('dc497c0a-6c41-4f46-aeb4-f6c401d65a17')
def point_id(revision,logical):return str(uuid5(NAMESPACE,revision+':'+logical))

def build_records(data,encoder,config):
    if not 0<=config.overlap<config.target:raise ValueError('Overlap phải nhỏ hơn chunk size.')
    doc=data.document;records=[];sentence_props={};prop_relations={}
    method=profile(encoder,config)['method']
    for p in data.propositions:
        for e in p.evidence:sentence_props.setdefault(e.sentence_id,[]).append(p.id)
    for r in data.relations:
        for pid in r.proposition_ids:prop_relations.setdefault(pid,[]).append(r)
    base={'document_id':doc.document_id,'document_title':doc.title,'document_type':doc.document_type,'language':doc.language}
    def add(kind,logical,text,embedding_text,**meta):
        row={**base,'kind':kind,'logical_id':logical,'text':text,'embedding_text':embedding_text,**meta}
        row['token_count']=encoder.count('passage: '+embedding_text)
        if row['token_count']>encoder.max_length:raise ValueError(f'{logical}: vượt giới hạn embedding.')
        row['content_hash']=digest(row);records.append(row)
    index=0
    for section in doc.sections:
        pieces=[];spans=[];cursor=0
        for paragraph in section.paragraphs:
            for s in paragraph.sentences:
                if pieces:cursor+=1
                pieces.append(s.text);spans.append((cursor,cursor+len(s.text),s.sentence_id,paragraph.paragraph_id));cursor+=len(s.text)
        full='\n'.join(pieces)
        if not full:continue
        header=f'Tài liệu: {doc.title}\nMục: {section.title}\n\n'
        if encoder.count('passage: '+header)>=encoder.max_length-32:raise ValueError(f'Tiêu đề quá dài: {section.section_id}')
        ranges=semantic_ranges(full,spans,header,encoder,config) if method=='semantic' else token_ranges(full,header,encoder,config)
        for boundary in ranges:
            a,b=boundary['start'],boundary['end']
            evidence=[{'sentence_id':sid,'paragraph_id':pid,'start_char':max(a,sa)-sa,'end_char':min(b,sb)-sa}
                      for sa,sb,sid,pid in spans if sa<b and sb>a]
            sids=list(dict.fromkeys(e['sentence_id'] for e in evidence));pids=sorted({p for sid in sids for p in sentence_props.get(sid,[])})
            index+=1;logical=f'{doc.document_id}_CHUNK_{index:06d}'
            add('chunk',logical,full[a:b],header+full[a:b],chunk_id=logical,chunk_index=index,
                section_id=section.section_id,section_title=section.title,sentence_ids=sids,
                paragraph_ids=list(dict.fromkeys(e['paragraph_id'] for e in evidence)),proposition_ids=pids,source_spans=evidence,
                chunk_method=method,boundary_reason=boundary['reason'],boundary_distance=boundary['distance'],semantic_threshold=boundary['threshold'])
    for p in data.propositions:
        rels=prop_relations.get(p.id,[])
        add('proposition',p.id,p.text,p.text,proposition_id=p.id,evidence_sentence_ids=list(dict.fromkeys(e.sentence_id for e in p.evidence)),
            entity_ids=sorted({e for r in rels for e in (r.source,r.target)}),relation_ids=[r.id for r in rels])
    if len({r['logical_id'] for r in records})!=len(records):raise ValueError('ID proposition trùng ID chunk được tạo.')
    return records
