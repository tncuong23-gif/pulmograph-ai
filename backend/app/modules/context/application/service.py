from __future__ import annotations

from datetime import datetime
import logging

from app.modules.context.application.context_resolution import ContextResolutionValidator
from app.modules.context.application.patient_assertion import PatientAssertionGate
from app.modules.context.application.discourse import RuleBasedDiscourseEntityExtractor
from app.modules.context.application.text import normalize_whitespace
from app.modules.context.application.validator import ClinicalAssertionValidator
from app.modules.context.domain.models import (
    DiscourseEntityCandidate,
    HistoryMention,
    HistoryTurn,
    ProcessRequest,
    ProcessResponse,
    Role,
)
from app.modules.context.domain.repositories import HistoryRepository, PatientRepository
from app.modules.context.domain.services import (
    ClinicalExtractor,
    ClinicalTerminologyNormalizer,
    DiscourseEntityExtractor,
    QuestionResolver,
)


class MedicalContextService:
    def __init__(
        self,
        *,
        history_repository: HistoryRepository,
        patient_repository: PatientRepository,
        question_resolver: QuestionResolver,
        clinical_extractor: ClinicalExtractor,
        clinical_validator: ClinicalAssertionValidator,
        discourse_extractor: DiscourseEntityExtractor | None = None,
        terminology_normalizer: ClinicalTerminologyNormalizer | None = None,
        history_limit: int = 20,
        recent_history_limit: int = 6,
    ) -> None:
        self.history_repository = history_repository
        self.patient_repository = patient_repository
        self.question_resolver = question_resolver
        self.clinical_extractor = clinical_extractor
        self.discourse_extractor = discourse_extractor or RuleBasedDiscourseEntityExtractor()
        self.clinical_validator = clinical_validator
        self.terminology_normalizer = terminology_normalizer
        self.history_limit = history_limit
        self.recent_history_limit = max(1, recent_history_limit)
        self.resolution_validator = ContextResolutionValidator()
        self.patient_assertion_gate = PatientAssertionGate()

    async def process(self, request: ProcessRequest) -> ProcessResponse:
        question = normalize_whitespace(request.question)

        history_context = await self._get_context_window(
            patient_id=request.patient_id,
            session_id=request.session_id,
            query=question,
        )
        patient_context = await self.patient_repository.get_relevant_context(
            patient_id=request.patient_id,
            query=question,
        )

        resolved = await self.question_resolver.resolve(
            question=question,
            history_context=history_context,
            patient_context=patient_context,
        )
        resolved = self.resolution_validator.validate(resolved)

        if self.patient_assertion_gate.is_general_information_question(question):
            extracted = []
            logging.getLogger('uvicorn.error').info('context.stage clinical_extraction=skipped_general_question')
        else:
            extracted = await self.clinical_extractor.extract(
                patient_id=request.patient_id,
                message_id=request.message_id,
                timestamp=request.timestamp,
                original_question=question,
                resolved_question=resolved,
                history_context=history_context,
            )
        # Discourse mentions are independent from Patient Graph assertions. A disease
        # mentioned in a knowledge question can remain available for coreference without
        # becoming a diagnosis/clinical fact of the patient.
        mentions = await self.discourse_extractor.extract(
            text=question,
            clinical_candidates=extracted,
        )

        # Hard deterministic gate: only direct patient/family clinical assertions are
        # allowed to proceed to terminology normalization and Patient Graph validation.
        patient_candidates = self.patient_assertion_gate.filter(
            original_text=question,
            facts=extracted,
        )
        normalized_facts = (
            await self.terminology_normalizer.normalize_facts(patient_candidates)
            if self.terminology_normalizer is not None
            else patient_candidates
        )
        valid_facts = self.clinical_validator.validate(normalized_facts)
        mentions = self._merge_resolved_mentions(mentions, resolved.resolved_references)
        resolved = resolved.model_copy(
            update={
                "active_topic": self._post_turn_active_topic(
                    question=question,
                    message_id=request.message_id,
                    mentions=mentions,
                    inherited=resolved.active_topic,
                )
            }
        )

        # Persist the source turn before patient facts so Neo4j can create provenance.
        await self.history_repository.add_turn(
            HistoryTurn(
                patient_id=request.patient_id,
                session_id=request.session_id,
                message_id=request.message_id,
                role=Role.USER,
                original_text=question,
                normalized_text=resolved.normalized_question,
                created_at=request.timestamp,
                mentions=mentions,
                metadata={
                    "resolution_confidence": resolved.confidence,
                    "resolution_status": resolved.resolution_status,
                    "resolution_method": resolved.resolution_method,
                    "candidate_entities": [
                        c.model_dump(mode="json") for c in resolved.candidate_entities
                    ],
                    "active_topic": (
                        resolved.active_topic.model_dump(mode="json")
                        if resolved.active_topic is not None
                        else None
                    ),
                },
            )
        )

        stored_count = (
            await self.patient_repository.upsert_facts(
                patient_id=request.patient_id,
                facts=valid_facts,
            )
            if valid_facts and request.persist_patient_facts
            else 0
        )

        return ProcessResponse(
            draft_facts=valid_facts,
            patient_facts=patient_context.facts,
            normalized_question=resolved.normalized_question,
            resolved_subject=resolved.subject,
            resolved_references=resolved.resolved_references,
            context_turn_ids=resolved.used_history_turn_ids,
            resolution_confidence=resolved.confidence,
            resolution_status=resolved.resolution_status,
            resolution_method=resolved.resolution_method,
            candidate_entities=resolved.candidate_entities,
            active_topic=resolved.active_topic,
            patient_graph_updated=stored_count > 0,
            stored_fact_count=stored_count,
        )

    async def add_history_turn(
        self,
        *,
        patient_id: str,
        session_id: str,
        message_id: str,
        role: Role,
        text: str,
        timestamp: datetime,
    ) -> None:
        normalized = normalize_whitespace(text)
        mentions = await self.discourse_extractor.extract(
            text=normalized,
            clinical_candidates=None,
        )
        await self.history_repository.add_turn(
            HistoryTurn(
                patient_id=patient_id,
                session_id=session_id,
                message_id=message_id,
                role=role,
                original_text=normalized,
                normalized_text=normalized,
                created_at=timestamp,
                mentions=mentions,
            )
        )

    async def _get_context_window(
        self,
        *,
        patient_id: str,
        session_id: str,
        query: str,
    ) -> list[HistoryTurn]:
        recent_limit = min(self.recent_history_limit, self.history_limit)
        relevant_limit = max(0, self.history_limit - recent_limit)

        recent = await self.history_repository.get_recent_turns(
            patient_id=patient_id,
            session_id=session_id,
            limit=recent_limit,
        )
        relevant = (
            await self.history_repository.get_relevant_turns(
                patient_id=patient_id,
                session_id=session_id,
                query=query,
                limit=relevant_limit,
            )
            if relevant_limit > 0
            else []
        )

        merged: dict[str, HistoryTurn] = {}
        for turn in (*relevant, *recent):
            merged[turn.message_id] = turn
        return sorted(merged.values(), key=lambda turn: turn.created_at)

    @staticmethod
    def _post_turn_active_topic(
        *,
        question: str,
        message_id: str,
        mentions: list[HistoryMention],
        inherited: DiscourseEntityCandidate | None,
    ) -> DiscourseEntityCandidate | None:
        explicit = [m for m in mentions if m.origin == "explicit"]
        unique: dict[tuple[str, str], HistoryMention] = {}
        for mention in explicit:
            unique[(mention.entity_type.casefold(), mention.canonical_name.casefold())] = mention
        if len(unique) == 1:
            mention = next(iter(unique.values()))
            return DiscourseEntityCandidate(
                canonical_name=mention.canonical_name,
                entity_type=mention.entity_type,
                source_message_id=message_id,
                source_role=Role.USER,
                source_text=question,
                score=max(0.90, mention.confidence),
                mention_confidence=mention.confidence,
                priority_tier=1,
                origin="explicit",
                turn_distance=0,
                focus_reason="current_user_explicit",
            )
        if len(unique) > 1:
            return None
        return inherited

    @staticmethod
    def _merge_resolved_mentions(
        mentions: list[HistoryMention],
        resolved_references,
    ) -> list[HistoryMention]:
        result = list(mentions)
        existing = {(m.entity_type.casefold(), m.canonical_name.casefold()) for m in result}
        for ref in resolved_references:
            if not (ref.resolved and ref.resolved_to and ref.entity_type):
                continue
            key = (ref.entity_type.casefold(), ref.resolved_to.casefold())
            if key in existing:
                continue
            result.append(
                HistoryMention(
                    text=ref.reference,
                    entity_type=ref.entity_type,
                    canonical_name=ref.resolved_to,
                    confidence=ref.confidence,
                    origin="resolved_reference",
                )
            )
            existing.add(key)
        return result
