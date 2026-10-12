"""Local query UI and reviewed KG import workspace.

Run from the project root: python -m uvicorn kg_query.web_app:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import logging
import secrets
import time
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from app.modules.kg_import.config import Settings
from app.modules.kg_import.service import IMPORT_LOCK
from app.modules.kg_import.utils import sha256_of
from app.modules.kg_query.intents import PRESET_CHAINS, describe_intents
from app.modules.kg_query.models import QuerySpec

log = logging.getLogger(__name__)
WEB = Path(__file__).with_name("web")


def create_app(service: Any | None = None, *, review_service: Any | None = None,
               import_service: Any | None = None) -> FastAPI:
    app = FastAPI(title="Medical KG Explorer", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=WEB), name="static")
    app.state.query_service = service
    app.state.resources = None
    app.state.import_service = import_service
    app.state.import_resources = None
    app.state.review_service = review_service
    app.state.preview_tokens = {}
    app.state.document_reviews = None

    def review_store():
        if app.state.document_reviews is None:
            from app.modules.kg_import.review_store import DocumentReviewStore
            app.state.document_reviews = DocumentReviewStore()
        return app.state.document_reviews

    def add_preview_token(response, payload):
        if response.get('status') == 'dry_run' and not (response.get('plan') or {}).get('entity_candidates'):
            now = time.monotonic()
            app.state.preview_tokens = {key: value for key, value in app.state.preview_tokens.items() if value[1] > now}
            if len(app.state.preview_tokens) >= 256: app.state.preview_tokens.pop(next(iter(app.state.preview_tokens)))
            token = secrets.token_urlsafe(32)
            app.state.preview_tokens[token] = (sha256_of(payload), now + 600)
            response['preview_token'] = token
        return response

    query_lock = Lock()

    def get_service():
        with query_lock:
            if app.state.query_service is None:
                from app.modules.kg_query.factory import build_query_resources
                app.state.resources = build_query_resources(Settings.from_env())
                app.state.query_service = app.state.resources.service
            return app.state.query_service

    app.state.get_query_service = get_service

    def get_import_service():
        with IMPORT_LOCK:
            if app.state.import_service is None:
                from app.modules.kg_import.factory import build_resources
                app.state.import_resources = build_resources(Settings.from_env())
                app.state.import_service = app.state.import_resources.service
            return app.state.import_service

    app.state.get_import_service = get_import_service

    def get_review_service():
        if app.state.review_service is None:
            from app.modules.kg_query.duplicate_review import DuplicateReviewService
            imp = get_import_service()
            app.state.review_service = DuplicateReviewService(imp.graph, imp.entity_index)
        return app.state.review_service

    @app.on_event("shutdown")
    def close_resources():
        if app.state.resources is not None:
            app.state.resources.close()
        if app.state.import_resources is not None:
            app.state.import_resources.close()
        if app.state.document_reviews is not None: app.state.document_reviews.close()

    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html")

    @app.get("/duplicates")
    def duplicates():
        return FileResponse(WEB / "duplicates.html")

    @app.get("/api/review/scan")
    async def review_scan(mode: str = "embedding", max_entities: int = 500, entity_type: str = "",
                          min_score: float = 0.70):
        if mode not in ("exact", "embedding") or not 1 <= max_entities <= 5000 or len(entity_type) > 80 or not 0.5 <= min_score <= 1.0:
            return JSONResponse({"error": "Tham số quét không hợp lệ."}, status_code=400)
        try:
            return await run_in_threadpool(get_review_service().scan, mode=mode, max_entities=max_entities,
                                           entity_type=entity_type, min_score=min_score)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception:
            log.exception("Duplicate scan failed")
            return JSONResponse({"error": "Không thể quét thực thể. Kiểm tra Neo4j và Qdrant."}, status_code=503)

    @app.get("/api/review/entities/{entity_id}")
    async def review_entity(entity_id: str):
        if len(entity_id) > 256:
            return JSONResponse({"error": "ID quá dài."}, status_code=400)
        try:
            result = await run_in_threadpool(get_review_service().detail, entity_id)
            return result if result is not None else JSONResponse({"error": "Không tìm thấy thực thể."}, status_code=404)
        except Exception:
            log.exception("Duplicate entity detail failed")
            return JSONResponse({"error": "Không thể đọc chi tiết thực thể."}, status_code=503)

    async def read_review_json(request: Request):
        try:
            import json
            max_bytes = 20 * 1024 * 1024
            if int(request.headers.get("content-length", "0")) > max_bytes:
                raise ValueError("File JSON vượt quá 20 MB.")
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise ValueError("File JSON vượt quá 20 MB.")
            payload = json.loads(body.decode("utf-8-sig"))
            if not isinstance(payload, dict):
                raise ValueError("File phải chứa đối tượng JSON.")
        except (ValueError, UnicodeDecodeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return payload

    @app.post("/api/review/preview")
    async def review_preview(request: Request):
        payload = await read_review_json(request)
        if isinstance(payload, JSONResponse):
            return payload
        try:
            result = await run_in_threadpool(get_import_service().preview_kg, payload)
            response = result.to_dict()
            response.update(review_store().status(payload, get_import_service().review_profile(),
                needs_review=bool((result.plan or {}).get('entity_candidates'))))
            add_preview_token(response, payload)
            return JSONResponse(response, status_code=result.http_status)
        except Exception:
            log.exception("Import preview failed")
            return JSONResponse({"error": "Không thể lập kế hoạch import. Kiểm tra các cơ sở dữ liệu."}, status_code=503)

    @app.post('/api/review/decisions')
    async def save_document_review(request: Request):
        body = await read_review_json(request)
        if isinstance(body, JSONResponse): return body
        payload, choices = body.get('payload'), body.get('choices')
        if not isinstance(payload, dict) or not isinstance(choices, dict):
            return JSONResponse({'error': 'Thiếu tài liệu hoặc lựa chọn duyệt.'}, status_code=400)
        try:
            from app.bulk_import.kg import KGAdapter
            adapter = KGAdapter(get_import_service)
            updated = await adapter.decisions(payload, choices)
            preview = await adapter.review(updated, refresh=True)
            if preview['plan'].get('entity_candidates'): raise ValueError('Có thêm thực thể cần duyệt. Hãy kiểm tra lại tài liệu.')
            response = {'status': 'dry_run', **preview, 'payload': updated,
                        **review_store().mark(updated, adapter.review_profile())}
            return add_preview_token(response, updated)
        except ValueError as exc:
            return JSONResponse({'error': str(exc)}, status_code=422)
        except Exception:
            log.exception('Document review save failed')
            return JSONResponse({'error': 'Chưa lưu được trạng thái duyệt. Kiểm tra kết nối và log backend.'}, status_code=503)

    @app.post("/api/review/import")
    async def review_import(request: Request):
        body = await read_review_json(request)
        if isinstance(body, JSONResponse):
            return body
        payload, token = body.get("payload"), body.get("preview_token")
        if not isinstance(payload, dict) or not isinstance(token, str) or len(token) > 128:
            return JSONResponse({"error": "Thiếu file JSON hoặc mã xác nhận dry-run."}, status_code=400)
        stamp = app.state.preview_tokens.pop(token, None)
        if stamp is None or stamp[1] <= time.monotonic() or stamp[0] != sha256_of(payload):
            return JSONResponse({"error": "Bản xem trước đã hết hạn hoặc file đã thay đổi. Hãy kiểm tra lại."}, status_code=409)
        try:
            result = await run_in_threadpool(get_import_service().import_kg, payload, "upsert", dry_run=False)
            return JSONResponse(result.to_dict(), status_code=result.http_status)
        except Exception:
            log.exception("Reviewed import failed")
            return JSONResponse({"error": "Không thể hoàn tất import. Kiểm tra log và trạng thái import."}, status_code=503)

    @app.get("/api/meta")
    def meta():
        return {"intents": [{"id": key, "description": desc} for key, desc in describe_intents()],
                "presets": list(PRESET_CHAINS)}

    @app.get("/api/health")
    async def health():
        try:
            await run_in_threadpool(get_service().ping)
        except Exception:
            log.exception("KG connection unavailable")
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return {"status": "connected"}

    @app.post("/api/query")
    async def query(request: Request):
        try:
            if int(request.headers.get("content-length", "0")) > 8192:
                raise ValueError("Yêu cầu quá lớn.")
            body = await request.body()
            if len(body) > 8192:
                raise ValueError("Yêu cầu quá lớn.")
            import json
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError("Dữ liệu truy vấn phải là đối tượng JSON.")
            mentions = payload.get("mentions")
            if not isinstance(mentions, list) or not 1 <= len(mentions) <= 2 or any(
                not isinstance(m, str) or not m.strip() or len(m) > 160 for m in mentions
            ):
                raise ValueError("Nhập một hoặc hai tên thực thể, tối đa 160 ký tự mỗi tên.")
            if payload.get("path") and len(mentions) != 2:
                raise ValueError("Đường đi cần hai thực thể.")
            if not isinstance(payload.get("intents", []), list):
                raise ValueError("Danh sách nhóm quan hệ không hợp lệ.")
            if len(payload.get("intents", [])) > 6 or any(
                not isinstance(i, str) or len(i) > 40 for i in payload.get("intents", [])
            ):
                raise ValueError("Nhóm quan hệ không hợp lệ.")
            if payload.get("chain") and payload["chain"] not in PRESET_CHAINS:
                raise ValueError("Chuỗi truy vấn không hợp lệ.")
            limit = int(payload.get("limit", 60))
            max_hops = int(payload.get("max_hops", 3))
            if not 1 <= limit <= 200 or not 1 <= max_hops <= 4:
                raise ValueError("Giới hạn truy vấn không hợp lệ.")
            spec = QuerySpec.from_dict({"mentions": mentions, "intents": payload.get("intents", []),
                                        "chain": payload.get("chain"), "path": payload.get("path", False),
                                        "limit": limit, "max_hops": max_hops}, PRESET_CHAINS)
        except (ValueError, TypeError, KeyError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        try:
            result = await run_in_threadpool(get_service().run, spec)
            return result.to_dict()
        except Exception:
            log.exception("KG query failed")
            return JSONResponse({"error": "Không thể truy vấn cơ sở dữ liệu. Kiểm tra kết nối Neo4j và MongoDB."},
                                status_code=503)

    return app


app = create_app()
