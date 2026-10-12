import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
import pytest

from app.services.voice import VoiceService, VoiceSettings
from app.services.voice_text import dialect_suggestion
from app.modules.context.application.patient_assertion import PatientAssertionGate
from app.modules.context.domain.models import ProcessRequest
from tests.upstream.context.test_patient_assertion_gate import build_service
from tests.test_voice_quality import engine


@pytest.mark.parametrize('text', ['Viêm phổi là gì?', 'COPD có những dấu hiệu nào?', 'Các dấu hiệu của covid19', 'Triệu chứng của viêm phổi là gì?'])
def test_general_questions_can_skip_clinical_extraction(text):
    assert PatientAssertionGate.is_general_information_question(text)


@pytest.mark.parametrize('text', ['Tui đang ho, hổng sốt.', 'Tôi có bị viêm phổi không?', 'Mẹ tôi bị bệnh gì?',
                                'Ho ba ngày rồi', 'Triệu chứng của tôi là ho', 'Viêm phổi là gì? Tôi đang sốt.',
                                'Các triệu chứng sau khi dùng thuốc', 'Viêm phổi ở trẻ là gì?'])
def test_personal_ambiguous_or_mixed_questions_keep_full_extraction(text):
    assert not PatientAssertionGate.is_general_information_question(text)


@pytest.mark.asyncio
async def test_fast_path_keeps_topic_history_and_does_not_call_llm_extractor():
    extractor = type('Extractor', (), {'extract': AsyncMock(return_value=[])})()
    service, history, _ = build_service(extractor)
    result = await service.process(ProcessRequest(patient_id='p', session_id='s', message_id='m',
        question='Viêm phổi có triệu chứng gì?', timestamp=datetime.now(timezone.utc)))
    extractor.extract.assert_not_awaited()
    assert result.normalized_question == 'Viêm phổi có triệu chứng gì?'
    turns = await history.get_recent_turns(patient_id='p', session_id='s', limit=1)
    assert any(m.canonical_name.casefold() == 'viêm phổi' for m in turns[0].mentions)
    await service.process(ProcessRequest(patient_id='p', session_id='s', message_id='n',
        question='Tôi đang sốt, liệu có viêm phổi không?', timestamp=datetime.now(timezone.utc)))
    extractor.extract.assert_awaited_once()


def test_dialect_suggestion_preserves_negation_body_parts_numbers_and_original():
    text = 'Tui hổng sốt, đau hông, SpO2 92.5%, 0.5 mg, má tui bịnh.'
    suggestion = dialect_suggestion(text)
    assert suggestion == 'Tôi không sốt, đau hông, SpO2 92.5%, 0.5 mg, má tôi bệnh.'
    assert 'hổng' in text and dialect_suggestion('Tôi đau hông.') is None


def test_careful_decode_uses_same_recording_without_vad(engine):
    calls, _, recording = engine
    service = VoiceService(VoiceSettings())
    audio = recording()
    fast = service.transcribe(audio)
    careful = service.transcribe(audio, mode='careful')
    assert fast['metrics']['beam_size'] == 3 and careful['metrics']['beam_size'] == 5
    assert calls[-1][2]['vad_filter'] is False
    assert (calls[1][1] == calls[-1][1]).all()
    assert len([c for c in calls if c[0] == 'load']) == 1


@pytest.mark.asyncio
async def test_preload_is_single_flight_and_transcribe_reuses_model(engine):
    calls, _, recording = engine
    service = VoiceService(VoiceSettings())
    service.preload_stt(); service.preload_stt()
    await service._warmup_task
    result = service.transcribe(recording())
    assert not result['metrics']['cold_start']
    assert len([c for c in calls if c[0] == 'load']) == 1


@pytest.mark.asyncio
async def test_tts_cache_contains_every_pcm_chunk_and_replay_needs_no_request():
    calls = []
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'\x00\x00'; yield b'\xff\x7f'; yield b'\x00\x80'
    def handle(request):
        calls.append(request)
        return httpx.Response(200, headers={'Content-Type': 'audio/pcm', 'X-Sample-Rate': '48000'}, stream=Stream())
    service = VoiceService()
    service._http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    first = b''.join([part async for part in service.speech_stream('Không sốt.')])
    again = b''.join([part async for part in service.speech_stream('Không sốt.')])
    assert first == again == b'\x00\x00\xff\x7f\x00\x80' and len(calls) == 1
    await service.close()


@pytest.mark.asyncio
async def test_next_synthesis_waits_locally_and_cancellation_releases_the_slot():
    calls = []
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'\x00\x00'; yield b'\xff\x7f'
    def handle(request):
        calls.append(request)
        return httpx.Response(200, headers={'Content-Type': 'audio/pcm', 'X-Sample-Rate': '48000'}, stream=Stream())
    service = VoiceService()
    service._http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    first = service.speech_stream('Câu một.')
    await anext(first)
    async def collect(): return b''.join([part async for part in service.speech_stream('Câu hai.')])
    second = asyncio.create_task(collect())
    await asyncio.sleep(0)
    assert len(calls) == 1 and not second.done()
    await first.aclose()
    assert await second == b'\x00\x00\xff\x7f' and len(calls) == 2
    assert not service._cached_speech((service.settings.tts_url, service.settings.tts_model, service.settings.tts_voice, 'Câu một.'))
    await service.close()


def test_cache_is_bounded_and_expires(monkeypatch):
    service = VoiceService()
    for i in range(20): service._cache_speech(i, bytes(1024*1024))
    assert service._speech_cache_bytes <= 16*1024*1024
    assert service._cached_speech(0) is None
    monkeypatch.setattr('app.services.voice.time.monotonic', lambda: float('inf'))
    assert service._cached_speech(19) is None and service._speech_cache_bytes == 0
