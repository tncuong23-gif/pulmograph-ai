from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from app.modules.context.domain.models import ClinicalFact, FactType


@dataclass(slots=True)
class TerminologyMatch:
    concept_id: str
    concept_system: str
    display: str | None = None
    confidence: float = 0.8
    source: str | None = None


class TerminologyBackend(Protocol):
    async def match(self, text: str) -> TerminologyMatch | None: ...


class NoOpTerminologyNormalizer:
    async def normalize_facts(self, facts: list[ClinicalFact]) -> list[ClinicalFact]:
        return [fact.model_copy(deep=True) for fact in facts]


class RxNormNormalizer:
    """Best-effort medication normalization through NLM RxNav/RxNorm."""

    def __init__(self, base_url: str = "https://rxnav.nlm.nih.gov", timeout: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def match(self, text: str) -> TerminologyMatch | None:
        url = f"{self.base_url}/REST/approximateTerm.json"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                url,
                params={"term": text, "maxEntries": 5, "option": 1},
            )
            response.raise_for_status()
            payload = response.json()

        candidates = payload.get("approximateGroup", {}).get("candidate") or []
        if isinstance(candidates, dict):
            candidates = [candidates]
        if not candidates:
            return None

        # Prefer active RxNorm vocabulary candidates and the best lexical rank.
        candidates = sorted(
            candidates,
            key=lambda c: (
                0 if str(c.get("source", "")).upper() == "RXNORM" else 1,
                int(c.get("rank") or 999),
                -float(c.get("score") or 0.0),
            ),
        )
        best = candidates[0]
        rxcui = best.get("rxcui")
        if not rxcui:
            return None
        rank = int(best.get("rank") or 99)
        confidence = 0.92 if rank == 1 else 0.78
        return TerminologyMatch(
            concept_id=str(rxcui),
            concept_system="RxNorm",
            display=best.get("name") or text,
            confidence=confidence,
            source="NLM RxNorm API",
        )


class FhirSnomedNormalizer:
    """SNOMED CT text normalization using a FHIR terminology server (e.g. Snowstorm)."""

    def __init__(
        self,
        base_url: str,
        *,
        value_set_url: str = "http://snomed.info/sct?fhir_vs",
        timeout: float = 5.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.value_set_url = value_set_url
        self.timeout = timeout

    async def match(self, text: str) -> TerminologyMatch | None:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}/ValueSet/$expand",
                params={
                    "url": self.value_set_url,
                    "filter": text,
                    "count": 5,
                    "includeDesignations": "true",
                },
                headers={"Accept": "application/fhir+json, application/json"},
            )
            response.raise_for_status()
            payload = response.json()

        contains = payload.get("expansion", {}).get("contains") or []
        if not contains:
            return None
        best = contains[0]
        code = best.get("code")
        if not code:
            return None
        return TerminologyMatch(
            concept_id=str(code),
            concept_system="SNOMED CT",
            display=best.get("display") or text,
            confidence=0.84,
            source="FHIR terminology server",
        )


class LoincSearchNormalizer:
    """LOINC normalization using the official authenticated Search API."""

    def __init__(
        self,
        *,
        username: str,
        password: str,
        base_url: str = "https://loinc.regenstrief.org/searchapi/loincs",
        timeout: float = 5.0,
    ) -> None:
        self.username = username
        self.password = password
        self.base_url = base_url
        self.timeout = timeout

    async def match(self, text: str) -> TerminologyMatch | None:
        async with httpx.AsyncClient(
            timeout=self.timeout,
            auth=httpx.BasicAuth(self.username, self.password),
        ) as client:
            response = await client.get(self.base_url, params={"query": text, "rows": 5})
            response.raise_for_status()
            payload = response.json()

        # Search API response shape has changed across versions. Accept common wrappers.
        rows = payload
        if isinstance(payload, dict):
            for key in ("results", "items", "loincs", "docs", "content"):
                if isinstance(payload.get(key), list):
                    rows = payload[key]
                    break
            else:
                response_obj = payload.get("response")
                if isinstance(response_obj, dict) and isinstance(response_obj.get("docs"), list):
                    rows = response_obj["docs"]
        if not isinstance(rows, list) or not rows:
            return None

        best = rows[0]
        if not isinstance(best, dict):
            return None
        code = (
            best.get("loinc_num")
            or best.get("LOINC_NUM")
            or best.get("loincNum")
            or best.get("code")
        )
        if not code:
            return None
        display = (
            best.get("long_common_name")
            or best.get("LONG_COMMON_NAME")
            or best.get("longCommonName")
            or best.get("display")
            or text
        )
        return TerminologyMatch(
            concept_id=str(code),
            concept_system="LOINC",
            display=str(display),
            confidence=0.82,
            source="LOINC Search API",
        )


class CompositeTerminologyNormalizer:
    def __init__(
        self,
        *,
        rxnorm: TerminologyBackend | None = None,
        snomed: TerminologyBackend | None = None,
        loinc: TerminologyBackend | None = None,
        min_confidence: float = 0.75,
    ) -> None:
        self.rxnorm = rxnorm
        self.snomed = snomed
        self.loinc = loinc
        self.min_confidence = min_confidence

    async def normalize_facts(self, facts: list[ClinicalFact]) -> list[ClinicalFact]:
        normalized: list[ClinicalFact] = []
        for original in facts:
            fact = original.model_copy(deep=True)
            backend = self._backend_for(fact)
            if backend is None or fact.concept_id:
                normalized.append(fact)
                continue

            try:
                match = await backend.match(fact.display)
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                match = None

            if match and match.confidence >= self.min_confidence:
                fact.attributes.setdefault("original_display", fact.display)
                fact.attributes["terminology_match"] = {
                    "concept_id": match.concept_id,
                    "concept_system": match.concept_system,
                    "display": match.display,
                    "confidence": match.confidence,
                    "source": match.source,
                }
                fact.concept_id = match.concept_id
                fact.concept_system = match.concept_system
                # Keep the user-facing assertion text in fact.display. The canonical terminology
                # label lives in attributes["terminology_match"]["display"] so context restoration
                # does not unexpectedly switch language or wording.
            normalized.append(fact)
        return normalized

    def _backend_for(self, fact: ClinicalFact) -> TerminologyBackend | None:
        if fact.fact_type == FactType.MEDICATION:
            return self.rxnorm
        if fact.fact_type in {
            FactType.CONDITION,
            FactType.SYMPTOM,
            FactType.ALLERGY,
            FactType.PROCEDURE,
            FactType.FAMILY_HISTORY,
        }:
            return self.snomed
        if fact.fact_type in {FactType.LAB_RESULT, FactType.OBSERVATION}:
            return self.loinc
        return None
