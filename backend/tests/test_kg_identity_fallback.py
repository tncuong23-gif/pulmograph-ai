import copy
from unittest.mock import AsyncMock, Mock
import pytest
from tests.upstream.kg.helpers import load_payload, load_ontology
from app.modules.kg_import.adapters.memory import MemoryGraphStore, MemoryDocumentStore, MemoryJobStore
from app.modules.kg_import.service import KGImportService
from app.services.orchestrator import Orchestrator
from app.services.retrieval_quality import select_kg_evidence


def importer():
    return KGImportService(load_ontology(), MemoryDocumentStore(), MemoryGraphStore(), MemoryJobStore())


def test_cross_type_in_same_document_requires_explicit_review_and_writes_nothing():
    svc=importer(); p=load_payload()
    p['entities'].append({'id':'ENT_OTHER','type':'ClinicalSign','canonical_name':'Ho'})
    preview=svc.import_kg(p,dry_run=True)
    assert preview.status=='dry_run'
    assert preview.plan['entity_candidates']['ENT_OTHER'][0]['link_allowed'] is False
    assert svc.import_kg(p).status=='failed'
    assert not svc.graph.entities and not svc.docs.document_exists('DOC_000001')
    p['entity_link_decisions']={'ENT_OTHER':'new','ENT_000002':'new'}
    assert svc.import_kg(p).status=='failed'  # Old bulk keep-all decisions cannot bypass new type review.
    p['entity_type_decisions']={'ENT_OTHER':'distinct','ENT_000002':'distinct'}
    assert svc.import_kg(p).status=='completed'
    assert svc.graph.entities['ENT_OTHER']['entity_type']=='ClinicalSign'


def test_cross_type_against_existing_graph_and_forced_link_rejected():
    svc=importer(); assert svc.import_kg(load_payload()).status=='completed'
    p=load_payload(); p['document']['document_id']='DOC_2'
    p['relations']=[];p['propositions']=[]
    p['entities']=[{'id':'ENT_NEW','type':'ClinicalSign','canonical_name':'ho'}]
    assert svc.import_kg(p,dry_run=True).plan['entity_candidates']['ENT_NEW']
    p['entity_link_decisions']={'ENT_NEW':'ENT_000002'}
    result=svc.import_kg(p)
    assert result.status=='failed' and any(e['code']=='ENTITY_TYPE_CONFLICT' for e in result.errors)
    assert 'ENT_NEW' not in svc.graph.entities


def test_exact_duplicates_still_merge_when_keep_all_says_new_and_preserve_original_id():
    svc=importer();p=load_payload()
    p['entities'].append({'id':'ENT_EXTRA','type':'Symptom','canonical_name':'  HO '})
    p['relations'][0]['target']='ENT_EXTRA'
    p['propositions'][0]['entity_ids']=['ENT_EXTRA']
    p['entity_link_decisions']={'ENT_EXTRA':'new'}
    assert svc.import_kg(p).status=='completed'
    assert 'ENT_EXTRA' not in svc.graph.entities
    assert svc.graph.relations['REL_000001']['target_id']=='ENT_000002'
    document=svc.docs.data['documents'][('DOC_000001','DOC_000001')]
    assert document['entity_id_map']['ENT_EXTRA']=='ENT_000002'
    assert svc.docs.data['propositions'][('DOC_000001','PROP_000001')]['entity_ids']==['ENT_000002']


def test_same_name_conflicting_properties_are_not_silently_overwritten():
    svc=importer();p=load_payload();p['entities'][1]['properties']={'qualifier':'dry'}
    p['entities'].append({'id':'ENT_EXTRA','type':'Symptom','canonical_name':'Ho','properties':{'qualifier':'productive'}})
    result=svc.import_kg(p)
    assert any(e['code']=='ENTITY_PROPERTY_CONFLICT' for e in result.errors)
    assert not svc.graph.entities


def fact(text='Văn bản nguồn thử nghiệm.'):
    return {'subject':{'name':'A','type':'Disease'},'predicate':'HAS_SYMPTOM',
            'object':{'name':'Ho','type':'Symptom'},'assertions':[{'properties_valid':True,'properties':{'negated':True}}],
            'evidence':[{'doc_id':'D','evidence_id':'E','text':text}]}


def result(facts=None, **retrieval):
    return {'status':'ok','query':{'mode':'one_hop','intents':['symptom']},
            'retrieval':retrieval,'llm_context':{'facts':[fact()] if facts is None else facts}}


def orchestration(kg, rag=None):
    modules=Mock()
    modules.context_resolve=AsyncMock(return_value={'resolution_status':'resolved'})
    modules.kg_query=AsyncMock(side_effect=kg if isinstance(kg,Exception) else None,return_value=kg)
    modules.rag_search=AsyncMock(return_value=rag if rag is not None else {'results':[{'document_id':'R','text':'Tài liệu thử nghiệm RAG.'}]})
    classifier=Mock();classifier.predict.return_value={'label':'RELATIONAL_QUERY'}
    llm=Mock();llm.generate=AsyncMock(return_value='Trả lời [1].')
    return Orchestrator(classifier,modules,llm),modules,llm


ARGS=dict(conversation_id='c',message_id='m',timestamp='now',attachments=[],question='A có triệu chứng gì?')


@pytest.mark.asyncio
@pytest.mark.parametrize('kg',[{'status':'no_facts'}, {'status':'no_entity'}, result([]), result([fact('')]), RuntimeError('database offline'),
                              {'status':'needs_clarification','clarification':{'reason':'duplicate_entities','message':'Duplicate'}}])
async def test_no_usable_kg_calls_rag_once_and_does_not_send_bad_kg_to_llm(kg):
    orchestrator,modules,llm=orchestration(kg)
    answer=await orchestrator.answer(**ARGS)
    assert answer['route']=='GENERAL_MEDICAL_QUERY'
    assert answer['classifier']['label']=='RELATIONAL_QUERY'
    modules.rag_search.assert_awaited_once()
    assert set(llm.generate.call_args.args[1]['module_results'])=={'rag'}


@pytest.mark.asyncio
async def test_partial_kg_uses_combined_evidence_and_preserves_negation():
    orchestrator,modules,llm=orchestration(result(truncated=True))
    answer=await orchestrator.answer(**ARGS)
    assert answer['route']=='CLINICAL_EXPLANATION_MANAGEMENT'
    payload=llm.generate.call_args.args[1]
    assert set(payload['module_results'])=={'kg','rag'}
    assert payload['module_results']['kg']['facts'][0]['assertions'][0]['properties']['negated']
    modules.rag_search.assert_awaited_once()


@pytest.mark.asyncio
async def test_sufficient_kg_does_not_call_rag():
    orchestrator,modules,llm=orchestration(result())
    answer=await orchestrator.answer(**ARGS)
    assert answer['route']=='RELATIONAL_QUERY'
    modules.rag_search.assert_not_awaited()
    llm.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_empty_rag_and_kg_never_call_llm():
    orchestrator,modules,llm=orchestration(result([]),{'results':[{'document_id':'ID_WITHOUT_TEXT'}]})
    answer=await orchestrator.answer(**ARGS)
    assert 'Chưa đủ bằng chứng' in answer['content']
    llm.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_kg_rejected_by_byte_budget_falls_back_once():
    orchestrator,modules,llm=orchestration(result([fact('x'*25000)]))
    answer=await orchestrator.answer(**ARGS)
    assert answer['route']=='GENERAL_MEDICAL_QUERY'
    modules.rag_search.assert_awaited_once()
    assert set(llm.generate.call_args.args[1]['module_results'])=={'rag'}


def test_invalid_fact_does_not_break_chain_and_does_not_leak_to_llm():
    kg=result([fact(),fact('')]);kg['query']['mode']='path'
    kg['llm_context']['paths']=[{'nodes':[],'fact_indices':[0,1]}]
    assert select_kg_evidence(kg)[1]=='empty'
    assert len(kg['llm_context']['facts'])==2


def test_partial_one_hop_discards_unsourced_facts():
    kg=result([fact(),fact('')]);selected,quality,_=select_kg_evidence(kg)
    assert quality=='partial' and len(selected['llm_context']['facts'])==1


def test_missing_requested_intent_uses_partial_status():
    kg=result();kg['query']['intents']=['symptom','treatment']
    assert select_kg_evidence(kg)[1]=='partial'


def test_assertion_without_its_own_source_is_not_sent_as_supported_fact():
    kg=result()
    kg['llm_context']['facts'][0]['assertions'][0].update(document_id='OTHER', evidence_ids=['OTHER_EVIDENCE'])
    assert select_kg_evidence(kg)[1]=='empty'


@pytest.mark.asyncio
async def test_failed_rag_fallback_uses_available_kg_and_is_not_retried():
    orchestrator,modules,llm=orchestration(result(truncated=True))
    modules.rag_search.side_effect=RuntimeError('offline')
    answer=await orchestrator.answer(**ARGS)
    modules.rag_search.assert_awaited_once()
    assert set(llm.generate.call_args.args[1]['module_results'])=={'kg'}
    assert any('chưa phản hồi' in w for w in answer['warnings'])


@pytest.mark.asyncio
async def test_type_review_is_saved_separately_and_cannot_force_cross_type_link():
    from app.bulk_import.kg import KGAdapter
    svc=importer();p=load_payload()
    p['entities'].append({'id':'ENT_OTHER','type':'ClinicalSign','canonical_name':'Ho'})
    adapter=KGAdapter(lambda:svc)
    with pytest.raises(ValueError):
        await adapter.decisions(p, {'ENT_OTHER':'ENT_000002','ENT_000002':'new'})
    reviewed=await adapter.decisions(p, {'ENT_OTHER':'new','ENT_000002':'new'})
    assert reviewed['entity_type_decisions']=={'ENT_OTHER':'distinct','ENT_000002':'distinct'}
    assert svc.import_kg(reviewed).status=='completed'


def test_existing_graph_audit_lists_cross_type_and_same_type_groups():
    from scripts.kg.audit_identity import audit_rows
    rows=[{'id':'A','canonical_name':'Ho','entity_type':'Symptom'},
          {'id':'B','canonical_name':'ho','entity_type':'Symptom'},
          {'id':'C','canonical_name':'HO','entity_type':'ClinicalSign'}]
    original=copy.deepcopy(rows)
    assert audit_rows(rows)[0]['kind']=='cross_type'
    assert audit_rows(rows[:2])[0]['kind']=='same_name_same_type'
    assert rows==original
