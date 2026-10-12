from datetime import datetime, timezone

import pytest

from app.modules.context.application.resolver import RuleBasedQuestionResolver
from app.modules.context.domain.models import HistoryMention, HistoryTurn, PatientContext, Role


@pytest.mark.asyncio
async def test_resolves_thuoc_do_from_history_entity():
    resolver = RuleBasedQuestionResolver()
    history = [
        HistoryTurn(
            patient_id="p1",
            session_id="s1",
            message_id="m1",
            role=Role.USER,
            original_text="Tôi đang uống losartan 50mg.",
            normalized_text="Tôi đang uống losartan 50mg.",
            created_at=datetime(2026, 9, 26, tzinfo=timezone.utc),
            mentions=[
                HistoryMention(
                    text="losartan 50mg",
                    entity_type="medication",
                    canonical_name="losartan",
                )
            ],
        )
    ]

    result = await resolver.resolve(
        question="Thuốc đó có gây chóng mặt không?",
        history_context=history,
        patient_context=PatientContext(patient_id="p1"),
    )

    assert "losartan" in result.normalized_question.casefold()
    assert result.used_history_turn_ids == ["m1"]
