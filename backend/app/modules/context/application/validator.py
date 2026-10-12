from __future__ import annotations

from app.modules.context.domain.models import AssertionType, ClinicalFact, FactType, StatementType


class ClinicalAssertionValidator:
    def __init__(self, min_confidence: float = 0.55) -> None:
        self.min_confidence = min_confidence

    def validate(self, facts: list[ClinicalFact]) -> list[ClinicalFact]:
        valid: list[ClinicalFact] = []
        for fact in facts:
            # Questions, plans and hypotheticals must never become active patient facts.
            if fact.statement_type != StatementType.FACT:
                continue
            if fact.confidence < self.min_confidence:
                continue
            # Inferred facts are reserved for another reasoning layer.
            if fact.assertion == AssertionType.INFERRED:
                continue
            # A relative's disease belongs only under family history.
            if fact.experiencer != "patient" and fact.fact_type != FactType.FAMILY_HISTORY:
                continue
            valid.append(fact)
        return valid
