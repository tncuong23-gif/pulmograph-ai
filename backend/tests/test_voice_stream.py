import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.services.voice import VoiceService, VoiceSettings
from app.services.voice_generation import VoiceJSONParser
from app.services.ollama import OllamaClient
from tests.test_voice import client


def test_incremental_parser_preserves_decimals_negation_and_escaped_quotes():
    parser = VoiceJSONParser()
    raw = json.dumps({'spoken_sentences': ['Không sốt; SpO2 92.5%, liều 0.5 mg.', 'Thông tin "chưa chắc chắn" được giữ.'], 'details': 'Nguồn DOC_1'}, ensure_ascii=False)
    emitted = []
    for character in raw:
        emitted += parser.feed(character)
    final = parser.finish()
    assert emitted == final['speech_chunks']
    assert all(sentence in final['content'] for sentence in emitted)
    assert 'Không' in final['spoken_text'] and '92.5%' in final['spoken_text']


def test_partial_json_never_emits_partial_medical_sentence():
    parser = VoiceJSONParser()
    assert parser.feed('{"spoken_sentences":["SpO2 92.') == []
    assert parser.feed('5%, không sốt.",') == ['SpO2 92.5%, không sốt.']
    with pytest.raises(json.JSONDecodeError):
        parser.finish()


@pytest.mark.parametrize('raw', [
    '{"spoken_sentences":[12],"details":""}',
    '{"spoken_sentences":[],"details":""}',
    '{"spoken_sentences":["Có."],"details":12}',
    '{"spoken_sentences":["Có."],"details":"","other":"x"}',
])
def test_invalid_voice_contract_is_rejected(raw):
    parser = VoiceJSONParser()
    with pytest.raises(ValueError):
        parser.feed(raw)
        parser.finish()


@pytest.mark.asyncio
async def test_one_llm_stream_emits_sentence_before_details_and_finishes(monkeypatch):
    observed = []
    calls = []
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield (json.dumps({'message': {'content': '{"spoken_sentences":["Chưa đủ bằng chứng.",'}}) + '\n').encode()
            assert observed == ['Chưa đủ bằng chứng.']  # callback ran before the answer completed
            yield (json.dumps({'message': {'content': '"Có thể xem nguồn trong chat."],"details":"Nguồn DOC_1"}'}}) + '\n').encode()
    def handle(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, stream=Stream())
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    async def on_sentence(text): observed.append(text)
    result = await OllamaClient('http://ollama.test', 'qwen', 30).generate_voice('Câu hỏi', {'module_results':{'rag':{'results':[{'text':'Nguồn thử nghiệm chưa đủ để kết luận.'}]} }}, on_sentence)
    assert len(calls) == 1 and calls[0]['stream'] is True
    assert result['speech_chunks'] == observed and observed[0] in result['content']


@pytest.mark.asyncio
async def test_replay_reuses_cached_script_without_llm():
    llm = SimpleNamespace(select_spoken_units=AsyncMock())
    message = {'content': 'Không sốt.\n\nNguồn DOC_1', 'metadata': {
        'spoken_text': 'Không sốt.', 'speech_chunks': ['Không sốt.'], 'speech_style': 'grounded_conversation'}}
    reply = await VoiceService().compose(llm, message)
    assert reply['has_more'] and reply['speech_chunks'][0] == 'Không sốt.'
    assert reply['speech_chunks'][-1] in reply['spoken_text']
    assert not llm.select_spoken_units.called
    full = await VoiceService().compose(llm, message, full=True)
    assert 'Nguồn' in full['spoken_text'] and not full['has_more']


@pytest.mark.asyncio
async def test_vieneu_proxy_uses_real_pcm_contract_and_emits_before_completion():
    seen = []
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'\x00\x00'
            assert seen == [b'\x00\x00']
            yield b'\xff\x7f'
    def handle(request):
        body = json.loads(request.content)
        assert body['response_format'] == 'pcm' and body['sample_rate'] == 48000
        assert body['voice'] == 'Mai Anh' and body['stream_format'] == 'audio'
        return httpx.Response(200, headers={'Content-Type': 'audio/pcm', 'X-Sample-Rate': '48000'}, stream=Stream())
    service = VoiceService(VoiceSettings())
    service._http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    async for chunk in service.speech_stream('Không sốt.'):
        seen.append(chunk)
    assert seen == [b'\x00\x00', b'\xff\x7f']
    await service.close()


@pytest.mark.asyncio
async def test_local_provider_refuses_remote_address():
    service = VoiceService(VoiceSettings(tts_url='https://remote.test/v1'))
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        await anext(service.speech_stream('Câu trả lời.'))


def test_streamed_turn_saves_shared_history_and_retry_does_not_regenerate(client):
    from app.main import app
    async def answer(**kwargs):
        assert kwargs['voice'] is True
        await kwargs['on_sentence']('Không sốt; SpO2 92.5%.')
        return {'content': 'Không sốt; SpO2 92.5%.\n\nNguồn DOC_1', 'route': 'GENERAL_MEDICAL_QUERY',
                'spoken_text': 'Không sốt; SpO2 92.5%.', 'speech_chunks': ['Không sốt; SpO2 92.5%.']}
    app.state.orchestrator.answer = AsyncMock(side_effect=answer)
    payload = {'conversationId': 'voice-stream', 'messageId': 'u1', 'transcript': 'Câu hỏi'}
    first = client.post('/api/v1/voice/turn/stream', json=payload)
    events = [json.loads(line) for line in first.text.splitlines()]
    assert [event['type'] for event in events] == ['sentence', 'complete']
    assert events[-1]['reply']['conversation']['messages'][0]['content'] == 'Câu hỏi'
    again = client.post('/api/v1/voice/turn/stream', json=payload)
    retry = json.loads(again.text)
    assert retry['type'] == 'complete' and retry['streamed_sentences'] == 0
    assert app.state.orchestrator.answer.await_count == 1


def test_stream_proxy_reports_failure_before_http_200(client):
    from app.main import app
    async def failed(text):
        raise RuntimeError('offline')
        yield b''
    app.state.voice.speech_stream = failed
    response = client.post('/api/v1/voice/speech/stream', json={'text': 'Câu trả lời.'})
    assert response.status_code == 502 and 'VieNeu' in response.json()['detail']


def test_stream_proxy_returns_pcm_metadata(client):
    from app.main import app
    async def audio(text):
        yield b'\x00\x00'
        yield b'\xff\x7f'
    app.state.voice.speech_stream = audio
    response = client.post('/api/v1/voice/speech/stream', json={'text': 'Câu trả lời.'})
    assert response.content == b'\x00\x00\xff\x7f'
    assert response.headers['X-Audio-Sample-Rate'] == '48000'


@pytest.mark.asyncio
@pytest.mark.parametrize('headers,pcm', [
    ({'Content-Type': 'audio/pcm', 'X-Sample-Rate': '24000'}, b'\x00\x00'),
    ({'Content-Type': 'audio/mpeg', 'X-Sample-Rate': '48000'}, b'\x00\x00'),
    ({'Content-Type': 'audio/pcm', 'X-Sample-Rate': '48000'}, b'\x00'),
])
async def test_vieneu_rejects_mismatched_or_truncated_audio(headers, pcm):
    service = VoiceService(VoiceSettings())
    service._http = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, headers=headers, content=pcm)))
    try:
        with pytest.raises(Exception):
            await service.speech('Không sốt.')
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_legacy_audio_endpoint_gets_valid_wav_with_vieneu():
    import io
    import wave
    service = VoiceService(VoiceSettings())
    service._http = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(
        200, headers={'Content-Type': 'audio/pcm', 'X-Sample-Rate': '48000'}, content=b'\x00\x00\xff\x7f')))
    try:
        with wave.open(io.BytesIO(await service.speech('Không sốt.'))) as audio:
            assert audio.getframerate() == 48000 and audio.getnchannels() == 1
            assert audio.getsampwidth() == 2 and audio.readframes(2) == b'\x00\x00\xff\x7f'
    finally:
        await service.close()


def test_streamed_confirmation_checks_fact_version_and_does_not_call_llm(client):
    from app.main import app
    from app.schemas import iso_now
    user = {'id': 'u', 'role': 'user', 'content': 'Tôi không sốt', 'createdAt': iso_now()}
    assistant = {'id': 'a', 'role': 'assistant', 'content': 'Xác nhận dữ kiện', 'createdAt': iso_now()}
    state = app.state.assessments.start('confirm-stream', 'u', user['content'], {'draft_facts': [
        {'display': 'sốt', 'fact_type': 'symptom', 'negated': True, 'source_text': user['content']}]}, (user, assistant))
    payload = {'conversationId': 'confirm-stream', 'messageId': 'confirm',
               'transcript': 'Tôi xác nhận các dữ kiện vừa đọc thuộc cùng một bệnh nhân', 'assessmentVersion': 99}
    error = json.loads(client.post('/api/v1/voice/turn/stream', json=payload).text)
    assert error['type'] == 'error' and error['status'] == 409
    assert app.state.store.latest_assessment('confirm-stream')['version'] == state['version']
    payload.update(assessmentVersion=state['version'], transcript='đúng rồi')
    reply = json.loads(client.post('/api/v1/voice/turn/stream', json=payload).text)['reply']
    assert 'sốt: không' in reply['spoken_text']
    assert app.state.store.latest_assessment('confirm-stream')['status'] == 'confirming'
    app.state.orchestrator.answer.assert_not_awaited()
