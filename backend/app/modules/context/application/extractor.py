from __future__ import annotations

import re
from datetime import datetime

from app.modules.context.application.text import normalize_whitespace
from app.modules.context.domain.models import (
    AssertionType,
    Certainty,
    ClinicalFact,
    FactType,
    HistoryTurn,
    ResolvedQuestion,
    StatementType,
)


class RuleBasedClinicalExtractor:
    """A deliberately conservative baseline extractor for Vietnamese input.

    It is not intended to replace a clinical NLP model. Its purpose is to make the project
    runnable end-to-end and, crucially, demonstrate safe assertion semantics: questions and
    hypotheses are detected and are not written as active patient facts.
    """

    KNOWN_SYMPTOMS = {
        "đau đầu", "đau bụng", "buồn nôn", "nôn", "chóng mặt", "phù chân", "chân phù",
        "khó thở", "ho", "sốt", "mệt", "đau ngực", "tiêu chảy", "táo bón", "phát ban",
    }

    FAMILY_PREFIX = re.compile(r"\b(mẹ|má|bố|ba|cha|anh|chị|em|con)\s+(?:tôi|mình)\b", re.IGNORECASE)

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
        text = normalize_whitespace(original_question)
        facts: list[ClinicalFact] = []
        facts.extend(self._extract_medications(text, message_id, timestamp))
        facts.extend(self._extract_allergies(text, message_id, timestamp))
        facts.extend(self._extract_conditions_and_symptoms(text, message_id, timestamp))
        return self._deduplicate(facts)

    def _extract_medications(self, text: str, message_id: str, timestamp: datetime) -> list[ClinicalFact]:
        facts: list[ClinicalFact] = []
        patterns = [
            re.compile(
                r"\b(?:tôi\s+)?(?:đang\s+)?(?:uống|dùng|sử dụng)\s+"
                r"(?P<name>[A-Za-zÀ-ỹ][A-Za-zÀ-ỹ0-9_-]{1,40})"
                r"(?:\s+(?P<dose>\d+(?:[.,]\d+)?\s*(?:mcg|mg|g|ml)))?"
                r"(?:\s+(?:mỗi|ngày)\s*(?P<freq>\d+\s*(?:lần|viên)(?:/ngày)?))?",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(?:bác sĩ|bs)\s+(?:cho|kê)\s+(?:tôi\s+)?(?:uống|dùng)?\s*"
                r"(?P<name>[A-Za-zÀ-ỹ][A-Za-zÀ-ỹ0-9_-]{1,40})"
                r"(?:\s+(?P<dose>\d+(?:[.,]\d+)?\s*(?:mcg|mg|g|ml)))?",
                re.IGNORECASE,
            ),
        ]
        for pattern in patterns:
            for match in pattern.finditer(text):
                name = match.group("name").strip(".,;:?!")
                if name.casefold() in {"thuốc", "này", "đó", "ngày"}:
                    continue
                statement_type = self._statement_type(text, match.start())
                status = "active"
                prefix = text[max(0, match.start() - 30):match.start()].casefold()
                if any(word in prefix for word in ("đã ngưng", "đã dừng", "đã ngừng")):
                    status = "stopped"
                facts.append(
                    ClinicalFact(
                        fact_type=FactType.MEDICATION,
                        display=name,
                        dose=match.groupdict().get("dose"),
                        frequency=match.groupdict().get("freq"),
                        status=status,
                        recorded_at=timestamp,
                        assertion=AssertionType.EXPLICIT,
                        statement_type=statement_type,
                        confidence=0.88,
                        source_message_id=message_id,
                        source_text=match.group(0),
                    )
                )

        stop_pattern = re.compile(
            r"\b(?:tôi\s+)?(?:đã\s+)?(?:ngưng|dừng|ngừng)\s+(?:uống|dùng|sử dụng)?\s*"
            r"(?P<name>[A-Za-zÀ-ỹ][A-Za-zÀ-ỹ0-9_-]{1,40})",
            re.IGNORECASE,
        )
        for match in stop_pattern.finditer(text):
            name = match.group("name").strip(".,;:?!")
            if name.casefold() not in {"thuốc", "này", "đó"}:
                facts.append(
                    ClinicalFact(
                        fact_type=FactType.MEDICATION,
                        display=name,
                        status="stopped",
                        recorded_at=timestamp,
                        assertion=AssertionType.EXPLICIT,
                        statement_type=self._statement_type(text, match.start()),
                        confidence=0.9,
                        source_message_id=message_id,
                        source_text=match.group(0),
                    )
                )
        return facts

    def _extract_allergies(self, text: str, message_id: str, timestamp: datetime) -> list[ClinicalFact]:
        pattern = re.compile(
            r"\b(?:tôi\s+)?(?P<neg>không\s+)?(?:bị\s+)?dị ứng\s+(?:với\s+)?"
            r"(?P<name>[A-Za-zÀ-ỹ][A-Za-zÀ-ỹ0-9 _-]{1,50})",
            re.IGNORECASE,
        )
        facts: list[ClinicalFact] = []
        for match in pattern.finditer(text):
            name = re.split(r"[,.?!;]", match.group("name"))[0].strip()
            if not name:
                continue
            facts.append(
                ClinicalFact(
                    fact_type=FactType.ALLERGY,
                    display=name,
                    status="active",
                    negated=bool(match.group("neg")),
                    recorded_at=timestamp,
                    assertion=AssertionType.EXPLICIT,
                    statement_type=self._statement_type(text, match.start()),
                    confidence=0.92,
                    source_message_id=message_id,
                    source_text=match.group(0),
                )
            )
        return facts

    def _extract_conditions_and_symptoms(
        self, text: str, message_id: str, timestamp: datetime
    ) -> list[ClinicalFact]:
        pattern = re.compile(
            r"(?P<subject>mẹ tôi|má tôi|bố tôi|ba tôi|cha tôi|tôi)\s+"
            r"(?P<neg>không\s+)?(?:bị|mắc|được chẩn đoán(?: là)?|đang bị|đang)\s+"
            r"(?P<concept>[^.?!;]{2,120})",
            re.IGNORECASE,
        )
        facts: list[ClinicalFact] = []
        for match in pattern.finditer(text):
            raw = match.group("concept").strip()
            raw = re.split(r"\b(?:nhưng|nên|thì)\b", raw, maxsplit=1, flags=re.IGNORECASE)[0].strip()
            if not raw:
                continue

            subject = match.group("subject").casefold()
            experiencer = "patient" if subject == "tôi" else self._family_role(subject)
            statement_type = self._statement_type(text, match.start())
            negated = bool(match.group("neg"))

            # Split coordinated clinical concepts, then reduce symptom displays to
            # atomic canonical spans ("ho", "sốt") instead of whole propositions.
            parts = [p.strip() for p in re.split(r"\s+và\s+|,", raw, flags=re.IGNORECASE) if p.strip()]
            for part in parts:
                lowered = part.casefold()
                matched_symptoms = [
                    symptom
                    for symptom in sorted(self.KNOWN_SYMPTOMS, key=len, reverse=True)
                    if re.search(rf"(?<!\w){re.escape(symptom)}(?!\w)", lowered)
                ]
                if matched_symptoms:
                    for symptom in matched_symptoms:
                        fact_type = FactType.SYMPTOM if experiencer == "patient" else FactType.FAMILY_HISTORY
                        facts.append(
                            ClinicalFact(
                                fact_type=fact_type,
                                display=symptom,
                                status="active",
                                negated=negated,
                                experiencer=experiencer,
                                recorded_at=timestamp,
                                assertion=AssertionType.EXPLICIT,
                                statement_type=statement_type,
                                confidence=0.86,
                                source_message_id=message_id,
                                source_text=match.group(0),
                                attributes={"related_fact_type": "symptom"} if fact_type == FactType.FAMILY_HISTORY else {},
                            )
                        )
                    continue

                concept = re.sub(
                    r"\s+(?:trong|kéo dài|được|từ)\s+\d+.*$",
                    "",
                    part,
                    flags=re.IGNORECASE,
                ).strip(" ,.;:?!")
                if not concept:
                    continue
                fact_type = FactType.CONDITION if experiencer == "patient" else FactType.FAMILY_HISTORY
                facts.append(
                    ClinicalFact(
                        fact_type=fact_type,
                        display=concept,
                        status="active",
                        negated=negated,
                        experiencer=experiencer,
                        recorded_at=timestamp,
                        assertion=AssertionType.EXPLICIT,
                        statement_type=statement_type,
                        confidence=0.78,
                        source_message_id=message_id,
                        source_text=match.group(0),
                        attributes={"related_fact_type": "condition"} if fact_type == FactType.FAMILY_HISTORY else {},
                    )
                )
        return facts

    @staticmethod
    def _statement_type(text: str, match_start: int) -> StatementType:
        before = text[:match_start].casefold().strip()
        sentence_start = max(text.rfind(".", 0, match_start), text.rfind("?", 0, match_start), text.rfind("!", 0, match_start)) + 1
        endings = [i for i in (text.find(".", match_start), text.find("?", match_start), text.find("!", match_start)) if i >= 0]
        sentence_end = min(endings) + 1 if endings else len(text)
        sentence = text[sentence_start:sentence_end].casefold().strip()

        if re.search(r"\b(nếu|giả sử|trong trường hợp)\b", (before[-80:] + " " + sentence)):
            return StatementType.HYPOTHESIS

        # A mixed utterance can contain a valid assertion followed by a diagnostic
        # question: "Tôi đang sốt, liệu tôi có bị viêm phổi không?". The assertion
        # before the transition remains FACT.
        transition = re.search(r"[,;]\s*(?:liệu|có phải|vậy thì|thế thì)\b", sentence, re.IGNORECASE)
        if not transition and re.search(r"\b(tôi|tui|mình|em|cháu)\b", sentence):
            transition = re.search(r"\b(?:thì|vậy)\s+(?=(?:(?:tôi|tui|mình|em|cháu)\s+)?(?:bị|mắc|là)\s+.*\b(?:gì|nào)\b)", sentence, re.I)
        relative_match_start = match_start - sentence_start
        question_applies = not transition or relative_match_start >= transition.start()
        if question_applies and ("?" in sentence or re.search(r"\b(có .* không|được không|nên .* không)\b", sentence)):
            return StatementType.QUESTION
        if re.search(r"\b(định|dự định|sẽ bắt đầu|muốn bắt đầu)\b", (before[-50:] + " " + sentence)):
            return StatementType.PLAN
        return StatementType.FACT

    @staticmethod
    def _family_role(subject: str) -> str:
        mapping = {
            "mẹ tôi": "mother",
            "má tôi": "mother",
            "bố tôi": "father",
            "ba tôi": "father",
            "cha tôi": "father",
        }
        return mapping.get(subject, "family_member")

    @staticmethod
    def _deduplicate(facts: list[ClinicalFact]) -> list[ClinicalFact]:
        result: list[ClinicalFact] = []
        seen: set[tuple] = set()
        for fact in facts:
            key = (
                fact.fact_type.value,
                fact.display.casefold(),
                fact.statement_type.value,
                fact.experiencer,
                fact.negated,
                fact.dose,
            )
            if key not in seen:
                seen.add(key)
                result.append(fact)
        return result
