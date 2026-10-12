from __future__ import annotations

import re

from app.modules.context.application.context_resolution import (
    AntecedentCandidateRanker,
    ContextNeedDetector,
    ContextResolutionValidator,
    ReferenceIntentDetector,
)
from app.modules.context.application.text import normalize_whitespace
from app.modules.context.domain.models import (
    DiscourseEntityCandidate,
    PatientContext,
    ResolvedQuestion,
    ResolvedReference,
    HistoryTurn,
)


class RuleBasedQuestionResolver:
    """Conservative hybrid rule resolver using ranked discourse candidates."""

    MEDICATION_REFS = ReferenceIntentDetector.MEDICATION_REFS
    CONDITION_REFS = ReferenceIntentDetector.CONDITION_REFS
    SYMPTOM_REFS = ReferenceIntentDetector.SYMPTOM_REFS
    LAB_REFS = ReferenceIntentDetector.LAB_REFS
    GENERIC_REFS = ReferenceIntentDetector.GENERIC_REFS

    def __init__(self) -> None:
        self.ranker = AntecedentCandidateRanker()
        self.validator = ContextResolutionValidator()
        self.need_detector = ContextNeedDetector()

    async def resolve(
        self,
        *,
        question: str,
        history_context: list[HistoryTurn],
        patient_context: PatientContext,
    ) -> ResolvedQuestion:
        original = normalize_whitespace(question)
        need = self.need_detector.detect(original)
        if need.status == "not_needed":
            return ResolvedQuestion(
                original_question=original,
                normalized_question=original,
                subject="patient",
                resolved_references=[],
                used_history_turn_ids=[],
                confidence=1.0,
                resolution_status="not_needed",
                resolution_method="context_not_needed",
                candidate_entities=[],
                active_topic=None,
            )

        rewritten = original
        resolved: list[ResolvedReference] = []

        candidates = self.ranker.rank(
            question=original,
            history_context=history_context,
            patient_context=patient_context,
        )

        medication = self._choose_for_types(candidates, {"medication", "allergy"})
        condition = self._choose_for_types(candidates, {"condition"})
        symptom = self._choose_for_types(candidates, {"symptom"})
        lab = self._choose_for_types(candidates, {"lab_result", "observation"})

        rewritten, refs = self._replace_refs(rewritten, self.MEDICATION_REFS, medication)
        resolved.extend(refs)
        rewritten, refs = self._replace_refs(rewritten, self.CONDITION_REFS, condition)
        resolved.extend(refs)
        rewritten, refs = self._replace_refs(rewritten, self.SYMPTOM_REFS, symptom)
        resolved.extend(refs)
        rewritten, refs = self._replace_refs(rewritten, self.LAB_REFS, lab)
        resolved.extend(refs)

        # Generic pronouns use semantic type hints from the current question.
        if ReferenceIntentDetector.contains_any(rewritten, self.GENERIC_REFS):
            expected = set(ReferenceIntentDetector.expected_types(rewritten))
            filtered = (
                [c for c in candidates if c.entity_type.casefold() in expected]
                if expected
                else candidates
            )
            generic_target = self.ranker.choose_unique(filtered)
            rewritten, refs = self._replace_refs(rewritten, self.GENERIC_REFS, generic_target)
            resolved.extend(refs)

        # Elliptical medication questions, e.g. "Có cần ngưng không?".
        lower = rewritten.casefold()
        if medication and not self._contains_name(rewritten, medication.canonical_name):
            if re.search(r"\b(ngưng|dừng|ngừng|tiếp tục|uống tiếp|dùng tiếp)\b", lower):
                rewritten = self._rewrite_medication_ellipsis(rewritten, medication)
                resolved.append(self._reference("[implicit medication]", medication, confidence=0.82))

        # Elliptical symptom safety/causality questions.
        lower = rewritten.casefold()
        if symptom and not self._contains_name(rewritten, symptom.canonical_name):
            if re.search(r"\b(nguy hiểm|có sao không|do .* không|bình thường không)\b", lower):
                rewritten = f"Tình trạng {symptom.canonical_name} của tôi: {self._lower_first(rewritten)}"
                resolved.append(self._reference("[implicit symptom]", symptom, confidence=0.75))

        # General subject ellipsis such as "Điều trị thế nào?" or "Còn triệu chứng?".
        # Only fill it when a unique high-priority compatible antecedent exists.
        if not resolved and not ReferenceIntentDetector.has_reference(original):
            expected = set(need.expected_types or tuple(ReferenceIntentDetector.expected_types(original)))
            filtered = (
                [c for c in candidates if c.entity_type.casefold() in expected]
                if expected
                else candidates
            )
            implicit_target = self.ranker.choose_unique(filtered)
            if implicit_target is not None:
                implicit_rewrite = self.need_detector.rewrite_implicit_subject(
                    original,
                    target_name=implicit_target.canonical_name,
                    entity_type=implicit_target.entity_type,
                )
                if implicit_rewrite is not None:
                    rewritten = implicit_rewrite
                    resolved.append(
                        self._reference("[implicit subject]", implicit_target, confidence=0.88)
                    )
            if not resolved:
                resolved.append(
                    ResolvedReference(
                        reference="[implicit subject]",
                        resolved_to=None,
                        entity_type=None,
                        source_message_id=None,
                        resolved=False,
                        confidence=0.35,
                    )
                )

        used_turns: list[str] = []
        for ref in resolved:
            if ref.resolved and ref.source_message_id and ref.source_message_id not in used_turns:
                used_turns.append(ref.source_message_id)

        resolved_confidences = [r.confidence for r in resolved if r.resolved]
        unresolved_exists = any(not r.resolved for r in resolved)
        if unresolved_exists or ReferenceIntentDetector.unresolved_reference_present(rewritten):
            confidence = 0.45
        elif resolved_confidences:
            confidence = min(resolved_confidences)
        else:
            confidence = 1.0

        result = ResolvedQuestion(
            original_question=original,
            normalized_question=normalize_whitespace(rewritten),
            subject="patient",
            resolved_references=resolved,
            used_history_turn_ids=used_turns,
            confidence=confidence,
            resolution_method="rule_ranked",
            candidate_entities=candidates,
            active_topic=self.ranker.active_topic(candidates),
        )
        return self.validator.validate(result)

    def _choose_for_types(
        self,
        candidates: list[DiscourseEntityCandidate],
        allowed_types: set[str],
    ) -> DiscourseEntityCandidate | None:
        filtered = [c for c in candidates if c.entity_type.casefold() in allowed_types]
        return self.ranker.choose_unique(filtered)

    @staticmethod
    def _replace_refs(
        text: str,
        phrases: tuple[str, ...],
        target: DiscourseEntityCandidate | None,
    ) -> tuple[str, list[ResolvedReference]]:
        refs: list[ResolvedReference] = []
        for phrase in phrases:
            pattern = re.compile(ReferenceIntentDetector.phrase_pattern(phrase), re.IGNORECASE)
            if not pattern.search(text):
                continue
            if target is None:
                refs.append(
                    ResolvedReference(
                        reference=phrase,
                        resolved_to=None,
                        entity_type=None,
                        source_message_id=None,
                        resolved=False,
                        confidence=0.35,
                    )
                )
                continue
            text = pattern.sub(target.canonical_name, text)
            refs.append(RuleBasedQuestionResolver._reference(phrase, target))
        return text, refs

    @staticmethod
    def _reference(
        reference: str,
        target: DiscourseEntityCandidate,
        confidence: float | None = None,
    ) -> ResolvedReference:
        return ResolvedReference(
            reference=reference,
            resolved_to=target.canonical_name,
            entity_type=target.entity_type,
            source_message_id=target.source_message_id,
            resolved=True,
            confidence=min(confidence or 0.95, target.score, target.mention_confidence),
        )

    @staticmethod
    def _contains_name(text: str, name: str) -> bool:
        return name.casefold() in text.casefold()

    @staticmethod
    def _rewrite_medication_ellipsis(
        text: str,
        medication: DiscourseEntityCandidate,
    ) -> str:
        lower = text.casefold()
        med = medication.canonical_name
        if re.search(r"\b(ngưng|dừng|ngừng)\b", lower):
            return re.sub(
                r"\b(ngưng|dừng|ngừng)\b",
                lambda m: f"{m.group(0)} sử dụng {med}",
                text,
                count=1,
                flags=re.IGNORECASE,
            )
        if "tiếp tục" in lower:
            return re.sub("tiếp tục", f"tiếp tục sử dụng {med}", text, count=1, flags=re.IGNORECASE)
        return f"Về việc sử dụng {med}, {RuleBasedQuestionResolver._lower_first(text)}"

    @staticmethod
    def _lower_first(text: str) -> str:
        if not text:
            return text
        return text[0].lower() + text[1:]
