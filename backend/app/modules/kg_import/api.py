"""FastAPI router. Mount it in your existing app:

    from app.modules.kg_import.api import create_router
    app.include_router(create_router(lambda: resources.service, max_body_bytes=settings.limits.max_body_bytes))

If your project already exposes POST /api/v1/kg/import-json, replace that handler's body with a call to
`service.import_kg(...)` instead of registering a second route.
Never returns HTTP 200 for a failed import; never returns stack traces.
"""
from __future__ import annotations

import json
from typing import Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .errors import KGImportError
from .service import KGImportService


def _err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"status": "failed", "errors": [{"code": code, "message": message}]})


async def _read_json(request: Request, max_bytes: int):
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        return None, _err(413, "PAYLOAD_TOO_LARGE", f"body exceeds {max_bytes} bytes")
    body = b""
    async for chunk in request.stream():  # enforced even when Content-Length is absent/lying
        body += chunk
        if len(body) > max_bytes:
            return None, _err(413, "PAYLOAD_TOO_LARGE", f"body exceeds {max_bytes} bytes")
    try:
        return json.loads(body.decode("utf-8-sig")), None
    except (UnicodeDecodeError, ValueError):
        return None, _err(400, "MALFORMED_JSON", "request body is not valid UTF-8 JSON")


def create_router(get_service: Callable[[], KGImportService], max_body_bytes: int = 20 * 1024 * 1024) -> APIRouter:
    router = APIRouter(prefix="/api/v1/kg", tags=["kg-import"])

    @router.post("/import-json")
    async def import_json(request: Request, mode: str = "upsert", dry_run: bool = False):
        payload, error = await _read_json(request, max_body_bytes)
        if error:
            return error
        result = await run_in_threadpool(get_service().import_kg, payload, mode, dry_run=dry_run)
        return JSONResponse(status_code=result.http_status, content=result.to_dict())

    @router.post("/imports/{import_id}/retry")
    async def retry_import(import_id: str, request: Request):
        payload, error = await _read_json(request, max_body_bytes)
        if error:
            return error
        result = await run_in_threadpool(get_service().retry, import_id, payload)
        return JSONResponse(status_code=result.http_status, content=result.to_dict())

    @router.get("/imports/{import_id}")
    def import_status(import_id: str):
        try:
            job = get_service().get_status(import_id)
        except KGImportError:
            return _err(404, "IMPORT_NOT_FOUND", f"import '{import_id}' not found")
        job.pop("plan", None)
        job.pop("payload_hash", None)
        return job

    @router.get("/health")
    def health():
        svc, out, ok = get_service(), {}, True
        for name, store in (("mongodb", svc.docs), ("neo4j", svc.graph)):
            try:
                store.ping()
                out[name] = "connected"
            except Exception:  # noqa: BLE001 - details stay in server logs
                out[name], ok = "unavailable", False
        return JSONResponse(status_code=200 if ok else 503, content={"status": "ok" if ok else "degraded", **out})

    return router
