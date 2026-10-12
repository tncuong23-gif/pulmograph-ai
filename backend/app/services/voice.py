"""Local speech adapters and replay scripts; medical decisions stay in assessment.py."""
from __future__ import annotations

import asyncio
import io
import os
import re
import threading
import time
import logging
import wave
import math
from urllib.parse import urlsplit
from dataclasses import dataclass
from collections import OrderedDict

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field
from .voice_text import dialect_suggestion

STT_PROMPT = 'Tiếng Việt. Thuật ngữ hô hấp: ho, khó thở, sốt, viêm phổi, hen phế quản, COPD, SpO2, X-quang.'

def env_bool(name, default):
    value = os.getenv(name, str(default)).strip().lower()
    if value not in {'true', 'false', '1', '0', 'yes', 'no'}:
        raise ValueError(f'{name} phải là true/false hoặc 1/0.')
    return value in {'true', '1', 'yes'}


@dataclass(frozen=True)
class VoiceSettings:
    stt_model: str = "large-v3-turbo"
    stt_device: str = "cpu"
    stt_compute: str = "int8"
    tts_provider: str = "vieneu"
    tts_voice: str = "Mai Anh"
    tts_url: str = "http://127.0.0.1:8880/v1"
    tts_model: str = "vieneu-v3-turbo"
    max_bytes: int = 12 * 1024 * 1024
    max_seconds: int = 90
    stt_beam: int = 5
    stt_prompt: str = STT_PROMPT
    stt_vad: bool = True
    stt_vad_threshold: float = 0.35
    stt_vad_silence_ms: int = 650
    stt_vad_pad_ms: int = 300
    stt_cpu_threads: int = 4
    stt_preload: bool = True
    tts_concurrency: int = 1

    def __post_init__(self):
        if not self.stt_model.strip() or self.stt_device not in {'cpu', 'cuda', 'auto'}:
            raise ValueError('VOICE_STT_MODEL không được trống; VOICE_STT_DEVICE dùng cpu/cuda/auto.')
        if not 1 <= self.stt_beam <= 10 or len(self.stt_prompt) > 1000:
            raise ValueError('VOICE_STT_BEAM_SIZE cần từ 1 đến 10; prompt tối đa 1000 ký tự.')
        if not math.isfinite(self.stt_vad_threshold) or not 0 < self.stt_vad_threshold < 1:
            raise ValueError('VOICE_STT_VAD_THRESHOLD cần nằm giữa 0 và 1.')
        if not 100 <= self.stt_vad_silence_ms <= 3000 or not 0 <= self.stt_vad_pad_ms <= 1000:
            raise ValueError('STT VAD silence cần 100–3000 ms; pad cần 0–1000 ms.')
        if not 1 <= self.stt_cpu_threads <= 32:
            raise ValueError('VOICE_STT_CPU_THREADS cần từ 1 đến 32.')
        if self.tts_concurrency not in {1, 2}:
            raise ValueError('VOICE_TTS_CONCURRENCY dùng 1 cho CPU hoặc 2 cho VieNeu GPU.')

    @classmethod
    def from_env(cls):
        return cls(stt_model=os.getenv("VOICE_STT_MODEL", "large-v3-turbo"),
                   stt_device=os.getenv("VOICE_STT_DEVICE", "cpu"),
                   stt_compute=os.getenv("VOICE_STT_COMPUTE", "int8"),
                   tts_provider=os.getenv("VOICE_TTS_PROVIDER", "vieneu"),
                   tts_voice=os.getenv("VOICE_TTS_VOICE", "Mai Anh"),
                   tts_url=os.getenv("VOICE_TTS_BASE_URL", "http://127.0.0.1:8880/v1").rstrip("/"),
                   tts_model=os.getenv("VOICE_TTS_MODEL", "vieneu-v3-turbo"),
                   stt_beam=int(os.getenv('VOICE_STT_BEAM_SIZE', '5')),
                   stt_prompt=os.getenv('VOICE_STT_INITIAL_PROMPT', STT_PROMPT),
                   stt_vad=env_bool('VOICE_STT_VAD', True),
                   stt_vad_threshold=float(os.getenv('VOICE_STT_VAD_THRESHOLD', '0.35')),
                   stt_vad_silence_ms=int(os.getenv('VOICE_STT_VAD_SILENCE_MS', '650')),
                   stt_vad_pad_ms=int(os.getenv('VOICE_STT_VAD_PAD_MS', '300')),
                   stt_cpu_threads=int(os.getenv('VOICE_STT_CPU_THREADS', '4')),
                   stt_preload=env_bool('VOICE_STT_PRELOAD', True),
                   tts_concurrency=int(os.getenv('VOICE_TTS_CONCURRENCY', '1')))


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=16000)


class VoiceTurn(BaseModel):
    conversationId: str = Field(min_length=1, max_length=200)
    messageId: str = Field(min_length=1, max_length=200)
    transcript: str = Field(min_length=1, max_length=6000)
    assessmentVersion: int | None = None


def clean_for_speech(text: str) -> str:
    # Preserve numbers, negations and units. Only remove presentation syntax.
    text = re.sub(r'```.*?```', ' Phần mã chi tiết được hiển thị trong khung chat. ', text, flags=re.S)
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'\bDOC_[A-Za-z0-9_]+\b', '', text)
    text = re.sub(r'^\s*[-| :]+\s*$', '', text, flags=re.M)
    text = re.sub(r'^\s{0,3}#{1,6}\s+', '', text, flags=re.M)
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.M)
    text = re.sub(r'\*\*|__|`', '', text)
    text = text.replace('|', '; ')
    return re.sub(r'\s+', ' ', text).strip()


def sentence_units(text: str) -> list[str]:
    # Never split a decimal number or abbreviations just to shorten a response.
    paragraphs = [clean_for_speech(p) for p in re.split(r'\n\s*\n', text)]
    return [p for p in paragraphs if p]


def assessment_script(state: dict) -> dict:
    status = state['status']
    if status == 'confirming':
        facts = [f for f in state['drafts'] if f.get('origin') != 'patient_graph']
        parts = ["Trước khi đánh giá, tôi cần bạn kiểm tra dữ kiện nhận được."]
        for f in facts:
            parts.append(f"{f['display']}: " + {'present': 'có', 'absent': 'không', 'unknown': 'chưa biết'}[f['presence']]
                         + ("; tiền sử" if f['timeframe'] == 'history' else "; hiện tại")
                         + ("; người thân" if f['experiencer'] == 'family' else "; bệnh nhân")
                         + ("; " + f['details'] if f.get('details') else '') + ".")
        if state.get('history_drafts') or any(f.get('origin') == 'patient_graph' for f in state['drafts']):
            parts.append("Dữ kiện cũ trong hồ sơ chưa được chọn. Bạn có thể xem và chọn lại trong bảng kiểm tra.")
        if facts:
            parts.append('Nếu tất cả thông tin vừa đọc đúng, hãy nói: Tôi xác nhận các dữ kiện vừa đọc thuộc cùng một bệnh nhân. Nếu cần sửa, hãy sửa trong bảng kiểm tra.')
        else:
            parts.append('Tôi chưa trích được dữ kiện chắc chắn. Hãy thêm và xác nhận thông tin trong bảng kiểm tra.')
        action = 'confirm_patient_facts'
    elif status == 'confirming_history':
        parts = ['Tiếp theo, hãy kiểm tra riêng dữ kiện đã khai trong Patient Graph. Các dữ kiện này chưa được dùng cho lần đánh giá này.',
                 'Bạn hãy chọn thông tin còn áp dụng trong bảng kiểm tra. Nếu không dùng dữ kiện cũ, hãy nói: Bỏ qua dữ kiện cũ.']
        action = 'review_patient_history'
    elif status == 'questioning':
        parts = [state['question_proposal']['question_text'], 'Đây là câu hỏi bổ sung từ tri thức, chưa phải kết luận về bạn. Hãy trả lời: có, không, không biết hoặc bỏ qua.']
        action = 'ask_follow_up'
    elif status in {'ready', 'failed'}:
        parts = ['Bản dữ kiện chuẩn bị gửi đánh giá gồm:']
        for f in state['facts']:
            parts.append(f"{f['display']}: " + {'present': 'có', 'absent': 'không', 'unknown': 'chưa biết'}[f['presence']]
                         + ('; tiền sử' if f['timeframe'] == 'history' else '; hiện tại')
                         + ('; người thân' if f['experiencer'] == 'family' else '; bệnh nhân')
                         + ('; ' + f['details'] if f.get('details') else '') + '.')
        parts.append('Nếu đồng ý, hãy nói: Tôi đồng ý gửi bản dữ kiện đã kiểm tra để đánh giá. Bạn cũng có thể dùng nút xác nhận bên dưới.')
        action = 'confirm_diagnosis'
    elif status == 'running':
        parts = ['Tôi đang xử lý bản dữ kiện bạn đã xác nhận. Vui lòng chờ kết quả.']
        action = 'processing'
    else:
        parts = ['Lượt đánh giá đã kết thúc. Bạn có thể tiếp tục đặt câu hỏi.']
        action = 'answer'
    return {'spoken_text': ' '.join(parts), 'conversation_action': action,
            'expects_reply': status not in {'running', 'completed', 'cancelled'}, 'has_more': False}


def voice_action(state: dict, text: str) -> dict | None:
    normalized = re.sub(r'[.!?]+$', '', text.strip().casefold()).strip()
    if normalized == 'hủy lượt đánh giá' and state['status'] != 'running':
        return {'action': 'cancel'}
    if state['status'] == 'confirming' and normalized == 'tôi xác nhận các dữ kiện vừa đọc thuộc cùng một bệnh nhân':
        facts = [{k: f[k] for k in ('id', 'display', 'fact_type', 'presence', 'timeframe', 'details', 'experiencer')}
                 for f in state['drafts'] if f.get('origin') != 'patient_graph']
        if facts:
            return {'action': 'confirm', 'same_patient': True, 'facts': facts}
    if state['status'] == 'confirming_history' and normalized == 'bỏ qua dữ kiện cũ':
        return {'action':'confirm_history', 'same_patient':True, 'reviewed':True, 'facts':[]}
    if state['status'] == 'questioning':
        answers = {'có': 'present', 'không': 'absent', 'không biết': 'unknown', 'bỏ qua': 'skip'}
        if normalized in answers:
            return {'action': 'answer', 'question_id': state['question_proposal']['question_id'],
                    'answer': answers[normalized], 'reviewed': True}
        if normalized == 'kết thúc hỏi bổ sung':
            return {'action': 'finish_questions'}
    if state['status'] in {'ready', 'failed'} and normalized == 'tôi đồng ý gửi bản dữ kiện đã kiểm tra để đánh giá':
        return {'action': 'diagnose', 'reviewed': True}
    return None


class VoiceService:
    def __init__(self, settings=None):
        self.settings = settings or VoiceSettings.from_env()
        self._model = None
        self._stt_lock = threading.Lock()
        # The bundled CPU VieNeu server handles one synthesis at a time. Queue here
        # instead of timing out its ten-second admission queue on the next sentence.
        self._tts_lock = asyncio.Semaphore(self.settings.tts_concurrency)
        self._http = None
        self._warmup_task = None
        self._speech_cache = OrderedDict()
        self._speech_cache_bytes = 0

    def _load_stt(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self.settings.stt_model, device=self.settings.stt_device,
                                       compute_type=self.settings.stt_compute, cpu_threads=self.settings.stt_cpu_threads)

    def _warm_stt(self):
        with self._stt_lock:
            self._load_stt()

    def preload_stt(self):
        if not self.settings.stt_preload or self._model is not None or self._warmup_task is not None:
            return
        async def warm():
            try:
                await asyncio.to_thread(self._warm_stt)
                logging.getLogger('uvicorn.error').info('voice.stage stage=stt_ready')
            except Exception as exc:
                logging.getLogger('uvicorn.error').warning('voice.stage stage=stt_warmup_failed error_type=%s', type(exc).__name__)
        self._warmup_task = asyncio.create_task(warm())

    def _cached_speech(self, key):
        now = time.monotonic()
        for old_key, (expiry, data) in list(self._speech_cache.items()):
            if expiry <= now:
                del self._speech_cache[old_key]; self._speech_cache_bytes -= len(data)
        if key not in self._speech_cache:
            return None
        self._speech_cache.move_to_end(key)
        return self._speech_cache[key][1]

    def _cache_speech(self, key, audio):
        budget = 16 * 1024 * 1024
        if len(audio) > budget:
            return
        previous = self._speech_cache.pop(key, None)
        if previous: self._speech_cache_bytes -= len(previous[1])
        while self._speech_cache and (self._speech_cache_bytes + len(audio) > budget or len(self._speech_cache) >= 16):
            _, (_, removed) = self._speech_cache.popitem(last=False)
            self._speech_cache_bytes -= len(removed)
        self._speech_cache[key] = (time.monotonic() + 300, audio)
        self._speech_cache_bytes += len(audio)

    def _local_url(self):
        if urlsplit(self.settings.tts_url).hostname not in {'127.0.0.1', 'localhost', '::1'}:
            raise HTTPException(503, 'VieNeu của bản này cần chạy cục bộ. Dùng VOICE_TTS_BASE_URL=http://127.0.0.1:8880/v1.')
        return self.settings.tts_url

    def _client(self):
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=httpx.Timeout(90, connect=5), trust_env=False)
        return self._http

    async def close(self):
        self._speech_cache.clear()
        self._speech_cache_bytes = 0
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def tts_status(self):
        if self.settings.tts_provider != 'vieneu':
            return None
        try:
            response = await self._client().get(self._local_url().removesuffix('/v1') + '/health', timeout=3)
            response.raise_for_status()
            data = response.json()
            return {'ready': data.get('status') == 'ok', 'backend': data.get('backend')}
        except Exception:
            return {'ready': False, 'detail': 'Chưa kết nối được VieNeu cục bộ tại cổng 8880. Chạy start_vieneu_windows.bat và chờ server sẵn sàng.'}

    async def speech_stream(self, text: str):
        """Proxy actual s16le/48 kHz mono chunks; never buffer a whole answer."""
        if self.settings.tts_provider != 'vieneu':
            raise HTTPException(409, 'Streaming PCM cần VOICE_TTS_PROVIDER=vieneu.')
        started = time.monotonic()
        headers = {}
        if os.getenv('VOICE_TTS_API_KEY'):
            headers['Authorization'] = 'Bearer ' + os.environ['VOICE_TTS_API_KEY']
        async with self._tts_lock:
            key = (self.settings.tts_url, self.settings.tts_model, self.settings.tts_voice, text)
            cached = self._cached_speech(key)
            if cached is not None:
                logging.getLogger('uvicorn.error').info('voice.stage stage=tts_cache_hit')
                yield cached
                return
            collected = bytearray()
            cacheable = True
            async with self._client().stream('POST', self._local_url() + '/audio/speech', headers=headers,
                json={'model': self.settings.tts_model, 'voice': self.settings.tts_voice,
                      'input': text, 'response_format': 'pcm', 'stream_format': 'audio', 'sample_rate': 48000}) as response:
                response.raise_for_status()
                if response.headers.get('content-type', '').split(';')[0] != 'audio/pcm' or response.headers.get('X-Sample-Rate') != '48000':
                    raise RuntimeError('VieNeu PCM format does not match 48 kHz mono')
                first = True
                total = 0
                async for chunk in response.aiter_bytes():
                    if not chunk:
                        continue
                    total += len(chunk)
                    if first:
                        first = False
                        logging.getLogger('uvicorn.error').info('voice.stage stage=tts_first_audio elapsed_ms=%.0f', (time.monotonic()-started)*1000)
                    if cacheable:
                        if len(collected) + len(chunk) <= 16 * 1024 * 1024:
                            collected.extend(chunk)
                        else:
                            collected.clear(); cacheable = False
                    yield chunk
                if not total or total % 2:
                    raise RuntimeError('VieNeu returned empty or truncated PCM')
                elapsed = time.monotonic()-started
                if cacheable: self._cache_speech(key, bytes(collected))
                logging.getLogger('uvicorn.error').info('voice.stage stage=tts_complete elapsed_ms=%.0f audio_ms=%.0f rtf=%.3f', elapsed*1000, total/96, elapsed/(total/96000))

    def transcribe(self, data: bytes, mode: str = 'fast'):
        if mode not in {'fast', 'careful'}:
            raise HTTPException(422, 'Chế độ nhận dạng không hợp lệ.')
        requested = time.monotonic()
        with self._stt_lock:
            acquired = time.monotonic()
            try:
                import av
                import numpy as np
                import faster_whisper  # noqa: F401 -- report a missing optional engine before decoding
            except ImportError as exc:
                raise HTTPException(503, 'Chưa cài STT. Cài requirements-voice.txt tại backend.') from exc
            # Decode with a hard duration limit before inference, including compressed files.
            try:
                samples = []
                count = 0
                with av.open(io.BytesIO(data)) as container:
                    resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
                    for frame in container.decode(audio=0):
                        for converted in resampler.resample(frame):
                            sample = converted.to_ndarray().reshape(-1)
                            count += len(sample)
                            if count > self.settings.max_seconds * 16000:
                                raise HTTPException(413, 'Mỗi lượt nói tối đa 90 giây.')
                            samples.append(sample)
                    for converted in resampler.resample(None):
                        sample = converted.to_ndarray().reshape(-1)
                        count += len(sample)
                        if count > self.settings.max_seconds * 16000:
                            raise HTTPException(413, 'Mỗi lượt nói tối đa 90 giây.')
                        samples.append(sample)
                if not samples:
                    raise ValueError('Empty audio')
                audio = np.concatenate(samples).astype(np.float32) / 32768.0
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(422, 'Âm thanh không hợp lệ hoặc không giải mã được.') from exc
            if not len(audio) or float(np.max(np.abs(audio))) < 0.00001:
                raise HTTPException(422, 'Bản ghi không có tiếng nói. Kiểm tra micro và thu lại.')
            decoded = time.monotonic()
            warnings = []
            rms = float(np.sqrt(np.mean(audio * audio)))
            if rms < 0.003:
                warnings.append('Âm thanh nhỏ; hãy kiểm tra micro và đối chiếu lời nhận dạng.')
            if float(np.mean(np.abs(audio) >= 0.995)) > 0.02:
                warnings.append('Âm thanh có dấu hiệu quá lớn/méo; giảm mức micro và kiểm tra lời nhận dạng.')
            cold = self._model is None
            self._load_stt()
            loaded = time.monotonic()
            beam = max(5, self.settings.stt_beam) if mode == 'careful' else min(3, self.settings.stt_beam)
            segments, _ = self._model.transcribe(audio, language='vi', beam_size=beam,
                                                 task='transcribe',
                                                 temperature=0.0, best_of=1, without_timestamps=True,
                                                 initial_prompt=self.settings.stt_prompt or None,
                                                 vad_filter=self.settings.stt_vad and mode != 'careful',
                                                 vad_parameters={'threshold': self.settings.stt_vad_threshold,
                                                                 'min_silence_duration_ms': self.settings.stt_vad_silence_ms,
                                                                 'speech_pad_ms': self.settings.stt_vad_pad_ms},
                                                 condition_on_previous_text=False)
            # Whisper already applies joint no-speech/log-probability filtering.
            # Do not drop a whole medical phrase based on no_speech_prob alone.
            texts = []
            uncertain = False
            for segment in segments:
                if segment.text.strip():
                    texts.append(segment.text.strip())
                    uncertain |= getattr(segment, 'avg_logprob', 0) < -1 or getattr(segment, 'no_speech_prob', 0) > 0.6
            text = ' '.join(texts).strip()
            if not text:
                raise HTTPException(422, 'Tôi chưa nghe rõ. Hãy nói lại gần micro hơn.')
            if uncertain:
                warnings.append('Có đoạn nhận dạng chưa chắc chắn; kiểm tra tên bệnh, phủ định, con số và đơn vị trước khi gửi.')
            finished = time.monotonic()
            inference = finished - loaded
            metrics = {'model': self.settings.stt_model, 'device': self.settings.stt_device, 'mode': mode, 'beam_size': beam,
                       'compute_type': self.settings.stt_compute, 'cold_start': cold,
                       'audio_seconds': round(len(audio)/16000, 3),
                       'queue_ms': round((acquired-requested)*1000), 'decode_ms': round((decoded-acquired)*1000),
                       'model_load_ms': round((loaded-decoded)*1000), 'inference_ms': round(inference*1000),
                       'inference_rtf': round(inference/(len(audio)/16000), 3)}
            logging.getLogger('uvicorn.error').info('voice.stage stage=stt_metrics metrics=%s', metrics)
            return {'transcript': text, 'warnings': warnings, 'metrics': metrics,
                    'uncertain': uncertain, 'suggested_transcript': dialect_suggestion(text)}

    async def speech(self, text: str):
        if self.settings.tts_provider == 'vieneu':
            pcm = b''.join([chunk async for chunk in self.speech_stream(text)])
            buffer = io.BytesIO()
            with wave.open(buffer, 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(48000)
                wav.writeframes(pcm)
            return buffer.getvalue()
        async with self._tts_lock:
            if self.settings.tts_provider == 'edge':
                try:
                    import edge_tts
                except ImportError as exc:
                    raise HTTPException(503, 'Chưa cài TTS. Cài requirements-voice.txt tại backend.') from exc
                async def collect():
                    data = bytearray()
                    async for chunk in edge_tts.Communicate(text, self.settings.tts_voice).stream():
                        if chunk['type'] == 'audio':
                            data.extend(chunk['data'])
                    return bytes(data)
                audio = await asyncio.wait_for(collect(), timeout=60)
            elif self.settings.tts_provider == 'compatible':
                headers = {}
                if os.getenv('VOICE_TTS_API_KEY'):
                    headers['Authorization'] = 'Bearer ' + os.environ['VOICE_TTS_API_KEY']
                async with httpx.AsyncClient(timeout=60) as client:
                    response = await client.post(self.settings.tts_url + '/audio/speech', headers=headers,
                        json={'model': self.settings.tts_model, 'voice': self.settings.tts_voice,
                              'input': text, 'response_format': 'mp3'})
                    response.raise_for_status()
                    audio = response.content
            else:
                raise HTTPException(503, 'VOICE_TTS_PROVIDER không hợp lệ.')
            if not audio:
                raise HTTPException(502, 'Dịch vụ chưa tạo được âm thanh.')
            return audio

    async def compose(self, llm, message: dict, assessment=None, full=False):
        if assessment and assessment['status'] not in {'completed', 'cancelled'}:
            return assessment_script(assessment)
        metadata = message.get('metadata') or {}
        scripted = metadata.get('spoken_text') if not full else None
        text = scripted or clean_for_speech(message['content'])
        more = bool(scripted and clean_for_speech(message['content']) != clean_for_speech(scripted))
        chunks = list(metadata.get('speech_chunks') or []) if scripted else None
        if more:
            outro = 'Nội dung đầy đủ và nguồn ở khung chat. Bạn có thể nói: nghe tiếp.'
            text += ' ' + outro
            if chunks is not None:
                chunks.append(outro)
        return {'spoken_text': text, 'conversation_action': 'clarify' if message.get('metadata', {}).get('route') == 'NEEDS_CLARIFICATION' else 'answer',
                'expects_reply': True, 'has_more': more, 'speech_chunks': chunks,
                'speech_style': metadata.get('speech_style', 'source_fallback')}
