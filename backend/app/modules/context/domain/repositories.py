from __future__ import annotations

from typing import Protocol

from app.modules.context.domain.models import ClinicalFact, HistoryTurn, PatientContext


class HistoryRepository(Protocol):
    async def initialize(self) -> None: ...

    async def close(self) -> None: ...

    async def add_turn(self, turn: HistoryTurn) -> None: ...

    async def get_relevant_turns(
        self,
        *,
        patient_id: str,
        session_id: str,
        query: str,
        limit: int,
    ) -> list[HistoryTurn]: ...

    async def get_recent_turns(
        self,
        *,
        patient_id: str,
        session_id: str,
        limit: int,
    ) -> list[HistoryTurn]: ...


class PatientRepository(Protocol):
    async def initialize(self) -> None: ...

    async def close(self) -> None: ...

    async def upsert_facts(self, *, patient_id: str, facts: list[ClinicalFact]) -> int: ...

    async def get_relevant_context(
        self,
        *,
        patient_id: str,
        query: str,
        limit: int = 50,
    ) -> PatientContext: ...
