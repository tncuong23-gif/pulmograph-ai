from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CONTEXT_", env_file=None, env_file_encoding="utf-8", extra="ignore")

    app_name: str = "medical-context-graph"
    app_env: str = "local"
    graph_backend: Literal["memory", "neo4j"] = "memory"

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "change-me-please"
    neo4j_database: str = "neo4j"

    history_limit: int = 20
    recent_history_limit: int = 6
    min_resolution_confidence: float = 0.55

    # NLP/LLM. Ollama + Qwen2.5:7b is the default local backend.
    nlp_backend: Literal["auto", "rule", "openai", "ollama"] = "ollama"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.6-terra"
    llm_fallback_to_rules: bool = True

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    ollama_timeout_seconds: float = 120.0
    ollama_temperature: float = 0.0

    # Embeddings. Hash embeddings keep local/test environments completely offline.
    embedding_backend: Literal["auto", "hash", "openai"] = "auto"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_embedding_dimensions: int = 1536
    hash_embedding_dimensions: int = 256

    # Terminology normalization. remote must be explicitly enabled because it may send
    # clinical strings to external terminology services.
    terminology_mode: Literal["off", "remote"] = "off"
    terminology_min_confidence: float = 0.75
    rxnorm_base_url: str = "https://rxnav.nlm.nih.gov"
    snomed_fhir_base_url: str | None = None
    snomed_value_set_url: str = "http://snomed.info/sct?fhir_vs"
    loinc_username: str | None = None
    loinc_password: str | None = None
    loinc_search_url: str = "https://loinc.regenstrief.org/searchapi/loincs"
    terminology_timeout_seconds: float = 5.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
