"""Question-to-evidence HTTP contract. No LLM, no generated medical answer."""
from __future__ import annotations

import logging
from copy import deepcopy
import threading
import time
from contextlib import asynccontextmanager
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.kg_import.config import Settings
from app.modules.kg_query.models import QuerySpec
from .entity_lookup import get_lookup, resolved_anchors
from .question_analysis import RULES, COMPARISON_MODES, comparison_mode, detect_intents, choose_mode, validate_mode, uses_context
from .comparison import compare
from .intents import PRESET_CHAINS
from app.modules.kg_query.assessment import (
    CoverageRequest, MapRequest, FollowupRequest, coverage, map_entities, followups,
)

log = logging.getLogger(__name__)


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    question: str = Field(min_length=1, max_length=2000)
    mentions: list[str] | None = Field(default=None, min_length=1, max_length=2)
    intents: list[str] | None = Field(default=None, min_length=1, max_length=6)
    context_mentions: list[str] | None = Field(default=None, min_length=1, max_length=2)
    entity_ids: list[str] | None = Field(default=None, min_length=1, max_length=2)
    mode: Literal['auto', 'one_hop', 'multi_hop', 'path', 'compare', 'common', 'difference'] = 'auto'
    preset: Literal['drugs_for_disease', 'drug_adverse_effects', 'drug_contraindications'] | None = None
    max_hops: int = Field(default=3, ge=1, le=4, strict=True)
    limit: int = Field(default=30, ge=1, le=200, strict=True)
    include_evidence: bool = True

    @field_validator('question')
    @classmethod
    def question_not_blank(cls, value):
        if not value.strip():
            raise ValueError('question must not be blank')
        return value.strip()

    @field_validator('mentions', 'intents', 'context_mentions', 'entity_ids')
    @classmethod
    def valid_list(cls, values):
        if values is not None and any(not v.strip() or len(v) > 160 for v in values):
            raise ValueError('items must be nonblank strings of at most 160 characters')
        return list(dict.fromkeys(v.strip() for v in values)) if values else values

    @model_validator(mode='after')
    def compatible_plan(self):
        if self.preset and self.mode not in ('auto', 'multi_hop'):
            raise ValueError('preset requires auto or multi_hop mode')
        if self.mode == 'multi_hop' and not self.preset:
            raise ValueError('multi_hop requires a supported preset')
        if self.entity_ids and self.mentions:
            raise ValueError('choose entity_ids or mentions, not both')
        if self.intents and (self.preset or self.mode in ('multi_hop', 'path')):
            raise ValueError('intents applies to one_hop or comparison; multi_hop uses preset')
        return self


class QueryResponse(BaseModel):
    schema_version: str = '1.2'
    request_id: str
    question: str
    status: Literal['ok', 'no_entity', 'no_facts', 'needs_clarification']
    query: dict[str, Any]
    retrieval: dict[str, Any]
    llm_context: dict[str, Any]
    warnings: list[str]
    elapsed_ms: float
    clarification: dict[str, Any] | None = None
    timings_ms: dict[str, float] = Field(default_factory=dict)


def detect_mentions(service, question):
    return [g['mention'] for g in get_lookup(service).detect(question)]


def _fact_key(fact):
    return (fact['subject']['id'], fact['predicate'], fact['object']['id'])


def evidence_bundle(result, mode, limit):
    """Budget whole paths/chains; never send a broken route to the answer model."""
    facts, positions, chains, paths = [], {}, [], []
    truncated = False

    def add_group(group):
        nonlocal truncated
        new = {_fact_key(f): f for f in group if _fact_key(f) not in positions}
        if len(facts) + len(new) > limit:
            truncated = True
            return None
        for key, fact in new.items():
            positions[key] = len(facts)
            facts.append(deepcopy(fact))
        # Shared edges across distinct paths can carry different source assertions.
        for fact in group:
            merged = facts[positions[_fact_key(fact)]]
            for field in ('relation_ids', 'doc_ids', 'proposition_ids', 'evidence', 'assertions'):
                for value in fact.get(field, []):
                    if value not in merged.setdefault(field, []):
                        merged[field].append(value)
            for doc, ids in fact.get('evidence_ids', {}).items():
                bucket = merged.setdefault('evidence_ids', {}).setdefault(doc, [])
                bucket.extend(eid for eid in ids if eid not in bucket)
        return [positions[_fact_key(f)] for f in group]

    if mode == 'path':
        for path in result.get('paths', []):
            indices = add_group(path['facts'])
            if indices:
                paths.append({'nodes': path['nodes'], 'fact_indices': indices})
    elif mode == 'multi_hop':
        for group in result.get('chains', []):
            indices = add_group(group)
            if indices:
                chains.append({'fact_indices': indices})
    else:
        for fact in result.get('facts', []):
            add_group([fact])
    sources = {}
    for f in facts:
        for ev in f.get('evidence', []):
            sources[(ev.get('doc_id'), ev.get('evidence_id'))] = ev
    return {'facts': facts, 'sources': list(sources.values()), 'chains': chains, 'paths': paths}, truncated


def retrieve(service, payload: QueryRequest):
    started = time.perf_counter()
    warnings = []
    if payload.intents and any(i not in service.intents for i in payload.intents):
        raise ValueError('Unknown intent; see GET /api/v1/kg/meta')
    lookup = get_lookup(service)
    issue, reason = None, None
    if payload.entity_ids:
        groups, issue = lookup.confirmed(payload.entity_ids)
        reason = 'missing_entity' if issue else None
    elif payload.mentions:
        groups = lookup.named(payload.mentions)
    else:
        groups = lookup.detect(payload.question)
        if not groups and uses_context(payload.question) and payload.context_mentions:
            groups = lookup.named(payload.context_mentions)
        if not groups and not uses_context(payload.question):
            suggestions = lookup.suggestions(payload.question)
            if suggestions:
                groups = [{'mention': payload.question, 'candidates': suggestions}]
    if lookup.truncated and not payload.entity_ids:
        issue = 'Kho KG vượt giới hạn bộ nhận diện tự động (20.000 thực thể). Vui lòng dùng KG Explorer để tra cứu.'
        reason = 'dictionary_limit'
    entity_ms = (time.perf_counter() - started) * 1000
    mentions = [g['mention'] for g in groups]
    intents = payload.intents or detect_intents(payload.question, mentions)
    anchors = resolved_anchors(groups)
    mode, preset, plan_issue = choose_mode(payload.question, anchors, intents,
        mode='one_hop' if payload.mode == 'auto' and payload.intents and not comparison_mode(payload.question)
                      else payload.mode, preset=payload.preset)
    if not issue and len(groups) > 2:
        issue, reason = 'Mỗi lượt hỗ trợ tối đa hai thực thể. Bạn vui lòng tách câu hỏi.', 'too_many_entities'
    if not issue and any(len(g['candidates']) != 1 or g['candidates'][0]['matched_by'] == 'fuzzy' for g in groups):
        issue, reason = 'Tôi chưa xác định chắc tên bệnh/thuốc. Bạn hãy xác nhận thực thể bên dưới hoặc viết lại câu hỏi với tên đầy đủ.', 'ambiguous_entity'
        if any(len({(c['name'].casefold(), c['type']) for c in g['candidates']}) < len(g['candidates']) for g in groups):
            issue, reason = 'KG đang có nhiều thực thể trùng tên và loại. Vui lòng kiểm tra mục Knowledge Graph → Rà soát trùng trong Quản lý dữ liệu trước khi truy vấn tên này.', 'duplicate_entities'
    if not issue and not groups:
        issue = 'Bạn vui lòng nêu rõ tên bệnh, thuốc hoặc thực thể cần tra cứu trong KG.'
        reason = 'missing_entity'
    if not issue:
        issue = plan_issue or validate_mode(mode, preset, intents, anchors, service)
        reason = 'query_scope' if issue else None
    planning_ms = (time.perf_counter() - started) * 1000 - entity_ms
    result = {'anchors': {}, 'facts': [], 'chains': [], 'paths': [], 'notes': []}
    clarification = None
    if issue:
        status = 'needs_clarification'
        # Even a single fuzzy suggestion requires an explicit user choice.
        clarification = {'reason': reason, 'message': issue,
            'groups': [{**g, 'candidate_count': len(g['candidates']), 'candidates': g['candidates'][:5]} for g in groups],
            'can_confirm': reason == 'ambiguous_entity' and 0 < len(groups) <= 2 and all(g['candidates'] for g in groups)}
    elif mode in COMPARISON_MODES:
        result = compare(service, anchors, intents, mode, limit=payload.limit, with_evidence=payload.include_evidence)
        status = result['status']
    else:
        spec = QuerySpec(mentions=mentions, intents=intents if mode == 'one_hop' else [],
            chain=list(PRESET_CHAINS[preset]) if preset else [], path=mode == 'path',
            max_hops=payload.max_hops, limit=payload.limit)
        result = service.run(spec, with_evidence=payload.include_evidence, resolved_anchors=anchors).to_dict()
        status = result['status']
    retrieval_ms = (time.perf_counter() - started) * 1000 - entity_ms - planning_ms
    context, truncated = evidence_bundle(result, mode, payload.limit)
    truncated = truncated or result.get('truncated', False)
    if result.get('comparison') is not None:
        context['comparison'] = result['comparison']
    if not issue and not context['facts']:
        status = 'no_facts'
    if truncated or len(context['facts']) >= payload.limit:
        warnings.append('Đã chạm giới hạn trả kết quả; danh sách có thể chưa đầy đủ.')
    if mode == 'path' and context['paths']:
        warnings.append('Đường liên kết mô tả các quan hệ đã lưu, không tự chứng minh quan hệ nhân quả giữa hai đầu.')
    if context['facts'] and any(not f.get('evidence') for f in context['facts']):
        warnings.append('Một số quan hệ chưa có văn bản bằng chứng; cần kiểm tra tài liệu nguồn trước khi sử dụng.')
    context['interpretation'] = {
        'missing_facts_mean': 'not_found_in_retrieved_data_not_absence',
        'path_semantics': 'stored_relations_not_inferred_causation',
        'confidence_semantics': 'source_metadata_not_disease_probability',
        'respect_assertion_properties': True,
        'comparison_semantics': 'observed_data_not_clinical_equivalence_or_exclusion',
    }
    return QueryResponse(request_id=str(uuid4()), question=payload.question, status=status,
        query={'mentions': mentions, 'intents': intents if mode == 'one_hop' or mode in COMPARISON_MODES else [], 'mode': mode,
               'preset': preset, 'max_hops': payload.max_hops if mode == 'path' else None,
               'entity_resolution': 'user_confirmed' if payload.entity_ids else 'dictionary',
               'analysis': 'validated_upstream' if payload.intents else 'dictionary_and_rules'},
        retrieval={'anchors': result.get('anchors', {}), 'fact_count': len(context['facts']),
                   'fallback_recommended': status != 'ok', 'complete': False, 'truncated': truncated},
        llm_context=context, warnings=warnings + result.get('notes', []), clarification=clarification,
        timings_ms={'entities': round(entity_ms, 2), 'planning': round(planning_ms, 2), 'retrieval': round(retrieval_ms, 2)},
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2))


def create_app(service=None, import_service=None):
    lock = threading.Lock()
    resources = None
    import_resources = None

    @asynccontextmanager
    async def lifespan(app):
        yield
        if resources is not None:
            resources.close()
        if import_resources is not None:
            import_resources.close()

    app = FastAPI(title='KG Retrieval API', version='1.3.0', lifespan=lifespan)

    def get_service():
        nonlocal service, resources
        with lock:
            if service is None:
                from app.modules.kg_query.factory import build_query_resources
                resources = build_query_resources(Settings.from_env())
                service = resources.service
        return service

    def get_import_service():
        nonlocal import_service, import_resources
        with lock:
            if import_service is None:
                from app.modules.kg_import.factory import build_resources
                import_resources = build_resources(Settings.from_env())
                import_service = import_resources.service
        return import_service

    from app.modules.kg_import.api import create_router, _read_json
    app.include_router(create_router(get_import_service))

    @app.post('/api/v1/kg/validate')
    async def validate_payload(request: Request):
        from app.modules.kg_import.ontology import Ontology
        from app.modules.kg_import.models import parse_import
        from app.modules.kg_import.validation import validate
        settings = Settings.from_env()
        payload, failure = await _read_json(request, settings.limits.max_body_bytes)
        if failure:
            return failure
        kg, issues = parse_import(payload)
        if kg is not None:
            issues = validate(kg, Ontology.load(settings.ontology_path), settings.limits)
        return {'valid': not issues, 'errors': [i.to_dict() for i in issues]}

    def error(code, message, status):
        return JSONResponse({'schema_version': '1.0', 'request_id': str(uuid4()),
                             'error': {'code': code, 'message': message}}, status_code=status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc):
        return error('INVALID_REQUEST', 'Invalid body; see /docs for the request schema.', 422)

    @app.get('/health/live')
    def live():
        return {'status': 'ok'}

    @app.get('/health/ready')
    def ready():
        try:
            svc = get_service()
            svc.ping()
            if svc.evidence_store is not None:
                svc.evidence_store.coll.database.client.admin.command('ping')
            return {'status': 'ready'}
        except Exception:
            log.exception('Readiness failed')
            return error('DEPENDENCY_UNAVAILABLE', 'KG dependencies unavailable.', 503)

    @app.get('/api/v1/kg/meta')
    def meta():
        try:
            return {'schema_version': '1.2', 'query_modes': ['one_hop', 'multi_hop', 'path', *COMPARISON_MODES],
                    'default_mode': 'auto', 'planner': 'dictionary_and_rules',
                    'comparison': {'max_entities': 2, 'max_criteria': 6, 'scope': 'direct_relations',
                                   'requires_criterion': True, 'absence_is_not_negation': True},
                    'presets': list(PRESET_CHAINS), 'automatic_intents': list(RULES),
                    'intents': [{'id': i.name, 'description': i.description,
                                 'relations': list(i.relations)} for i in get_service().intents.values()]}
        except Exception:
            log.exception('Metadata failed')
            return error('DEPENDENCY_UNAVAILABLE', 'KG configuration unavailable.', 503)

    @app.post('/api/v1/kg/query', response_model=QueryResponse,
              responses={422: {'description': 'Invalid request'}, 503: {'description': 'Dependency unavailable'}})
    def query(payload: QueryRequest):
        try:
            return retrieve(get_service(), payload)
        except ValueError as exc:
            return error('INVALID_REQUEST', str(exc), 422)
        except Exception:
            log.exception('Retrieval failed')
            return error('DEPENDENCY_UNAVAILABLE', 'KG retrieval unavailable.', 503)

    def assessment_call(fn, payload):
        try:
            return fn(get_service(), payload)
        except ValueError as exc:
            return error('INVALID_REQUEST', str(exc), 422)
        except Exception:
            log.exception('KG assessment support failed')
            return error('DEPENDENCY_UNAVAILABLE', 'KG assessment support unavailable.', 503)

    @app.post('/api/v1/kg/assessment/coverage')
    def assessment_coverage(payload: CoverageRequest):
        """Paginated structural coverage. Does not measure clinical completeness."""
        return assessment_call(coverage, payload)

    @app.post('/api/v1/kg/assessment/map')
    def assessment_map(payload: MapRequest):
        """Resolve names to candidates; ambiguous/fuzzy matches require confirmation."""
        return assessment_call(map_entities, payload)

    @app.post('/api/v1/kg/assessment/followups')
    def assessment_followups(payload: FollowupRequest):
        """Read-only proposals using upstream-confirmed facts. Not diagnosis or automatic interview."""
        return assessment_call(followups, payload)

    return app


app = create_app()
