"""Regression cases for separate declaration/history/KG review, no real ML calls."""
from types import SimpleNamespace
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4
import pytest
from fastapi import HTTPException
from app.services.assessment import AssessmentService, AssessmentAction
from app.services.assessment_facts import make_drafts, consolidate, clean_details
from app.services.voice import assessment_script, voice_action
from app.storage import ConversationStore
from app.modules.context.application.patient_assertion import PatientAssertionGate
from app.modules.context.domain.models import ClinicalFact


def raw(name='ho',source='old',time='current',details='',**kw):
    return {'display':name,'fact_type':'symptom','source_message_id':source,'source_text':'Tôi bị '+name,
            'status':'user_reported','attributes':{'timeframe':time,'details':details},**kw}


def choices(drafts):
    return [{k:f[k] for k in ('id','display','fact_type','presence','timeframe','details','experiencer')} for f in drafts]


def action(state,kind,**kw):
    return AssessmentAction(action_id=str(uuid4()),version=state['version'],action=kind,**kw)


@pytest.fixture
def env(tmp_path):
    modules=SimpleNamespace(kg_url='http://kg',_post=AsyncMock(),clinical_query=AsyncMock(),append_assistant_turn=AsyncMock())
    async def post(base,path,data):
        if path.endswith('/map'):
            return {'items':[{'mention':n,'status':'resolved','kg_entity_id':n} for n in data['mentions']]}
        return {'status':'ok','questions':[{'question_id':'fever','target_entity_id':'sốt','target_name':'sốt','target_type':'Symptom',
            'question_text':'Bạn có sốt không?', 'basis':[{'evidence':[{'text':'test source'}], 'assertions':[{'properties_valid':True,'properties':{}}]}]}]}
    modules._post.side_effect=post
    container=SimpleNamespace(patient_repository=SimpleNamespace(upsert_facts=AsyncMock()),
        history_repository=SimpleNamespace(add_turn=AsyncMock()), service=SimpleNamespace(add_history_turn=AsyncMock()))
    store=ConversationStore(tmp_path/'db.sqlite')
    return AssessmentService(store,modules,SimpleNamespace(generate=AsyncMock()),container),modules,container


def test_exact_report_only_current_cough_and_group_old_sources(env):
    svc,modules,_=env
    old=[raw(name,source=str(i),details='status: user_reportedstatus: historical')
         for i,name in enumerate(['ho','ho','sốt','sốt','chóng mặt','chóng mặt','Khó thở','khó thở'])]
    state=svc.start('c','m','Tôi bị ho khan thì bị gì?',{'draft_facts':[raw(source='m'),raw('sốt')],'patient_facts':old})
    assert [f['display'] for f in state['drafts']]==['ho khan']
    assert len(state['history_drafts'])==4
    assert all('status:' not in f['details'] for f in state['history_drafts'])
    assert all(f['timeframe']=='current' for f in state['history_drafts'])
    assert all(len(f['source_refs'])==2 for f in state['history_drafts'])
    assert state['facts']==[]
    modules._post.assert_not_called()


@pytest.mark.asyncio
async def test_declaration_then_history_then_kg_and_no_rewrite_old_fact(env):
    svc,modules,container=env
    state=svc.start('c','m','Tôi bị ho khan thì bị gì?',{'draft_facts':[raw(source='m')],
        'patient_facts':[raw('ho'),raw('chóng mặt',source='old1'),raw('chóng mặt',source='old2')]})
    history_id=state['history_drafts'][0]['id']
    with pytest.raises(HTTPException):
        await svc.action(state['id'],action(state,'confirm',same_patient=True,facts=choices(state['history_drafts'])))
    state=await svc.action(state['id'],action(state,'confirm',same_patient=True,facts=choices(state['drafts'])))
    assert state['status']=='confirming_history'
    assert [f['display'] for f in state['facts']]==['ho khan']
    assert [f['display'] for f in state['history_drafts']]==['chóng mặt']
    modules._post.assert_not_called()
    for kind in ['diagnose','answer','finish_questions']:
        with pytest.raises(HTTPException):await svc.action(state['id'],action(state,kind,reviewed=True))
    reopened=ConversationStore(svc.store.path);reopened.recover_assessments()
    assert reopened.get_assessment(state['id'])['status']=='confirming_history'
    history=choices(state['history_drafts'])
    state=await svc.action(state['id'],action(state,'confirm_history',same_patient=True,reviewed=True,facts=history))
    assert state['status']=='questioning'
    assert [f['display'] for f in state['facts']]==['ho khan','chóng mặt']
    assert modules._post.call_args_list[0].args[2]['mentions']==['ho','chóng mặt']
    assert 'sốt' not in [f['display'] for f in state['facts']]
    state=await svc.action(state['id'],action(state,'answer',question_id='fever',answer='unknown',reviewed=True))
    assert state['status']=='ready'
    state=await svc.action(state['id'],action(state,'diagnose',reviewed=True))
    await svc._sync_graph(state)
    written=container.patient_repository.upsert_facts.call_args.kwargs['facts']
    assert [f.display for f in written]==['ho khan']
    assert all('original_fact' not in f.attributes for f in written)
    assert 'ho khan' in state['clinical_input'] and 'sốt: CHƯA BIẾT' in state['clinical_input']


@pytest.mark.asyncio
async def test_skip_history_does_not_use_or_delete_old_statements(env):
    svc,modules,container=env
    state=svc.start('c','m','Tôi bị ho',{'draft_facts':[raw(source='m')],'patient_facts':[raw('chóng mặt')]})
    state=await svc.action(state['id'],action(state,'confirm',same_patient=True,facts=choices(state['drafts'])))
    state=await svc.action(state['id'],action(state,'confirm_history',reviewed=True,facts=[]))
    assert [f['display'] for f in state['facts']]==['ho']
    assert modules._post.call_args_list[0].args[2]['mentions']==['ho']
    container.patient_repository.upsert_facts.assert_not_called()


@pytest.mark.asyncio
async def test_history_selected_requires_review_and_history_id(env):
    svc,_,_=env
    state=svc.start('c','m','Tôi bị ho',{'draft_facts':[raw(source='m')],'patient_facts':[raw('sốt')]})
    state=await svc.action(state['id'],action(state,'confirm',same_patient=True,facts=choices(state['drafts'])))
    for kw in [dict(reviewed=False,same_patient=True,facts=choices(state['history_drafts'])),
               dict(reviewed=True,same_patient=False,facts=choices(state['history_drafts'])),
               dict(reviewed=True,same_patient=True,facts=choices(state['drafts']))]:
        with pytest.raises(HTTPException):await svc.action(state['id'],action(state,'confirm_history',**kw))


def test_distinct_presence_time_subject_and_measurements_not_merged():
    variants=[raw(),raw(time='history'),raw(negated=True),raw(experiencer='family'),raw(details='3 ngày'),raw(details='7 ngày')]
    assert len(make_drafts(variants,'patient_graph'))==6
    assert clean_details('3 ngày; status: user_reportedstatus: historical; 38 °C')=='3 ngày; 38 °C'


@pytest.mark.asyncio
async def test_equal_manual_fact_values_consolidate_and_conflicts_block(env):
    svc,_,_=env
    state=svc.start('c','m','Tôi bị ho',{'draft_facts':[raw(source='m')]})
    first=choices(state['drafts'])[0]
    duplicate={**first,'id':None,'display':'HO'}
    state=await svc.action(state['id'],action(state,'confirm',same_patient=True,facts=[first,duplicate]))
    assert len(state['facts'])==1


def test_legacy_pending_migration_is_idempotent_and_preserves_snapshot(env):
    svc,_,_=env
    state=svc.start('c','m','Tôi bị ho khan',{'draft_facts':[raw(source='m')],'patient_facts':[raw('sốt')]})
    version=state['version'];state.pop('workflow_version')
    state['drafts']+=state.pop('history_drafts')
    svc.store.commit_assessment(state,expected_version=version)
    svc.store.recover_assessments()
    migrated=svc.store.get_assessment(state['id'])
    assert migrated['workflow_version']==2 and len(migrated['drafts'])==1 and len(migrated['history_drafts'])==1
    svc.store.recover_assessments()
    assert svc.store.get_assessment(state['id'])['version']==migrated['version']


@pytest.mark.parametrize('text,accepted',[
    ('Tôi bị ho khan thì bị gì?',True),
    ('Tôi bị ho khan thì tôi bị bệnh gì?',True),
    ('Nếu tôi bị ho khan thì bị gì?',False),
    ('Tôi có bị ho khan không?',False),
    ('Ho khan thì bị gì?',False),
])
def test_personal_assertion_before_question_without_inventing_diagnosis(text,accepted):
    fact=ClinicalFact(display='ho',fact_type='symptom',source_message_id='m',source_text=text,recorded_at=datetime.now(timezone.utc))
    assert bool(PatientAssertionGate().filter(original_text=text,facts=[fact]))==accepted


def test_voice_history_requires_explicit_selection_or_skip(env):
    svc,_,_=env
    state=svc.start('c','m','Tôi bị ho',{'draft_facts':[raw(source='m')],'patient_facts':[raw('sốt')]})
    state['status']='confirming_history'
    assert assessment_script(state)['conversation_action']=='review_patient_history'
    assert voice_action(state,'Tôi xác nhận các dữ kiện vừa đọc thuộc cùng một bệnh nhân') is None
    assert voice_action(state,'Bỏ qua dữ kiện cũ')['facts']==[]


@pytest.mark.asyncio
async def test_real_rule_extractor_keeps_only_assertion_before_diagnostic_tail(env):
    from app.modules.context.application.extractor import RuleBasedClinicalExtractor
    from app.modules.context.domain.models import ResolvedQuestion, StatementType
    text='Tôi bị ho khan thì bị gì?'
    extracted=await RuleBasedClinicalExtractor().extract(patient_id='c',message_id='m',timestamp=datetime.now(timezone.utc),
        original_question=text,resolved_question=ResolvedQuestion(original_question=text,normalized_question=text),history_context=[])
    accepted=PatientAssertionGate().filter(original_text=text,facts=extracted)
    assert len(accepted)==1 and accepted[0].statement_type==StatementType.FACT
    svc,_,_=env
    state=svc.start('c','m',text,{'draft_facts':[f.model_dump(mode='json') for f in accepted]})
    assert state['drafts'][0]['display']=='ho khan' and state['drafts'][0]['timeframe']=='current'
