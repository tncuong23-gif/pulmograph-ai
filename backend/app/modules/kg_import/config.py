"""Configuration. Values come from environment variables; nothing is hard-coded or logged."""
from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass, field

MEDICAL_MODEL = "Dqdung205/medical_vietnamese_embedding"
MEDICAL_REVISION = "b6b9d6ff9b2f2c7e910c352df19f0e6c9c0834de"
MEDICAL_COLLECTION = "kg_entity_names_medical_vi_v1"
BACKEND_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Limits:
    max_body_bytes: int = 20 * 1024 * 1024
    max_entities: int = 100_000
    max_relations: int = 200_000
    max_propositions: int = 200_000
    max_sentences: int = 500_000
    supported_schema_versions: tuple[str, ...] = ("1.0",)
    require_provenance: bool = True  # every relation must trace to proposition -> evidence
    neo4j_batch_size: int = 1000
    mongo_batch_size: int = 1000


@dataclass(frozen=True)
class EntityEmbeddingSettings:
    enabled: bool = False
    qdrant_url: str = "http://localhost:6333"
    collection: str = MEDICAL_COLLECTION
    model: str = MEDICAL_MODEL
    candidate_score: float = 0.70  # candidate floor, never automatic merge
    revision: str | None = MEDICAL_REVISION
    trust_remote_code: bool = True
    device: str = "auto"
    batch_size: int = 16
    query_batch_size: int = 64
    max_seq_length: int = 256
    cache_size: int = 4096
    cache_dir: str = str(BACKEND_ROOT / "models" / "hf-cache")

    def __post_init__(self):
        if not -1 <= self.candidate_score <= 1: raise ValueError("invalid KG_ENTITY_CANDIDATE_SCORE")
        for key in ("batch_size", "query_batch_size", "max_seq_length"):
            if not 1 <= getattr(self, key) <= 8192: raise ValueError(f"invalid KG entity {key}")
        if not 0 <= self.cache_size <= 100_000: raise ValueError("invalid KG_ENTITY_CACHE_SIZE")


@dataclass(frozen=True)
class Settings:
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: str = field(default="", repr=False)
    neo4j_database: str = "neo4j"
    mongodb_uri: str = field(default="mongodb://localhost:27017", repr=False)
    mongodb_database: str = "medical_kg"
    ontology_path: str = str(Path(__file__).resolve().parents[3] / "examples/kg/kg_ontology.example.json")
    limits: Limits = field(default_factory=Limits)
    entity_embedding: EntityEmbeddingSettings = field(default_factory=EntityEmbeddingSettings)

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ
        model = env.get("KG_ENTITY_MODEL", MEDICAL_MODEL)
        cache = Path(env.get("KG_ENTITY_CACHE_DIR", str(BACKEND_ROOT / "models" / "hf-cache")))
        if not cache.is_absolute(): cache = BACKEND_ROOT / cache
        return cls(
            neo4j_uri=env.get("KG_NEO4J_URI", cls.neo4j_uri),
            neo4j_username=env.get("KG_NEO4J_USERNAME", cls.neo4j_username),
            neo4j_password=env.get("KG_NEO4J_PASSWORD", ""),
            neo4j_database=env.get("KG_NEO4J_DATABASE", cls.neo4j_database),
            mongodb_uri=env.get("KG_MONGODB_URI", cls.mongodb_uri),
            mongodb_database=env.get("KG_MONGODB_DATABASE", cls.mongodb_database),
            ontology_path=env.get("KG_ONTOLOGY_PATH", cls.ontology_path),
            entity_embedding=EntityEmbeddingSettings(
                enabled=env.get("KG_ENTITY_EMBEDDING_ENABLED", "0").lower() in ("1", "true", "yes"),
                qdrant_url=env.get("KG_QDRANT_URL", "http://localhost:6333"),
                collection=env.get("KG_ENTITY_COLLECTION", MEDICAL_COLLECTION),
                model=model,
                candidate_score=float(env.get("KG_ENTITY_CANDIDATE_SCORE", "0.70")),
                revision=env.get("KG_ENTITY_MODEL_REVISION", MEDICAL_REVISION if model == MEDICAL_MODEL else "") or None,
                trust_remote_code=env.get("KG_ENTITY_TRUST_REMOTE_CODE", "1" if model == MEDICAL_MODEL else "0").lower() in ("1", "true", "yes"),
                device=env.get("KG_ENTITY_DEVICE", "auto"),
                batch_size=int(env.get("KG_ENTITY_BATCH_SIZE", "16")),
                query_batch_size=int(env.get("KG_ENTITY_QUERY_BATCH_SIZE", "64")),
                max_seq_length=int(env.get("KG_ENTITY_MAX_SEQ_LENGTH", "256")),
                cache_size=int(env.get("KG_ENTITY_CACHE_SIZE", "4096")), cache_dir=str(cache),
            ),
        )
