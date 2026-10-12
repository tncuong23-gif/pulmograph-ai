import json
from datetime import datetime, timezone

import httpx
import pytest

from app.modules.context.domain.models import HistoryTurn, PatientContext, ResolvedQuestion, Role
from app.modules.context.infrastructure.llm.ollama_structured import (
    OllamaStructuredClinicalExtractor,
    OllamaStructuredQuestionResolver,
)


def mock_ollama_transport():
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        assert request.url.path == "/api/chat"
        assert body["model"] == "qwen2.5:7b"
        assert isinstance(body["format"], dict)
        assert body["options"]["temperature"] == 0.0

        system = body["messages"][0]["content"]
        if "Context Resolution Engine" in system:
            content = {
                "normalized_question": "Tôi có cần ngưng sử dụng amoxicillin không?",
                "subject": "patient",
                "resolved_references": [
                    {
                        "reference": "[implicit medication]",
                        "resolved_to": "amoxicillin",
                        "entity_type": "medication",
                        "source_message_id": "m1",
                        "resolved": True,
                        "confidence": 0.96,
                    }
                ],
                "temporal_context": [],
                "used_history_turn_ids": ["m1"],
                "confidence": 0.96,
            }
        else:
            content = {
                "facts": [
                    {
                        "fact_type": "medication",
                        "display": "amoxicillin",
                        "dose": "500 mg",
                        "frequency": "3 lần/ngày",
                        "status": "active",
                        "negated": False,
                        "certainty": "confirmed",
                        "experiencer": "patient",
                        "assertion": "explicit",
                        "statement_type": "fact",
                        "confidence": 0.98,
                        "source_text": "Tôi đang uống amoxicillin 500 mg ngày 3 lần.",
                    }
                ]
            }
        return httpx.Response(200, json={"message": {"role": "assistant", "content": json.dumps(content, ensure_ascii=False)}})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_qwen_ollama_question_resolver_uses_json_schema():
    resolver = OllamaStructuredQuestionResolver(
        model="qwen2.5:7b",
        fallback_to_rules=False,
        transport=mock_ollama_transport(),
    )
    history = [
        HistoryTurn(
            patient_id="p1",
            session_id="s1",
            message_id="m1",
            role=Role.USER,
            original_text="Tôi đang uống amoxicillin 500 mg ngày 3 lần.",
            normalized_text="Tôi đang uống amoxicillin 500 mg ngày 3 lần.",
            created_at=datetime(2026, 9, 26, tzinfo=timezone.utc),
        )
    ]

    result = await resolver.resolve(
        question="Có cần ngưng không?",
        history_context=history,
        patient_context=PatientContext(patient_id="p1"),
    )

    assert "amoxicillin" in result.normalized_question.casefold()
    assert result.used_history_turn_ids == ["m1"]
    assert result.confidence == 0.96


@pytest.mark.asyncio
async def test_qwen_ollama_clinical_extractor_validates_structured_output():
    extractor = OllamaStructuredClinicalExtractor(
        model="qwen2.5:7b",
        fallback_to_rules=False,
        transport=mock_ollama_transport(),
    )
    resolved = ResolvedQuestion(
        original_question="Tôi đang uống amoxicillin 500 mg ngày 3 lần.",
        normalized_question="Tôi đang uống amoxicillin 500 mg ngày 3 lần.",
    )

    facts = await extractor.extract(
        patient_id="p1",
        message_id="m1",
        timestamp=datetime(2026, 9, 26, tzinfo=timezone.utc),
        original_question="Tôi đang uống amoxicillin 500 mg ngày 3 lần.",
        resolved_question=resolved,
        history_context=[],
    )

    assert len(facts) == 1
    assert facts[0].display == "amoxicillin"
    assert facts[0].dose == "500 mg"
    assert facts[0].source_message_id == "m1"


def mock_wrong_topic_switch_transport():
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        # Deliberately simulate Qwen choosing the repeatedly mentioned old topic.
        content = {
            "normalized_question": "Viêm phổi có triệu chứng gì?",
            "subject": "patient",
            "resolved_references": [
                {
                    "reference": "Nó",
                    "resolved_to": "Viêm phổi",
                    "entity_type": "condition",
                    "source_message_id": "m1",
                    "resolved": True,
                    "confidence": 0.96,
                }
            ],
            "temporal_context": [],
            "used_history_turn_ids": ["m1"],
            "confidence": 0.96,
        }
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": json.dumps(content, ensure_ascii=False)}},
        )

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_qwen_wrong_old_topic_is_rejected_and_rule_repair_uses_latest_explicit_topic():
    from app.modules.context.domain.models import HistoryMention

    resolver = OllamaStructuredQuestionResolver(
        model="qwen2.5:7b",
        fallback_to_rules=True,
        transport=mock_wrong_topic_switch_transport(),
    )
    history = [
        HistoryTurn(
            patient_id="p1",
            session_id="s1",
            message_id="m1",
            role=Role.USER,
            original_text="Viêm phổi là gì?",
            normalized_text="Viêm phổi là gì?",
            created_at=datetime(2026, 9, 26, 0, 1, tzinfo=timezone.utc),
            mentions=[
                HistoryMention(
                    text="Viêm phổi",
                    entity_type="condition",
                    canonical_name="Viêm phổi",
                    origin="explicit",
                    confidence=0.9,
                )
            ],
        ),
        HistoryTurn(
            patient_id="p1",
            session_id="s1",
            message_id="m4",
            role=Role.USER,
            original_text="COPD là gì?",
            normalized_text="COPD là gì?",
            created_at=datetime(2026, 9, 26, 0, 4, tzinfo=timezone.utc),
            mentions=[
                HistoryMention(
                    text="COPD",
                    entity_type="condition",
                    canonical_name="COPD",
                    origin="explicit",
                    confidence=0.9,
                )
            ],
        ),
    ]

    result = await resolver.resolve(
        question="Nó có triệu chứng gì?",
        history_context=history,
        patient_context=PatientContext(patient_id="p1"),
    )

    assert result.normalized_question == "COPD có triệu chứng gì?"
    assert result.resolution_status == "resolved"
    assert result.resolved_references[0].resolved_to == "COPD"
    assert result.used_history_turn_ids == ["m4"]
    assert result.resolution_method == "ollama_qwen+rule_repair"
    assert result.active_topic is not None
    assert result.active_topic.canonical_name == "COPD"
