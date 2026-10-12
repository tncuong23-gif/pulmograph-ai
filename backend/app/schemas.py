from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Attachment(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    type: Literal["medical_record", "xray"]
    fileName: str
    fileSize: int = 0
    mimeType: str = "application/octet-stream"
    status: str = "processed"
    progress: int = 100
    serverId: str | None = None
    error: str | None = None


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str = Field(default_factory=lambda: str(uuid4()))
    role: Literal["user", "assistant"] = "user"
    content: str = ""
    createdAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    attachments: list[Attachment] = Field(default_factory=list)

    @model_validator(mode="after")
    def content_or_attachment(self):
        self.content = self.content.strip()
        if not self.content and not self.attachments:
            raise ValueError("message content or an attachment is required")
        return self


class KGConfirmation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    message_id: str = Field(min_length=1, max_length=200)
    entity_ids: list[str] = Field(min_length=1, max_length=2)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    conversationId: str = Field(min_length=1, max_length=200)
    message: ChatMessage
    regenerateMessageId: str | None = None
    kg_confirmation: KGConfirmation | None = None


class UploadResponse(BaseModel):
    id: str
    serverId: str
    type: Literal["medical_record"]
    fileName: str
    fileSize: int
    mimeType: str
    status: Literal["pending", "processing", "processed", "error"] = "processing"
    error: str | None = None
    progress: int = 100


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ApiError(BaseModel):
    code: str
    message: str
    request_id: str
    details: dict[str, Any] | None = None
