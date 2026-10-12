from __future__ import annotations

import re

from app.modules.context.application.text import normalize_whitespace
from app.modules.context.domain.models import ClinicalFact, HistoryMention


class RuleBasedDiscourseEntityExtractor:
    """Extract discourse mentions independently from patient-fact validity.

    This layer intentionally records entities discussed in questions/hypotheses without
    asserting that the patient has the disease, symptom, or medication.
    """

    KNOWN_SYMPTOMS = (
        "khó thở",
        "đau ngực",
        "đau đầu",
        "đau bụng",
        "buồn nôn",
        "chóng mặt",
        "tiêu chảy",
        "táo bón",
        "phát ban",
        "ho",
        "sốt",
        "mệt",
        "nôn",
    )

    STOP_NAMES = {
        "nó",
        "cái này",
        "cái đó",
        "bệnh này",
        "bệnh đó",
        "thuốc này",
        "thuốc đó",
        "triệu chứng này",
        "triệu chứng đó",
        "tình trạng này",
        "tình trạng đó",
    }

    async def extract(
        self,
        *,
        text: str,
        clinical_candidates: list[ClinicalFact] | None = None,
    ) -> list[HistoryMention]:
        source = normalize_whitespace(text)
        mentions: list[HistoryMention] = []

        # A candidate can enter History only when its display is grounded in this turn.
        # Resolved pronouns are merged separately with their reference provenance.
        for fact in clinical_candidates or []:
            if not self._usable_candidate_display(fact.display):
                continue
            span = re.search(rf"(?<!\w){re.escape(fact.display)}(?!\w)", source, re.IGNORECASE)
            if span is None:
                continue
            entity_type = (
                fact.attributes.get("related_fact_type", "condition")
                if fact.fact_type.value == "family_history"
                else fact.fact_type.value
            )
            mentions.append(
                HistoryMention(
                    text=source[span.start():span.end()],
                    start=span.start(),
                    end=span.end(),
                    entity_type=entity_type,
                    canonical_name=fact.display,
                    entity_id=fact.concept_id,
                    confidence=max(0.55, fact.confidence),
                    origin="clinical_candidate",
                )
            )

        mentions.extend(self._extract_comparison(source))
        mentions.extend(self._extract_topic_subject(source))
        mentions.extend(self._extract_medication_cues(source))
        mentions.extend(self._extract_known_symptoms(source))
        return self._deduplicate(mentions)

    def _extract_comparison(self, text: str) -> list[HistoryMention]:
        pattern = re.compile(
            r"^(?P<a>[^?!.]{2,60}?)\s+khác\s+(?P<b>[^?!.]{2,60}?)\s+"
            r"(?:như thế nào|ra sao|ở điểm nào)\??$",
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if not match:
            return []
        result: list[HistoryMention] = []
        for key in ("a", "b"):
            name = self._clean_name(match.group(key))
            if self._valid_name(name):
                result.append(
                    HistoryMention(
                        text=name,
                        entity_type="condition",
                        canonical_name=name,
                        start=match.start(key),
                        end=match.end(key),
                        confidence=0.88,
                        origin="explicit",
                    )
                )
        return result

    def _extract_topic_subject(self, text: str) -> list[HistoryMention]:
        patterns = [
            re.compile(
                r"^(?:(?:các|những)\s+)?(?:triệu chứng|dấu hiệu|biểu hiện|nguyên nhân|cách điều trị)"
                r"\s+(?:của\s+)?(?P<name>[^?!.]{2,80}?)(?:\s+là gì)?[?!.]*$",
                re.IGNORECASE,
            ),
            re.compile(
                r"^(?P<name>[^?!.]{2,80}?)\s+(?:là\s+(?:thuốc\s+)?gì|có\s+triệu\s+chứng\s+gì|"
                r"có\s+dấu\s+hiệu\s+gì|có\s+biểu\s+hiện\s+gì|có\s+nguy\s+hiểm\s+không|"
                r"được\s+điều\s+trị\s+(?:như thế nào|ra sao))\??$",
                re.IGNORECASE,
            ),
            re.compile(
                r"^(?P<name>[^?!.]{2,80}?)\s+là\s+(?:một\s+)?(?:bệnh|tình trạng|hội chứng)\b",
                re.IGNORECASE,
            ),
        ]
        mentions: list[HistoryMention] = []
        for pattern in patterns:
            match = pattern.search(text)
            if not match:
                continue
            name = self._clean_name(match.group("name"))
            entity_type = self._guess_type(name, text)
            if self._valid_name(name):
                mentions.append(
                    HistoryMention(
                        text=name,
                        entity_type=entity_type,
                        canonical_name=name,
                        start=match.start("name"),
                        end=match.end("name"),
                        confidence=0.90,
                        origin="explicit",
                    )
                )
        return mentions

    def _extract_medication_cues(self, text: str) -> list[HistoryMention]:
        patterns = [
            re.compile(
                r"\b(?:thuốc|uống|dùng|sử dụng)\s+(?P<name>[A-Za-zÀ-ỹ][A-Za-zÀ-ỹ0-9_-]{2,40})",
                re.IGNORECASE,
            )
        ]
        result: list[HistoryMention] = []
        for pattern in patterns:
            for match in pattern.finditer(text):
                name = self._clean_name(match.group("name"))
                if self._valid_name(name) and name.casefold() not in {"này", "đó", "tiếp"}:
                    result.append(
                        HistoryMention(
                            text=name,
                            entity_type="medication",
                            canonical_name=name,
                            start=match.start("name"),
                            end=match.end("name"),
                            confidence=0.82,
                            origin="explicit",
                        )
                    )
        return result

    def _extract_known_symptoms(self, text: str) -> list[HistoryMention]:
        lower = text.casefold()
        result: list[HistoryMention] = []
        for symptom in sorted(self.KNOWN_SYMPTOMS, key=len, reverse=True):
            for match in re.finditer(rf"(?<!\w){re.escape(symptom)}(?!\w)", lower, re.IGNORECASE):
                result.append(
                    HistoryMention(
                        text=text[match.start():match.end()],
                        entity_type="symptom",
                        canonical_name=text[match.start():match.end()],
                        start=match.start(),
                        end=match.end(),
                        confidence=0.84,
                        origin="explicit",
                    )
                )
        return result


    @staticmethod
    def _usable_candidate_display(value: str) -> bool:
        value = normalize_whitespace(value).strip(" \t\r\n,.;:?!\"'()[]{}")
        if not value or len(value) > 96 or len(value.split()) > 10:
            return False
        lower = value.casefold()
        bad_prefixes = (
            "các triệu chứng", "những triệu chứng", "triệu chứng của",
            "các dấu hiệu", "dấu hiệu của", "các biểu hiện", "biểu hiện của",
            "thông tin về", "câu hỏi về", "tôi ", "bệnh nhân ",
        )
        if lower.startswith(bad_prefixes):
            return False
        if any(token in lower for token in (" là gì", " có triệu chứng gì", " có dấu hiệu gì")):
            return False
        return True

    @staticmethod
    def _guess_type(name: str, text: str) -> str:
        lower_name = name.casefold()
        lower_text = text.casefold()
        if (
            lower_name.startswith("thuốc ")
            or "tác dụng phụ" in lower_text
            or "thuốc gì" in lower_text
            or "là thuốc" in lower_text
        ):
            return "medication"
        if lower_name.startswith("triệu chứng "):
            return "symptom"
        if lower_name.startswith("chỉ số ") or lower_name.startswith("xét nghiệm "):
            return "lab_result"
        return "condition"

    @staticmethod
    def _clean_name(value: str) -> str:
        value = value.strip(" \t\r\n,.;:?!\"'()[]{}")
        value = re.sub(r"^(?:bệnh|thuốc|triệu chứng)\s+", "", value, flags=re.IGNORECASE)
        return normalize_whitespace(value)

    def _valid_name(self, value: str) -> bool:
        return bool(value and len(value) >= 2 and value.casefold() not in self.STOP_NAMES)

    @staticmethod
    def _deduplicate(items: list[HistoryMention]) -> list[HistoryMention]:
        # Direct text mentions must beat LLM clinical-candidate echoes even when the
        # LLM reports a slightly higher confidence. v2.2 relies on this distinction
        # for reliable topic switching.
        origin_priority = {
            "explicit": 0,
            "resolved_reference": 1,
            "clinical_candidate": 2,
            "legacy_inferred": 3,
        }
        best: dict[tuple[str, str], HistoryMention] = {}
        order: list[tuple[str, str]] = []
        for item in items:
            key = (item.entity_type.casefold(), item.canonical_name.casefold())
            if key not in best:
                order.append(key)
                best[key] = item
                continue
            old = best[key]
            old_priority = origin_priority.get(old.origin, 9)
            new_priority = origin_priority.get(item.origin, 9)
            if new_priority < old_priority or (
                new_priority == old_priority and item.confidence > old.confidence
            ):
                best[key] = item
        return [best[key] for key in order]
