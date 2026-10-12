from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import HTTPException, APIRouter, Query, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

from app.modules.context.domain.models import ProcessRequest, ProcessResponse, Role

router = APIRouter()


UI_INDEX = Path(__file__).resolve().parents[1] / "ui" / "index.html"


@router.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/modules/context/ui")


@router.get("/ui", include_in_schema=False)
async def test_ui() -> FileResponse:
    return FileResponse(
        UI_INDEX,
        media_type="text/html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


class AddHistoryTurnRequest(BaseModel):
    patient_id: str
    session_id: str
    message_id: str
    role: Role
    text: str = Field(min_length=1)
    timestamp: datetime


@router.get("/health")
async def health(request: Request) -> dict:
    container = request.app.state.container
    return {
        "status": "ok",
        "graph_backend": container.settings.graph_backend,
        "app": container.settings.app_name,
        "context_resolver_version": "2.3",
    }


@router.post("/v1/context/resolve", response_model=ProcessResponse)
async def resolve_context(payload: ProcessRequest, request: Request) -> ProcessResponse:
    if payload.persist_patient_facts:
        raise HTTPException(422, "Dùng luồng đánh giá của backend để xác nhận trước khi ghi Patient Graph.")
    return await request.app.state.container.service.process(payload)


@router.post("/v1/history/turns", status_code=204, response_model=None, response_class=Response)
async def add_history_turn(payload: AddHistoryTurnRequest, request: Request) -> None:
    """Append a turn and extract discourse mentions for later coreference resolution."""
    await request.app.state.container.service.add_history_turn(
        patient_id=payload.patient_id,
        session_id=payload.session_id,
        message_id=payload.message_id,
        role=payload.role,
        text=payload.text,
        timestamp=payload.timestamp,
    )


@router.get("/v1/history")
async def get_history(
    request: Request,
    patient_id: str = Query(...),
    session_id: str = Query(...),
    query: str = Query(default=""),
    limit: int = Query(default=20, ge=1, le=100),
):
    turns = await request.app.state.container.history_repository.get_relevant_turns(
        patient_id=patient_id,
        session_id=session_id,
        query=query,
        limit=limit,
    )
    return {"items": [turn.model_dump(mode="json") for turn in turns]}


@router.get("/v1/patients/{patient_id}/context")
async def get_patient_context(
    patient_id: str,
    request: Request,
    query: str = Query(default=""),
    limit: int = Query(default=50, ge=1, le=200),
):
    context = await request.app.state.container.patient_repository.get_relevant_context(
        patient_id=patient_id,
        query=query,
        limit=limit,
    )
    return context.model_dump(mode="json")
