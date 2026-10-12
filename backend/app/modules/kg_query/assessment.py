"""Read-only KG tools for the confirmed-patient assessment workflow.

No patient data is written, no diagnosis is produced, no model is invoked.
Confirmation fields describe upstream assertions; this module cannot authenticate
who confirmed them. Production callers must load a server-owned confirmed snapshot.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import EntityRef, Fact

DISEASE_TYPES = ['Disease', 'DiseaseSubtype', 'Syndrome', 'AcuteCondition']
GROUPS = {
    'symptoms': ['HAS_SYMPTOM'],
    'signs': ['HAS_CLINICAL_SIGN'],
    'labs': ['HAS_LAB_FINDING'],
    'imaging': ['HAS_IMAGING_FINDING'],
    'risk_factors': ['HAS_RISK_FACTOR', 'RISK_FACTOR_FOR'],
    'criteria': ['HAS_DIAGNOSTIC_CRITERION', 'HAS_CRITERION'],
    'differential': ['DIFFERENTIAL_DIAGNOSIS_OF', 'DIFFERENTIAL_DIAGNOSIS', 'HAS_DIFFERENTIAL_DIAGNOSIS'],
    'emergency': ['HAS_EMERGENCY_SIGN'],
}
ASSOCIATIONS = GROUPS['symptoms'] + GROUPS['signs'] + GROUPS['labs'] + GROUPS['imaging'] + GROUPS['risk_factors']
ASKABLE = {
    'Symptom': 'Trong đợt hiện tại, bạn có gặp tình trạng “{name}” không?',
    'RiskFactor': 'Thông tin “{name}” có đúng với bạn không?',
    'LifestyleFactor': 'Thông tin “{name}” có đúng với bạn không?',
    'ExposureFactor': 'Bạn có thông tin về việc tiếp xúc với “{name}” không?',
    'OccupationalExposure': 'Bạn có thông tin về việc tiếp xúc với “{name}” không?',
    'EnvironmentalFactor': 'Bạn có thông tin về việc tiếp xúc với “{name}” không?',
}

ENTITIES = '''
MATCH (e:Entity) WHERE e.id IN $ids
RETURN e.id AS id, e.canonical_name AS name, e.entity_type AS type
ORDER BY id
'''
DISEASE_PAGE = '''
MATCH (d:Entity)
WHERE d.entity_type IN $types AND d.id > $after AND ($ids IS NULL OR d.id IN $ids)
RETURN d.id AS id, d.canonical_name AS name, d.entity_type AS type
ORDER BY id LIMIT $limit
'''
COVERAGE = '''
MATCH (d:Entity) WHERE d.id IN $ids
OPTIONAL MATCH (d)-[r]-(f:Entity)
WHERE type(r) IN $relations
WITH d, type(r) AS relation, count(r) AS edge_count,
     sum(CASE WHEN r.source_document_id IS NOT NULL AND size(coalesce(r.evidence_ids, [])) > 0 THEN 1 ELSE 0 END) AS evidence_reference_count
RETURN d.id AS disease_id, relation, edge_count, evidence_reference_count
ORDER BY disease_id, relation
'''
RELATIONS = '''
MATCH (d:Entity)-[r]-(f:Entity)
WHERE d.entity_type IN $types AND type(r) IN $relations
  AND ($disease_ids IS NULL OR d.id IN $disease_ids)
  AND ($feature_ids IS NULL OR f.id IN $feature_ids)
  AND ((type(r) = 'RISK_FACTOR_FOR' AND startNode(r) = f)
       OR (type(r) <> 'RISK_FACTOR_FOR' AND startNode(r) = d))
RETURN d.id AS disease_id, d.canonical_name AS disease_name, d.entity_type AS disease_type,
       f.id AS feature_id, f.canonical_name AS feature_name, f.entity_type AS feature_type,
       r.id AS rel_id, type(r) AS rel, r.source_document_id AS doc_id,
       r.evidence_ids AS evidence_ids, r.source_proposition_ids AS proposition_ids,
       r.confidence AS confidence, r.properties_json AS properties_json
ORDER BY disease_id, feature_id, rel_id LIMIT $limit
'''

class InputModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

class CoverageRequest(InputModel):
    disease_ids: list[str] | None = Field(default=None, min_length=1, max_length=200)
    after_id: str = Field(default='', max_length=200)
    page_size: int = Field(default=30, ge=1, le=100)

class MapRequest(InputModel):
    mentions: list[str] = Field(min_length=1, max_length=30)

    @field_validator('mentions')
    @classmethod
    def valid_mentions(cls, values):
        if any(not v.strip() or len(v) > 160 for v in values):
            raise ValueError('mentions must be nonblank and at most 160 characters')
        return list(dict.fromkeys(v.strip() for v in values))

class ConfirmedFact(InputModel):
    fact_id: str = Field(min_length=1, max_length=200)
    kg_entity_id: str = Field(min_length=1, max_length=200)
    presence: Literal['present', 'absent', 'unknown']
    confirmation_status: Literal['user_confirmed']
    confirmed_at: datetime
    source_id: str = Field(min_length=1, max_length=200)
    timeframe: Literal['current', 'history']

    @field_validator('confirmed_at')
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError('confirmed_at requires a timezone')
        return value

class FollowupRequest(InputModel):
    patient_id: str = Field(min_length=1, max_length=200)
    assessment_id: str = Field(min_length=1, max_length=200)
    facts: list[ConfirmedFact] = Field(min_length=1, max_length=100)
    asked_entity_ids: list[str] = Field(default_factory=list, max_length=200)
    max_questions: int = Field(default=3, ge=1, le=5)

    @model_validator(mode='after')
    def unique_facts(self):
        if len({f.fact_id for f in self.facts}) != len(self.facts):
            raise ValueError('fact_id must be unique')
        return self


def map_entities(service, payload: MapRequest):
    items = []
    for mention in payload.mentions:
        anchors = service.resolve(mention)
        direct = [a for a in anchors if a.matched_by in {'exact_name', 'alias'}]
        # Even matching names may identify distinct concepts. Never pick among them.
        resolved = len(anchors) == 1 and len(direct) == 1
        items.append({'mention': mention, 'status': 'resolved' if resolved else 'needs_confirmation' if anchors else 'not_found',
                      'kg_entity_id': anchors[0].entity.id if resolved else None,
                      'candidates': [{'entity': vars(a.entity), 'matched_by': a.matched_by} for a in anchors]})
    return {'items': items, 'mapping_scope': 'KG entity mapping only; not clinical fact confirmation'}


def coverage(service, payload: CoverageRequest):
    rows = service._read(DISEASE_PAGE, types=DISEASE_TYPES, after=payload.after_id,
                         ids=payload.disease_ids, limit=payload.page_size + 1)
    more = len(rows) > payload.page_size
    nodes = rows[:payload.page_size]
    relations = list(dict.fromkeys(r for group in GROUPS.values() for r in group))
    counts = service._read(COVERAGE, ids=[d['id'] for d in nodes], relations=relations) if nodes else []
    by_id = defaultdict(dict)
    for row in counts:
        if row.get('relation'):
            by_id[row['disease_id']][row['relation']] = row
    items = []
    for node in nodes:
        groups = {}
        for name, names in GROUPS.items():
            matches = [by_id[node['id']].get(r, {}) for r in names]
            total = sum(m.get('edge_count', 0) for m in matches)
            sourced = sum(m.get('evidence_reference_count', 0) for m in matches)
            groups[name] = {'edge_count': total, 'with_evidence_reference': sourced,
                            'without_evidence_reference': total - sourced}
        items.append({'disease': node, 'groups': groups,
                      'empty_groups': [g for g, c in groups.items() if not c['edge_count']]})
    missing_ids = []
    if payload.disease_ids:
        existing = {r['id'] for r in service._read(ENTITIES, ids=payload.disease_ids)
                    if r['type'] in DISEASE_TYPES}
        missing_ids = sorted(set(payload.disease_ids) - existing)
    return {'schema_version': '1.0', 'items': items, 'next_after_id': nodes[-1]['id'] if more else None,
            'missing_or_non_disease_ids': missing_ids,
            'scope': 'stored_graph_structure', 'audited_entity_types': DISEASE_TYPES, 'evidence_text_checked': False,
            'clinical_completeness_assessed': False,
            'warnings': ['Empty groups mean missing graph data, not absence of a clinical relationship.',
                         'Evidence references are counted; their text must be verified separately.',
                         'Model label coverage requires an explicit label-to-KG-ID mapping.']}


def _read_relations(service, *, features=None, diseases=None):
    # Never silently select a subset from an over-large neighborhood.
    rows = service._read(RELATIONS, types=DISEASE_TYPES, relations=ASSOCIATIONS,
                         feature_ids=features, disease_ids=diseases, limit=501)
    return rows[:500], len(rows) > 500


def _fact(row):
    disease = EntityRef(row['disease_id'], row['disease_name'], row['disease_type'])
    feature = EntityRef(row['feature_id'], row['feature_name'], row['feature_type'])
    subject, obj = (feature, disease) if row['rel'] == 'RISK_FACTOR_FOR' else (disease, feature)
    result = Fact(subject, row['rel'], obj, disease.id)
    result.add_row(row)
    return result


def _supported(service, rows):
    facts = [_fact(r) for r in rows]
    service.attach_evidence(facts)
    usable, excluded = [], 0
    for row, fact in zip(rows, facts):
        # Require actual source text, not just a dangling reference.
        props = fact.assertions[0]['properties']
        non_assertion = (props.get('negated') is True or props.get('polarity') in ('negative', 'negated')
                         or props.get('statement_type') in ('question', 'plan', 'hypothesis')
                         or props.get('status') in ('retracted', 'entered_in_error'))
        if non_assertion or not fact.assertions[0]['properties_valid'] or not any(str(e.get('text') or '').strip() for e in fact.evidence_texts):
            excluded += 1
        else:
            usable.append((row, fact))
    return usable, excluded


def followups(service, payload: FollowupRequest):
    result = {'schema_version': '1.0', 'patient_id': payload.patient_id,
              'assessment_id': payload.assessment_id, 'status': 'no_candidates',
              'questions': [], 'candidate_diseases': [], 'warnings': [],
              'diagnostic_ready': False, 'ranking_method': 'graph_coverage_heuristic_not_probability',
              'confirmation_check': 'upstream_declaration_only', 'writes_patient_graph': False}
    grouped = defaultdict(set)
    for f in payload.facts:
        grouped[(f.kg_entity_id, f.timeframe)].add(f.presence)
    if any('present' in v and 'absent' in v for v in grouped.values()):
        result.update(status='conflicting_facts')
        return result
    ids = list(dict.fromkeys(f.kg_entity_id for f in payload.facts))
    nodes = {n['id']: n for n in service._read(ENTITIES, ids=ids)}
    if set(ids) - nodes.keys():
        result.update(status='unmapped_facts', missing_entity_ids=sorted(set(ids) - nodes.keys()))
        return result
    # Historical symptoms are not silently treated as current symptoms.
    present = [f.kg_entity_id for f in payload.facts if f.presence == 'present' and f.timeframe == 'current']
    if not present:
        result.update(status='no_current_positive_facts')
        return result
    rows, truncated = _read_relations(service, features=present)
    if truncated:
        result.update(status='needs_narrower_scope')
        return result
    supported, excluded = _supported(service, rows)
    candidate_ids = sorted({row['disease_id'] for row, _ in supported})
    if not candidate_ids:
        result['warnings'].append('No candidate with retrievable evidence; this does not exclude disease.')
        return result
    if len(candidate_ids) > 30:
        result.update(status='needs_narrower_scope')
        return result
    result['candidate_diseases'] = [
        {'id': cid, 'name': next(r['disease_name'] for r, _ in supported if r['disease_id'] == cid),
         'basis': [f.to_dict() for r, f in supported if r['disease_id'] == cid]}
        for cid in candidate_ids]
    rows, truncated = _read_relations(service, diseases=candidate_ids)
    if truncated:
        result.update(status='needs_narrower_scope')
        return result
    supported, extra_excluded = _supported(service, rows)
    excluded += extra_excluded
    # Unknown and skipped answers are also excluded to avoid asking repeatedly.
    skip = set(ids) | set(payload.asked_entity_ids)
    questions = {}
    for row, fact in supported:
        eid, kind = row['feature_id'], row['feature_type']
        if eid in skip or kind not in ASKABLE:
            continue
        question = questions.setdefault(eid, {
            'question_id': f"kg:{payload.assessment_id}:{eid}", 'target_entity_id': eid,
            'target_name': row['feature_name'], 'target_type': kind,
            'question_text': ASKABLE[kind].format(name=row['feature_name']),
            'answer_type': 'presence', 'answer_options': ['present', 'absent', 'unknown', 'skip'],
            'candidate_disease_ids': [], 'basis': [], 'requires_review': True,
            'review_reason': 'Check source context and applicability before presenting to the patient.',
        })
        if row['disease_id'] not in question['candidate_disease_ids']:
            question['candidate_disease_ids'].append(row['disease_id'])
        question['basis'].append(fact.to_dict())
    # Order only by association coverage in the retrieved graph; no diagnostic likelihood.
    ranked = sorted(questions.values(), key=lambda q: (-len(q['candidate_disease_ids']), q['target_entity_id']))
    result.update(status='proposals' if ranked else 'no_more_supported_questions',
                  questions=ranked[:payload.max_questions], proposal_count=len(ranked))
    result['warnings'] += [
        'These are reviewable question proposals, not a diagnosis or an autonomous interview.',
        'Missing KG edges are not negative clinical evidence.',
        'All assertion properties and source texts must be considered; applicability is not automatically evaluated.',
        'Only current positive findings seed candidates; historical facts are preserved upstream, not reinterpreted here.',
    ]
    if excluded:
        result['warnings'].append(f'{excluded} relation occurrences excluded for missing source text, invalid properties or explicit non-assertion metadata.')
    return result
