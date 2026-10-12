from datetime import datetime, timezone

import pytest

from app.modules.context.application.extractor import RuleBasedClinicalExtractor
from app.modules.context.application.resolver import RuleBasedQuestionResolver
from app.modules.context.application.service import MedicalContextService
from app.modules.context.application.validator import ClinicalAssertionValidator
from app.modules.context.domain.models import (
    AssertionType,
    ClinicalFact,
    FactType,
    ProcessRequest,
    StatementType,
)
from app.modules.context.infrastructure.memory import InMemoryHistoryRepository, InMemoryPatientRepository


def ts(minute: int = 1):
    return datetime(2026, 9, 27, 1, minute, tzinfo=timezone.utc)


def build_service(extractor):
    history = InMemoryHistoryRepository()
    patient = InMemoryPatientRepository()
    service = MedicalContextService(
        history_repository=history,
        patient_repository=patient,
        question_resolver=RuleBasedQuestionResolver(),
        clinical_extractor=extractor,
        clinical_validator=ClinicalAssertionValidator(0.55),
        history_limit=20,
        recent_history_limit=6,
    )
    return service, history, patient


class MisclassifyingExtractor:
    """Simulates an LLM that incorrectly labels question content as patient facts."""

    async def extract(
        self,
        *,
        patient_id,
        message_id,
        timestamp,
        original_question,
        resolved_question,
        history_context,
    ):
        text = original_question.casefold()
        facts = []
        if "viêm phổi" in text:
            facts.append(
                ClinicalFact(
                    fact_type=FactType.CONDITION,
                    display="viêm phổi",
                    recorded_at=timestamp,
                    assertion=AssertionType.EXPLICIT,
                    statement_type=StatementType.FACT,  # deliberately wrong
                    confidence=1.0,
                    source_message_id=message_id,
                    source_text=original_question,
                )
            )
        if "triệu chứng" in text:
            facts.append(
                ClinicalFact(
                    fact_type=FactType.SYMPTOM,
                    display="các triệu chứng lâm sàng của viêm phổi",
                    recorded_at=timestamp,
                    assertion=AssertionType.EXPLICIT,
                    statement_type=StatementType.FACT,  # deliberately wrong
                    confidence=1.0,
                    source_message_id=message_id,
                    source_text=original_question,
                )
            )
        if "sốt" in text:
            facts.append(
                ClinicalFact(
                    fact_type=FactType.SYMPTOM,
                    display="sốt",
                    recorded_at=timestamp,
                    assertion=AssertionType.EXPLICIT,
                    statement_type=StatementType.FACT,
                    confidence=1.0,
                    source_message_id=message_id,
                    source_text="Tôi đang sốt",
                )
            )
        return facts


@pytest.mark.asyncio
async def test_general_knowledge_question_does_not_contaminate_patient_graph():
    service, history, patient = build_service(MisclassifyingExtractor())

    result = await service.process(
        ProcessRequest(
            persist_patient_facts=True,
            patient_id="p1",
            session_id="s1",
            message_id="m1",
            question="Viêm phổi có triệu chứng gì?",
            timestamp=ts(),
        )
    )

    assert result.stored_fact_count == 0
    assert result.patient_graph_updated is False
    ctx = await patient.get_relevant_context(patient_id="p1", query="viêm phổi")
    assert ctx.facts == []

    turns = await history.get_recent_turns(patient_id="p1", session_id="s1", limit=10)
    assert any(m.canonical_name.casefold() == "viêm phổi" for m in turns[0].mentions)


@pytest.mark.asyncio
async def test_diagnostic_question_does_not_become_diagnosis():
    service, _, patient = build_service(MisclassifyingExtractor())

    result = await service.process(
        ProcessRequest(
            persist_patient_facts=True,
            patient_id="p1",
            session_id="s1",
            message_id="m1",
            question="Tôi có bị viêm phổi không?",
            timestamp=ts(),
        )
    )

    assert result.stored_fact_count == 0
    ctx = await patient.get_relevant_context(patient_id="p1", query="viêm phổi")
    assert ctx.facts == []


@pytest.mark.asyncio
async def test_mixed_assertion_and_diagnostic_question_keeps_only_explicit_symptom():
    service, _, patient = build_service(MisclassifyingExtractor())

    result = await service.process(
        ProcessRequest(
            persist_patient_facts=True,
            patient_id="p1",
            session_id="s1",
            message_id="m1",
            question="Tôi đang sốt, liệu tôi có bị viêm phổi không?",
            timestamp=ts(),
        )
    )

    assert result.stored_fact_count == 1
    ctx = await patient.get_relevant_context(patient_id="p1", query="sốt viêm phổi")
    assert len(ctx.facts) == 1
    assert ctx.facts[0].fact_type == FactType.SYMPTOM
    assert ctx.facts[0].display.casefold() == "sốt"


@pytest.mark.asyncio
async def test_rule_extractor_stores_atomic_symptoms_not_long_propositions():
    service, _, patient = build_service(RuleBasedClinicalExtractor())

    result = await service.process(
        ProcessRequest(
            persist_patient_facts=True,
            patient_id="p1",
            session_id="s1",
            message_id="m1",
            question="Tôi bị ho và sốt ba ngày nay.",
            timestamp=ts(),
        )
    )

    assert result.stored_fact_count == 2
    ctx = await patient.get_relevant_context(patient_id="p1", query="ho sốt")
    displays = {fact.display.casefold() for fact in ctx.facts}
    assert displays == {"ho", "sốt"}


@pytest.mark.asyncio
async def test_negative_patient_assertion_is_allowed_as_negative_fact():
    service, _, patient = build_service(RuleBasedClinicalExtractor())

    result = await service.process(
        ProcessRequest(
            persist_patient_facts=True,
            patient_id="p1",
            session_id="s1",
            message_id="m1",
            question="Tôi không bị sốt.",
            timestamp=ts(),
        )
    )

    assert result.stored_fact_count == 1
    ctx = await patient.get_relevant_context(patient_id="p1", query="sốt")
    assert ctx.facts[0].display.casefold() == "sốt"
    assert ctx.facts[0].negated is True
