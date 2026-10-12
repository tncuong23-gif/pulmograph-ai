from datetime import datetime, timezone

import httpx
import pytest

from app.modules.context.application.context_resolution import ContextNeedDetector
from app.modules.context.application.extractor import RuleBasedClinicalExtractor
from app.modules.context.application.resolver import RuleBasedQuestionResolver
from app.modules.context.application.service import MedicalContextService
from app.modules.context.application.validator import ClinicalAssertionValidator
from app.modules.context.domain.models import PatientContext, ProcessRequest
from app.modules.context.infrastructure.llm.ollama_structured import OllamaStructuredQuestionResolver
from app.modules.context.infrastructure.memory import InMemoryHistoryRepository, InMemoryPatientRepository


def ts(minute: int):
    return datetime(2026, 9, 29, 2, minute, tzinfo=timezone.utc)


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


async def ask(service, mid: str, minute: int, question: str):
    return await service.process(
        ProcessRequest(
            patient_id="p-v23",
            session_id="s-v23",
            message_id=mid,
            question=question,
            timestamp=ts(minute),
        )
    )


def test_context_need_detector_only_flags_real_context_dependencies():
    assert ContextNeedDetector.detect("Viêm phổi có triệu chứng gì?").status == "not_needed"
    assert ContextNeedDetector.detect("COPD có nguy hiểm không?").status == "not_needed"
    assert ContextNeedDetector.detect("Tôi bị ho ba ngày nay.").status == "not_needed"
    assert ContextNeedDetector.detect("Nó có triệu chứng gì?").status == "needs_resolution"
    assert ContextNeedDetector.detect("Bệnh này có nguy hiểm không?").status == "needs_resolution"
    assert ContextNeedDetector.detect("Có nguy hiểm không?").status == "needs_resolution"
    assert ContextNeedDetector.detect("Điều trị thế nào?").status == "needs_resolution"
    assert ContextNeedDetector.detect("Còn triệu chứng?").status == "needs_resolution"


def test_pronoun_detection_does_not_match_no_inside_nong():
    # "nó" must not be detected inside the unrelated word "nóng".
    assert ContextNeedDetector.detect("Tôi thấy nóng trong người.").status == "not_needed"


@pytest.mark.asyncio
async def test_clear_question_is_immutable_even_when_another_topic_is_active():
    service, _, _ = build_service()
    await ask(service, "m1", 1, "COPD là gì?")

    result = await ask(service, "m2", 2, "Viêm phổi có triệu chứng gì?")

    assert result.normalized_question == "Viêm phổi có triệu chứng gì?"
    assert result.resolution_status == "not_needed"
    assert result.resolution_method == "context_not_needed"
    assert result.resolved_references == []
    assert result.context_turn_ids == []
    # The clear current turn may still become the NEW discourse topic for future turns.
    assert result.active_topic is not None
    assert result.active_topic.canonical_name == "Viêm phổi"


@pytest.mark.asyncio
async def test_clear_patient_assertion_is_not_rewritten():
    service, _, _ = build_service()
    await ask(service, "m1", 1, "Viêm phổi là gì?")
    result = await ask(service, "m2", 2, "Tôi bị ho ba ngày nay.")

    assert result.normalized_question == "Tôi bị ho ba ngày nay."
    assert result.resolution_status == "not_needed"


@pytest.mark.asyncio
async def test_explicit_pronoun_is_resolved():
    service, _, _ = build_service()
    await ask(service, "m1", 1, "COPD là gì?")
    result = await ask(service, "m2", 2, "Nó có triệu chứng gì?")

    assert result.normalized_question == "COPD có triệu chứng gì?"
    assert result.resolution_status == "resolved"


@pytest.mark.asyncio
async def test_subject_ellipsis_danger_question_is_resolved():
    service, _, _ = build_service()
    await ask(service, "m1", 1, "Viêm phổi là gì?")
    result = await ask(service, "m2", 2, "Có nguy hiểm không?")

    assert result.normalized_question == "Viêm phổi có nguy hiểm không?"
    assert result.resolution_status == "resolved"
    assert result.context_turn_ids == ["m1"]


@pytest.mark.asyncio
async def test_subject_ellipsis_treatment_question_is_resolved():
    service, _, _ = build_service()
    await ask(service, "m1", 1, "COPD là gì?")
    result = await ask(service, "m2", 2, "Điều trị thế nào?")

    assert result.normalized_question == "COPD được điều trị thế nào?"
    assert result.resolution_status == "resolved"


@pytest.mark.asyncio
async def test_subject_ellipsis_symptom_question_is_resolved():
    service, _, _ = build_service()
    await ask(service, "m1", 1, "Viêm phổi là gì?")
    result = await ask(service, "m2", 2, "Còn triệu chứng?")

    assert result.normalized_question == "Viêm phổi có triệu chứng gì?"
    assert result.resolution_status == "resolved"


@pytest.mark.asyncio
async def test_subject_ellipsis_without_context_stays_unresolved_and_unchanged():
    resolver = RuleBasedQuestionResolver()
    result = await resolver.resolve(
        question="Có nguy hiểm không?",
        history_context=[],
        patient_context=PatientContext(patient_id="p1"),
    )

    assert result.normalized_question == "Có nguy hiểm không?"
    assert result.resolution_status == "unresolved"


@pytest.mark.asyncio
async def test_ambiguous_two_condition_context_does_not_guess_implicit_subject():
    service, _, _ = build_service()
    await ask(service, "m1", 1, "Viêm phổi khác COPD như thế nào?")
    result = await ask(service, "m2", 2, "Có nguy hiểm không?")

    assert result.normalized_question == "Có nguy hiểm không?"
    assert result.resolution_status == "unresolved"


@pytest.mark.asyncio
async def test_ollama_is_not_called_for_self_contained_question():
    called = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500, json={"error": "must not be called"})

    resolver = OllamaStructuredQuestionResolver(
        transport=httpx.MockTransport(handler),
        fallback_to_rules=False,
    )
    result = await resolver.resolve(
        question="Viêm phổi có triệu chứng gì?",
        history_context=[],
        patient_context=PatientContext(patient_id="p1"),
    )

    assert called is False
    assert result.normalized_question == "Viêm phổi có triệu chứng gì?"
    assert result.resolution_status == "not_needed"
    assert result.resolution_method == "context_not_needed"


def test_validator_discards_paraphrase_for_clear_question():
    from app.modules.context.application.context_resolution import ContextResolutionValidator
    from app.modules.context.domain.models import ResolvedQuestion

    proposed = ResolvedQuestion(
        original_question="Viêm phổi có triệu chứng gì?",
        normalized_question="Các triệu chứng lâm sàng thường gặp của viêm phổi là gì?",
        confidence=0.99,
        resolution_method="ollama_qwen_hybrid",
    )
    validated = ContextResolutionValidator().validate(proposed)

    assert validated.normalized_question == "Viêm phổi có triệu chứng gì?"
    assert validated.resolution_status == "not_needed"
    assert validated.resolution_method == "context_not_needed"
