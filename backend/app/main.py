from __future__ import annotations

import json
import asyncio
import logging
import time
import httpx
import os
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .config import Settings
from .integrated import MOUNTS, create_module_apps, module_lifespans
from .services.evidence import prepare_evidence, validate_answer
from .schemas import ChatRequest, iso_now
from .services.classifier import E5SVMClassifier
from .services.modules import ModuleClient
from .services.ollama import OllamaClient
from .services.orchestrator import Orchestrator
from .storage import ConversationStore
from .services.assessment import AssessmentService, AssessmentAction, TERMINAL
from .services.voice import VoiceService, VoiceTurn, SpeechRequest, voice_action, assessment_script
from .bulk_import.api import create_router as create_import_router
from .data_workspace.api import create_router as create_data_router


load_dotenv(Path(__file__).resolve().parents[1] / ".env")
settings = Settings.from_env()
logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with module_lifespans(app.state.embedded_apps):
        settings.database_path.parent.mkdir(parents=True, exist_ok=True)
        settings.upload_dir.mkdir(parents=True, exist_ok=True)
        app.state.store = ConversationStore(settings.database_path)
        app.state.store.mark_interrupted_uploads()
        app.state.modules = ModuleClient(
            context_url=settings.context_base_url,
            clinical_url=settings.clinical_ie_base_url,
            kg_url=settings.kg_base_url,
            rag_url=settings.rag_base_url,
            timeout=settings.request_timeout_seconds,
            clinical_timeout=settings.clinical_timeout_seconds,
            embedded_apps={"http://context.internal": app.state.embedded_apps["context"],
                           "http://rag.internal": app.state.embedded_apps["rag"],
                           "http://kg.internal": app.state.embedded_apps["kg"]},
        )
        app.state.classifier = E5SVMClassifier(
            model_path=settings.classifier_path,
            embedding_model=settings.embedding_model,
            id2label=settings.id2label,
            embedding_prefix=settings.embedding_prefix,
            normalize_embeddings=settings.normalize_embeddings,
            device=os.getenv("CLASSIFIER_DEVICE", "auto"),
            revision=os.getenv("CLASSIFIER_EMBEDDING_REVISION", "d13f1b27baf31030b7fd040960d60d909913633f"),
        )
        app.state.llm = OllamaClient(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            timeout=settings.ollama_timeout_seconds,
        )
        app.state.orchestrator = Orchestrator(
            classifier=app.state.classifier,
            modules=app.state.modules,
            llm=app.state.llm,
        )
        app.state.orchestrator.attachment_lookup = app.state.store.get_attachment
        app.state.store.recover_assessments()
        app.state.assessments = AssessmentService(app.state.store, app.state.modules, app.state.llm,
            getattr(app.state.embedded_apps["context"].state, "container", None))
        app.state.voice = VoiceService()
        app.state.import_batches = {}
        app.state.data_overview_cache = None
        app.state.data_overview_lock = asyncio.Lock()
        try:
            yield
        finally:
            for batch in app.state.import_batches.values():
                await batch.close()
            await app.state.voice.close()



app = FastAPI(title="Medical AI Assistant Backend", version="1.0.0", lifespan=lifespan)
app.include_router(create_import_router())
from .clinical_routes import create_router as create_clinical_router
app.include_router(create_clinical_router(settings))
app.include_router(create_data_router(settings.cors_origins))
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Audio-Sample-Rate", "X-Audio-Channels", "X-Audio-Format"],
)


@app.get("/health/live")
async def health_live():
    return {"status": "ok"}


@app.get("/api/v1/status")
async def system_status():
    checks = await app.state.modules.health()
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{settings.ollama_base_url}/api/tags")
            checks["ollama"] = response.is_success
    except Exception:
        checks["ollama"] = False
    return {
        "online": True,
        "model": settings.ollama_model,
        "knowledgeBase": "Medical RAG + Knowledge Graph",
        "mode": "live",
        "health": "ready" if all(checks.values()) else "degraded",
        "execution": "embedded",
        "modules": MOUNTS,
        "ragMode": os.getenv("RAG_MODE", "live"),
        "dependencies": checks,
        "classifier": str(settings.classifier_path.name),
    }


@app.post("/api/v1/chat/message")
async def chat_message(payload: ChatRequest):
    async with app.state.assessments.chat_lock(payload.conversationId):
        state = app.state.store.latest_assessment(payload.conversationId)
        if state and state["message_id"] == payload.message.id:
            conversation = app.state.store.get_conversation(payload.conversationId)
            message = next(m for m in conversation["messages"] if m.get("metadata", {}).get("assessment_id") == state["id"] and m["role"] == "assistant")
            return {"message": message, "assessment": state, "conversation": conversation}
        if state and state["status"] not in TERMINAL:
            raise HTTPException(409, "Hãy trả lời trong khung đánh giá hoặc hủy lượt hiện tại trước khi nhập câu hỏi mới.")
        return await _chat_message(payload)


async def _chat_message(payload: ChatRequest, *, voice=False, on_sentence=None):
    if payload.message.role != "user":
        raise HTTPException(status_code=422, detail="Only user messages can be submitted to this endpoint.")
    if any(item.type == "medical_record" for item in payload.message.attachments):
        raise HTTPException(
            status_code=422,
            detail="Bệnh án được phân tích tự động khi tải lên; không gửi bệnh án qua luồng chat.",
        )
    if not payload.message.content:
        raise HTTPException(status_code=422, detail="Enter a question.")
    if any(item.type == "xray" for item in payload.message.attachments):
        raise HTTPException(status_code=501, detail="X-ray upload and analysis are not enabled in this backend version.")

    started = time.monotonic()
    logger.info("chat.start message_id=%s", payload.message.id)
    message = payload.message.model_dump(mode="json")
    kg_confirmation = None
    if payload.kg_confirmation:
        from .services.kg_chat import confirmed_request
        kg_confirmation = confirmed_request(app.state.store, payload.conversationId, payload.kg_confirmation)
    try:
        result = await app.state.orchestrator.answer(
            conversation_id=payload.conversationId,
            message_id=payload.message.id,
            question=payload.message.content,
            timestamp=payload.message.createdAt or iso_now(),
            attachments=[item.model_dump(mode="json") for item in payload.message.attachments],
            **({'kg_confirmation': kg_confirmation} if kg_confirmation else {}),
            **({'voice': True, 'on_sentence': on_sentence} if voice else {}),
        )
    except Exception as exc:
        request_id = str(uuid4())
        logger.error("chat.failed request_id=%s elapsed=%.1fs error_type=%s", request_id, time.monotonic()-started, type(exc).__name__)
        return JSONResponse(
            status_code=502,
            content={
                "detail": {
                    "code": "UPSTREAM_FAILURE",
                    "message": "Không xử lý được câu hỏi do một dịch vụ phụ thuộc chưa sẵn sàng.",
                    "request_id": request_id,
                    "hint": str(exc) if os.getenv("DEBUG", "false").lower() == "true" else None,
                }
            },
        )

    assistant_message = {
        "id": str(uuid4()),
        "role": "assistant",
        "content": result["content"],
        "createdAt": iso_now(),
        "attachments": [],
        "metadata": {k: v for k, v in result.items() if k != "content"},
    }
    assessment = None
    if result.get("route") == "DIAGNOSTIC_ASSESSMENT":
        assessment = app.state.assessments.start(payload.conversationId, payload.message.id,
            payload.message.content, result.get("context_resolution", {}), (message, assistant_message))
    else:
        app.state.store.save_exchange(payload.conversationId, message, assistant_message)
    try:
        await app.state.modules.append_assistant_turn(
            conversation_id=payload.conversationId,
            message_id=assistant_message["id"],
            text=assistant_message["content"],
            timestamp=assistant_message["createdAt"],
        )
    except Exception as exc:
        logger.warning("history.append_failed message_id=%s error_type=%s", assistant_message["id"], type(exc).__name__)
    logger.info("chat.done message_id=%s route=%s elapsed=%.1fs", payload.message.id, result.get("route"), time.monotonic()-started)
    return {"message": assistant_message, "assessment": assessment}


@app.get("/api/v1/assessments/{assessment_id}")
async def get_assessment(assessment_id: str):
    state = app.state.store.get_assessment(assessment_id)
    if state is None:
        raise HTTPException(404, "Không tìm thấy lượt đánh giá.")
    return {"assessment": state, "conversation": app.state.store.get_conversation(state["conversation_id"])}


@app.post("/api/v1/assessments/{assessment_id}/actions")
async def assessment_action(assessment_id: str, payload: AssessmentAction, background_tasks: BackgroundTasks):
    state = await app.state.assessments.action(assessment_id, payload)
    if state["status"] == "running":
        background_tasks.add_task(app.state.assessments.run, assessment_id)
    return {"assessment": state, "conversation": app.state.store.get_conversation(state["conversation_id"])}


@app.get("/api/v1/voice/config")
async def voice_config():
    from importlib.util import find_spec
    cfg = app.state.voice.settings
    from urllib.parse import urlsplit
    external = cfg.tts_provider == "edge" or urlsplit(cfg.tts_url).hostname not in {"localhost", "127.0.0.1", "::1"}
    local = await app.state.voice.tts_status()
    stt = find_spec("faster_whisper") is not None
    if stt:
        app.state.voice.preload_stt()
    return {"stt_installed": find_spec("faster_whisper") is not None,
            "tts_installed": local['ready'] if local is not None else (cfg.tts_provider == "compatible" or find_spec("edge_tts") is not None),
            "tts_provider": cfg.tts_provider, "external_tts": external,
            "streaming": cfg.tts_provider == 'vieneu', "sample_rate": 48000,
            "tts_backend": (local or {}).get('backend'), "tts_voice": cfg.tts_voice,
            "stt_model": cfg.stt_model, "stt_device": cfg.stt_device, "stt_compute": cfg.stt_compute,
            "detail": 'Chưa cài faster-whisper tại backend. Cài requirements-voice.txt.' if not stt else (local or {}).get('detail'),
            "max_seconds": cfg.max_seconds,
            "greeting": "Chào bạn, mình có thể giúp bạn tìm hiểu thông tin về bệnh phổi. Bạn muốn hỏi điều gì?"}


@app.post("/api/v1/voice/transcribe")
async def transcribe_voice(file: UploadFile = File(...), mode: str = Form('fast')):
    if mode not in {'fast', 'careful'}:
        raise HTTPException(422, 'Chế độ nhận dạng không hợp lệ.')
    try:
        content = await file.read(app.state.voice.settings.max_bytes + 1)
    finally:
        await file.close()
    if len(content) > app.state.voice.settings.max_bytes:
        raise HTTPException(413, "Âm thanh vượt quá 12 MB.")
    if not content:
        raise HTTPException(422, "Âm thanh trống. Hãy thu lại.")
    try:
        started = time.monotonic()
        result = await asyncio.to_thread(app.state.voice.transcribe, content, **({'mode': mode} if mode != 'fast' else {}))
        logger.info('voice.stage stage=stt_complete elapsed_ms=%.0f', (time.monotonic()-started)*1000)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("voice.stt_failed error_type=%s", type(exc).__name__)
        raise HTTPException(503, "STT chưa sẵn sàng. Kiểm tra model và cấu hình VOICE_STT tại backend.") from exc


@app.post("/api/v1/voice/speech")
async def voice_speech(payload: SpeechRequest):
    try:
        audio = await app.state.voice.speech(payload.text)
        return Response(audio, media_type="audio/wav" if app.state.voice.settings.tts_provider == 'vieneu' else "audio/mpeg", headers={"Cache-Control": "no-store"})
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("voice.tts_failed error_type=%s", type(exc).__name__)
        raise HTTPException(502, "Chưa phát được âm thanh. Câu trả lời vẫn ở khung chat; hãy kiểm tra TTS hoặc thử phát lại.") from exc


@app.post('/api/v1/voice/speech/stream')
async def stream_voice_speech(payload: SpeechRequest):
    iterator = app.state.voice.speech_stream(payload.text)
    # Fetch one chunk before sending HTTP 200 so offline/invalid-voice errors are JSON.
    try:
        first = await anext(iterator)
    except HTTPException:
        await iterator.aclose()
        raise
    except Exception as exc:
        await iterator.aclose()
        logger.error('voice.tts_failed error_type=%s', type(exc).__name__)
        raise HTTPException(502, 'VieNeu chưa tạo được âm thanh. Kiểm tra server và tên giọng; câu trả lời vẫn được giữ trong chat.') from exc

    async def body():
        try:
            yield first
            async for chunk in iterator:
                yield chunk
        finally:
            await iterator.aclose()
    return StreamingResponse(body(), media_type='audio/pcm', headers={
        'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no',
        'X-Audio-Sample-Rate': '48000', 'X-Audio-Channels': '1', 'X-Audio-Format': 's16le'})


async def _voice_reply(conversation_id: str, full=False):
    conversation = app.state.store.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(404, "Không tìm thấy cuộc trò chuyện.")
    message = next((m for m in reversed(conversation["messages"]) if m["role"] == "assistant"), None)
    if not message:
        raise HTTPException(404, "Chưa có câu trả lời để đọc.")
    state = conversation.get("assessment")
    speech = await app.state.voice.compose(app.state.llm, message, state, full=full)
    return {"conversation": conversation, "message": message, "assessment": state,
            "display_text": message["content"], **speech}


@app.get("/api/v1/voice/reply/{conversation_id}")
async def voice_reply(conversation_id: str, full: bool = False):
    async with app.state.assessments.chat_lock(conversation_id):
        return await _voice_reply(conversation_id, full)


@app.post("/api/v1/voice/turn")
async def voice_turn(payload: VoiceTurn, background_tasks: BackgroundTasks):
    return await _voice_turn(payload, background_tasks)


async def _voice_turn(payload: VoiceTurn, background_tasks: BackgroundTasks, on_sentence=None):
    # Every spoken transcript has been explicitly reviewed by the user in the UI.
    async with app.state.assessments.chat_lock(payload.conversationId):
        state = app.state.store.latest_assessment(payload.conversationId)
        if state and payload.messageId in state["action_ids"]:
            return await _voice_reply(payload.conversationId)
        conversation = app.state.store.get_conversation(payload.conversationId)
        if conversation and any(m["id"] == payload.messageId for m in conversation["messages"]):
            return await _voice_reply(payload.conversationId)
        if state and state["status"] not in TERMINAL:
            if payload.assessmentVersion != state["version"]:
                raise HTTPException(409, "Dữ kiện đã thay đổi. Hãy nghe và kiểm tra lại trước khi xác nhận.")
            action = voice_action(state, payload.transcript)
            if action is None:
                script = assessment_script(state)
                script["spoken_text"] = "Tôi chưa nhận được câu xác nhận rõ ràng. " + script["spoken_text"]
                return {"conversation": conversation, "assessment": state, "message": None,
                        "display_text": script["spoken_text"], **script}
            action.update(action_id=payload.messageId, version=state["version"])
            state = await app.state.assessments.action(state["id"], AssessmentAction(**action))
            if state["status"] == "running":
                background_tasks.add_task(app.state.assessments.run, state["id"])
            return await _voice_reply(payload.conversationId)
        if payload.transcript.strip().casefold().rstrip(".!?") == "nghe tiếp" and conversation:
            return await _voice_reply(payload.conversationId, full=True)
        result = await _chat_message(ChatRequest(conversationId=payload.conversationId,
            message={"id": payload.messageId, "role": "user", "content": payload.transcript}), voice=True, on_sentence=on_sentence)
        if isinstance(result, Response):
            return result
        return await _voice_reply(payload.conversationId)


@app.post('/api/v1/voice/turn/stream')
async def stream_voice_turn(payload: VoiceTurn, background_tasks: BackgroundTasks):
    async def events():
        queue = asyncio.Queue(maxsize=12)
        started = time.monotonic()
        count = 0

        async def sentence(text):
            nonlocal count
            count += 1
            await queue.put({'type': 'sentence', 'index': count-1, 'text': text})
            if count == 1:
                logger.info('voice.stage message_id=%s stage=first_spoken_sentence elapsed_ms=%.0f', payload.messageId, (time.monotonic()-started)*1000)

        async def run():
            try:
                result = await _voice_turn(payload, background_tasks, sentence)
                if isinstance(result, Response):
                    await queue.put({'type': 'error', 'status': result.status_code, 'detail': json.loads(result.body).get('detail')})
                else:
                    await queue.put({'type': 'complete', 'reply': result, 'streamed_sentences': count})
                    logger.info('voice.stage message_id=%s stage=turn_complete elapsed_ms=%.0f', payload.messageId, (time.monotonic()-started)*1000)
            except HTTPException as exc:
                await queue.put({'type': 'error', 'status': exc.status_code, 'detail': exc.detail})
            except Exception as exc:
                logger.error('voice.turn_failed message_id=%s error_type=%s', payload.messageId, type(exc).__name__)
                await queue.put({'type': 'error', 'status': 502, 'detail': 'Chưa hoàn tất câu trả lời. Kiểm tra dịch vụ rồi gửi lại.'})

        task = asyncio.create_task(run())
        try:
            while True:
                event = await queue.get()
                yield json.dumps(event, ensure_ascii=False) + '\n'
                if event['type'] in {'complete', 'error'}:
                    break
            await task
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    return StreamingResponse(events(), media_type='application/x-ndjson', background=background_tasks,
        headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})


ALLOWED_RECORD_EXTENSIONS = {".txt"}


def attachment_response(row: dict) -> dict:
    return {
        "id": row["id"], "serverId": row["id"], "type": row.get("attachment_type", "medical_record"),
        "fileName": row["file_name"], "fileSize": row["file_size"],
        "mimeType": row["mime_type"], "status": row["status"],
        "progress": 100, "error": row.get("error"),
        "analysisAnswer": row.get("analysis_answer"),
        "sources": json.loads(row.get("analysis_sources") or "[]"),
    }


async def analyze_uploaded_record(attachment_id: str) -> None:
    started = time.monotonic()
    row = app.state.store.get_attachment(attachment_id)
    if row is None:
        return
    logger.info("clinical_file.start attachment_id=%s", attachment_id)
    try:
        content = await asyncio.to_thread(Path(row["stored_path"]).read_bytes)
        result = await app.state.modules.clinical_analyze_file(row["file_name"], content, row["mime_type"])
        logger.info("clinical_file.stage stage=qwen_summary attachment_id=%s", attachment_id)
        pack = prepare_evidence({"route": "MEDICAL_RECORD_ANALYSIS", "clinical_ie_analysis": result})
        try:
            answer = await app.state.llm.generate(
                "Hãy tóm tắt kết quả phân tích bệnh án bằng tiếng Việt. Nêu các dữ kiện lâm sàng, xét nghiệm và nhận định hỗ trợ đánh giá nếu chúng có trong kết quả. Chỉ dựa trên dữ liệu được cung cấp; phân biệt rõ thông tin trích xuất với nhận định của mô hình; không khẳng định chẩn đoán xác định và nói rõ nếu dữ liệu chưa đủ.",
                pack.payload,
            )
        except Exception as exc:
            answer = "Clinical IE đã phân tích bệnh án, nhưng Qwen chưa tạo được phần tóm tắt. Hãy kiểm tra Ollama rồi tải lại tệp."
            logger.error("clinical_file.qwen_failed attachment_id=%s error_type=%s", attachment_id, type(exc).__name__)
        app.state.store.set_attachment_analysis(attachment_id, "processed", result=result, answer=validate_answer(answer,pack.sources),sources=pack.sources)
        logger.info("clinical_file.done attachment_id=%s elapsed=%.1fs", attachment_id, time.monotonic()-started)
    except Exception as exc:
        if isinstance(exc, httpx.TimeoutException):
            message = "Clinical IE xử lý quá thời gian chờ. Kiểm tra log Clinical IE rồi tải lại tệp."
        elif isinstance(exc, httpx.HTTPStatusError):
            message = f"Clinical IE trả HTTP {exc.response.status_code}. Kiểm tra log Clinical IE và định dạng bệnh án."
        else:
            message = "Không xử lý được bệnh án qua Clinical IE. Kiểm tra kết nối và log dịch vụ."
        app.state.store.set_attachment_analysis(attachment_id, "error", error=message)
        logger.error("clinical_file.failed attachment_id=%s elapsed=%.1fs error_type=%s", attachment_id, time.monotonic()-started, type(exc).__name__)


@app.post("/api/v1/files/medical-record", status_code=202)
async def upload_medical_record(background_tasks: BackgroundTasks, file: UploadFile = File(...), clientId: str = Form(...)):
    del clientId  # Retained for frontend contract; server IDs are generated independently.
    original_name = Path(file.filename or "record.bin").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_RECORD_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Unsupported medical-record file type.")
    attachment_id = str(uuid4())
    stored_path = settings.upload_dir / f"{attachment_id}{suffix}"
    total = 0
    try:
        with stored_path.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > settings.max_upload_bytes:
                    output.close()
                    stored_path.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail="Uploaded file exceeds the configured size limit.")
                output.write(chunk)
    finally:
        await file.close()
    if total == 0:
        stored_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")

    mime_type = file.content_type or "application/octet-stream"
    app.state.store.add_attachment({
        "id": attachment_id,
        "file_name": original_name,
        "mime_type": mime_type,
        "file_size": total,
        "stored_path": str(stored_path),
    })
    app.state.store.set_attachment_analysis(attachment_id, "processing")
    background_tasks.add_task(analyze_uploaded_record, attachment_id)
    return attachment_response(app.state.store.get_attachment(attachment_id))


@app.post("/api/v1/files/xray")
async def xray_not_enabled():
    raise HTTPException(status_code=501, detail="X-ray upload is not enabled in this backend version.")


@app.get("/api/v1/files/{attachment_id}")
async def get_file_status(attachment_id: str):
    row = app.state.store.get_attachment(attachment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="File not found.")
    return attachment_response(row)


@app.get("/api/v1/conversations")
async def list_conversations():
    return app.state.store.list_conversations()


@app.get("/api/v1/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    conversation = app.state.store.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return conversation


@app.patch("/api/v1/conversations/{conversation_id}")
async def rename_conversation(conversation_id: str, body: dict):
    title = body.get("title")
    if not isinstance(title, str) or not title.strip():
        raise HTTPException(status_code=422, detail="title must be a non-empty string")
    if not app.state.store.rename(conversation_id, title):
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return {"ok": True}


@app.delete("/api/v1/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    async with app.state.assessments.chat_lock(conversation_id):
        state = app.state.store.latest_assessment(conversation_id)
        if state and state["status"] == "running":
            raise HTTPException(409, "Lượt đánh giá đang xử lý. Hãy chờ hoàn tất trước khi xóa cuộc trò chuyện.")
        if state:
            async with app.state.assessments.locks.setdefault(state["id"], asyncio.Lock()):
                # Recheck after waiting for a concurrent confirmation request.
                state = app.state.store.get_assessment(state["id"])
                if state and state["status"] == "running":
                    raise HTTPException(409, "Lượt đánh giá đang xử lý.")
                deleted = app.state.store.delete(conversation_id)
        else:
            deleted = app.state.store.delete(conversation_id)
        if not deleted:
            raise HTTPException(404, detail="Conversation not found.")
        return {"ok": True}



@app.get("/", include_in_schema=False)
async def index():
    from fastapi.responses import HTMLResponse
    return HTMLResponse("""<!doctype html><html lang="vi"><meta charset="utf-8"><title>Medical AI Backend</title>
    <style>body{font:18px system-ui;max-width:850px;margin:60px auto;padding:24px;line-height:1.8}a{color:#087c82}li{margin:10px}</style>
    <h1>Medical AI — Backend tích hợp</h1><p>Context, RAG và KG chạy trong cùng backend.</p><ul>
    <li><a href="/data">Quản lý dữ liệu: RAG · KG · Context · Báo cáo</a></li>
    <li><a href="/docs">API backend</a> · <a href="/api/v1/status">Trạng thái dịch vụ</a></li>
    <li><a href="/modules/context/ui">Context: kiểm tra history / patient</a> · <a href="/modules/context/docs">API Context</a></li>
    <li><a href="/modules/rag/">RAG: nhập tài liệu / tìm kiếm</a> · <a href="/modules/rag/docs">API RAG</a></li>
    <li><a href="/modules/kg-explorer/">KG: xem đồ thị / nhập dữ liệu</a> · <a href="/modules/kg/docs">API KG Retrieval</a></li>
    </ul></html>""")

app.state.embedded_apps = create_module_apps()
for module_name, module_app in app.state.embedded_apps.items():
    app.mount(MOUNTS[module_name], module_app, name=module_name)
