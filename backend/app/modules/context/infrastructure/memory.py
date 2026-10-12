from __future__ import annotations

from collections import defaultdict

from app.modules.context.application.text import token_set
from app.modules.context.domain.models import ClinicalFact, HistoryTurn, PatientContext
from app.modules.context.infrastructure.embedding import EmbeddingService, HashEmbeddingService, cosine_similarity


class InMemoryHistoryRepository:
    def __init__(self, embedding_service: EmbeddingService | None = None) -> None:
        self._turns: dict[tuple[str, str], list[HistoryTurn]] = defaultdict(list)
        self._vectors: dict[str, list[float]] = {}
        self.embedding_service = embedding_service or HashEmbeddingService()

    async def initialize(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def add_turn(self, turn: HistoryTurn) -> None:
        key = (turn.patient_id, turn.session_id)
        turns = self._turns[key]
        turns[:] = [t for t in turns if t.message_id != turn.message_id]
        turns.append(turn)
        turns.sort(key=lambda t: t.created_at)
        text = turn.normalized_text or turn.original_text
        self._vectors[turn.message_id] = await self.embedding_service.embed(text)

    async def get_relevant_turns(
        self,
        *,
        patient_id: str,
        session_id: str,
        query: str,
        limit: int,
    ) -> list[HistoryTurn]:
        turns = list(self._turns.get((patient_id, session_id), []))
        if not turns:
            return []

        q_tokens = token_set(query)
        q_vector = await self.embedding_service.embed(query)
        scored: list[tuple[float, int, HistoryTurn]] = []
        total = len(turns)
        for index, turn in enumerate(turns):
            text = turn.normalized_text or turn.original_text
            t_tokens = token_set(text)
            lexical = len(q_tokens & t_tokens) / max(1, len(q_tokens | t_tokens))
            vector = max(0.0, cosine_similarity(q_vector, self._vectors.get(turn.message_id)))

            entity_continuity = 0.0
            for mention in turn.mentions:
                mention_tokens = token_set(mention.canonical_name)
                if mention.canonical_name.casefold() in query.casefold():
                    entity_continuity = max(entity_continuity, 1.0)
                elif q_tokens & mention_tokens:
                    entity_continuity = max(entity_continuity, 0.65)

            recency = (index + 1) / total
            score = (
                0.45 * vector
                + 0.20 * lexical
                + 0.20 * entity_continuity
                + 0.15 * recency
            )
            scored.append((score, index, turn))

        selected = sorted(scored, key=lambda item: item[0], reverse=True)[:limit]
        return [item[2] for item in sorted(selected, key=lambda item: item[1])]

    async def get_recent_turns(
        self,
        *,
        patient_id: str,
        session_id: str,
        limit: int,
    ) -> list[HistoryTurn]:
        turns = list(self._turns.get((patient_id, session_id), []))
        if limit <= 0:
            return []
        return turns[-limit:]


class InMemoryPatientRepository:
    def __init__(self, embedding_service: EmbeddingService | None = None) -> None:
        self._facts: dict[str, list[ClinicalFact]] = defaultdict(list)
        self._vectors: dict[tuple[str, tuple], list[float]] = {}
        self.embedding_service = embedding_service or HashEmbeddingService()

    async def initialize(self) -> None:
        return None

    async def close(self) -> None:
        return None

    @staticmethod
    def _identity(fact: ClinicalFact) -> tuple:
        return (
            fact.source_message_id,
            fact.fact_type.value,
            fact.display.casefold(),
            fact.experiencer,
            fact.negated,
            fact.status,
            fact.dose,
            fact.frequency,
        )

    @staticmethod
    def _embedding_text(fact: ClinicalFact) -> str:
        chunks = [fact.fact_type.value, fact.display]
        if fact.status:
            chunks.append(f"status {fact.status}")
        if fact.dose:
            chunks.append(f"dose {fact.dose}")
        if fact.frequency:
            chunks.append(f"frequency {fact.frequency}")
        if fact.unit:
            chunks.append(f"unit {fact.unit}")
        if fact.experiencer != "patient":
            chunks.append(f"experiencer {fact.experiencer}")
        if fact.negated:
            chunks.append("negated")
        return " | ".join(chunks)

    async def upsert_facts(self, *, patient_id: str, facts: list[ClinicalFact]) -> int:
        stored = self._facts[patient_id]
        count = 0
        for fact in facts:
            identity = self._identity(fact)
            exists = any(self._identity(old) == identity for old in stored)
            if not exists:
                copy = fact.model_copy(deep=True)
                stored.append(copy)
                self._vectors[(patient_id, identity)] = await self.embedding_service.embed(
                    self._embedding_text(copy)
                )
                count += 1
        stored.sort(key=lambda f: f.recorded_at)
        return count

    async def get_relevant_context(
        self,
        *,
        patient_id: str,
        query: str,
        limit: int = 50,
    ) -> PatientContext:
        facts = list(self._facts.get(patient_id, []))
        if not facts:
            return PatientContext(patient_id=patient_id)

        q = query.casefold()
        q_tokens = token_set(query)
        q_vector = await self.embedding_service.embed(query)
        scored: list[tuple[float, ClinicalFact]] = []
        for idx, fact in enumerate(facts):
            fact_tokens = token_set(fact.display)
            lexical = len(q_tokens & fact_tokens) / max(1, len(q_tokens | fact_tokens))
            vector = max(
                0.0,
                cosine_similarity(
                    q_vector,
                    self._vectors.get((patient_id, self._identity(fact))),
                ),
            )
            clinical_type = 0.0
            if any(word in q for word in ("thuốc", "uống", "dùng", "ngưng", "tương tác")):
                clinical_type += 1.0 if fact.fact_type.value in {"medication", "allergy"} else 0.0
            if any(word in q for word in ("bệnh", "chẩn đoán", "tình trạng", "triệu chứng")):
                clinical_type += 1.0 if fact.fact_type.value in {"condition", "symptom"} else 0.0
            if any(word in q for word in ("xét nghiệm", "lab", "chỉ số")):
                clinical_type += 1.0 if fact.fact_type.value in {"lab_result", "observation"} else 0.0
            clinical_type = min(1.0, clinical_type)
            recency = (idx + 1) / len(facts)
            score = 0.50 * vector + 0.20 * lexical + 0.20 * clinical_type + 0.10 * recency
            scored.append((score, fact))

        selected = [fact for _, fact in sorted(scored, key=lambda x: x[0], reverse=True)[:limit]]
        return PatientContext(patient_id=patient_id, facts=selected)
