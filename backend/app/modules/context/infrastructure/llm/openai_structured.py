from __future__ import annotations

import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

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


class LLMResolvedReference(BaseModel):
    reference: str
    resolved_to: str | None = None
    entity_type: str | None = None
    source_message_id: str | None = None
    resolved: bool = True
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class LLMResolvedQuestion(BaseModel):
    normalized_question: str
    subject: str = "patient"
    resolved_references: list[LLMResolvedReference] = Field(default_factory=list)
    temporal_context: list[dict] = Field(default_factory=list)
    used_history_turn_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class LLMClinicalFact(BaseModel):
    fact_type: Literal[
        "condition",
        "symptom",
        "medication",
        "allergy",
        "observation",
        "lab_result",
        "procedure",
        "family_history",
        "lifestyle",
    ]
    display: str
    value: str | float | int | bool | None = None
    unit: str | None = None
    dose: str | None = None
    frequency: str | None = None
    route: str | None = None
    status: str | None = None
    negated: bool = False
    certainty: Literal["confirmed", "probable", "possible", "unknown"] = "confirmed"
    experiencer: str = "patient"
    assertion: Literal["explicit", "resolved", "inferred"] = "explicit"
    statement_type: Literal["fact", "question", "plan", "hypothesis"] = "fact"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_text: str | None = None
    related_fact_type: str | None = None


class LLMClinicalExtraction(BaseModel):
    facts: list[LLMClinicalFact] = Field(default_factory=list)


class OpenAIStructuredQuestionResolver:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-5.6-terra",
        fallback_to_rules: bool = True,
    ) -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model
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
            "Chỉ thay phần tham chiếu/chủ thể bị thiếu và không paraphrase phần đã rõ. Chỉ viết lại CURRENT_QUESTION thành câu tự đủ nghĩa; "
            "không trả lời và không chẩn đoán. CANDIDATE_ENTITIES có priority_tier; tier nhỏ hơn luôn ưu tiên hơn. "
            "origin='explicit' là thực thể vừa được nêu trực tiếp, còn origin='resolved_reference' là chủ đề kế thừa. "
            "Khi resolved=true, resolved_to và source_message_id phải khớp một candidate và không được chọn candidate "
            "tier yếu hơn khi cùng entity_type có tier mạnh hơn. Nếu tier mạnh nhất có nhiều candidate cùng loại gần "
            "ngang nhau thì unresolved, không đoán. Ví dụ topic switch: 'Viêm phổi...' rồi 'COPD là gì?' rồi "
            "'Nó có triệu chứng gì?' => 'COPD có triệu chứng gì?'. Giữ nguyên intent, phủ định, experiencer và thời gian."
        )
        try:
            response = await self._client.responses.parse(
                model=self._model,
                input=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                text_format=LLMResolvedQuestion,
            )
            parsed = response.output_parsed
            if parsed is None:
                raise RuntimeError("OpenAI response did not contain parsed structured output")
            result = ResolvedQuestion(
                original_question=question,
                normalized_question=parsed.normalized_question,
                subject=parsed.subject,
                resolved_references=[ResolvedReference(**r.model_dump()) for r in parsed.resolved_references],
                temporal_context=parsed.temporal_context,
                used_history_turn_ids=parsed.used_history_turn_ids,
                confidence=parsed.confidence,
                resolution_method="openai_hybrid",
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
                    return repaired.model_copy(update={"resolution_method": "openai+rule_repair"})
            return validated
        except Exception:
            if self._fallback is None:
                raise
            return await self._fallback.resolve(
                question=question,
                history_context=history_context,
                patient_context=patient_context,
            )


class OpenAIStructuredClinicalExtractor:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-5.6-terra",
        fallback_to_rules: bool = True,
    ) -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model
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
            "Bạn là Clinical Fact Extraction Engine. Trích xuất các assertion lâm sàng từ ORIGINAL_QUESTION. "
            "RESOLVED_QUESTION chỉ dùng để hiểu tham chiếu, không biến thông tin ngữ cảnh thành fact mới nếu người dùng "
            "không khẳng định lại. Không suy luận chẩn đoán từ thuốc hoặc triệu chứng. Phải phân biệt fact, question, plan, "
            "hypothesis. Câu giả định hoặc câu hỏi không được gắn statement_type=fact. Phải nhận diện phủ định, experiencer "
            "(patient hay người thân), mức chắc chắn và trạng thái thuốc. family_history dùng khi bệnh thuộc người thân. "
            "Chỉ trích xuất clinical fact khi người dùng thực sự khẳng định thông tin về bệnh nhân hoặc family history. "
            "Không tạo fact chỉ vì bệnh/triệu chứng/thuốc xuất hiện trong câu hỏi kiến thức hay câu hỏi chẩn đoán. "
            "Ví dụ: 'Viêm phổi có triệu chứng gì?' => facts=[]; 'Tôi có bị viêm phổi không?' => không tạo condition=viêm phổi; "
            "'Tôi đang sốt, liệu tôi có bị viêm phổi không?' => chỉ tạo symptom=sốt. "
            "display phải là concept nguyên tử, ngắn gọn; không dùng cả mệnh đề. "
            "Không tự tạo concept_id; terminology normalization sẽ làm ở bước sau. source_text là đoạn văn bản làm bằng chứng."
        )
        try:
            response = await self._client.responses.parse(
                model=self._model,
                input=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                text_format=LLMClinicalExtraction,
            )
            parsed = response.output_parsed
            if parsed is None:
                raise RuntimeError("OpenAI response did not contain parsed structured output")

            facts: list[ClinicalFact] = []
            for item in parsed.facts:
                attrs = {}
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
