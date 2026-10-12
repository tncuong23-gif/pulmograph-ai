from datetime import datetime, timezone

import pytest

from app.modules.context.application.context_resolution import ContextResolutionValidator
from app.modules.context.application.extractor import RuleBasedClinicalExtractor
from app.modules.context.application.resolver import RuleBasedQuestionResolver
from app.modules.context.application.service import MedicalContextService
from app.modules.context.application.validator import ClinicalAssertionValidator
from app.modules.context.domain.models import (
    DiscourseEntityCandidate,
    ProcessRequest,
    ResolvedQuestion,
    ResolvedReference,
)
from app.modules.context.infrastructure.memory import InMemoryHistoryRepository, InMemoryPatientRepository


def ts(minute: int):
    return datetime(2026, 9, 27, 1, minute, tzinfo=timezone.utc)


def build_service():
    history = InMemoryHistoryRepository()
    patient = InMemoryPatientRepository()
    return MedicalContextService(
        history_repository=history,
        patient_repository=patient,
        question_resolver=RuleBasedQuestionResolver(),
        clinical_extractor=RuleBasedClinicalExtractor(),
        clinical_validator=ClinicalAssertionValidator(0.55),
        history_limit=20,
        recent_history_limit=6,
    ), history, patient


async def ask(service, message_id: str, minute: int, question: str):
    return await service.process(
        ProcessRequest(
            patient_id="p-v22",
            session_id="s-v22",
            message_id=message_id,
            question=question,
            timestamp=ts(minute),
        )
    )


@pytest.mark.asyncio
async def test_latest_explicit_topic_switch_to_copd_wins_over_repeated_pneumonia_topic():
    service, _, _ = build_service()

    await ask(service, "m1", 1, "Viêm phổi là gì?")
    second = await ask(service, "m2", 2, "Nó có triệu chứng gì?")
    assert second.normalized_question == "Viêm phổi có triệu chứng gì?"

    await ask(service, "m3", 3, "Viêm phổi có nguy hiểm không?")
    switched = await ask(service, "m4", 4, "COPD là gì?")
    assert switched.active_topic is not None
    assert switched.active_topic.canonical_name == "COPD"
    assert switched.active_topic.focus_reason == "current_user_explicit"
    result = await ask(service, "m5", 5, "Nó có triệu chứng gì?")

    assert result.normalized_question == "COPD có triệu chứng gì?"
    assert result.resolution_status == "resolved"
    assert result.resolved_references[0].resolved_to == "COPD"
    assert result.context_turn_ids == ["m4"]
    assert result.candidate_entities[0].canonical_name == "COPD"
    assert result.candidate_entities[0].priority_tier == 1
    assert result.candidate_entities[0].origin == "explicit"
    pneumonia = next(c for c in result.candidate_entities if c.canonical_name == "Viêm phổi")
    assert pneumonia.priority_tier > result.candidate_entities[0].priority_tier


@pytest.mark.asyncio
async def test_new_explicit_topic_beats_previous_resolved_reference_topic():
    service, history, _ = build_service()

    await ask(service, "m1", 1, "Viêm phổi là gì?")
    await ask(service, "m2", 2, "Nó có triệu chứng gì?")

    turns = await history.get_recent_turns(patient_id="p-v22", session_id="s-v22", limit=5)
    m2 = next(t for t in turns if t.message_id == "m2")
    assert any(m.origin == "resolved_reference" and m.canonical_name == "Viêm phổi" for m in m2.mentions)

    await ask(service, "m3", 3, "COPD là gì?")
    result = await ask(service, "m4", 4, "Nó có nguy hiểm không?")

    assert result.normalized_question == "COPD có nguy hiểm không?"
    assert result.resolved_references[0].resolved_to == "COPD"


@pytest.mark.asyncio
async def test_reverse_topic_switch_back_to_pneumonia():
    service, _, _ = build_service()

    await ask(service, "m1", 1, "COPD là gì?")
    await ask(service, "m2", 2, "Viêm phổi là gì?")
    result = await ask(service, "m3", 3, "Nó có nguy hiểm không?")

    assert result.normalized_question == "Viêm phổi có nguy hiểm không?"
    assert result.resolved_references[0].resolved_to == "Viêm phổi"


@pytest.mark.asyncio
async def test_medication_topic_switch_uses_latest_explicit_medication():
    service, _, _ = build_service()

    await ask(service, "m1", 1, "Amoxicillin là thuốc gì?")
    await ask(service, "m2", 2, "Paracetamol là thuốc gì?")
    result = await ask(service, "m3", 3, "Thuốc đó có tác dụng phụ gì?")

    assert result.normalized_question == "Paracetamol có tác dụng phụ gì?"
    assert result.resolved_references[0].resolved_to == "Paracetamol"
    assert result.resolved_references[0].entity_type == "medication"


def test_validator_rejects_lower_priority_llm_choice_and_restores_original_question():
    validator = ContextResolutionValidator()
    result = ResolvedQuestion(
        original_question="Nó có triệu chứng gì?",
        normalized_question="Viêm phổi có triệu chứng gì?",
        resolved_references=[
            ResolvedReference(
                reference="nó",
                resolved_to="Viêm phổi",
                entity_type="condition",
                source_message_id="m1",
                resolved=True,
                confidence=0.95,
            )
        ],
        used_history_turn_ids=["m1"],
        confidence=0.95,
        resolution_method="ollama_qwen_hybrid",
        candidate_entities=[
            DiscourseEntityCandidate(
                canonical_name="COPD",
                entity_type="condition",
                source_message_id="m4",
                score=0.93,
                priority_tier=1,
                origin="explicit",
            ),
            DiscourseEntityCandidate(
                canonical_name="Viêm phổi",
                entity_type="condition",
                source_message_id="m1",
                score=0.94,
                priority_tier=4,
                origin="resolved_reference",
            ),
        ],
    )

    validated = validator.validate(result)

    assert validated.resolution_status == "unresolved"
    assert validated.normalized_question == "Nó có triệu chứng gì?"
    assert validated.resolved_references[0].resolved is False
    assert validated.used_history_turn_ids == []
