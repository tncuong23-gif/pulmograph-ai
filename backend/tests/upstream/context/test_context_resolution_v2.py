from datetime import datetime, timedelta, timezone

import pytest

from app.modules.context.application.extractor import RuleBasedClinicalExtractor
from app.modules.context.application.resolver import RuleBasedQuestionResolver
from app.modules.context.application.service import MedicalContextService
from app.modules.context.application.validator import ClinicalAssertionValidator
from app.modules.context.domain.models import ProcessRequest, Role
from app.modules.context.infrastructure.memory import InMemoryHistoryRepository, InMemoryPatientRepository


def build_service():
    history = InMemoryHistoryRepository()
    patient = InMemoryPatientRepository()
    service = MedicalContextService(
        history_repository=history,
        patient_repository=patient,
        question_resolver=RuleBasedQuestionResolver(),
        clinical_extractor=RuleBasedClinicalExtractor(),
        clinical_validator=ClinicalAssertionValidator(0.55),
        history_limit=20,
        recent_history_limit=6,
    )
    return service, history, patient


def ts(minute: int):
    return datetime(2026, 9, 27, 0, minute, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_discourse_question_becomes_mention_but_not_patient_fact_then_resolves_pronoun():
    service, history, patient = build_service()

    first = await service.process(
        ProcessRequest(
            patient_id="p1",
            session_id="s1",
            message_id="m1",
            question="Viêm phổi là gì?",
            timestamp=ts(1),
        )
    )

    assert first.stored_fact_count == 0
    patient_context = await patient.get_relevant_context(patient_id="p1", query="viêm phổi")
    assert patient_context.facts == []

    turns = await history.get_recent_turns(patient_id="p1", session_id="s1", limit=2)
    assert len(turns) == 1
    assert [(m.entity_type, m.canonical_name) for m in turns[0].mentions] == [
        ("condition", "Viêm phổi")
    ]

    second = await service.process(
        ProcessRequest(
            patient_id="p1",
            session_id="s1",
            message_id="m2",
            question="Nó có triệu chứng gì?",
            timestamp=ts(2),
        )
    )

    assert second.normalized_question == "Viêm phổi có triệu chứng gì?"
    assert second.resolution_status == "resolved"
    assert second.context_turn_ids == ["m1"]
    assert second.resolved_references[0].resolved_to == "Viêm phổi"
    assert second.resolved_references[0].entity_type == "condition"


@pytest.mark.asyncio
async def test_ambiguous_same_type_candidates_are_not_guessed():
    service, _, _ = build_service()

    await service.process(
        ProcessRequest(
            patient_id="p1",
            session_id="s1",
            message_id="m1",
            question="Viêm phổi khác COPD như thế nào?",
            timestamp=ts(1),
        )
    )

    result = await service.process(
        ProcessRequest(
            patient_id="p1",
            session_id="s1",
            message_id="m2",
            question="Nó nguy hiểm không?",
            timestamp=ts(2),
        )
    )

    assert result.normalized_question == "Nó nguy hiểm không?"
    assert result.resolution_status == "unresolved"
    assert result.resolution_confidence <= 0.45
    assert result.resolved_references[0].resolved is False
    assert {c.canonical_name for c in result.candidate_entities[:2]} == {"Viêm phổi", "COPD"}


@pytest.mark.asyncio
async def test_assistant_turn_also_extracts_discourse_entity_for_followup():
    service, history, _ = build_service()

    await service.add_history_turn(
        patient_id="p1",
        session_id="s1",
        message_id="a1",
        role=Role.ASSISTANT,
        text="Viêm phổi là bệnh nhiễm trùng đường hô hấp.",
        timestamp=ts(1),
    )

    turns = await history.get_recent_turns(patient_id="p1", session_id="s1", limit=2)
    assert any(m.canonical_name == "Viêm phổi" for m in turns[0].mentions)

    result = await service.process(
        ProcessRequest(
            patient_id="p1",
            session_id="s1",
            message_id="m2",
            question="Nó có triệu chứng gì?",
            timestamp=ts(2),
        )
    )
    assert result.normalized_question == "Viêm phổi có triệu chứng gì?"
    assert result.context_turn_ids == ["a1"]


@pytest.mark.asyncio
async def test_recent_window_is_kept_even_when_semantic_retrieval_prefers_old_turns():
    service, _, _ = build_service()
    base = ts(0)

    for i, text in enumerate(
        [
            "Tôi đang dùng amoxicillin.",
            "Hôm nay tôi ngủ khá tốt.",
            "Tôi vừa ăn sáng.",
            "Viêm phổi là gì?",
        ],
        start=1,
    ):
        await service.process(
            ProcessRequest(
                patient_id="p1",
                session_id="s1",
                message_id=f"m{i}",
                question=text,
                timestamp=base + timedelta(minutes=i),
            )
        )

    result = await service.process(
        ProcessRequest(
            patient_id="p1",
            session_id="s1",
            message_id="m5",
            question="Nó có triệu chứng gì?",
            timestamp=base + timedelta(minutes=5),
        )
    )

    assert result.normalized_question == "Viêm phổi có triệu chứng gì?"
    assert "m4" in result.context_turn_ids
