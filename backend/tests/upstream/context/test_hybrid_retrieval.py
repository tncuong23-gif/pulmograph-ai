from datetime import datetime, timedelta, timezone

import pytest

from app.modules.context.domain.models import HistoryMention, HistoryTurn, Role
from app.modules.context.infrastructure.embedding import HashEmbeddingService
from app.modules.context.infrastructure.memory import InMemoryHistoryRepository


@pytest.mark.asyncio
async def test_hybrid_history_can_retrieve_older_entity_relevant_turn():
    repo = InMemoryHistoryRepository(HashEmbeddingService(128))
    base = datetime(2026, 9, 26, tzinfo=timezone.utc)

    await repo.add_turn(
        HistoryTurn(
            patient_id="p1",
            session_id="s1",
            message_id="m-old",
            role=Role.USER,
            original_text="Tôi đang uống losartan 50mg mỗi ngày.",
            normalized_text="Tôi đang uống losartan 50mg mỗi ngày.",
            created_at=base,
            mentions=[
                HistoryMention(
                    text="losartan 50mg",
                    entity_type="medication",
                    canonical_name="losartan",
                )
            ],
        )
    )

    for i, text in enumerate(
        [
            "Hôm nay trời nóng.",
            "Tôi vừa ăn sáng.",
            "Tôi muốn hỏi thêm một việc.",
            "Cảm ơn bạn.",
        ],
        start=1,
    ):
        await repo.add_turn(
            HistoryTurn(
                patient_id="p1",
                session_id="s1",
                message_id=f"m{i}",
                role=Role.USER,
                original_text=text,
                normalized_text=text,
                created_at=base + timedelta(minutes=i),
            )
        )

    result = await repo.get_relevant_turns(
        patient_id="p1",
        session_id="s1",
        query="losartan có cần ngưng không?",
        limit=2,
    )

    assert any(turn.message_id == "m-old" for turn in result)
