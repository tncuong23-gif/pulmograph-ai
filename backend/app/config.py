from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _json_env(name: str, default: dict) -> dict:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} must contain valid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{name} must be a JSON object")
    return value


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    context_base_url: str
    clinical_ie_base_url: str
    kg_base_url: str
    rag_base_url: str
    ollama_base_url: str
    ollama_model: str
    classifier_path: Path
    embedding_model: str
    embedding_prefix: str
    normalize_embeddings: bool
    id2label: dict[str, str]
    database_path: Path
    upload_dir: Path
    max_upload_bytes: int
    request_timeout_seconds: float
    ollama_timeout_seconds: float
    cors_origins: list[str]
    clinical_timeout_seconds: float = 240.0

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            host=os.getenv("BACKEND_HOST", "127.0.0.1"),
            port=int(os.getenv("BACKEND_PORT", "8100")),
            context_base_url='http://context.internal',
            clinical_ie_base_url=os.getenv("CLINICAL_IE_BASE_URL", "http://127.0.0.1:8002").rstrip("/"),
            kg_base_url='http://kg.internal',
            rag_base_url='http://rag.internal',
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/"),
            ollama_model=os.getenv("OLLAMA_MODEL", "qwen2.5:7b"),
            classifier_path=Path(os.getenv("CLASSIFIER_PATH", str(ROOT / "models" / "E5_SVM_seed456.joblib"))).resolve(),
            embedding_model=os.getenv("CLASSIFIER_EMBEDDING_MODEL", "intfloat/multilingual-e5-base"),
            embedding_prefix=os.getenv("CLASSIFIER_EMBEDDING_PREFIX", "query: "),
            normalize_embeddings=os.getenv("CLASSIFIER_NORMALIZE_EMBEDDINGS", "true").lower() == "true",
            id2label=_json_env(
                "CLASSIFIER_ID2LABEL_JSON",
                {
                    "0": "DIAGNOSTIC_ASSESSMENT",
                    "1": "OUT_OF_SCOPE",
                    "2": "GENERAL_MEDICAL_QUERY",
                    "3": "RELATIONAL_QUERY",
                    "4": "CLINICAL_EXPLANATION_MANAGEMENT",
                },
            ),
            database_path=Path(os.getenv("DATABASE_PATH", str(ROOT / "data" / "assistant.sqlite3"))).resolve(),
            upload_dir=Path(os.getenv("UPLOAD_DIR", str(ROOT / "data" / "uploads"))).resolve(),
            max_upload_bytes=int(os.getenv("MAX_UPLOAD_MB", "20")) * 1024 * 1024,
            clinical_timeout_seconds=float(os.getenv("CLINICAL_IE_TIMEOUT_SECONDS", "240")),
            request_timeout_seconds=float(os.getenv("MODULE_TIMEOUT_SECONDS", "180")),
            ollama_timeout_seconds=float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180")),
            cors_origins=[x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173").split(",") if x.strip()],
        )
