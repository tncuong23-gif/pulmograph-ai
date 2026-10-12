"""Error taxonomy for the KG import module."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Issue:
    """A single, API-safe problem description (no stack traces, no secrets)."""

    code: str
    message: str
    path: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.path:
            out["path"] = self.path
        out.update(self.context)
        return out


class KGImportError(Exception):
    """Base class. `kind` drives the HTTP status: validation|conflict|infrastructure|state."""

    code = "KG_IMPORT_ERROR"
    kind = "infrastructure"

    def __init__(self, message: str, *, issues: list[Issue] | None = None, **context: Any):
        super().__init__(message)
        self.message = message
        self.issues = list(issues or [])
        self.context = context

    def to_issues(self) -> list[Issue]:
        return self.issues or [Issue(self.code, self.message, context=self.context)]


class ValidationError(KGImportError):
    code = "VALIDATION_ERROR"
    kind = "validation"


class SchemaValidationError(ValidationError):
    code = "SCHEMA_VALIDATION_ERROR"


class OntologyValidationError(ValidationError):
    code = "ONTOLOGY_VALIDATION_ERROR"


class EntityNotFoundError(ValidationError):
    code = "ENTITY_NOT_FOUND"


class DuplicateEntityError(KGImportError):
    code = "DUPLICATE_ENTITY"
    kind = "conflict"


class DuplicateRelationError(KGImportError):
    code = "DUPLICATE_RELATION"
    kind = "conflict"


class ImportConflictError(KGImportError):
    code = "IMPORT_CONFLICT"
    kind = "conflict"


class MongoImportError(KGImportError):
    code = "MONGO_IMPORT_ERROR"


class Neo4jImportError(KGImportError):
    code = "NEO4J_IMPORT_ERROR"


class ImportTransactionError(KGImportError):
    code = "IMPORT_TRANSACTION_ERROR"


class ImportStateError(KGImportError):
    """Import not found / not retryable."""

    code = "IMPORT_STATE_ERROR"
    kind = "state"


class OntologyConfigError(ValueError):
    """The ontology configuration itself is malformed (developer error, not input error)."""
