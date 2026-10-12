import io
import sys
import types
import wave

import pytest
from fastapi import HTTPException

from app.services.voice import VoiceService, VoiceSettings


@pytest.fixture
def engine(monkeypatch):
    pytest.importorskip('av')
    np = pytest.importorskip('numpy')
    calls = []
    segments = [types.SimpleNamespace(text=' Không sốt, SpO2 92.5%. ', no_speech_prob=0.8, avg_logprob=-0.2)]
    class Model:
        def __init__(self, name, **kwargs):
            calls.append(('load', name, kwargs))
        def transcribe(self, audio, **kwargs):
            calls.append(('transcribe', audio, kwargs))
            return iter(segments), None
    monkeypatch.setitem(sys.modules, 'faster_whisper', types.SimpleNamespace(WhisperModel=Model))
    def recording(seconds=1, sample=3000, stereo=False):
        # Actual WAV decoding/resampling, with controlled inference only.
        data = np.full((int(seconds*8000), 2 if stereo else 1), sample, dtype='<i2')
        output = io.BytesIO()
        with wave.open(output, 'wb') as wav:
            wav.setnchannels(2 if stereo else 1); wav.setsampwidth(2); wav.setframerate(8000)
            wav.writeframes(data.tobytes())
        return output.getvalue()
    return calls, segments, recording


def test_stt_defaults_and_env_validation(monkeypatch):
    assert VoiceSettings().stt_model == 'large-v3-turbo'
    assert VoiceSettings().stt_device == 'cpu'
    monkeypatch.setenv('VOICE_STT_VAD', 'false')
    monkeypatch.setenv('VOICE_STT_BEAM_SIZE', '7')
    settings = VoiceSettings.from_env()
    assert not settings.stt_vad and settings.stt_beam == 7
    monkeypatch.setenv('VOICE_STT_VAD', 'maybe')
    with pytest.raises(ValueError): VoiceSettings.from_env()


@pytest.mark.parametrize('kwargs', [{'stt_beam': 0}, {'stt_vad_threshold': float('nan')},
                                    {'stt_vad_silence_ms': 0}, {'stt_prompt': 'a'*1001}])
def test_stt_rejects_invalid_configuration(kwargs):
    with pytest.raises(ValueError): VoiceSettings(**kwargs)


def test_real_decoder_preserves_accepted_phrase_and_caches_model(engine):
    calls, _, recording = engine
    service = VoiceService(VoiceSettings())
    first = service.transcribe(recording(stereo=True))
    second = service.transcribe(recording())
    assert first['transcript'] == 'Không sốt, SpO2 92.5%.'
    assert first['warnings']  # Retain phrase, flag uncertainty, do not silently delete it.
    assert first['metrics']['cold_start'] and not second['metrics']['cold_start']
    assert first['metrics']['audio_seconds'] == 1
    assert len([call for call in calls if call[0] == 'load']) == 1
    audio, kwargs = calls[1][1:]
    assert len(audio) == 16000 and audio.ndim == 1
    assert kwargs['language'] == 'vi' and kwargs['beam_size'] == 3
    assert kwargs['initial_prompt'] and not kwargs['condition_on_previous_text']
    assert kwargs['vad_parameters']['threshold'] == 0.35


def test_vad_and_vocabulary_can_be_disabled(engine):
    calls, _, recording = engine
    VoiceService(VoiceSettings(stt_vad=False, stt_prompt='', stt_beam=1)).transcribe(recording())
    assert calls[1][2]['initial_prompt'] is None
    assert not calls[1][2]['vad_filter'] and calls[1][2]['beam_size'] == 1


@pytest.mark.parametrize('sample,word', [(20, 'nhỏ'), (32767, 'méo')])
def test_signal_quality_warning_keeps_transcript(engine, sample, word):
    _, _, recording = engine
    result = VoiceService().transcribe(recording(sample=sample))
    assert result['transcript'].startswith('Không sốt')
    assert any(word in warning for warning in result['warnings'])


def test_silence_invalid_and_overlong_audio_do_not_load_model(engine):
    calls, _, recording = engine
    service = VoiceService(VoiceSettings(max_seconds=1))
    for data, status in [(recording(sample=0), 422), (b'bad file', 422), (recording(seconds=2), 413)]:
        with pytest.raises(HTTPException) as caught: service.transcribe(data)
        assert caught.value.status_code == status
    assert not calls


def test_empty_inference_asks_for_new_recording(engine):
    _, segments, recording = engine
    segments.clear()
    with pytest.raises(HTTPException) as caught: VoiceService().transcribe(recording())
    assert caught.value.status_code == 422
