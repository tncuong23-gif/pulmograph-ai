"""Name collisions across ontology types require a separate, explicit review."""
from .utils import fold
from collections import defaultdict


def cross_type_candidates(kg, graph, type_decisions):
    names = sorted({fold(v) for e in kg.entities for v in (e.canonical_name, *e.aliases)})
    rows = graph.find_entity_candidates([e.id for e in kg.entities], names, [])
    local = [{'id': e.id, 'canonical_name': e.canonical_name, 'entity_type': e.type,
              'aliases': list(e.aliases)} for e in kg.entities]
    stored_ids = {r['id'] for r in rows}
    by_name, by_alias = defaultdict(dict), defaultdict(dict)
    for row in rows + [r for r in local if r['id'] not in stored_ids]:
        by_name[fold(row['canonical_name'])][row['id']] = row
        for alias in row.get('aliases') or []: by_alias[fold(alias)][row['id']] = row
    out = {}
    for e in kg.entities:
        name = fold(e.canonical_name)
        matches = {**by_name[name], **by_alias[name]}
        for alias in e.aliases: matches.update(by_name[fold(alias)])
        for c in matches.values():
            if c['id'] == e.id or c['entity_type'] == e.type:
                continue
            # Shared generic alias alone does not establish identity.
            if not (fold(e.canonical_name) == fold(c['canonical_name']) or
                    fold(e.canonical_name) in {fold(a) for a in c.get('aliases') or []} or
                    fold(c['canonical_name']) in {fold(a) for a in e.aliases}):
                continue
            if type_decisions.get(e.id) == 'distinct':
                continue  # Explicit per-item decision that the concepts are distinct.
            candidate = {'entity_id': c['id'], 'canonical_name': c['canonical_name'],
                         'matched_name': c['canonical_name'], 'entity_type': c['entity_type'],
                         'incoming_type': e.type, 'score': 1.0, 'match_kind': 'cross_type',
                         'link_allowed': False,
                         'review_note': 'Trùng tên/bí danh khác loại: sửa loại trong JSON nếu cùng khái niệm; chỉ giữ riêng khi thật sự khác khái niệm.'}
            if candidate not in out.setdefault(e.id, []): out[e.id].append(candidate)
    return out
