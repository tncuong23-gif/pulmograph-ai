from __future__ import annotations

import json
from datetime import datetime
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from app.modules.context.application.context_resolution import (
    AntecedentCandidateRanker,
    ContextNeedDetector,
    ContextResolutionValidator,
)
from app.modules.context.application.extractor import RuleBasedClinicalExtractor
from app.modules.context.application.resolver import RuleBasedQuestionResolver
from app.modules.context.domain.models import (
    AssertionType,
    Certainty,
    ClinicalFact,
    FactType,
    HistoryTurn,
    PatientContext,
    ResolvedQuestion,
    ResolvedReference,
    StatementType,
)
from app.modules.context.infrastructure.llm.openai_structured import (
    LLMClinicalExtraction,
    LLMResolvedQuestion,
)

T = TypeVar("T", bound=BaseModel)


class OllamaStructuredClient:
    """Small async client for Ollama structured outputs.

    Ollama accepts a JSON Schema in the `format` field of `/api/chat`.
    We validate the returned JSON again with Pydantic before it enters
    the application layer.
    """

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:11434",
        model: str = "qwen2.5:7b",
        timeout_seconds: float = 120.0,
        temperature: float = 0.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.transport = transport

    async def parse(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
        response_model: type[T],
    ) -> T:
        schema = response_model.model_json_schema()
        user_content = (
            "INPUT:\n"
            + json.dumps(payload, ensure_ascii=False)
            + "\n\nOUTPUT_JSON_SCHEMA:\n"
            + json.dumps(schema, ensure_ascii=False)
        )
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "stream": False,
            "format": schema,
            "options": {"temperature": self.temperature},
        }

        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            response = await client.post("/api/chat", json=body)
            response.raise_for_status()
            data = response.json()

        try:
            content = data["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise RuntimeError("Ollama response is missing message.content") from exc

        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Ollama returned an empty structured response")

        return response_model.model_validate_json(content)


class OllamaStructuredQuestionResolver:
    def __init__(
        self,
        *,
        base_url: str = "http://localhost:11434",
        model: str = "qwen2.5:7b",
        timeout_seconds: float = 120.0,
        temperature: float = 0.0,
        fallback_to_rules: bool = True,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = OllamaStructuredClient(
            base_url=base_url,
            model=model,
            timeout_seconds=timeout_seconds,
            temperature=temperature,
            transport=transport,
        )
        self._fallback = RuleBasedQuestionResolver() if fallback_to_rules else None
        self._ranker = AntecedentCandidateRanker()
        self._validator = ContextResolutionValidator()
        self._need_detector = ContextNeedDetector()

    async def resolve(
        self,
        *,
        question: str,
        history_context: list[HistoryTurn],
        patient_context: PatientContext,
    ) -> ResolvedQuestion:
        clean_question = " ".join(question.strip().split())
        if self._need_detector.detect(clean_question).status == "not_needed":
            return ResolvedQuestion(
                original_question=clean_question,
                normalized_question=clean_question,
                subject="patient",
                confidence=1.0,
                resolution_status="not_needed",
                resolution_method="context_not_needed",
            )

        candidates = self._ranker.rank(
            question=question,
            history_context=history_context,
            patient_context=patient_context,
        )
        payload = {
            "current_question": question,
            "candidate_entities": [c.model_dump(mode="json") for c in candidates],
            "history_context": [
                {
                    "message_id": turn.message_id,
                    "role": turn.role.value,
                    "text": turn.original_text,
                    "normalized_text": turn.normalized_text,
                    "mentions": [m.model_dump(mode="json") for m in turn.mentions],
                    "created_at": turn.created_at.isoformat(),
                }
                for turn in history_context
            ],
            "patient_context": [
                {
                    "fact_type": fact.fact_type.value,
                    "display": fact.display,
                    "concept_id": fact.concept_id,
                    "concept_system": fact.concept_system,
                    "status": fact.status,
                    "negated": fact.negated,
                    "experiencer": fact.experiencer,
                    "recorded_at": fact.recorded_at.isoformat(),
                }
                for fact in patient_context.facts
            ],
        }
        system = (
            "Bạn là Context Resolution Engine cho hệ thống y khoa. Chỉ các câu thực sự thiếu ngữ cảnh mới được gửi tới bạn. "
            "Chỉ thay thế phần tham chiếu/chủ thể bị thiếu; không diễn đạt lại các phần đã rõ nghĩa. Nhiệm vụ duy nhất là viết lại "
            "CURRENT_QUESTION thành câu tự đủ nghĩa, không trả lời câu hỏi và không chẩn đoán. "
            "CANDIDATE_ENTITIES đã được Discourse Focus Manager xếp theo priority_tier; số tier nhỏ hơn "
            "luôn ưu tiên hơn số lớn hơn. Không được chọn một candidate tier thấp ưu tiên hơn khi cùng "
            "entity_type đang có candidate tier mạnh hơn. origin='explicit' nghĩa là người dùng vừa nêu "
            "trực tiếp thực thể; origin='resolved_reference' chỉ là chủ đề được kế thừa từ đại từ trước. "
            "Khi resolved=true, resolved_to và source_message_id phải khớp chính xác một candidate; không "
            "tự tạo thực thể mới. Nếu tier mạnh nhất có nhiều candidate cùng loại gần ngang nhau thì phải "
            "unresolved thay vì đoán. Giữ nguyên intent, phủ định, experiencer và thời gian. "
            "Ví dụ topic switch: HISTORY='Viêm phổi là gì? ... COPD là gì?', CURRENT='Nó có triệu chứng gì?' "
            "và COPD là latest explicit tier=1 => normalized_question='COPD có triệu chứng gì?'. "
            "Ví dụ mơ hồ: HISTORY='Viêm phổi khác COPD như thế nào?', CURRENT='Nó nguy hiểm không?' "
            "=> unresolved. Chỉ trả JSON phù hợp schema đã cung cấp."
        )

        try:
            parsed = await self._client.parse(
                system_prompt=system,
                payload=payload,
                response_model=LLMResolvedQuestion,
            )
            result = ResolvedQuestion(
                original_question=question,
                normalized_question=parsed.normalized_question,
                subject=parsed.subject,
                resolved_references=[
                    ResolvedReference(**item.model_dump()) for item in parsed.resolved_references
                ],
                temporal_context=parsed.temporal_context,
                used_history_turn_ids=parsed.used_history_turn_ids,
                confidence=parsed.confidence,
                resolution_method="ollama_qwen_hybrid",
                candidate_entities=candidates,
                active_topic=self._ranker.active_topic(candidates),
            )
            validated = self._validator.validate(result)
            if validated.resolution_status == "unresolved" and self._fallback is not None:
                repaired = await self._fallback.resolve(
                    question=question,
                    history_context=history_context,
                    patient_context=patient_context,
                )
                if repaired.resolution_status == "resolved":
                    return repaired.model_copy(update={"resolution_method": "ollama_qwen+rule_repair"})
            return validated
        except Exception:
            if self._fallback is None:
                raise
            return await self._fallback.resolve(
                question=question,
                history_context=history_context,
                patient_context=patient_context,
            )


class OllamaStructuredClinicalExtractor:
    def __init__(
        self,
        *,
        base_url: str = "http://localhost:11434",
        model: str = "qwen2.5:7b",
        timeout_seconds: float = 120.0,
        temperature: float = 0.0,
        fallback_to_rules: bool = True,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = OllamaStructuredClient(
            base_url=base_url,
            model=model,
            timeout_seconds=timeout_seconds,
            temperature=temperature,
            transport=transport,
        )
        self._fallback = RuleBasedClinicalExtractor() if fallback_to_rules else None

    async def extract(
        self,
        *,
        patient_id: str,
        message_id: str,
        timestamp: datetime,
        original_question: str,
        resolved_question: ResolvedQuestion,
        history_context: list[HistoryTurn],
    ) -> list[ClinicalFact]:
        payload = {
            "original_question": original_question,
            "resolved_question": resolved_question.model_dump(mode="json"),
            "history_context": [
                {
                    "message_id": turn.message_id,
                    "role": turn.role.value,
                    "text": turn.original_text,
                    "normalized_text": turn.normalized_text,
                }
                for turn in history_context
            ],
        }
        system = (
            "Bạn là Clinical Fact Extraction Engine. Trích xuất assertion lâm sàng từ ORIGINAL_QUESTION. "
            "RESOLVED_QUESTION chỉ dùng để hiểu tham chiếu, không biến dữ liệu lịch sử thành fact mới nếu người dùng "
            "không khẳng định lại. Không suy luận chẩn đoán từ thuốc hoặc triệu chứng. Phải phân biệt fact, question, "
            "plan, hypothesis. Câu giả định hoặc câu hỏi không được gắn statement_type=fact. Phải nhận diện phủ định, "
            "experiencer, mức chắc chắn và trạng thái thuốc. family_history dùng khi bệnh thuộc người thân. "
            "Chỉ trích xuất clinical fact khi người dùng thực sự khẳng định thông tin về bệnh nhân hoặc family history. "
            "Không tạo fact chỉ vì một bệnh/triệu chứng/thuốc xuất hiện như đối tượng của câu hỏi kiến thức. "
            "Ví dụ: 'Viêm phổi có triệu chứng gì?' => facts=[]; 'Tôi có bị viêm phổi không?' => không tạo condition=viêm phổi; "
            "'Tôi đang sốt, liệu tôi có bị viêm phổi không?' => chỉ tạo symptom=sốt. "
            "display phải là concept nguyên tử, ngắn gọn như 'ho', 'sốt', 'amoxicillin', không phải cả mệnh đề hoặc cụm như 'các triệu chứng của viêm phổi'. "
            "Không tự tạo concept_id; terminology normalization sẽ làm ở bước sau. source_text phải là bằng chứng nguyên văn. "
            "Chỉ trả JSON phù hợp schema đã cung cấp."
        )

        try:
            parsed = await self._client.parse(
                system_prompt=system,
                payload=payload,
                response_model=LLMClinicalExtraction,
            )
            facts: list[ClinicalFact] = []
            for item in parsed.facts:
                attrs: dict[str, Any] = {}
                if item.related_fact_type:
                    attrs["related_fact_type"] = item.related_fact_type
                facts.append(
                    ClinicalFact(
                        fact_type=FactType(item.fact_type),
                        display=item.display,
                        value=item.value,
                        unit=item.unit,
                        dose=item.dose,
                        frequency=item.frequency,
                        route=item.route,
                        status=item.status,
                        negated=item.negated,
                        certainty=Certainty(item.certainty),
                        experiencer=item.experiencer,
                        recorded_at=timestamp,
                        assertion=AssertionType(item.assertion),
                        statement_type=StatementType(item.statement_type),
                        confidence=item.confidence,
                        source_message_id=message_id,
                        source_text=item.source_text,
                        attributes=attrs,
                    )
                )
            return facts
        except Exception:
            if self._fallback is None:
                raise
            return await self._fallback.extract(
                patient_id=patient_id,
                message_id=message_id,
                timestamp=timestamp,
                original_question=original_question,
                resolved_question=resolved_question,
                history_context=history_context,
            )
