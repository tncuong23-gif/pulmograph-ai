from datetime import datetime, timezone

import pytest

from app.modules.context.application.extractor import RuleBasedClinicalExtractor
from app.modules.context.application.resolver import RuleBasedQuestionResolver
from app.modules.context.application.service import MedicalContextService
from app.modules.context.application.validator import ClinicalAssertionValidator
from app.modules.context.domain.models import FactType, ProcessRequest
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
    )
    return service, history, patient


def ts(minute: int):
    return datetime(2026, 9, 26, 3, minute, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_medication_is_stored_and_elliptical_question_is_resolved():
    service, _, patient = build_service()

    first = await service.process(
        ProcessRequest(
            persist_patient_facts=True,
            patient_id="p1",
            session_id="s1",
            message_id="m1",
            question="Tôi đang uống amoxicillin 500mg ngày 3 lần.",
            timestamp=ts(1),
        )
    )
    assert first.patient_graph_updated is True

    second = await service.process(
        ProcessRequest(
            persist_patient_facts=True,
            patient_id="p1",
            session_id="s1",
            message_id="m2",
            question="Có cần ngưng không?",
            timestamp=ts(2),
        )
    )

    assert "amoxicillin" in second.normalized_question.casefold()
    assert "m1" in second.context_turn_ids

    ctx = await patient.get_relevant_context(patient_id="p1", query="thuốc")
    meds = [f for f in ctx.facts if f.fact_type == FactType.MEDICATION]
    assert len(meds) == 1
    assert meds[0].display.casefold() == "amoxicillin"
    assert meds[0].dose == "500mg"


@pytest.mark.asyncio
async def test_hypothetical_medication_is_not_written_to_patient_graph():
    service, _, patient = build_service()

    result = await service.process(
        ProcessRequest(
            persist_patient_facts=True,
            patient_id="p1",
            session_id="s1",
            message_id="m1",
            question="Nếu tôi uống aspirin thì có sao không?",
            timestamp=ts(1),
        )
    )

    assert result.stored_fact_count == 0
    ctx = await patient.get_relevant_context(patient_id="p1", query="aspirin")
    assert ctx.facts == []


@pytest.mark.asyncio
async def test_family_history_is_not_stored_as_patient_condition():
    service, _, patient = build_service()

    result = await service.process(
        ProcessRequest(
            persist_patient_facts=True,
            patient_id="p1",
            session_id="s1",
            message_id="m1",
            question="Mẹ tôi bị tiểu đường.",
            timestamp=ts(1),
        )
    )

    assert result.stored_fact_count == 1
    ctx = await patient.get_relevant_context(patient_id="p1", query="tiểu đường")
    assert len(ctx.facts) == 1
    fact = ctx.facts[0]
    assert fact.fact_type == FactType.FAMILY_HISTORY
    assert fact.experiencer == "mother"


@pytest.mark.asyncio
async def test_negated_condition_is_kept_as_negative_assertion():
    service, _, patient = build_service()

    await service.process(
        ProcessRequest(
            persist_patient_facts=True,
            patient_id="p1",
            session_id="s1",
            message_id="m1",
            question="Tôi không bị tiểu đường.",
            timestamp=ts(1),
        )
    )

    ctx = await patient.get_relevant_context(patient_id="p1", query="tiểu đường")
    assert len(ctx.facts) == 1
    assert ctx.facts[0].negated is True


@pytest.mark.asyncio
async def test_explicit_fact_before_followup_question_remains_fact():
    service, _, patient = build_service()

    result = await service.process(
        ProcessRequest(
            persist_patient_facts=True,
            patient_id="p1",
            session_id="s1",
            message_id="m1",
            question="Tôi đang uống amlodipine 5mg. Có cần ngưng không?",
            timestamp=ts(1),
        )
    )

    assert result.stored_fact_count == 1
    ctx = await patient.get_relevant_context(patient_id="p1", query="amlodipine")
    assert ctx.facts[0].display.casefold() == "amlodipine"
