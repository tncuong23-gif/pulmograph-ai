from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from app.services.voice import VoiceService, clean_for_speech, assessment_script, voice_action
from app.schemas import iso_now


def fact(origin='current_message', **overrides):
    return {'id': origin, 'display': 'ho', 'fact_type': 'symptom', 'presence': 'absent',
            'timeframe': 'current', 'details': '3 ngày', 'experiencer': 'patient', 'origin': origin, **overrides}


def test_confirmation_preserves_negation_subject_units_and_excludes_old_graph():
    state = {'status': 'confirming', 'drafts': [fact(), fact('patient_graph', display='COPD'),
        fact('current_message', id='lab', display='SpO2', details='92%', experiencer='family', timeframe='history')]}
    script = assessment_script(state)['spoken_text']
    assert 'ho: không' in script and 'SpO2: không; tiền sử; người thân; 92%' in script
    assert 'COPD' not in script
    assert voice_action(state, 'đúng') is None
    assert len(voice_action(state, 'Tôi xác nhận các dữ kiện vừa đọc thuộc cùng một bệnh nhân.')['facts']) == 2


def test_followup_unknown_is_not_negative_and_diagnosis_requires_specific_phrase():
    state = {'status': 'questioning', 'question_proposal': {'question_id': 'q'}}
    assert voice_action(state, 'Không biết.')['answer'] == 'unknown'
    assert voice_action(state, 'Tôi không chắc có sốt không') is None
    state['status'] = 'ready'
    assert voice_action(state, 'có') is None
    assert voice_action(state, 'Tôi đồng ý gửi bản dữ kiện đã kiểm tra để đánh giá')['reviewed']


@pytest.mark.asyncio
async def test_legacy_speech_keeps_all_limits_without_a_second_llm_call():
    llm = SimpleNamespace(select_spoken_units=AsyncMock(return_value=[0]))
    content = 'Ho là thông tin được cung cấp.\n\nPhần thứ hai.\n\nPhần thứ ba.\n\nChưa đủ bằng chứng để khẳng định chẩn đoán.'
    result = await VoiceService().compose(llm, {'content': content})
    assert 'Chưa đủ bằng chứng' in result['spoken_text'] and not result['has_more']
    assert 'Phần thứ hai' in result['spoken_text']
    llm.select_spoken_units.assert_not_awaited()


def test_cleaner_keeps_numbers_and_negation():
    text = clean_for_speech('## Dữ kiện\n**Không** sốt; SpO2 92.5%; liều 0.5 mg. [Nguồn](https://example.com).')
    assert 'Không sốt' in text and '92.5%' in text and '0.5 mg' in text
    assert 'https://' not in text and '**' not in text


@pytest.fixture
def client(tmp_path):
    from app.main import app
    from app.storage import ConversationStore
    from app.services.assessment import AssessmentService
    original = dict(app.state._state)
    app.state.store = ConversationStore(tmp_path / 'voice.sqlite3')
    app.state.modules = SimpleNamespace(append_assistant_turn=AsyncMock())
    app.state.llm = SimpleNamespace(select_spoken_units=AsyncMock(return_value=[0]))
    app.state.assessments = AssessmentService(app.state.store, SimpleNamespace(), app.state.llm)
    app.state.voice = VoiceService()
    app.state.orchestrator = SimpleNamespace(answer=AsyncMock(return_value={'content': 'Kết quả có dẫn chứng.', 'route': 'GENERAL_MEDICAL_QUERY'}))
    yield TestClient(app)
    app.state._state.clear()
    app.state._state.update(original)


def test_transcript_goes_through_shared_chat_history_and_retry_is_idempotent(client):
    from app.main import app
    body = {'conversationId': 'voice', 'messageId': 'turn-1', 'transcript': 'Triệu chứng COPD là gì?'}
    first = client.post('/api/v1/voice/turn', json=body)
    assert first.status_code == 200, first.text
    assert first.json()['conversation']['messages'][0]['content'] == body['transcript']
    assert client.post('/api/v1/voice/turn', json=body).status_code == 200
    assert app.state.orchestrator.answer.await_count == 1
    assert len(app.state.store.get_conversation('voice')['messages']) == 2


def test_stale_confirmation_rejected_and_ambiguous_confirmation_does_not_commit(client):
    from app.main import app
    user = {'id': 'u', 'role': 'user', 'content': 'Tôi ho', 'createdAt': iso_now()}
    assistant = {'id': 'a', 'role': 'assistant', 'content': 'Xác nhận dữ kiện', 'createdAt': iso_now()}
    state = app.state.assessments.start('voice', 'u', 'Tôi ho', {'draft_facts': [
        {'display': 'ho', 'fact_type': 'symptom', 'source_text': 'Tôi ho'}]}, (user, assistant))
    body = {'conversationId': 'voice', 'messageId': 'confirm', 'transcript': 'Tôi xác nhận các dữ kiện vừa đọc thuộc cùng một bệnh nhân', 'assessmentVersion': 9}
    assert client.post('/api/v1/voice/turn', json=body).status_code == 409
    body.update(assessmentVersion=state['version'], transcript='đúng rồi')
    response = client.post('/api/v1/voice/turn', json=body)
    assert response.status_code == 200
    assert app.state.store.latest_assessment('voice')['status'] == 'confirming'
    assert app.state.orchestrator.answer.await_count == 0


def test_audio_upload_limit_and_tts_failure_preserve_text(client):
    from app.main import app
    assert client.post('/api/v1/voice/transcribe', files={'file': ('empty.webm', b'', 'audio/webm')}).status_code == 422
    assert client.post('/api/v1/voice/transcribe', files={'file': ('large.webm', b'x' * (12*1024*1024+1), 'audio/webm')}).status_code == 413
    app.state.voice.speech = AsyncMock(side_effect=RuntimeError('offline'))
    response = client.post('/api/v1/voice/speech', json={'text': 'Câu trả lời đã hiển thị.'})
    assert response.status_code == 502 and 'khung chat' in response.json()['detail']
