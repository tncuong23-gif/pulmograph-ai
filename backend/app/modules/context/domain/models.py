from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class StatementType(StrEnum):
    FACT = "fact"
    QUESTION = "question"
    PLAN = "plan"
    HYPOTHESIS = "hypothesis"


class FactType(StrEnum):
    CONDITION = "condition"
    SYMPTOM = "symptom"
    MEDICATION = "medication"
    ALLERGY = "allergy"
    OBSERVATION = "observation"
    LAB_RESULT = "lab_result"
    PROCEDURE = "procedure"
    FAMILY_HISTORY = "family_history"
    LIFESTYLE = "lifestyle"


class Certainty(StrEnum):
    CONFIRMED = "confirmed"
    PROBABLE = "probable"
    POSSIBLE = "possible"
    UNKNOWN = "unknown"


class AssertionType(StrEnum):
    EXPLICIT = "explicit"
    RESOLVED = "resolved"
    INFERRED = "inferred"


class HistoryMention(BaseModel):
    text: str
    entity_type: str
    canonical_name: str
    entity_id: str | None = None
    start: int | None = None
    end: int | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    # Where the mention came from. v2.3 uses this to distinguish an entity
    # explicitly named by the user from one propagated by coreference.
    origin: Literal[
        "explicit",
        "resolved_reference",
        "clinical_candidate",
        "legacy_inferred",
    ] = "explicit"


class HistoryTurn(BaseModel):
    patient_id: str
    session_id: str
    message_id: str
    role: Role
    original_text: str
    normalized_text: str | None = None
    created_at: datetime
    mentions: list[HistoryMention] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DiscourseEntityCandidate(BaseModel):
    canonical_name: str
    entity_type: str
    source_message_id: str | None = None
    source_role: Role | None = None
    source_text: str | None = None
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    mention_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    # Smaller number means stronger discourse priority. The ranker first
    # compares priority tiers and only then compares numeric score.
    priority_tier: int = Field(default=4, ge=1, le=5)
    origin: str = "explicit"
    turn_distance: int | None = Field(default=None, ge=0)
    focus_reason: str | None = None


class ResolvedReference(BaseModel):
    reference: str
    resolved_to: str | None = None
    entity_type: str | None = None
    source_message_id: str | None = None
    resolved: bool = True
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ResolvedQuestion(BaseModel):
    original_question: str
    normalized_question: str
    subject: str = "patient"
    resolved_references: list[ResolvedReference] = Field(default_factory=list)
    temporal_context: list[dict[str, Any]] = Field(default_factory=list)
    used_history_turn_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    resolution_status: Literal["resolved", "unresolved", "not_needed"] = "not_needed"
    resolution_method: str = "unknown"
    candidate_entities: list[DiscourseEntityCandidate] = Field(default_factory=list)
    active_topic: DiscourseEntityCandidate | None = None


class ClinicalFact(BaseModel):
    fact_type: FactType
    display: str
    concept_id: str | None = None
    concept_system: str | None = None

    value: Any | None = None
    unit: str | None = None
    dose: str | None = None
    frequency: str | None = None
    route: str | None = None

    status: str | None = None
    negated: bool = False
    certainty: Certainty = Certainty.CONFIRMED
    experiencer: str = "patient"

    valid_from: datetime | None = None
    valid_to: datetime | None = None
    recorded_at: datetime

    assertion: AssertionType = AssertionType.EXPLICIT
    statement_type: StatementType = StatementType.FACT
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    source_message_id: str
    source_text: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("display")
    @classmethod
    def display_must_not_be_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("display must not be empty")
        return value


class PatientContext(BaseModel):
    patient_id: str
    facts: list[ClinicalFact] = Field(default_factory=list)


class ProcessRequest(BaseModel):
    persist_patient_facts: bool = False
    patient_id: str
    session_id: str
    message_id: str
    question: str = Field(min_length=1)
    timestamp: datetime


class ProcessResponse(BaseModel):
    draft_facts: list[ClinicalFact] = Field(default_factory=list)
    patient_facts: list[ClinicalFact] = Field(default_factory=list)
    normalized_question: str
    resolved_subject: str
    resolved_references: list[ResolvedReference]
    context_turn_ids: list[str]
    resolution_confidence: float
    resolution_status: Literal["resolved", "unresolved", "not_needed"] = "not_needed"
    resolution_method: str = "unknown"
    candidate_entities: list[DiscourseEntityCandidate] = Field(default_factory=list)
    active_topic: DiscourseEntityCandidate | None = None
    patient_graph_updated: bool
    stored_fact_count: int
