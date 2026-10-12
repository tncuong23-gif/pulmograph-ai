"""Server-owned evidence selection and citation registry shared by every answer path."""
from __future__ import annotations
import copy
import json
import re
from dataclasses import dataclass

VERSION = 'numbered_evidence_v1'
# Conservative UTF-8 byte ceiling, not an exact count for the Ollama tokenizer.
MAX_BYTES = 18000
LABELS = {'Binhthuong':'Bình thường','Covid':'COVID-19','Hen':'Hen','Lao':'Lao','Phuphoi':'Phù phổi',
          'Suyhohap':'Suy hô hấp','Trandich':'Tràn dịch','Trankhi':'Tràn khí','Uphoi':'U phổi','Viemphoi':'Viêm phổi','Xepphoi':'Xẹp phổi'}
PRIVATE_KEYS = {'id','entity_id','subject_id','object_id','relation_id','document_id','doc_id','evidence_id','evidence_ids',
                'source_id','source_message_id','proposition_id','proposition_ids','original_fact','original_source_id','source_refs',
                'recorded_at','confirmed_at','assessment_id','snapshot_id','patient_id','model_versions','engine','filter_provenance'}


def clinical_fields(value):
    """Retain clinical attributes recursively; exclude identifiers and technical provenance."""
    if isinstance(value, list): return [clinical_fields(x) for x in value]
    if isinstance(value, dict):
        return {k:clinical_fields(v) for k,v in value.items() if k not in PRIVATE_KEYS and k not in {'vector','embedding_text','start','end','offset','segment_id','confidence'}}
    return value


def pick(value, keys):
    return {k:copy.deepcopy(value[k]) for k in keys if k in value}


def size(value):
    return len(json.dumps(value,ensure_ascii=False,default=str).encode('utf-8'))


@dataclass
class EvidencePack:
    payload: dict
    sources: list


class Registry:
    def __init__(self): self.rows=[]; self.keys={}
    def add(self, source, kind='document', module=None):
        if not isinstance(source,dict) or not isinstance(source.get('text'),str) or not source['text'].strip(): return None
        text=source['text'].strip()
        doc=source.get('doc_id') or source.get('document_id')
        key=(kind,doc,' '.join(text.split()))
        origin=pick(source,['doc_id','document_id','evidence_id','chunk_id','proposition_id','logical_id'])
        title=source.get('document_title') or source.get('title')
        if title and doc and str(doc) in str(title):title=str(title).replace(str(doc),'').strip(' -:;()') or None
        if key in self.keys:
            row=self.rows[self.keys[key]-1]
            if origin not in row['origins']:row['origins'].append(origin)
            if title:row['title']=title
            return row['number']
        number=len(self.rows)+1
        self.keys[key]=number
        self.rows.append({'number':number,'title':title or ('Kết quả mô hình Clinical IE' if kind=='model' else 'Tài liệu truy xuất'),
                          'section':source.get('section_title') or source.get('section') or '', 'text':text,
                          'kind':kind,'module':module,'origins':[origin]})
        return number
    def public(self):return [pick(row,['number','title','section','text','kind']) for row in self.rows]


def kg_context(result, registry):
    raw=result.get('llm_context') or {}
    facts=[]
    for fact in raw.get('facts',[]):
        if not isinstance(fact,dict):continue
        refs=[]
        for source in fact.get('evidence',[]):
            ref=registry.add(source,module='kg')
            if ref and ref not in refs:refs.append(ref)
        assertions=[]
        for assertion in fact.get('assertions',[]):
            assertion_refs=[]
            for source in fact.get('evidence',[]):
                if (source.get('doc_id') or source.get('document_id')) == assertion.get('document_id') and source.get('evidence_id') in (assertion.get('evidence_ids') or []):
                    ref=registry.add(source,module='kg')
                    if ref and ref not in assertion_refs:assertion_refs.append(ref)
            assertions.append({**pick(assertion,['properties','properties_valid']),'source_refs':assertion_refs})
        facts.append({'subject':pick(fact.get('subject') or {},['name','type']),
                      'predicate':fact.get('predicate'),'object':pick(fact.get('object') or {},['name','type']),
                      'assertions':assertions,
                      'source_refs':refs})
    context={'status':result.get('status'),'facts':facts,
             'chains':[{'fact_indices':g.get('fact_indices',[])} for g in raw.get('chains',[])],
             'paths':[{'nodes':[pick(n,['name','type']) for n in p.get('nodes',[])],
                       'fact_indices':p.get('fact_indices',[])} for p in raw.get('paths',[])],
             'interpretation':raw.get('interpretation',{}),'warnings':result.get('warnings',[])}
    comparison=raw.get('comparison')
    if comparison:
        entities=comparison.get('entities',[])
        positions={e.get('id'):i for i,e in enumerate(entities)}
        context['comparison']={**pick(comparison,['mode','notice','truncated','complete','criteria']),
            'entities':[pick(e,['name','type']) for e in entities],
            'rows':[{**pick(row,['criterion_label','predicate','direction','classification','label']),
                     'feature':pick(row.get('feature') or {},['name','type']),
                     'cells':[{'entity_index':positions.get(c.get('entity_id')),'status':c.get('status'),
                               'fact_indices':c.get('fact_indices',[])} for c in row.get('cells',[])]} for row in comparison.get('rows',[])]}
    groups=[g.get('fact_indices',[]) for g in context['chains']+context['paths']]
    if context.get('comparison'):
        groups += [cell.get('fact_indices',[]) for row in context['comparison']['rows'] for cell in row.get('cells',[])]
    if any(not isinstance(indices,list) or any(not isinstance(i,int) or isinstance(i,bool) or i<0 or i>=len(facts) for i in indices) for indices in groups):
        raise ValueError('KG trả tham chiếu facts không hợp lệ; không gửi chuỗi bị lỗi cho LLM.')
    return context


def clinical_context(result,registry):
    data=result.get('data',result) if isinstance(result,dict) else {}
    if not isinstance(data,dict):return {'status':'invalid_result'}
    top=[]
    for row in data.get('top5',[])[:5]:
        entry=pick(row,['rank','label','calibrated_score','decision_score','score'])
        entry['label']=LABELS.get(entry.get('label'),entry.get('label'))
        top.append(entry)
    explanation='Đầu ra hỗ trợ đánh giá của mô hình Clinical IE, không phải tài liệu y khoa hoặc chẩn đoán xác định. Điểm xếp hạng chưa hiệu chuẩn, không phải xác suất mắc bệnh.'
    summary='\n'.join(str(r.get('label',''))+': '+str(r.get('calibrated_score',r.get('decision_score',r.get('score','chưa có điểm')))) for r in top)
    ref=registry.add({'text':explanation+('\n'+summary if summary else ''),'title':'Kết quả mô hình Clinical IE'},kind='model',module='clinical_ie')
    return {**pick(data,['status','modality','input_type','missing_information_questions','warnings']),
            'extracted_facts':clinical_fields(data.get('extracted_facts',{})), 'top5':top,
            'score_semantics':'uncalibrated_decision_scores_not_disease_probability','model_source_refs':[ref] if ref else []}


def prepare_evidence(context, max_bytes=MAX_BYTES):
    if context.get('evidence_version')==VERSION:
        return EvidencePack(copy.deepcopy(context),copy.deepcopy(context.get("sources",[])))  # Only internal callers pass prepared payloads.
    registry=Registry(); modules={}; warnings=list(context.get('warnings') or [])
    snapshot=context.get('confirmed_snapshot') or {}
    confirmed=[pick(f,['display','fact_type','presence','timeframe','experiencer','details']) for f in snapshot.get('facts',[])]
    # The confirmed snapshot is atomic: never silently drop a user's negation/value.
    base={'evidence_version':VERSION,'route':context.get('route'),'confirmed_patient_facts':confirmed,
          'module_results':modules,'sources':[],'warnings':warnings}
    if size(base)>max_bytes:raise ValueError('Bản dữ kiện đã xác nhận vượt ngân sách đầu vào; cần thu hẹp lượt đánh giá.')
    results=copy.deepcopy(context.get('module_results') or {})
    if context.get('clinical_ie_analysis') is not None:results['clinical_ie']=context['clinical_ie_analysis']
    for name,result in results.items():
        if not isinstance(result,dict):continue
        if name=='rag':
            accepted=[]
            for row in result.get('results',[]):
                candidate=copy.deepcopy(registry)
                ref=candidate.add(row,module='rag')
                if ref is None:continue
                item={'source_refs':[ref]}
                proposed = accepted if item in accepted else accepted+[item]
                trial={**base,'module_results':{**modules,'rag':{'evidence':proposed}},'sources':candidate.public()}
                if size(trial)>max_bytes-min(1024,max_bytes//4):
                    if 'Đã bỏ bằng chứng vượt ngân sách đầu vào; phần dữ liệu có thể chưa đầy đủ.' not in warnings:
                        warnings.append('Đã bỏ bằng chứng vượt ngân sách đầu vào; phần dữ liệu có thể chưa đầy đủ.')
                    continue
                registry=candidate;accepted=proposed
            modules[name]={'evidence':accepted,'warnings':result.get('reindex_required') and ['Một số tài liệu cần tạo lại chỉ mục.'] or []}
        else:
            candidate=copy.deepcopy(registry)
            try:
                filtered=kg_context(result,candidate) if name=='kg' else clinical_context(result,candidate) if name.startswith('clinical') else None
            except ValueError:
                if name != 'kg':
                    raise
                warnings.append('Dữ liệu KG có tham chiếu không hợp lệ; đã bỏ trọn nhóm KG. Các nguồn còn lại được giữ riêng.')
                continue
            if filtered is None:continue
            trial={**base,'module_results':{**modules,name:filtered},'sources':candidate.public()}
            if size(trial)>max_bytes-min(1024,max_bytes//4):
                warnings.append(f'Bằng chứng {"KG" if name=="kg" else "Clinical IE"} vượt ngân sách; đã bỏ trọn nhóm để không cắt mất điều kiện hoặc chuỗi quan hệ.')
                continue
            registry=candidate;modules[name]=filtered
    # Leave room for warnings and JSON overhead; do not truncate medical text mid-sentence.
    base['sources']=registry.public();base['warnings']=list(dict.fromkeys(warnings))
    if size(base)>max_bytes:raise ValueError('Bằng chứng vượt ngân sách sau khi thêm giới hạn dữ liệu.')
    return EvidencePack(base,registry.rows)


def validate_answer(text, sources):
    valid={s['number'] for s in sources}
    invalid=set()
    def replace(match):
        digits=match.group(1)
        number=int(digits) if len(digits)<=9 else None
        if number not in valid:invalid.add(number);return ''
        return match.group(0)
    text=re.sub(r'\[(\d+)\]',replace,text)
    identifiers={str(v) for s in sources for origin in s.get('origins',[]) for v in origin.values() if v}
    for identifier in sorted(identifiers,key=len,reverse=True):
        if len(identifier)>=6:text=re.sub(r'(?<!\w)'+re.escape(identifier)+r'(?!\w)','tài liệu nguồn',text)
    text=re.sub(r'\b(?:DOC|PROP|PROPOSITION|SENT|ENT|REL|CHUNK)_[A-Za-z0-9_-]+\b','nguồn nội bộ',text)
    if invalid:text+='\n\n**Giới hạn nguồn:** Một số trích dẫn do mô hình sinh không khớp nguồn được cung cấp và đã được loại bỏ. Cần kiểm tra bằng chứng trước khi sử dụng các nhận định đó.'
    return text


def has_evidence(payload):
    if payload.get('confirmed_patient_facts'):return True
    for name,data in payload.get('module_results',{}).items():
        if name=='rag' and data.get('evidence'):return True
        if name=='kg' and data.get('facts'):return True
        if name.startswith('clinical') and (data.get('top5') or any(data.get('extracted_facts',{}).get(k) for k in ('entities','triples','input_entities'))):return True
    return False


def insufficient_answer(payload):
    text='Chưa đủ bằng chứng phù hợp trong phần dữ liệu được cung cấp để trả lời câu hỏi này.'
    if payload.get('warnings'):text+='\n\n**Giới hạn dữ liệu**\n'+'\n'.join('- '+w for w in payload['warnings'])
    return text
