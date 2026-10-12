"""KGImportService: validate -> normalize -> plan -> MongoDB -> Neo4j -> finalize.

MongoDB and Neo4j have no shared transaction. The guarantees are:
* each database write is atomic/idempotent on its own (Neo4j: one transaction; Mongo: keyed upserts);
* a persisted ImportJob records status/stage/statistics/errors, so failures are visible and retryable;
* if the document did NOT exist before the import and a write stage fails, the Mongo records written by
  this import are deleted (compensation) -> status "failed", nothing left behind;
* if the document DID exist (upsert/replace) or compensation itself fails -> status "partial", and
  `retry()` re-runs the remaining stages (all writes are idempotent).
"""
from __future__ import annotations

import logging
import time
from collections import OrderedDict
from copy import deepcopy
from functools import wraps
from threading import RLock
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .config import Limits
from .errors import (ImportConflictError, ImportStateError, ImportTransactionError, Issue, KGImportError,
                     MongoImportError, Neo4jImportError, ValidationError)
from .models import KGImport, parse_import
from .entity_linking import link_entities
from .normalization import NormalizedImport, normalize
from .ontology import Ontology
from .planner import MODES, ImportPlan, build_plan
from .ports import DocumentStore, GraphStore, JobStore
from .utils import new_import_id, sha256_of, utcnow_iso
from .validation import validate

log = logging.getLogger("kg_import")
IMPORT_LOCK = RLock()


def serialized(fn):
    @wraps(fn)
    def call(*args, **kwargs):
        with IMPORT_LOCK:
            return fn(*args, **kwargs)
    return call


class Status(str, Enum):
    PENDING = "pending"
    VALIDATING = "validating"
    VALIDATED = "validated"
    WRITING_MONGO = "writing_mongo"
    WRITING_NEO4J = "writing_neo4j"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"
    DRY_RUN = "dry_run"


_HTTP = {"validation": 422, "conflict": 409, "state": 409, "infrastructure": 500}
_RETRYABLE_STAGES = ("mongodb", "neo4j", "finalize", "vector")


@dataclass
class ImportResult:
    import_id: str
    status: str
    mode: str
    document_id: str | None = None
    stage: str | None = None
    statistics: dict[str, Any] = field(default_factory=dict)
    plan: dict[str, Any] | None = None
    errors: list[dict[str, Any]] = field(default_factory=list)
    retryable: bool = False
    compensated: bool = False
    failure_kind: str | None = None

    @property
    def http_status(self) -> int:
        if self.status in (Status.COMPLETED.value, Status.DRY_RUN.value):
            return 200
        return _HTTP.get(self.failure_kind or "infrastructure", 500)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"import_id": self.import_id, "status": self.status, "mode": self.mode,
                               "document_id": self.document_id, "statistics": self.statistics, "errors": self.errors}
        if self.stage and self.status not in (Status.COMPLETED.value, Status.DRY_RUN.value):
            out["stage"] = self.stage
            out["retryable"] = self.retryable
            out["compensated"] = self.compensated
        if self.plan is not None:
            out["plan"] = self.plan
        return out


@dataclass
class _Run:
    import_id: str
    mode: str
    dry_run: bool
    payload_hash: str
    is_retry: bool = False
    document_id: str | None = None
    stage: str = "validation"
    persisted: bool = False
    orig_stage: str | None = None
    stats: dict[str, Any] = field(default_factory=dict)


def _peek_document_id(payload: Any) -> str | None:
    doc = payload.get("document") if isinstance(payload, dict) else None
    v = doc.get("document_id") if isinstance(doc, dict) else None
    return v if isinstance(v, str) and len(v) <= 128 else None


class KGImportService:
    """Public entry points: import_kg, retry, get_status, validate_payload."""

    def __init__(self, ontology: Ontology, docs: DocumentStore, graph: GraphStore, jobs: JobStore,
                 limits: Limits | None = None, entity_index: Any | None = None) -> None:
        self.ontology, self.docs, self.graph, self.jobs = ontology, docs, graph, jobs
        self.limits = limits or Limits()
        self.entity_index = entity_index
        self._previews = OrderedDict()

    def review_profile(self):
        settings = getattr(self.entity_index, 'settings', None)
        return sha256_of({'policy': 'kg-review-v3-identity',
            'embedding': getattr(self.entity_index, 'profile', type(self.entity_index).__name__),
            'threshold': getattr(settings, 'candidate_score', None), 'types': sorted(self.ontology.entity_types),
            'relations': {k: [sorted(v.domain), sorted(v.range)] for k, v in self.ontology.relations.items()}})

    @serialized
    def preview_kg(self, payload, *, refresh=False):
        """Read cache only; actual imports always revalidate the graph."""
        key = (sha256_of(payload), self.review_profile())
        saved = self._previews.get(key)
        if not refresh and saved and saved[0] > time.monotonic():
            self._previews.move_to_end(key)
            return deepcopy(saved[1])
        result = self.import_kg(payload, 'upsert', dry_run=True)
        if result.status == 'dry_run':
            self._previews[key] = (time.monotonic() + 45, deepcopy(result))
            self._previews.move_to_end(key)
            while len(self._previews) > 16: self._previews.popitem(last=False)
        return result

    def invalidate_previews(self):
        self._previews.clear()

    # ------------------------------------------------------------------ public API
    def validate_payload(self, payload: Any) -> list[Issue]:
        """Schema + semantic + ontology validation only. No database access."""
        kg, issues = parse_import(payload)
        return issues if kg is None else validate(kg, self.ontology, self.limits)

    def get_status(self, import_id: str) -> dict[str, Any]:
        job = self.jobs.get_job(import_id)
        if job is None:
            raise ImportStateError(f"import '{import_id}' not found", import_id=import_id)
        return job

    @serialized
    def import_kg(self, payload: Any, mode: str = "upsert", *, dry_run: bool = False) -> ImportResult:
        run = _Run(new_import_id(), mode, dry_run, sha256_of(payload))
        return self._guarded(run, lambda: self._pipeline(run, payload))

    @serialized
    def retry(self, import_id: str, payload: Any) -> ImportResult:
        """Resume a failed/partial import. The payload must be byte-for-byte the same content (hash checked)."""
        try:
            job = self.get_status(import_id)
        except KGImportError as exc:
            run = _Run(import_id, "unknown", False, "")
            return self._result_from_error(run, exc)
        run = _Run(import_id, job["mode"], False, job["payload_hash"], is_retry=True, orig_stage=job.get("stage"),
                   document_id=job.get("document_id"), persisted=True, stats=dict(job.get("statistics") or {}))
        return self._guarded(run, lambda: self._retry_pipeline(run, job, payload))

    # ------------------------------------------------------------------ pipelines
    def _guarded(self, run: _Run, fn) -> ImportResult:
        try:
            return fn()
        except KGImportError as exc:
            return self._result_from_error(run, exc)
        except Exception as exc:  # noqa: BLE001 - converted to a sanitized error, full detail goes to the server log
            log.error("[IMPORT] import_id=%s stage=%s status=error exc=%s: %.300s", run.import_id, run.stage,
                      type(exc).__name__, exc)
            cls = {"mongodb": MongoImportError, "neo4j": Neo4jImportError}.get(run.stage, ImportTransactionError)
            return self._result_from_error(run, cls(f"{run.stage} stage failed ({type(exc).__name__}); see server logs",
                                                    document_id=run.document_id, stage=run.stage))

    def _pipeline(self, run: _Run, payload: Any) -> ImportResult:
        if run.mode not in MODES:
            raise ValidationError("invalid mode", issues=[Issue("INVALID_MODE", f"mode must be one of {list(MODES)}")])
        run.document_id = _peek_document_id(payload)
        if not run.dry_run:
            run.stage = "job_store"
            self.jobs.create_job({
                "import_id": run.import_id, "document_id": run.document_id, "mode": run.mode,
                "status": Status.PENDING.value, "stage": "pending", "payload_hash": run.payload_hash,
                "statistics": {}, "errors": [], "mongo_done": False, "neo4j_done": False, "compensated": False,
                "document_preexisting": None, "retry_count": 0, "started_at": utcnow_iso(), "completed_at": None,
            })
            run.persisted = True
        norm, plan = self._prepare(run, payload, run.mode)
        if run.dry_run:
            self._log(run, "dry_run", "success")
            return ImportResult(run.import_id, Status.DRY_RUN.value, run.mode, run.document_id, plan=plan.to_dict())
        self._job(run, document_preexisting=plan.document_exists, plan=plan.to_dict())
        return self._execute(run, norm, plan, preexisting=plan.document_exists, done={})

    def _retry_pipeline(self, run: _Run, job: dict[str, Any], payload: Any) -> ImportResult:
        if job["status"] not in (Status.FAILED.value, Status.PARTIAL.value) or job.get("stage") not in _RETRYABLE_STAGES:
            raise ImportStateError(f"import '{run.import_id}' is not retryable (status={job['status']}, stage={job.get('stage')}); "
                                   "submit it as a new import", import_id=run.import_id)
        if sha256_of(payload) != job["payload_hash"]:
            raise ImportStateError("payload differs from the original import; submit it as a new import", import_id=run.import_id)
        if job.get('stage') == 'vector':
            return self._retry_vectors(run, job)
        self._job(run, status=Status.VALIDATING.value, retry_count=job.get("retry_count", 0) + 1, errors=[], completed_at=None)
        plan_mode = "upsert" if run.mode == "insert" else run.mode  # our own partial writes must not count as conflicts
        norm, plan = self._prepare(run, payload, plan_mode)
        stage = job.get("stage")
        done = {"mongo": bool(job.get("mongo_done")) and stage in ("neo4j", "finalize"),
                "neo4j": bool(job.get("neo4j_done")) and stage == "finalize"}
        return self._execute(run, norm, plan, preexisting=bool(job.get("document_preexisting")), done=done)

    def _prepare(self, run: _Run, payload: Any, plan_mode: str) -> tuple[NormalizedImport, ImportPlan]:
        t0 = time.perf_counter()
        run.stage = "validation"
        self._job(run, status=Status.VALIDATING.value, stage="validation")
        kg, issues = parse_import(payload)
        if kg is not None:
            run.document_id = kg.document.document_id
            issues = validate(kg, self.ontology, self.limits)
        if issues:
            raise ValidationError("payload failed validation", issues=issues)
        self._log(run, "validation", "success", t0)
        self._job(run, status=Status.VALIDATED.value, document_id=run.document_id)
        t0 = time.perf_counter()
        run.stage = "planning"
        decisions = payload.get("entity_link_decisions", {}) if isinstance(payload, dict) else {}
        if not isinstance(decisions, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                                   for k, v in decisions.items()):
            raise ValidationError("invalid entity link decisions",
                                  issues=[Issue("ENTITY_LINK_DECISION_INVALID", "expected a mapping of input ids to 'new' or an existing id")])
        type_decisions = payload.get('entity_type_decisions', {})
        if (not isinstance(type_decisions, dict) or any(k not in {e.id for e in kg.entities} or v != 'distinct' for k,v in type_decisions.items())):
            raise ValidationError('invalid type review decisions', issues=[Issue('ENTITY_TYPE_REVIEW_INVALID', 'Expected input IDs mapped to distinct after individual type review.')])
        linked, entity_links = link_entities(kg, self.graph, decisions)  # type: ignore[arg-type]
        # Revalidate endpoints after linking; no ontology check may be bypassed by rewriting IDs.
        linked_issues = validate(linked, self.ontology, self.limits)
        if linked_issues:
            raise ValidationError("linked payload failed validation", issues=linked_issues)
        norm = normalize(linked)
        # Keep document-scoped original IDs for provenance without duplicating graph nodes.
        norm.mongo['documents'][0]['entity_id_map'] = {e.id: entity_links.get(e.id, e.id) for e in kg.entities}
        plan = build_plan(norm, plan_mode, self.ontology, self.graph, self.docs, batch=self.limits.neo4j_batch_size)
        plan.entity_links = entity_links
        from .identity_review import cross_type_candidates
        plan.entity_candidates.update(cross_type_candidates(kg, self.graph, type_decisions))
        if plan.errors:
            raise ValidationError("payload references could not be resolved", issues=plan.errors + plan.conflicts)
        if plan.conflicts:
            raise ImportConflictError("import conflicts with existing data", issues=plan.conflicts)
        if self.entity_index is not None:
            try:
                index_ready = self.entity_index.ready()
            except ValueError as exc:
                raise ValidationError('entity index incompatible', issues=[Issue('ENTITY_INDEX_INCOMPATIBLE', str(exc))]) from exc
            if not index_ready:
                raise ValidationError('entity index missing', issues=[Issue('ENTITY_INDEX_NOT_READY', 'run python -m scripts.kg.index_entities first')])
            existing_ids = self.graph.get_entities([e['id'] for e in norm.entities])
            pending = [e for e in norm.entities if e['id'] not in existing_ids]
            queries = [(e['canonical_name'], None) for e in pending]
            many = getattr(self.entity_index, 'suggest_many', None)
            groups = many(queries) if many else [self.entity_index.suggest(*q) for q in queries]
            if len(groups) != len(pending): raise ValueError('entity candidate batch count mismatch')
            known = {}
            ids = sorted({c['entity_id'] for group in groups for c in group})
            for start in range(0, len(ids), self.limits.neo4j_batch_size):
                known.update(self.graph.get_entities(ids[start:start + self.limits.neo4j_batch_size]))
            for e, candidates in zip(pending, groups):
                candidates = [c for c in candidates if c['entity_id'] in known and c['entity_id'] != e['id']
                              and (known[c['entity_id']]['entity_type'] != e['entity_type'] or decisions.get(e['id']) != 'new')
                              and (known[c['entity_id']]['entity_type'] == e['entity_type'] or type_decisions.get(e['id']) != 'distinct')]
                for c in candidates:
                    c['entity_type'] = known[c['entity_id']]['entity_type']
                    if c['entity_type'] != e['entity_type']:
                        c.update(match_kind='cross_type', link_allowed=False, incoming_type=e['entity_type'])
                if candidates: plan.entity_candidates.setdefault(e['id'], []).extend(candidates)
        if plan.entity_candidates and not run.dry_run:
            raise ValidationError("similar entity names require review before import",
                                  issues=[Issue("ENTITY_LINK_REVIEW_REQUIRED", f"review candidate(s) for '{i}'",
                                                context={"entity_id": i, "candidates": c})
                                          for i, c in plan.entity_candidates.items()])
        self._log(run, "planning", "success", t0)
        return norm, plan

    # ------------------------------------------------------------------ execution
    def _execute(self, run: _Run, norm: NormalizedImport, plan: ImportPlan, *, preexisting: bool,
                 done: dict[str, bool]) -> ImportResult:
        doc = norm.document_id
        self.invalidate_previews()
        stats = run.stats
        stats.update(entities_skipped=plan.entities["skip"], relations_skipped=plan.relations["skip"])
        mongo_mode = "insert" if run.mode == "insert" and not run.is_retry else "upsert"

        if not done.get("mongo"):
            run.stage = "mongodb"
            self._job(run, status=Status.WRITING_MONGO.value, stage="mongodb")
            t0 = time.perf_counter()
            try:
                counts = self.docs.write(norm.mongo, mode=mongo_mode, import_id=run.import_id, now=utcnow_iso())
            except Exception as exc:  # noqa: BLE001
                return self._abort(run, "mongodb", exc, MongoImportError, preexisting)
            stats.update(mongo_records=sum(counts.values()), mongo=counts)
            self._job(run, mongo_done=True, statistics=stats)
            self._log(run, "mongodb", "success", t0)

        if not done.get("neo4j"):
            run.stage = "neo4j"
            self._job(run, status=Status.WRITING_NEO4J.value, stage="neo4j")
            t0 = time.perf_counter()
            try:
                res = self.graph.write(norm.entities, norm.relations, document_id=doc, import_id=run.import_id,
                                       now=utcnow_iso(), replace=(run.mode == "replace"))
            except Exception as exc:  # noqa: BLE001
                return self._abort(run, "neo4j", exc, Neo4jImportError, preexisting)
            written_e = plan.entities["create"] + plan.entities["update"]
            written_r = plan.relations["create"] + plan.relations["update"]
            stats.update(entities_created=res.entities_created, entities_updated=max(0, written_e - res.entities_created),
                         relations_created=res.relations_created, relations_updated=max(0, written_r - res.relations_created))
            if run.mode == "replace":
                stats.update(relations_deleted=res.relations_deleted, entities_unlinked=res.entities_unlinked,
                             entities_deleted=res.entities_deleted)
            self._job(run, neo4j_done=True, statistics=stats)
            self._log(run, "neo4j", "success", t0)

        vector_error = None
        if self.entity_index is not None:
            self._job(run, vector_entity_ids=[e['id'] for e in norm.entities], vector_done=False)
            try:
                stats["entity_names_indexed"] = self.entity_index.upsert_entities(norm.entities)
                stats.pop('entity_index_warning', None)
                self._job(run, vector_done=True)
            except Exception as exc:  # graph and Mongo writes have already committed
                log.error("[IMPORT] entity index sync failed: %s: %.200s", type(exc).__name__, exc)
                vector_error = exc
                stats["entity_index_warning"] = "Qdrant chưa đồng bộ. Thử lại import này để chỉ cập nhật vector."

        run.stage = "finalize"
        self._job(run, status=Status.FINALIZING.value, stage="finalize")
        if run.mode == "replace":
            try:
                stale = self.docs.delete_stale(doc, run.import_id)
            except Exception as exc:  # noqa: BLE001
                return self._abort(run, "finalize", exc, MongoImportError, preexisting, compensate=False)
            stats["mongo_stale_deleted"] = sum(stale.values())
        self._job(run, finalize_done=True)
        if vector_error is not None:
            return self._vector_failure(run)
        self._job(run, status=Status.COMPLETED.value, stage="completed", statistics=stats, errors=[],
                  completed_at=utcnow_iso())
        self._log(run, "finalize", "success")
        return ImportResult(run.import_id, Status.COMPLETED.value, run.mode, doc, statistics=stats)

    def _vector_failure(self, run: _Run) -> ImportResult:
        errors = [{'code': 'VECTOR_SYNC_FAILED', 'message': 'MongoDB/Neo4j đã ghi xong; Qdrant chưa đồng bộ. Thử lại bước vector.'}]
        self._job(run, status='partial', stage='vector', errors=errors, statistics=run.stats, completed_at=utcnow_iso())
        return ImportResult(run.import_id, 'partial', run.mode, run.document_id, stage='vector',
                            statistics=run.stats, errors=errors, retryable=True, failure_kind='infrastructure')

    def _retry_vectors(self, run: _Run, job: dict) -> ImportResult:
        self.invalidate_previews()
        if not (job.get('mongo_done') and job.get('neo4j_done') and job.get('finalize_done')):
            raise ImportStateError('storage writes must finish before vector-only retry', import_id=run.import_id)
        self._job(run, retry_count=job.get('retry_count', 0) + 1)
        try:
            if self.entity_index is None:
                raise RuntimeError('entity vector index is disabled')
            ids = job.get('vector_entity_ids', [])
            entities = []
            for start in range(0, len(ids), 500):
                entities.extend(self.graph.find_entity_candidates(ids[start:start + 500], [], []))
            if {e['id'] for e in entities} != set(ids):
                raise RuntimeError('an imported entity no longer exists; review the source again')
            run.stats['entity_names_indexed'] = self.entity_index.upsert_entities(entities)
        except Exception:
            log.exception('[IMPORT] vector retry failed import_id=%s', run.import_id)
            return self._vector_failure(run)
        run.stats.pop('entity_index_warning', None)
        self._job(run, status='completed', stage='completed', vector_done=True, errors=[],
                  statistics=run.stats, completed_at=utcnow_iso())
        return ImportResult(run.import_id, 'completed', run.mode, run.document_id, statistics=run.stats)

    def _abort(self, run: _Run, stage: str, exc: Exception, err_cls: type[KGImportError], preexisting: bool,
               *, compensate: bool = True) -> ImportResult:
        log.error("[IMPORT] import_id=%s document_id=%s stage=%s status=failed exc=%s: %.300s", run.import_id,
                  run.document_id, stage, type(exc).__name__, exc)
        issues = [Issue(err_cls.code, f"{stage} stage failed ({type(exc).__name__}); see server logs",
                        context={"document_id": run.document_id, "stage": stage})]
        status, compensated = Status.PARTIAL, False
        if compensate and not preexisting:
            try:
                self.docs.delete_by_import(run.document_id or "", run.import_id)
                status, compensated = Status.FAILED, True
                self._job(run, mongo_done=False)
            except Exception as cexc:  # noqa: BLE001
                log.error("[IMPORT] import_id=%s compensation failed: %s: %.300s", run.import_id, type(cexc).__name__, cexc)
                issues.append(Issue("COMPENSATION_FAILED", "could not roll back MongoDB records; manual cleanup or retry needed",
                                    context={"document_id": run.document_id}))
        errors = [i.to_dict() for i in issues]
        self._job(run, status=status.value, stage=stage, errors=errors, compensated=compensated,
                  statistics=run.stats, completed_at=utcnow_iso())
        return ImportResult(run.import_id, status.value, run.mode, run.document_id, stage=stage, statistics=run.stats,
                            errors=errors, retryable=True, compensated=compensated, failure_kind="infrastructure")

    def _result_from_error(self, run: _Run, exc: KGImportError) -> ImportResult:
        issues = exc.to_issues()
        errors = [i.to_dict() for i in issues]
        stage, status, retryable = run.stage, Status.FAILED, False
        if run.is_retry and exc.kind == "infrastructure" and stage in ("validation", "planning"):
            stage, status, retryable = run.orig_stage or stage, Status.PARTIAL, True  # storage hiccup: stay retryable
        if run.persisted:
            self._job(run, status=status.value, stage=stage, errors=errors, completed_at=utcnow_iso())
        self._log(run, stage, "failed", code=exc.code)
        return ImportResult(run.import_id, status.value, run.mode, run.document_id, stage=stage,
                            statistics=run.stats, errors=errors, retryable=retryable, failure_kind=exc.kind)

    # ------------------------------------------------------------------ helpers
    def _job(self, run: _Run, **fields: Any) -> None:
        if not run.persisted:
            return
        try:
            self.jobs.update_job(run.import_id, {**fields, "updated_at": utcnow_iso()})
        except Exception as exc:  # noqa: BLE001 - job bookkeeping must never mask the import outcome
            log.error("[IMPORT] import_id=%s could not update job: %s: %.200s", run.import_id, type(exc).__name__, exc)

    def _log(self, run: _Run, stage: str, status: str, t0: float | None = None, **extra: Any) -> None:
        dur = f" duration_ms={(time.perf_counter() - t0) * 1000:.0f}" if t0 is not None else ""
        more = "".join(f" {k}={v}" for k, v in extra.items())
        log.info("[IMPORT] import_id=%s document_id=%s stage=%s status=%s%s%s", run.import_id, run.document_id, stage,
                 status, dur, more)
