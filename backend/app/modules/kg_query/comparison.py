"""Bounded, read-only comparisons of direct KG relations.

A common row requires the same target ID, predicate, direction and complete set
of valid assertion properties on both sides. Names alone never establish
equivalence. A one-sided row describes retrieval coverage, NOT medical absence.
"""
from __future__ import annotations

import json
from collections import Counter

NOTICE = ('Kết quả chỉ đối chiếu phần dữ liệu đã truy xuất. Chưa tìm thấy thông tin ở một bên '
          'không có nghĩa bệnh/thuốc đó không có đặc điểm này. Cần đọc điều kiện và phủ định trong nguồn.')

LABELS = {
    'common': 'Ghi nhận tương ứng ở cả hai',
    'left_only': 'Mới tìm thấy ở bên trái',
    'right_only': 'Mới tìm thấy ở bên phải',
    'assertion_difference': 'Thuộc tính nguồn khác nhau; cần đọc điều kiện/phủ định',
    'needs_review': 'Thuộc tính nguồn chưa hợp lệ; cần kiểm tra',
}


def fact_key(fact):
    return fact.subject.id, fact.predicate, fact.object.id


def signatures(facts):
    result, valid = set(), True
    for fact in facts:
        if not fact.assertions:
            valid = False
        for assertion in fact.assertions:
            properties = assertion.get('properties')
            if assertion.get('properties_valid') is not True or not isinstance(properties, dict):
                valid = False
                continue
            result.add(json.dumps(properties, sort_keys=True, ensure_ascii=False, allow_nan=False))
    return result, valid


def compare(service, anchors, intents, mode, *, limit=30, with_evidence=True):
    entities = [group[0].entity for group in anchors.values()]
    candidates, coverage = [], []
    # Each side and each criterion has its own retrieval budget. Large left-side
    # neighbourhoods cannot starve the right side before the comparison is made.
    row_limit = min(service.limits.per_query_rows, max(30, limit + 1))
    for intent_name in intents:
        intent = service.intents[intent_name]
        buckets = {}
        for side, entity in enumerate(entities):
            diagnostic = {'query_limited': False}
            facts = service.neighbors([entity], intent.relations, limit=row_limit, diagnostics=diagnostic)
            coverage.append({'entity_id': entity.id, 'criterion': intent_name,
                             'fact_count': len(facts), **diagnostic})
            for fact in facts:
                direction = 'out' if fact.subject.id == entity.id else 'in'
                far = fact.object if direction == 'out' else fact.subject
                key = (fact.predicate, direction, far.id)
                row = buckets.setdefault(key, {'criterion': intent_name, 'criterion_label': intent.description,
                    'feature': vars(far), 'predicate': fact.predicate, 'direction': direction, '_sides': [[], []]})
                row['_sides'][side].append(fact)
        for row in buckets.values():
            left, right = row['_sides']
            if left and right:
                lset, lvalid = signatures(left)
                rset, rvalid = signatures(right)
                status = ('needs_review' if not lvalid or not rvalid else
                          'common' if lset == rset else 'assertion_difference')
            else:
                status = 'left_only' if left else 'right_only'
            row['classification'], row['label'] = status, LABELS[status]
            candidates.append(row)

    counts = dict(Counter(r['classification'] for r in candidates))
    filtered = [r for r in candidates if mode == 'compare' or
                (mode == 'common' and r['classification'] == 'common') or
                (mode == 'difference' and r['classification'] != 'common')]
    # Deterministic ordering, with compatible common rows first for overview.
    priority = {'common': 0, 'assertion_difference': 1, 'needs_review': 2, 'left_only': 3, 'right_only': 3}
    filtered.sort(key=lambda r: (intents.index(r['criterion']), priority[r['classification']],
                                r['feature']['name'].casefold(), r['feature']['id'], r['predicate'], r['direction']))
    facts, positions, rows = [], {}, []
    budget_limited = False
    for row in filtered:
        group = [f for side in row['_sides'] for f in side]
        new = {fact_key(f): f for f in group if fact_key(f) not in positions}
        if len(facts) + len(new) > limit:
            # Never drop one half of a common row and then call it a difference.
            budget_limited = True
            continue
        for key, fact in new.items():
            positions[key] = len(facts)
            facts.append(fact)
        cells = [{'entity_id': entity.id, 'status': 'recorded' if side else 'not_found_in_retrieved_data',
                  'fact_indices': [positions[fact_key(f)] for f in side]}
                 for entity, side in zip(entities, row['_sides'])]
        rows.append({k: v for k, v in row.items() if k != '_sides'} | {'cells': cells})
    if with_evidence and facts:
        service.attach_evidence(facts)
    query_limited = any(c['query_limited'] for c in coverage)
    warnings = [NOTICE]
    if query_limited:
        warnings.append('Ít nhất một truy vấn đã chạm giới hạn dữ liệu; điểm chung/khác có thể chưa được tìm thấy hết.')
    if budget_limited:
        warnings.append('Một số hàng đối chiếu đã được bỏ qua vì giới hạn kết quả; mỗi hàng được giữ nguyên bằng chứng của cả hai bên.')
    if counts.get('assertion_difference') or counts.get('needs_review'):
        warnings.append('Có thuộc tính nguồn khác nhau hoặc cần kiểm tra. Không tự coi đây là khác biệt y khoa đã được xác nhận.')
    comparison = {
        'mode': mode, 'entities': [vars(e) for e in entities],
        'criteria': [{'id': i, 'label': service.intents[i].description} for i in intents],
        'rows': rows, 'coverage': coverage, 'notice': NOTICE,
        'counts_in_retrieved_data': counts, 'returned_rows': len(rows),
        'complete': False, 'truncated': query_limited or budget_limited,
        'matching': 'entity_id_predicate_direction_and_exact_assertion_properties',
        'no_result_reason': (None if rows else 'result_limit' if filtered else
                             'no_matching_rows' if candidates else 'no_data'),
    }
    return {'status': 'ok' if rows else 'no_facts', 'facts': [f.to_dict() for f in facts],
            'anchors': {m: [{**vars(a.entity), 'matched_by': a.matched_by} for a in group]
                        for m, group in anchors.items()},
            'chains': [], 'paths': [], 'comparison': comparison,
            'truncated': query_limited or budget_limited, 'notes': warnings}
