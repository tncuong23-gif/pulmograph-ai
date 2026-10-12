from datetime import datetime, timezone

import pytest

from app.modules.context.domain.models import ClinicalFact, FactType
from app.modules.context.infrastructure.terminology.normalizer import (
    CompositeTerminologyNormalizer,
    TerminologyMatch,
)


class FakeBackend:
    async def match(self, text: str):
        return TerminologyMatch(
            concept_id="TEST-123",
            concept_system="TEST-SYSTEM",
            display="Canonical medication",
            confidence=0.95,
            source="test",
        )


@pytest.mark.asyncio
async def test_terminology_normalizer_adds_code_and_preserves_original_display():
    normalizer = CompositeTerminologyNormalizer(rxnorm=FakeBackend())
    fact = ClinicalFact(
        fact_type=FactType.MEDICATION,
        display="thuoc demo",
        recorded_at=datetime(2026, 9, 26, tzinfo=timezone.utc),
        source_message_id="m1",
    )

    result = await normalizer.normalize_facts([fact])

    assert result[0].concept_id == "TEST-123"
    assert result[0].concept_system == "TEST-SYSTEM"
    assert result[0].display == "thuoc demo"
    assert result[0].attributes["terminology_match"]["display"] == "Canonical medication"
    assert result[0].attributes["original_display"] == "thuoc demo"
    assert result[0].attributes["terminology_match"]["confidence"] == 0.95
