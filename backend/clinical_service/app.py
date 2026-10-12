"""Private HTTP adapter for the bundled library; no public paths or auto-fallback."""
import asyncio
import logging
import tempfile
from pathlib import Path
from uuid import uuid4
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ConfigDict
from app.services.clinical_inputs import MAX_FILE, MAX_TEXT, decode_txt, validate_modalities, validate_image, validate_text
from .runtime import ClinicalRuntime

load_dotenv(Path(__file__).resolve().parents[1]/'.env')
logger = logging.getLogger('uvicorn.error')


def create_app(runtime=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.gate = asyncio.Lock()
        yield
    app = FastAPI(title='Clinical IE 0.2 local service', lifespan=lifespan)
    app.state.runtime = runtime or ClinicalRuntime()

    @app.get('/health')
    async def health():
        missing = app.state.runtime.inventory()
        return JSONResponse({'status':'degraded' if missing else 'available',
            'capabilities':{'text':not missing,'text_xray':not missing,
                            'xray':not any(x.startswith('fusion/') for x in missing)},
            'missing_files':missing,'models_loaded':bool(getattr(app.state.runtime,'assistant',None)),
            'note':'Inventory only; inference verifies checksums and runtime dependencies.'}, status_code=503 if missing else 200)

    async def run(text=None, image=None, same_case=False, symptom_query=False):
        try: validate_modalities(text, image, same_case)
        except ValueError as exc: raise HTTPException(422, str(exc)) from None
        try: await asyncio.wait_for(app.state.gate.acquire(), timeout=.1)
        except asyncio.TimeoutError: raise HTTPException(409, 'Clinical IE đang xử lý một ca khác. Hãy thử lại sau.') from None
        # Shield the thread: cancellation must not release the lock/delete the image while it is in use.
        task = None
        try:
            with tempfile.TemporaryDirectory(prefix='clinical_case_') as directory:
                path = None
                if image is not None:
                    path = Path(directory)/('xray'+validate_image(image)); path.write_bytes(image)
                task = asyncio.create_task(asyncio.to_thread(app.state.runtime.analyze, text=text, image_path=path,
                    document_id=str(uuid4()), symptom_query=symptom_query))
                try: return await asyncio.shield(task)
                except asyncio.CancelledError:
                    await task
                    raise
        except (RuntimeError, FileNotFoundError, ImportError) as exc:
            logger.exception('clinical.unavailable')
            missing = app.state.runtime.inventory()
            detail = 'Thiếu file model Clinical IE: '+', '.join(missing) if missing else 'Clinical IE chưa nạp được model. Kiểm tra dependency và CLINICAL_DEVICE của dịch vụ.'
            raise HTTPException(503, detail) from None
        except ValueError:
            raise HTTPException(422, 'Bundle hoặc đầu vào Clinical IE không hợp lệ. Kiểm tra manifest/checksum và định dạng dữ liệu.') from None
        finally: app.state.gate.release()

    async def read_file(file):
        if file is None: return None
        try:
            content = await file.read(MAX_FILE+1)
            if len(content)>MAX_FILE: raise HTTPException(413, 'File vượt 20 MB.')
            return content
        finally: await file.close()

    @app.post('/api/v1/analyze')
    async def analyze(text: str | None = Form(None), file: UploadFile | None = File(None),
                      image: UploadFile | None = File(None), same_case: bool = Form(False)):
        try:
            if file is not None:
                if text and text.strip(): raise HTTPException(422, 'Chọn văn bản hoặc một file TXT, không gửi cả hai.')
                if Path(file.filename or '').suffix.lower() != '.txt': raise HTTPException(415, 'Chỉ hỗ trợ bệnh án TXT UTF-8.')
                text = decode_txt(await read_file(file))
            if text is not None and not text.strip(): text = None
            content = await read_file(image)
            return await run(text, content, same_case)
        except ValueError as exc: raise HTTPException(422, str(exc)) from None
        finally:
            if file: await file.close()
            if image: await image.close()

    @app.post('/api/v1/analyze-file')
    async def analyze_file(file: UploadFile = File(...)):
        return await analyze(file=file, text=None, image=None, same_case=False)

    class TextRequest(BaseModel):
        model_config = ConfigDict(extra='forbid')
        text: str = Field(min_length=1, max_length=MAX_TEXT)

    @app.post('/api/v1/ask-symptoms')
    async def symptoms(body: TextRequest):
        return await run(text=body.text, symptom_query=True)

    @app.post('/api/v1/analyze-text')
    async def analyze_text(body: TextRequest):
        return await run(text=body.text)
    return app

app = create_app()
