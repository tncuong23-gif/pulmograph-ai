from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass

from app.modules.context.domain.models import (
    DiscourseEntityCandidate,
    HistoryMention,
    HistoryTurn,
    PatientContext,
    ResolvedQuestion,
    ResolvedReference,
    Role,
)


class ReferenceIntentDetector:
    """Detect reference words and entity types compatible with the current intent."""

    GENERIC_REFS = ("nó", "cái đó", "cái này", "đối tượng đó", "đối tượng này")
    MEDICATION_REFS = ("thuốc đó", "thuốc này", "loại thuốc đó", "loại thuốc này")
    CONDITION_REFS = ("bệnh đó", "bệnh này", "chẩn đoán đó", "chẩn đoán này")
    SYMPTOM_REFS = (
        "triệu chứng đó",
        "triệu chứng này",
        "tình trạng đó",
        "tình trạng này",
        "biểu hiện đó",
        "biểu hiện này",
    )
    LAB_REFS = ("chỉ số đó", "chỉ số này", "kết quả đó", "kết quả này")

    @staticmethod
    def phrase_pattern(phrase: str) -> str:
        # Unicode-aware token boundaries prevent pronouns such as "nó" from
        # matching inside unrelated words such as "nóng".
        return rf"(?<!\w){re.escape(phrase)}(?!\w)"

    @classmethod
    def contains_phrase(cls, text: str, phrase: str) -> bool:
        return re.search(cls.phrase_pattern(phrase), text, flags=re.IGNORECASE) is not None

    @classmethod
    def contains_any(cls, text: str, phrases: tuple[str, ...]) -> bool:
        return any(cls.contains_phrase(text, phrase) for phrase in phrases)

    @classmethod
    def has_reference(cls, text: str) -> bool:
        return cls.contains_any(
            text,
            (
                *cls.GENERIC_REFS,
                *cls.MEDICATION_REFS,
                *cls.CONDITION_REFS,
                *cls.SYMPTOM_REFS,
                *cls.LAB_REFS,
            ),
        )

    @classmethod
    def unresolved_reference_present(cls, text: str) -> bool:
        return cls.has_reference(text)

    @classmethod
    def expected_types(cls, text: str) -> list[str]:
        lower = text.casefold()

        if cls.contains_any(text, cls.MEDICATION_REFS):
            return ["medication", "allergy"]
        if cls.contains_any(text, cls.CONDITION_REFS):
            return ["condition"]
        if cls.contains_any(text, cls.SYMPTOM_REFS):
            return ["symptom", "condition"]
        if cls.contains_any(text, cls.LAB_REFS):
            return ["lab_result", "observation"]

        # Semantic hints for generic references such as "nó".
        if re.search(r"\b(triệu chứng|dấu hiệu|biểu hiện)\b", lower):
            return ["condition"]
        if re.search(r"\b(tác dụng phụ|liều|ngưng|ngừng|dừng|uống|dùng|tương tác|thuốc)\b", lower):
            return ["medication", "allergy"]
        if re.search(r"\b(xét nghiệm|chỉ số|kết quả|nồng độ|giá trị)\b", lower):
            return ["lab_result", "observation"]
        if re.search(r"\b(kéo dài|đỡ|hết|tái phát|nặng hơn|đau|ho|sốt|khó thở)\b", lower):
            return ["symptom", "condition"]
        if re.search(r"\b(nguy hiểm|bệnh|chẩn đoán|điều trị|nguyên nhân|biến chứng)\b", lower):
            return ["condition"]
        return []


@dataclass(frozen=True)
class ContextNeedDecision:
    status: str  # not_needed | needs_resolution | uncertain
    reason: str
    expected_types: tuple[str, ...] = ()


class ContextNeedDetector:
    """Decide whether a question actually needs conversational restoration.

    v2.3 follows a conservative rule:
    - A clear/self-contained question is never rewritten.
    - Explicit references or known subject-ellipsis patterns require resolution.
    - Broad discourse continuations are marked uncertain and may be resolved only
      when a unique high-priority antecedent exists.
    """

    # Patterns are deliberately anchored. A full question such as
    # "Viêm phổi có nguy hiểm không?" must NOT be mistaken for the elliptical
    # "Có nguy hiểm không?".
    ELLIPSIS_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"^(?:có\s+)?nguy\s+hiểm\s+không\s*[?!.]*$", re.IGNORECASE),
        re.compile(r"^(?:điều\s+trị|chữa)\s+(?:thế\s+nào|như\s+thế\s+nào|ra\s+sao)\s*[?!.]*$", re.IGNORECASE),
        re.compile(r"^(?:có\s+)?(?:điều\s+trị|chữa)\s+được\s+không\s*[?!.]*$", re.IGNORECASE),
        re.compile(r"^(?:còn\s+)?(?:triệu\s+chứng|dấu\s+hiệu|biểu\s+hiện)(?:\s+(?:gì|nào|nào\s+khác))?\s*[?!.]*$", re.IGNORECASE),
        re.compile(r"^(?:còn\s+)?(?:nguyên\s+nhân|biến\s+chứng)(?:\s+(?:gì|là\s+gì))?\s*[?!.]*$", re.IGNORECASE),
        re.compile(r"^(?:phòng\s+ngừa|phòng\s+bệnh)\s+(?:thế\s+nào|như\s+thế\s+nào|ra\s+sao)\s*[?!.]*$", re.IGNORECASE),
        re.compile(r"^(?:có\s+)?cần\s+(?:ngưng|ngừng|dừng|tiếp\s+tục)(?:\s+(?:dùng|uống))?\s+không\s*[?!.]*$", re.IGNORECASE),
        re.compile(r"^(?:liều|liều\s+dùng|cách\s+dùng|tác\s+dụng\s+phụ)(?:\s+(?:thế\s+nào|như\s+thế\s+nào|là\s+gì|gì))?\s*[?!.]*$", re.IGNORECASE),
    )
    UNCERTAIN_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"^(?:còn|thế\s+còn|vậy\s+còn)\s+(?:gì|sao|thế\s+nào)(?:\s+nữa)?\s*[?!.]*$", re.IGNORECASE),
        re.compile(r"^(?:rồi\s+)?sao\s+nữa\s*[?!.]*$", re.IGNORECASE),
    )

    @classmethod
    def detect(cls, text: str) -> ContextNeedDecision:
        normalized = " ".join(text.strip().split())
        if ReferenceIntentDetector.has_reference(normalized):
            return ContextNeedDecision(
                status="needs_resolution",
                reason="explicit_reference",
                expected_types=tuple(ReferenceIntentDetector.expected_types(normalized)),
            )
        if any(pattern.match(normalized) for pattern in cls.ELLIPSIS_PATTERNS):
            return ContextNeedDecision(
                status="needs_resolution",
                reason="subject_ellipsis",
                expected_types=tuple(ReferenceIntentDetector.expected_types(normalized)),
            )
        if any(pattern.match(normalized) for pattern in cls.UNCERTAIN_PATTERNS):
            return ContextNeedDecision(
                status="uncertain",
                reason="broad_discourse_ellipsis",
                expected_types=tuple(ReferenceIntentDetector.expected_types(normalized)),
            )
        return ContextNeedDecision(status="not_needed", reason="self_contained")

    @classmethod
    def needs_resolution(cls, text: str) -> bool:
        return cls.detect(text).status != "not_needed"

    @staticmethod
    def rewrite_implicit_subject(
        text: str,
        *,
        target_name: str,
        entity_type: str,
    ) -> str | None:
        """Deterministically fill only the omitted subject; do not paraphrase clear text."""
        q = " ".join(text.strip().split())
        lower = q.casefold().rstrip("?!. ")
        name = target_name

        if re.fullmatch(r"(?:có\s+)?nguy\s+hiểm\s+không", lower):
            return f"{name} có nguy hiểm không?"
        if re.fullmatch(r"điều\s+trị\s+(?:thế\s+nào|như\s+thế\s+nào|ra\s+sao)", lower):
            tail = re.sub(r"^điều\s+trị\s+", "", lower, count=1)
            return f"{name} được điều trị {tail}?"
        if re.fullmatch(r"chữa\s+(?:thế\s+nào|như\s+thế\s+nào|ra\s+sao)", lower):
            tail = re.sub(r"^chữa\s+", "", lower, count=1)
            return f"{name} được chữa {tail}?"
        if re.fullmatch(r"(?:có\s+)?điều\s+trị\s+được\s+không", lower):
            return f"{name} có điều trị được không?"
        if re.fullmatch(r"(?:có\s+)?chữa\s+được\s+không", lower):
            return f"{name} có chữa được không?"
        if re.fullmatch(r"(?:còn\s+)?triệu\s+chứng(?:\s+(?:gì|nào|nào\s+khác))?", lower):
            return f"{name} có triệu chứng gì?"
        if re.fullmatch(r"(?:còn\s+)?(?:dấu\s+hiệu|biểu\s+hiện)(?:\s+(?:gì|nào|nào\s+khác))?", lower):
            return f"{name} có dấu hiệu gì?"
        if re.fullmatch(r"(?:còn\s+)?nguyên\s+nhân(?:\s+(?:gì|là\s+gì))?", lower):
            return f"Nguyên nhân của {name} là gì?"
        if re.fullmatch(r"(?:còn\s+)?biến\s+chứng(?:\s+(?:gì|là\s+gì))?", lower):
            return f"{name} có biến chứng gì?"
        if re.fullmatch(r"(?:phòng\s+ngừa|phòng\s+bệnh)\s+(?:thế\s+nào|như\s+thế\s+nào|ra\s+sao)", lower):
            return f"Phòng ngừa {name} như thế nào?"
        if re.fullmatch(r"(?:có\s+)?cần\s+(?:ngưng|ngừng|dừng|tiếp\s+tục)(?:\s+(?:dùng|uống))?\s+không", lower):
            if entity_type.casefold() not in {"medication", "allergy"}:
                return None
            action = re.search(r"(ngưng|ngừng|dừng|tiếp\s+tục)", lower)
            verb = action.group(1) if action else "ngưng"
            return f"Có cần {verb} sử dụng {name} không?"
        if re.fullmatch(r"(?:tác\s+dụng\s+phụ)(?:\s+(?:thế\s+nào|như\s+thế\s+nào|là\s+gì|gì))?", lower):
            return f"{name} có tác dụng phụ gì?"
        if re.fullmatch(r"(?:liều|liều\s+dùng|cách\s+dùng)(?:\s+(?:thế\s+nào|như\s+thế\s+nào|là\s+gì|gì))?", lower):
            return f"Cách dùng {name} như thế nào?"
        return None


@dataclass(frozen=True)
class DiscourseFocus:
    keys: frozenset[tuple[str, str]]
    tier: int
    source_message_id: str | None
    ambiguous: bool
    reason: str


class DiscourseFocusManager:
    """Derive the active conversational topic from recent history.

    Priority is intentionally categorical rather than a tiny numeric recency boost:
    - Tier 1: latest USER turn explicitly names one compatible entity (or multiple -> ambiguous).
    - Tier 2: latest USER resolved-reference topic, or latest explicit assistant topic.
    - No focus: fall back to ordinary ranked history.

    This makes a real topic switch such as "COPD là gì?" dominate an older, repeatedly
    discussed "Viêm phổi" topic without making a two-entity comparison falsely deterministic.
    """

    @staticmethod
    def _compatible(mention: HistoryMention, expected: list[str]) -> bool:
        if not expected:
            return True
        return mention.entity_type.casefold() in {x.casefold() for x in expected}

    @staticmethod
    def _key(mention: HistoryMention) -> tuple[str, str]:
        return (mention.entity_type.casefold(), mention.canonical_name.casefold())

    def detect(
        self,
        *,
        history_context: list[HistoryTurn],
        expected_types: list[str],
        mention_provider,
    ) -> DiscourseFocus | None:
        # Strongest signal: explicit compatible entity in latest USER turn that has one.
        for turn in reversed(history_context):
            if turn.role != Role.USER:
                continue
            mentions = turn.mentions or mention_provider(turn.original_text)
            explicit = [
                m for m in mentions
                if m.origin == "explicit" and self._compatible(m, expected_types)
            ]
            if explicit:
                keys = frozenset(self._key(m) for m in explicit)
                return DiscourseFocus(
                    keys=keys,
                    tier=1,
                    source_message_id=turn.message_id,
                    ambiguous=len(keys) > 1,
                    reason="latest_user_explicit",
                )

        # If the user's most recent discourse-only turn inherited a topic through a
        # validated pronoun, keep that topic active until a new explicit topic appears.
        for turn in reversed(history_context):
            if turn.role != Role.USER:
                continue
            mentions = turn.mentions or mention_provider(turn.original_text)
            inherited = [
                m for m in mentions
                if m.origin == "resolved_reference" and self._compatible(m, expected_types)
            ]
            if inherited:
                keys = frozenset(self._key(m) for m in inherited)
                return DiscourseFocus(
                    keys=keys,
                    tier=2,
                    source_message_id=turn.message_id,
                    ambiguous=len(keys) > 1,
                    reason="active_resolved_topic",
                )

        # Assistant can establish the topic when there is no suitable user focus.
        for turn in reversed(history_context):
            mentions = turn.mentions or mention_provider(turn.original_text)
            explicit = [
                m for m in mentions
                if m.origin == "explicit" and self._compatible(m, expected_types)
            ]
            if explicit:
                keys = frozenset(self._key(m) for m in explicit)
                return DiscourseFocus(
                    keys=keys,
                    tier=2,
                    source_message_id=turn.message_id,
                    ambiguous=len(keys) > 1,
                    reason="latest_conversation_explicit",
                )
        return None


class AntecedentCandidateRanker:
    """Rank antecedents using discourse-priority tiers first, score second."""

    def __init__(self) -> None:
        self.focus_manager = DiscourseFocusManager()

    def rank(
        self,
        *,
        question: str,
        history_context: list[HistoryTurn],
        patient_context: PatientContext,
        limit: int = 8,
    ) -> list[DiscourseEntityCandidate]:
        expected = ReferenceIntentDetector.expected_types(question)
        candidates: list[DiscourseEntityCandidate] = []
        focus = self.focus_manager.detect(
            history_context=history_context,
            expected_types=expected,
            mention_provider=self._infer_mentions_from_text,
        )

        # History mentions are preferred because they preserve discourse provenance.
        for turn_index, turn in enumerate(history_context):
            distance_from_latest = (len(history_context) - 1) - turn_index
            recency = max(0.0, 1.0 - min(distance_from_latest, 10) / 10.0)
            turn_mentions = turn.mentions or self._infer_mentions_from_text(turn.original_text)
            for mention in turn_mentions:
                type_score = self._type_score(mention.entity_type, expected)
                explicit_score = (
                    1.0 if mention.canonical_name.casefold() in question.casefold() else 0.0
                )
                origin_score = {
                    "explicit": 1.0,
                    "resolved_reference": 0.88,
                    "clinical_candidate": 0.72,
                    "legacy_inferred": 0.62,
                }.get(mention.origin, 0.65)
                score = (
                    0.40 * type_score
                    + 0.28 * recency
                    + 0.17 * mention.confidence
                    + 0.10 * origin_score
                    + 0.05 * explicit_score
                )

                key = (mention.entity_type.casefold(), mention.canonical_name.casefold())
                if focus and key in focus.keys:
                    tier = focus.tier
                    focus_reason = focus.reason
                    # A categorical focus should still be visually obvious in debug output.
                    score = max(score, 0.90 if focus.tier == 1 else 0.82)
                else:
                    tier = self._base_tier(mention.origin)
                    focus_reason = None

                candidates.append(
                    DiscourseEntityCandidate(
                        canonical_name=mention.canonical_name,
                        entity_type=mention.entity_type,
                        source_message_id=turn.message_id,
                        source_role=turn.role,
                        source_text=turn.original_text,
                        score=min(1.0, max(0.0, score)),
                        mention_confidence=mention.confidence,
                        priority_tier=tier,
                        origin=mention.origin,
                        turn_distance=distance_from_latest,
                        focus_reason=focus_reason,
                    )
                )

        # Patient facts are fallback antecedents only after discourse candidates.
        for fact_index, fact in enumerate(patient_context.facts[:20]):
            if fact.negated or (fact.status or "active") in {"stopped", "resolved", "inactive"}:
                continue
            entity_type = (
                fact.attributes.get("related_fact_type", "condition")
                if fact.fact_type.value == "family_history"
                else fact.fact_type.value
            )
            type_score = self._type_score(entity_type, expected)
            recency = max(0.35, 1.0 - min(fact_index, 10) / 12.0)
            score = 0.48 * type_score + 0.22 * recency + 0.20 * fact.confidence
            candidates.append(
                DiscourseEntityCandidate(
                    canonical_name=fact.display,
                    entity_type=entity_type,
                    source_message_id=fact.source_message_id,
                    source_text=fact.source_text,
                    score=min(0.92, max(0.0, score)),
                    mention_confidence=fact.confidence,
                    priority_tier=5,
                    origin="patient_context",
                    turn_distance=None,
                    focus_reason="patient_context_fallback",
                )
            )

        # Keep the best occurrence of each entity. Priority tier dominates raw score.
        dedup: OrderedDict[tuple[str, str], DiscourseEntityCandidate] = OrderedDict()
        ordered = sorted(candidates, key=self._sort_key)
        for item in ordered:
            key = (item.entity_type.casefold(), item.canonical_name.casefold())
            if key not in dedup:
                dedup[key] = item

        return list(dedup.values())[:limit]

    @staticmethod
    def active_topic(candidates: list[DiscourseEntityCandidate]) -> DiscourseEntityCandidate | None:
        if not candidates:
            return None
        best_tier = min(c.priority_tier for c in candidates)
        if best_tier > 2:
            return None
        strongest = [c for c in candidates if c.priority_tier == best_tier]
        return strongest[0] if len(strongest) == 1 else None

    @staticmethod
    def _sort_key(candidate: DiscourseEntityCandidate) -> tuple:
        return (
            candidate.priority_tier,
            -candidate.score,
            candidate.turn_distance if candidate.turn_distance is not None else 9999,
            candidate.canonical_name.casefold(),
        )

    @staticmethod
    def _base_tier(origin: str) -> int:
        return {
            "explicit": 3,
            "resolved_reference": 4,
            "clinical_candidate": 4,
            "legacy_inferred": 5,
        }.get(origin, 5)

    @staticmethod
    def _infer_mentions_from_text(text: str) -> list[HistoryMention]:
        """Bootstrap legacy/externally-added turns that were stored without mentions."""
        mentions: list[HistoryMention] = []
        medication = re.search(
            r"\b(?:uống|dùng|sử dụng|thuốc)\s+(?P<name>[A-Za-zÀ-ỹ][A-Za-zÀ-ỹ0-9_-]{2,40})",
            text,
            re.IGNORECASE,
        )
        if medication and medication.group("name").casefold() not in {"đó", "này", "tiếp"}:
            mentions.append(
                HistoryMention(
                    text=medication.group("name"),
                    entity_type="medication",
                    canonical_name=medication.group("name"),
                    confidence=0.78,
                    origin="legacy_inferred",
                )
            )

        topic = re.search(
            r"^(?P<name>[^?!.]{2,80}?)\s+(?:là\s+(?:thuốc\s+)?gì|có\s+triệu\s+chứng\s+gì|có\s+nguy\s+hiểm\s+không)\??$",
            text.strip(),
            re.IGNORECASE,
        )
        if topic:
            name = re.sub(r"^(?:bệnh|thuốc)\s+", "", topic.group("name").strip(), flags=re.IGNORECASE)
            if name.casefold() not in {"nó", "bệnh đó", "bệnh này", "thuốc đó", "thuốc này"}:
                entity_type = "medication" if re.search(r"\blà\s+thuốc\s+gì\b", text, re.IGNORECASE) else "condition"
                mentions.append(
                    HistoryMention(
                        text=name,
                        entity_type=entity_type,
                        canonical_name=name,
                        confidence=0.82,
                        origin="legacy_inferred",
                    )
                )
        return mentions

    @staticmethod
    def _type_score(entity_type: str, expected: list[str]) -> float:
        if not expected:
            return 0.62
        lower = entity_type.casefold()
        if lower == expected[0]:
            return 1.0
        if lower in expected[1:]:
            return 0.78
        if lower == "family_history" and "condition" in expected:
            return 0.62
        return 0.08

    @staticmethod
    def choose_unique(
        candidates: list[DiscourseEntityCandidate],
        *,
        min_score: float = 0.55,
        ambiguity_margin: float = 0.11,
    ) -> DiscourseEntityCandidate | None:
        if not candidates:
            return None
        ordered = sorted(candidates, key=AntecedentCandidateRanker._sort_key)
        first = ordered[0]
        if first.score < min_score:
            return None
        if len(ordered) == 1:
            return first

        # Only candidates in the same strongest tier can make the decision ambiguous.
        same_tier_same_type = [
            c for c in ordered
            if c.priority_tier == first.priority_tier
            and c.entity_type.casefold() == first.entity_type.casefold()
        ]
        if len(same_tier_same_type) >= 2:
            second = same_tier_same_type[1]
            if first.score - second.score < ambiguity_margin:
                return None
        return first


class ContextResolutionValidator:
    """Validate a proposed resolution against discourse focus and candidate priority."""

    def validate(self, result: ResolvedQuestion) -> ResolvedQuestion:
        need = ContextNeedDetector.detect(result.original_question)
        # Hard guarantee for v2.3: a self-contained question is immutable. Even if
        # an LLM proposes a stylistic rewrite, it is discarded.
        if need.status == "not_needed":
            return result.model_copy(
                update={
                    "normalized_question": result.original_question,
                    "resolved_references": [],
                    "used_history_turn_ids": [],
                    "confidence": 1.0,
                    "resolution_status": "not_needed",
                    "resolution_method": "context_not_needed",
                }
            )

        candidate_by_name = {
            (c.entity_type.casefold(), c.canonical_name.casefold()): c
            for c in result.candidate_entities
        }
        valid_refs: list[ResolvedReference] = []
        used: list[str] = []
        invalidated = False

        for ref in result.resolved_references:
            copy = ref.model_copy(deep=True)
            if copy.resolved and copy.resolved_to and copy.entity_type:
                candidate = candidate_by_name.get(
                    (copy.entity_type.casefold(), copy.resolved_to.casefold())
                )
                invalid = (
                    candidate is None
                    or self._candidate_is_lower_priority(candidate, result.candidate_entities)
                    or self._candidate_is_ambiguous(candidate, result.candidate_entities)
                )
                if invalid:
                    invalidated = True
                    copy.resolved = False
                    copy.confidence = min(copy.confidence, 0.35)
                    copy.source_message_id = None
                    if candidate is None:
                        copy.resolved_to = None
                        copy.entity_type = None
                else:
                    copy.resolved_to = candidate.canonical_name
                    copy.entity_type = candidate.entity_type
                    copy.source_message_id = candidate.source_message_id
                    copy.confidence = min(copy.confidence, max(0.55, candidate.score))
                    if candidate.source_message_id and candidate.source_message_id not in used:
                        used.append(candidate.source_message_id)
            valid_refs.append(copy)

        original_has_ref = ReferenceIntentDetector.has_reference(result.original_question)
        any_resolved = any(r.resolved and r.resolved_to for r in valid_refs)

        # Build the final normalized question from the ORIGINAL question and only
        # validated references. Explicit references are replaced literally. For
        # subject ellipsis, use a deterministic template so an LLM cannot paraphrase
        # unrelated parts of an otherwise clear question.
        normalized = result.original_question
        if original_has_ref:
            normalized = self._rewrite_from_validated_refs(result.original_question, valid_refs)
        elif any_resolved:
            implicit = next((r for r in valid_refs if r.resolved and r.resolved_to and r.entity_type), None)
            if implicit is not None:
                rewritten = ContextNeedDetector.rewrite_implicit_subject(
                    result.original_question,
                    target_name=implicit.resolved_to or "",
                    entity_type=implicit.entity_type or "",
                )
                if rewritten is not None:
                    normalized = rewritten

        remaining_need = ContextNeedDetector.detect(normalized).status != "not_needed"
        confidence = result.confidence
        if remaining_need or not any_resolved or invalidated:
            status = "unresolved"
            confidence = min(confidence, 0.45)
            # Never leak a rejected or free-form rewrite.
            if invalidated or not any_resolved or remaining_need:
                normalized = result.original_question
        else:
            status = "resolved"

        if not used and status != "unresolved":
            for message_id in result.used_history_turn_ids:
                if any(c.source_message_id == message_id for c in result.candidate_entities):
                    used.append(message_id)

        return result.model_copy(
            update={
                "normalized_question": normalized,
                "resolved_references": valid_refs,
                "used_history_turn_ids": used,
                "confidence": max(0.0, min(1.0, confidence)),
                "resolution_status": status,
            }
        )

    @staticmethod
    def _rewrite_from_validated_refs(
        original_question: str,
        refs: list[ResolvedReference],
    ) -> str:
        rewritten = original_question
        # Replace longer surface forms first (e.g. "loại thuốc đó" before "thuốc đó").
        direct_refs = [
            r for r in refs
            if r.resolved and r.resolved_to and r.reference and not r.reference.startswith("[")
        ]
        for ref in sorted(direct_refs, key=lambda r: len(r.reference), reverse=True):
            rewritten = re.sub(
                re.escape(ref.reference),
                ref.resolved_to or ref.reference,
                rewritten,
                flags=re.IGNORECASE,
            )
        return rewritten

    @staticmethod
    def _candidate_is_lower_priority(
        selected: DiscourseEntityCandidate,
        candidates: list[DiscourseEntityCandidate],
    ) -> bool:
        same_type = [
            c for c in candidates
            if c.entity_type.casefold() == selected.entity_type.casefold()
        ]
        if not same_type:
            return True
        best_tier = min(c.priority_tier for c in same_type)
        return selected.priority_tier > best_tier

    @staticmethod
    def _candidate_is_ambiguous(
        selected: DiscourseEntityCandidate,
        candidates: list[DiscourseEntityCandidate],
        margin: float = 0.11,
    ) -> bool:
        same_type = [
            c for c in candidates
            if c.entity_type.casefold() == selected.entity_type.casefold()
        ]
        if len(same_type) < 2:
            return False
        best_tier = min(c.priority_tier for c in same_type)
        strongest = sorted(
            [c for c in same_type if c.priority_tier == best_tier],
            key=lambda c: c.score,
            reverse=True,
        )
        if len(strongest) < 2:
            return False
        first, second = strongest[0], strongest[1]
        return (
            selected.priority_tier == best_tier
            and selected.canonical_name.casefold() in {
                first.canonical_name.casefold(),
                second.canonical_name.casefold(),
            }
            and first.score - second.score < margin
        )
