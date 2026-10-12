from __future__ import annotations

from typing import Protocol

from app.modules.context.domain.models import ClinicalFact, HistoryMention, HistoryTurn, PatientContext, ResolvedQuestion


class QuestionResolver(Protocol):
    async def resolve(
        self,
        *,
        question: str,
        history_context: list[HistoryTurn],
        patient_context: PatientContext,
    ) -> ResolvedQuestion: ...


class DiscourseEntityExtractor(Protocol):
    async def extract(
        self,
        *,
        text: str,
        clinical_candidates: list[ClinicalFact] | None = None,
    ) -> list[HistoryMention]: ...


class ClinicalExtractor(Protocol):
    async def extract(
        self,
        *,
        patient_id: str,
        message_id: str,
        timestamp,
        original_question: str,
        resolved_question: ResolvedQuestion,
        history_context: list[HistoryTurn],
    ) -> list[ClinicalFact]: ...


class ClinicalTerminologyNormalizer(Protocol):
    async def normalize_facts(self, facts: list[ClinicalFact]) -> list[ClinicalFact]: ...
