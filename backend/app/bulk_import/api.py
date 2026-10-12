from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from .context import ContextAdapter
from .kg import KGAdapter
from .manager import BatchManager, ImportBusy, MAX_BYTES, MAX_FILES

Module = Literal['kg', 'context']
ROOT = Path(__file__).resolve().parents[2]
WEB = Path(__file__).parent / 'web'
log = logging.getLogger('uvicorn.error')


class JobRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mode: Literal['validate', 'preview', 'commit', 'retry', 'index'] = 'preview'
    source: Literal['directory', 'files'] = 'directory'
    files: list[str] | None = Field(default=None, max_length=MAX_FILES)
    previous_job_id: str | None = None
    confirmed: bool = False
    file_errors: dict[str, str] = Field(default_factory=dict, max_length=MAX_FILES)


class Decisions(BaseModel):
    model_config = ConfigDict(extra='forbid')
    choices: dict[str, str]


def manager(request, module):
    app = request.app
    if module not in app.state.import_batches:
        if module == 'kg':
            def service():
                return app.state.embedded_apps['kg_explorer'].state.get_import_service()
            adapter = KGAdapter(service)
        else:
            def container():
                state = app.state.embedded_apps['context'].state
                if not getattr(state, 'available', False) or not getattr(state, 'container', None):
                    raise ValueError('Context chưa khởi tạo thành công. Kiểm tra module.startup_failed và Neo4j, rồi khởi động lại backend.')
                return state.container
            adapter = ContextAdapter(container)
        data = Path(os.getenv('BATCH_DATA_ROOT', str(ROOT / 'data')))
        app.state.import_batches[module] = BatchManager(module, adapter, data / 'import' / module,
                                                        data / 'import_reports' / module)
    return app.state.import_batches[module]


def fail(exc):
    if isinstance(exc, ImportBusy):
        raise HTTPException(409, str(exc))
    if isinstance(exc, (KeyError, IndexError)):
        raise HTTPException(404, 'Không tìm thấy lượt nạp hoặc file trong lượt.')
    if isinstance(exc, ValueError):
        raise HTTPException(422, str(exc))
    log.exception('batch.api_failed')
    raise HTTPException(503, 'Chưa thực hiện được thao tác. Kiểm tra log, kết nối CSDL và thư mục dữ liệu.')


def create_router():
    router = APIRouter()

    @router.get('/imports', include_in_schema=False)
    async def page():
        return FileResponse(WEB / 'index.html', headers={'Cache-Control': 'no-store'})

    @router.get('/imports-assets/{filename}', include_in_schema=False)
    async def asset(filename: Literal['app.js', 'style.css']):
        return FileResponse(WEB / filename, headers={'Cache-Control': 'no-cache'})

    @router.get('/api/v1/imports/{module}/jobs')
    async def jobs(module: Module, request: Request):
        try:
            return manager(request, module).list()
        except Exception as exc:
            fail(exc)

    @router.post('/api/v1/imports/{module}/jobs', status_code=202)
    async def start(module: Module, body: JobRequest, request: Request):
        try:
            return manager(request, module).start(**body.model_dump())
        except Exception as exc:
            fail(exc)

    @router.get('/api/v1/imports/{module}/jobs/{job_id}')
    async def job(module: Module, job_id: str, request: Request):
        try:
            return manager(request, module).get(job_id)
        except Exception as exc:
            fail(exc)

    @router.get('/api/v1/imports/{module}/jobs/{job_id}/report')
    async def report(module: Module, job_id: str, request: Request, kind: Literal['json', 'csv', 'errors'] = 'json'):
        try:
            path = manager(request, module).report(job_id, kind)
            return FileResponse(path, filename=path.name)
        except Exception as exc:
            fail(exc)

    @router.put('/api/v1/imports/{module}/uploads/{filename:path}')
    async def upload(module: Module, filename: str, request: Request):
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > MAX_BYTES:
                raise HTTPException(413, 'Mỗi file tối đa 20 MiB.')
        try:
            return manager(request, module).upload(filename, content)
        except Exception as exc:
            fail(exc)

    @router.get('/api/v1/imports/{module}/jobs/{job_id}/items/{position}/preview')
    async def preview(module: Module, job_id: str, position: int, request: Request):
        try:
            if position < 0:
                raise IndexError(position)
            return await manager(request, module).review(job_id, position)
        except Exception as exc:
            fail(exc)

    @router.post('/api/v1/imports/{module}/jobs/{job_id}/items/{position}/decisions')
    async def decisions(module: Module, job_id: str, position: int, body: Decisions, request: Request):
        try:
            if position < 0:
                raise IndexError(position)
            return await manager(request, module).decisions(job_id, position, body.choices)
        except Exception as exc:
            fail(exc)

    return router
