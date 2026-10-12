"""Full chat -> KG -> choice -> answer contract, with synthetic graph and fake LLM."""
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import main
from app.modules.kg_query.retrieval_api import create_app
from tests.test_kg_chat_query import fixture_service


@pytest.fixture
def chat_client():
    with TestClient(main.app) as client:
        service = fixture_service()
        service.driver.g.entities['D1']['aliases'].append('ABC')
        service.driver.g.entities['D2']['aliases'].append('ABC')
        main.app.state.modules.embedded_apps['http://kg.internal'] = create_app(service)
        main.app.state.modules.context_resolve = AsyncMock(side_effect=lambda **kw: {
            'normalized_question': kw['question'], 'resolution_status': 'resolved'})
        main.app.state.modules.append_assistant_turn = AsyncMock()
        classifier = Mock()
        classifier.predict.return_value = {'label': 'RELATIONAL_QUERY'}
        main.app.state.orchestrator.classifier = classifier
        llm = AsyncMock()
        llm.generate.return_value = 'Phản hồi từ bằng chứng giả lập.'
        main.app.state.orchestrator.llm = llm
        yield client, classifier, llm, service


def post(client, cid, question, confirmation=None):
    payload = {'conversationId': cid, 'message': {'id': str(uuid4()), 'role': 'user', 'content': question}}
    if confirmation:
        payload['kg_confirmation'] = confirmation
    return client.post('/api/v1/chat/message', json=payload)


def pending(client, cid):
    response = post(client, cid, 'ABC có triệu chứng gì?')
    assert response.status_code == 200, response.text
    message = response.json()['message']
    assert message['metadata']['kg_clarification']['can_confirm']
    return {'message_id': message['id'], 'entity_ids': ['D1']}


def test_confirmed_choice_resumes_original_question_without_reclassification(chat_client):
    client, classifier, llm, _ = chat_client
    cid = str(uuid4())
    confirmation = pending(client, cid)
    llm.generate.assert_not_awaited()
    response = post(client, cid, 'Tôi xác nhận COPD.', confirmation)
    assert response.status_code == 200, response.text
    metadata = response.json()['message']['metadata']
    assert metadata['route'] == 'RELATIONAL_QUERY'
    assert metadata['kg_confirmation_used'] is True
    assert metadata['kg_query']['mode'] == 'one_hop'
    assert metadata['sources'][0]['origins'][0]['doc_id'] == 'SYNTHETIC_TEST'
    classifier.predict.assert_called_once()
    assert llm.generate.call_args.args[0] == 'ABC có triệu chứng gì?'
    assert len(main.app.state.store.get_conversation(cid)['messages']) == 4


def test_forged_stale_cross_conversation_and_removed_choices_are_blocked(chat_client):
    client, _, llm, service = chat_client
    cid = str(uuid4())
    confirmation = pending(client, cid)
    assert post(client, cid, 'Tôi chọn thuốc A', {**confirmation, 'entity_ids': ['M1']}).status_code == 422
    assert post(client, str(uuid4()), 'Chọn COPD', confirmation).status_code == 409
    assert post(client, cid, 'Chọn COPD', {**confirmation, 'question': 'Dữ liệu bịa'}).status_code == 422
    llm.generate.assert_not_awaited()
    del service.driver.g.entities['D1']
    removed = post(client, cid, 'Chọn COPD', confirmation)
    assert removed.status_code == 200
    assert removed.json()['message']['metadata']['route'] == 'NEEDS_CLARIFICATION'
    llm.generate.assert_not_awaited()
    assert post(client, cid, 'Thử lựa chọn cũ', confirmation).status_code == 409


def test_combined_route_keeps_rag_after_confirmation(chat_client):
    client, classifier, llm, _ = chat_client
    classifier.predict.return_value = {'label': 'CLINICAL_EXPLANATION_MANAGEMENT'}
    main.app.state.modules.rag_search = AsyncMock(return_value={'results': [{'document_id': 'RAG_TEST', 'text': 'Dữ liệu giả lập.'}]})
    cid = str(uuid4())
    confirmation = pending(client, cid)
    llm.generate.assert_not_awaited()
    result = post(client, cid, 'Chọn COPD', confirmation)
    assert result.status_code == 200
    assert result.json()['message']['metadata']['route'] == 'CLINICAL_EXPLANATION_MANAGEMENT'
    assert set(llm.generate.call_args.args[1]['module_results']) == {'rag', 'kg'}
    classifier.predict.assert_called_once()


def test_comparison_two_choices_resume_mode_and_persist_table(chat_client):
    client, classifier, llm, _ = chat_client
    classifier.predict.return_value = {'label': 'GENERAL_MEDICAL_QUERY'}
    cid = str(uuid4())
    question = 'So sánh triệu chứng ABC và Viêm phổi'
    pending_message = post(client, cid, question).json()['message']
    assert pending_message['metadata']['kg_query']['mode'] == 'compare'
    assert pending_message['metadata']['kg_clarification']['can_confirm']
    llm.generate.assert_not_awaited()
    confirmation = {'message_id': pending_message['id'], 'entity_ids': ['D1', 'D2']}
    assert post(client, cid, 'Chọn hai tên', {**confirmation, 'entity_ids': ['D1', 'M1']}).status_code == 422
    response = post(client, cid, 'Chọn hai tên', confirmation)
    assert response.status_code == 200, response.text
    metadata = response.json()['message']['metadata']
    assert metadata['kg_query']['mode'] == 'compare'
    assert metadata['kg_confirmation_used']
    assert metadata['kg_comparison']['rows'][0]['classification'] == 'common'
    assert metadata['classifier']['original_label'] == 'GENERAL_MEDICAL_QUERY'
    assert llm.generate.call_args.args[0] == question
    classifier.predict.assert_called_once()
    stored = main.app.state.store.get_conversation(cid)['messages'][-1]['metadata']
    assert stored['kg_comparison'] == metadata['kg_comparison']
