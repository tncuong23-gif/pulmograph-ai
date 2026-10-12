import copy
import json
from unittest.mock import patch
import httpx
import pytest
from app.services.evidence import prepare_evidence, validate_answer, size
from app.services.ollama import OllamaClient


def rag(text='Ho là triệu chứng được mô tả.',doc='DOC_SECRET'):
    return {'document_id':doc,'document_title':'Tài liệu bệnh phổi','chunk_id':'CHUNK_SECRET','text':text,
            'vector':[1,2],'embedding_text':'hidden','revision':'private_revision','score':.9}


def kg(text='Ho là triệu chứng được mô tả.'):
    return {'status':'ok','request_id':'request_secret','timings_ms':{'a':1},'llm_context':{
        'facts':[{'subject':{'id':'NODE_SECRET','name':'Bệnh A','type':'Disease'},'predicate':'HAS_SYMPTOM',
                  'object':{'id':'NODE2_SECRET','name':'ho','type':'Symptom'},
                  'assertions':[{'relation_id':'REL_SECRET','properties_valid':True,'properties':{'negated':True,'condition':'nhóm cụ thể'}}],
                  'evidence':[{'doc_id':'DOC_SECRET','evidence_id':'SENT_SECRET','text':text}]}],
        'sources':[{'doc_id':'DOC_SECRET','evidence_id':'SENT_SECRET','text':text}],
        'chains':[{'fact_indices':[0]}],'paths':[]}}


def test_shared_numbering_deduplication_and_original_result_unchanged():
    raw={'route':'CLINICAL_EXPLANATION_MANAGEMENT','module_results':{'rag':{'results':[rag(),rag()]},'kg':kg()}}
    before=copy.deepcopy(raw);pack=prepare_evidence(raw)
    assert raw==before
    assert len(pack.sources)==1 and len(pack.sources[0]['origins'])==2
    wire=json.dumps(pack.payload,ensure_ascii=False)
    for technical in ['DOC_SECRET','CHUNK_SECRET','SENT_SECRET','NODE_SECRET','REL_SECRET','timings_ms','embedding_text','revision']:
        assert technical not in wire
    assert wire.count('Ho là triệu chứng được mô tả.')==1
    fact=pack.payload['module_results']['kg']['facts'][0]
    assert fact['assertions'][0]['properties']=={'negated':True,'condition':'nhóm cụ thể'}
    assert fact['source_refs']==[1]
    assert pack.payload['module_results']['kg']['chains']==[{'fact_indices':[0]}]


def test_budget_omits_whole_kg_chain_and_never_cuts_qualifier():
    result=kg('Không được dùng nếu có điều kiện này. '*300)
    pack=prepare_evidence({'module_results':{'kg':result}},max_bytes=2000)
    assert 'kg' not in pack.payload['module_results']
    assert pack.sources==[] and pack.payload['warnings']
    assert size(pack.payload)<=2000


def test_clinical_and_confirmed_facts_keep_subject_negation_time_and_values():
    raw={'confirmed_snapshot':{'id':'snapshot_secret','facts':[{'display':'ho khan','presence':'absent','timeframe':'history',
        'experiencer':'family','details':'3 ngày; 38 °C','original_fact':{'secret':'old'}}]},
        'module_results':{'clinical_ie':{'ok':True,'data':{'top5':[{'label':'Viemphoi','rank':1,'calibrated_score':-1.2,'raw_probability':.8}],
        'graph':{'id':'BIG_GRAPH'},'all_scores':{'unused':1},'extracted_facts':{'entities':[{'id':'E1','text':'ho','label':'SYMPTOM','negated':True}]}}}}}
    pack=prepare_evidence(raw)
    assert pack.payload['confirmed_patient_facts'][0]['details']=='3 ngày; 38 °C'
    assert pack.payload['confirmed_patient_facts'][0]['presence']=='absent'
    assert pack.sources[0]['kind']=='model'
    wire=json.dumps(pack.payload)
    for omitted in ['snapshot_secret','original_fact','BIG_GRAPH','all_scores','raw_probability']:assert omitted not in wire
    assert pack.payload['module_results']['clinical_ie']['extracted_facts']['entities'][0]['negated'] is True


def test_invalid_citations_removed_with_warning_and_ids_not_printed():
    pack=prepare_evidence({'module_results':{'rag':{'results':[rag()]}}})
    text=validate_answer('Thông tin [1][99]. DOC_SECRET',pack.sources)
    assert '[1]' in text and '[99]' not in text and 'DOC_SECRET' not in text
    assert 'Giới hạn nguồn' in text


@pytest.mark.asyncio
async def test_actual_ollama_request_uses_filtered_json_and_checks_citations():
    captured=[]
    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200,json={'message':{'content':'Kết quả [1].'}})
    original=httpx.AsyncClient
    with patch('app.services.ollama.httpx.AsyncClient',side_effect=lambda **kw:original(transport=httpx.MockTransport(handler),**kw)):
        answer=await OllamaClient('http://ollama','test',5).generate('Câu hỏi',{'module_results':{'rag':{'results':[rag()]}}})
    assert answer=='Kết quả [1].'
    prompt=captured[0]['messages'][1]['content']
    assert 'DOC_SECRET' not in prompt and 'CHUNK_SECRET' not in prompt
    assert 'numbered_evidence_v1' in prompt and 'Tài liệu bệnh phổi' in prompt


def test_prepared_payload_keeps_reference_registry_on_second_boundary():
    pack=prepare_evidence({'module_results':{'rag':{'results':[rag()]}}})
    again=prepare_evidence(pack.payload)
    assert again.payload==pack.payload and validate_answer('[1]',again.sources)=='[1]'


def test_confirmed_snapshot_over_budget_fails_instead_of_silently_dropping_facts():
    with pytest.raises(ValueError):prepare_evidence({'confirmed_snapshot':{'facts':[{'details':'x'*5000}]}},max_bytes=1000)


def test_comparison_cells_and_indices_stay_consistent_without_ids():
    result=kg()
    result['llm_context']['comparison']={'mode':'compare','entities':[{'id':'NODE_SECRET','name':'A','type':'Disease'}],
       'rows':[{'feature':{'id':'F_SECRET','name':'ho'},'classification':'left_only','direction':'out',
                'cells':[{'entity_id':'NODE_SECRET','fact_indices':[0],'status':'recorded'}]}]}
    pack=prepare_evidence({'module_results':{'kg':result}})
    comparison=pack.payload['module_results']['kg']['comparison']
    assert comparison['rows'][0]['cells'][0]=={'entity_index':0,'fact_indices':[0],'status':'recorded'}
    assert 'NODE_SECRET' not in json.dumps(pack.payload)


@pytest.mark.asyncio
async def test_no_evidence_after_filter_does_not_call_ollama():
    with patch('app.services.ollama.httpx.AsyncClient',side_effect=AssertionError('LLM must not run')):
        answer=await OllamaClient('http://ollama','test',5).generate('question',{'module_results':{'rag':{'results':[{'chunk_id':'EMPTY'}]}}})
    assert 'Chưa đủ bằng chứng' in answer


def test_assertion_is_bound_to_its_own_source_not_another_condition():
    result=kg()
    fact=result['llm_context']['facts'][0]
    fact['evidence']=[{'doc_id':'DOC_A','evidence_id':'E_A','text':'Chỉ áp dụng nhóm A.'},
                      {'doc_id':'DOC_B','evidence_id':'E_B','text':'Không áp dụng nhóm B.'}]
    fact['assertions']=[{'document_id':'DOC_A','evidence_ids':['E_A'],'properties_valid':True,'properties':{'population':'A'}},
                        {'document_id':'DOC_B','evidence_ids':['E_B'],'properties_valid':True,'properties':{'population':'B','negated':True}}]
    pack=prepare_evidence({'module_results':{'kg':result}})
    assertions=pack.payload['module_results']['kg']['facts'][0]['assertions']
    assert assertions[0]['source_refs']==[1] and assertions[1]['source_refs']==[2]


def test_private_document_title_falls_back_to_readable_source_title():
    row=rag();row['document_title']=row['document_id']
    pack=prepare_evidence({'module_results':{'rag':{'results':[row]}}})
    assert pack.sources[0]['title']=='Tài liệu truy xuất'
    assert 'DOC_SECRET' not in json.dumps(pack.payload)


def test_broken_chain_reference_is_rejected_instead_of_changing_its_meaning():
    result=kg();result['llm_context']['chains']=[{'fact_indices':[0,99]}]
    pack=prepare_evidence({'module_results':{'kg':result,'rag':{'results':[rag()]}}})
    assert 'kg' not in pack.payload['module_results']
    assert pack.payload['module_results']['rag']['evidence']==[{'source_refs':[1]}]
    assert len(pack.sources)==1 and pack.payload['warnings']


def test_duplicate_source_cannot_bypass_budget_by_replacing_title():
    first=rag();duplicate=rag();duplicate['document_title']='Tên rất dài '*1000
    pack=prepare_evidence({'module_results':{'rag':{'results':[first,duplicate]}}},max_bytes=2000)
    assert pack.sources[0]['title']==first['document_title']
    assert size(pack.payload)<=2000 and pack.payload['warnings']


def test_unknown_citation_with_more_than_three_digits_is_removed():
    pack=prepare_evidence({'module_results':{'rag':{'results':[rag()]}}})
    answer=validate_answer('[1] [1000] ['+'9'*5000+']',pack.sources)
    assert '[1]' in answer and '[1000]' not in answer and '9999' not in answer
    assert 'Giới hạn nguồn' in answer
