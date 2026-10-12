from __future__ import annotations

from dataclasses import dataclass

from app.modules.context.application.extractor import RuleBasedClinicalExtractor
from app.modules.context.application.resolver import RuleBasedQuestionResolver
from app.modules.context.application.service import MedicalContextService
from app.modules.context.application.validator import ClinicalAssertionValidator
from app.modules.context.config import Settings
from app.modules.context.domain.repositories import HistoryRepository, PatientRepository
from app.modules.context.infrastructure.embedding import HashEmbeddingService, OpenAIEmbeddingService
from app.modules.context.infrastructure.memory import InMemoryHistoryRepository, InMemoryPatientRepository
from app.modules.context.infrastructure.terminology import (
    CompositeTerminologyNormalizer,
    FhirSnomedNormalizer,
    LoincSearchNormalizer,
    NoOpTerminologyNormalizer,
    RxNormNormalizer,
)


@dataclass
class ApplicationContainer:
    settings: Settings
    history_repository: HistoryRepository
    patient_repository: PatientRepository
    service: MedicalContextService
    driver: object | None = None

    @classmethod
    def build(cls, settings: Settings) -> "ApplicationContainer":
        embedding_service = cls._build_embedding_service(settings)
        driver = None
        if settings.graph_backend == "neo4j":
            from neo4j import AsyncGraphDatabase
            from app.modules.context.infrastructure.neo4j.history_repository import Neo4jHistoryRepository
            from app.modules.context.infrastructure.neo4j.patient_repository import Neo4jPatientRepository

            driver = AsyncGraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password),
            )
            history_repository = Neo4jHistoryRepository(
                driver,
                settings.neo4j_database,
                embedding_service=embedding_service,
            )
            patient_repository = Neo4jPatientRepository(
                driver,
                settings.neo4j_database,
                embedding_service=embedding_service,
            )
        else:
            history_repository = InMemoryHistoryRepository(embedding_service)
            patient_repository = InMemoryPatientRepository(embedding_service)

        question_resolver, clinical_extractor = cls._build_nlp(settings)
        terminology_normalizer = cls._build_terminology(settings)

        service = MedicalContextService(
            history_repository=history_repository,
            patient_repository=patient_repository,
            question_resolver=question_resolver,
            clinical_extractor=clinical_extractor,
            clinical_validator=ClinicalAssertionValidator(settings.min_resolution_confidence),
            terminology_normalizer=terminology_normalizer,
            history_limit=settings.history_limit,
            recent_history_limit=settings.recent_history_limit,
        )
        return cls(
            settings=settings,
            history_repository=history_repository,
            patient_repository=patient_repository,
            service=service,
            driver=driver,
        )

    @staticmethod
    def _build_embedding_service(settings: Settings):
        use_openai = settings.embedding_backend == "openai" or (
            settings.embedding_backend == "auto" and bool(settings.openai_api_key)
        )
        if use_openai:
            if not settings.openai_api_key:
                raise ValueError("OPENAI_API_KEY is required when EMBEDDING_BACKEND=openai")
            return OpenAIEmbeddingService(
                api_key=settings.openai_api_key,
                model=settings.openai_embedding_model,
                dimensions=settings.openai_embedding_dimensions,
            )
        return HashEmbeddingService(settings.hash_embedding_dimensions)

    @staticmethod
    def _build_nlp(settings: Settings):
        backend = settings.nlp_backend
        if backend == "auto":
            backend = "openai" if settings.openai_api_key else "ollama"

        if backend == "rule":
            return RuleBasedQuestionResolver(), RuleBasedClinicalExtractor()

        if backend == "ollama":
            from app.modules.context.infrastructure.llm.ollama_structured import (
                OllamaStructuredClinicalExtractor,
                OllamaStructuredQuestionResolver,
            )

            common = dict(
                base_url=settings.ollama_base_url,
                model=settings.ollama_model,
                timeout_seconds=settings.ollama_timeout_seconds,
                temperature=settings.ollama_temperature,
                fallback_to_rules=settings.llm_fallback_to_rules,
            )
            return (
                OllamaStructuredQuestionResolver(**common),
                OllamaStructuredClinicalExtractor(**common),
            )

        if backend == "openai":
            if not settings.openai_api_key:
                raise ValueError("OPENAI_API_KEY is required when NLP_BACKEND=openai")

            from app.modules.context.infrastructure.llm.openai_structured import (
                OpenAIStructuredClinicalExtractor,
                OpenAIStructuredQuestionResolver,
            )

            return (
                OpenAIStructuredQuestionResolver(
                    api_key=settings.openai_api_key,
                    model=settings.openai_model,
                    fallback_to_rules=settings.llm_fallback_to_rules,
                ),
                OpenAIStructuredClinicalExtractor(
                    api_key=settings.openai_api_key,
                    model=settings.openai_model,
                    fallback_to_rules=settings.llm_fallback_to_rules,
                ),
            )

        raise ValueError(f"Unsupported NLP_BACKEND={backend}")

    @staticmethod
    def _build_terminology(settings: Settings):
        if settings.terminology_mode == "off":
            return NoOpTerminologyNormalizer()

        rxnorm = RxNormNormalizer(
            base_url=settings.rxnorm_base_url,
            timeout=settings.terminology_timeout_seconds,
        )
        snomed = None
        if settings.snomed_fhir_base_url:
            snomed = FhirSnomedNormalizer(
                settings.snomed_fhir_base_url,
                value_set_url=settings.snomed_value_set_url,
                timeout=settings.terminology_timeout_seconds,
            )
        loinc = None
        if settings.loinc_username and settings.loinc_password:
            loinc = LoincSearchNormalizer(
                username=settings.loinc_username,
                password=settings.loinc_password,
                base_url=settings.loinc_search_url,
                timeout=settings.terminology_timeout_seconds,
            )
        return CompositeTerminologyNormalizer(
            rxnorm=rxnorm,
            snomed=snomed,
            loinc=loinc,
            min_confidence=settings.terminology_min_confidence,
        )

    async def initialize(self) -> None:
        await self.history_repository.initialize()
        await self.patient_repository.initialize()

    async def close(self) -> None:
        await self.history_repository.close()
        await self.patient_repository.close()
        if self.driver is not None:
            await self.driver.close()
