from __future__ import annotations

import re

from app.modules.context.application.text import normalize_whitespace, normalized_key
from app.modules.context.domain.models import ClinicalFact, FactType


class PatientAssertionGate:
    """Deterministic safety gate before anything is written to Patient Graph.

    The clinical extractor may be LLM-backed and can occasionally misclassify a
    knowledge question as a patient fact. This gate requires direct evidence that
    a fact is actually asserted about the patient (or explicitly as family history).

    Discourse mentions are handled independently, so rejecting a patient fact here
    does *not* remove the entity from History/Discourse context.
    """

    _QUESTION_CUES = (
        r"\blà\s+gì\b",
        r"\bcó\s+.+\s+không\b",
        r"\bcó\s+phải\b",
        r"\bliệu\b",
        r"\bphải\s+không\b",
        r"\bbao\s+nhiêu\b",
        r"\bnhư\s+thế\s+nào\b",
        r"\bra\s+sao\b",
        r"\btại\s+sao\b",
        r"\bvì\s+sao\b",
        r"\bkhi\s+nào\b",
        r"\bở\s+đâu\b",
        r"\bai\b",
        r"\bgì\b",
    )
    _HYPOTHETICAL_CUES = re.compile(
        r"\b(nếu|giả\s+sử|giả\s+định|trong\s+trường\s+hợp|ví\s+dụ\s+nếu)\b",
        re.IGNORECASE,
    )
    _PLAN_CUES = re.compile(
        r"\b(dự\s+định|định\s+uống|định\s+dùng|sẽ\s+bắt\s+đầu|muốn\s+bắt\s+đầu)\b",
        re.IGNORECASE,
    )

    _PATIENT_PRONOUN = r"(?:tôi|mình|em|cháu)"
    _FAMILY_PRONOUN = r"(?:mẹ|má|bố|ba|cha|anh|chị|em|con|ông|bà)\s+(?:tôi|mình)"

    _SYMPTOM_WORDS = (
        "ho",
        "sốt",
        "khó thở",
        "đau ngực",
        "đau đầu",
        "đau bụng",
        "buồn nôn",
        "nôn",
        "chóng mặt",
        "mệt",
        "phát ban",
        "tiêu chảy",
        "táo bón",
        "phù",
    )

    _GENERIC_DISPLAY_PREFIXES = (
        "các triệu chứng",
        "những triệu chứng",
        "triệu chứng của",
        "các dấu hiệu",
        "dấu hiệu của",
        "các biểu hiện",
        "biểu hiện của",
        "tình trạng của",
        "câu hỏi về",
        "thông tin về",
        "tôi ",
        "bệnh nhân ",
    )

    @staticmethod
    def is_general_information_question(text: str) -> bool:
        """Fast path only for an explicit, impersonal knowledge question.

        Anything personal, multi-clause or ambiguous retains the full extractor.
        This is an extraction gate, never an intent classifier or diagnosis rule.
        """
        value = normalize_whitespace(text).casefold().strip().rstrip('?.!')
        if re.search(r'[,;\n!?]|\b(tôi|tui|mình|em|cháu|con|bạn|ông|bà|anh|chị|mẹ|má|ba|bố|cha|bệnh nhân|bé|trẻ|người nhà|nếu|giả sử)\b', value):
            return False
        patterns = (
            r'(?:bệnh )?[\w -]{2,70} là gì',
            r'(?:bệnh )?[\w -]{2,70} có (?:những |các )?(?:triệu chứng|dấu hiệu|biểu hiện|nguyên nhân) (?:gì|nào)',
            r'(?:các |những )?(?:triệu chứng|dấu hiệu|biểu hiện|nguyên nhân) (?:của )?(?:bệnh )?[\w -]{2,70}(?: là gì| là những gì)?',
        )
        # Personal state/time phrases must not slip through a broad topic slot.
        if re.search(r'\b(bị|đang|vừa|từng|hôm|ngày|tuần|tháng|năm|không|hổng|hông|chưa|chẳng|sau khi|kèm|kéo dài)\b', value):
            return False
        return any(re.fullmatch(pattern, value) for pattern in patterns)

    def filter(self, *, original_text: str, facts: list[ClinicalFact]) -> list[ClinicalFact]:
        source = normalize_whitespace(original_text)
        accepted: list[ClinicalFact] = []
        for fact in facts:
            if not self._atomic_display(fact.display):
                continue
            evidence = self._evidence_clause(source, fact)
            if not evidence:
                continue
            if self._is_question_like(evidence):
                continue
            if self._HYPOTHETICAL_CUES.search(evidence):
                continue
            if self._PLAN_CUES.search(evidence):
                continue
            if fact.fact_type == FactType.FAMILY_HISTORY:
                if not self._supports_family_history(evidence):
                    continue
            elif fact.experiencer != "patient":
                # Non-patient facts must be represented explicitly as FAMILY_HISTORY.
                continue
            elif not self._supports_patient_fact(evidence, fact):
                continue
            accepted.append(fact)
        return accepted

    def _atomic_display(self, display: str) -> bool:
        value = normalize_whitespace(display).strip(" \t\r\n,.;:?!\"'()[]{}")
        if not value or len(value) > 96:
            return False
        key = normalized_key(value)
        if not key:
            return False
        if len(key.split()) > 10:
            return False
        if any(key.startswith(normalized_key(prefix)) for prefix in self._GENERIC_DISPLAY_PREFIXES):
            return False
        if self._is_question_like(value):
            return False
        return True

    def _evidence_clause(self, original_text: str, fact: ClinicalFact) -> str:
        candidates = self._split_clauses(original_text)
        display_key = normalized_key(fact.display)

        # Prefer a local clause from the original user utterance containing the concept.
        for clause in candidates:
            if display_key and display_key in normalized_key(clause):
                return clause

        # source_text is secondary evidence and must still be a substring-like extract,
        # not an arbitrary LLM-generated summary.
        if fact.source_text:
            src = normalize_whitespace(fact.source_text)
            src_key = normalized_key(src)
            original_key = normalized_key(original_text)
            if src_key and (src_key in original_key):
                for clause in self._split_clauses(src):
                    if not display_key or display_key in normalized_key(clause):
                        return clause

        return ""

    @staticmethod
    def _split_clauses(text: str) -> list[str]:
        # Preserve transition phrases as part of the following clause so interrogative
        # semantics are not lost: "Tôi đang sốt, liệu tôi có bị viêm phổi không?"
        marked = re.sub(
            r"\b(liệu|có\s+phải|vậy\s+thì|thế\s+thì)\b",
            r"|||\1 ",
            text,
            flags=re.IGNORECASE,
        )
        # A personal assertion followed by a diagnostic question remains evidence:
        # "Tôi bị ho khan thì bị gì?". Do not split hypothetical/general questions.
        if (re.search(r"\b(tôi|tui|mình|em|cháu)\b", text, re.I)
                and not re.search(r"\b(nếu|giả sử|giả định)\b", text, re.I)):
            marked = re.sub(r"\b(thì|vậy)\s+(?=(?:(?:tôi|tui|mình|em|cháu)\s+)?(?:bị|mắc|là)\s+.*\b(?:gì|nào)\b)",
                            r"|||\1 ", marked, flags=re.I)
        raw = re.split(r"\|\|\||[,;]|(?<=[.!?])\s+", marked)
        return [normalize_whitespace(part) for part in raw if normalize_whitespace(part)]

    def _is_question_like(self, text: str) -> bool:
        lower = normalize_whitespace(text).casefold()
        if "?" in lower:
            return True
        return any(re.search(pattern, lower, flags=re.IGNORECASE) for pattern in self._QUESTION_CUES)

    def _supports_family_history(self, clause: str) -> bool:
        lower = clause.casefold()
        return bool(
            re.search(rf"\b{self._FAMILY_PRONOUN}\b", lower, flags=re.IGNORECASE)
            and re.search(r"\b(bị|mắc|được\s+chẩn\s+đoán|có)\b", lower, flags=re.IGNORECASE)
        )

    def _supports_patient_fact(self, clause: str, fact: ClinicalFact) -> bool:
        lower = clause.casefold()
        has_patient = bool(re.search(rf"\b{self._PATIENT_PRONOUN}\b", lower, flags=re.IGNORECASE))

        if fact.fact_type == FactType.MEDICATION:
            return bool(
                re.search(r"\b(uống|dùng|sử\s+dụng|ngưng|ngừng|dừng)\b", lower)
                and (has_patient or re.search(r"\b(bác\s+sĩ|bs)\b", lower))
            )

        if fact.fact_type == FactType.ALLERGY:
            return bool(re.search(r"\bdị\s+ứng\b", lower) and has_patient)

        if fact.fact_type == FactType.CONDITION:
            return bool(
                has_patient
                and re.search(r"\b(bị|mắc|được\s+chẩn\s+đoán(?:\s+là)?)\b", lower)
            ) or bool(
                re.search(r"\b(bác\s+sĩ|bs)\b.*\bchẩn\s+đoán\b.*\b(tôi|mình|em|cháu)\b", lower)
            )

        if fact.fact_type == FactType.SYMPTOM:
            if has_patient and re.search(r"\b(bị|có|đang|thấy|cảm\s+thấy)\b", lower):
                return True
            if has_patient and any(re.search(rf"(?<!\w){re.escape(sym)}(?!\w)", lower) for sym in self._SYMPTOM_WORDS):
                return True
            # In a patient chat, short declarative symptom fragments such as
            # "Sốt 3 ngày rồi." are treated as direct self-report if not interrogative.
            if any(lower.startswith(sym) for sym in self._SYMPTOM_WORDS):
                return True
            return False

        if fact.fact_type in {FactType.LAB_RESULT, FactType.OBSERVATION}:
            return bool(
                (has_patient or "của tôi" in lower)
                and re.search(r"\b(xét\s+nghiệm|chỉ\s+số|kết\s+quả|tăng|giảm|cao|thấp|bằng|là)\b", lower)
            )

        if fact.fact_type == FactType.PROCEDURE:
            return bool(
                has_patient
                and re.search(r"\b(đã|được|vừa|từng)\b.*\b(phẫu\s+thuật|nội\s+soi|chụp|thủ\s+thuật|điều\s+trị)\b", lower)
            )

        if fact.fact_type == FactType.LIFESTYLE:
            return bool(has_patient and re.search(r"\b(hút\s+thuốc|uống\s+rượu|tập\s+thể\s+dục|ăn\s+uống)\b", lower))

        return has_patient
