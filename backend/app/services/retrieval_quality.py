"""Structural evidence coverage, not a claim of clinical completeness."""
from copy import deepcopy
from app.modules.kg_query.intents import _DEFS


def usable_fact(fact):
    if not isinstance(fact, dict): return False
    sources = [e for e in fact.get('evidence', []) if isinstance(e, dict)
               and isinstance(e.get('text'), str) and e['text'].strip()]
    if not sources: return False
    for assertion in fact.get('assertions', []):
        if assertion.get('properties_valid') is False: return False
        # A condition from document B cannot be supported by the excerpt of document A.
        if assertion.get('document_id') or assertion.get('evidence_ids'):
            if not any((s.get('doc_id') or s.get('document_id')) == assertion.get('document_id')
                       and s.get('evidence_id') in (assertion.get('evidence_ids') or []) for s in sources):
                return False
    return True


def select_kg_evidence(result):
    if not isinstance(result, dict) or result.get('status') != 'ok':
        return None, 'empty', ['kg_unavailable_or_empty']
    selected = deepcopy(result)
    context = selected.get('llm_context') or {}
    facts = context.get('facts') or []
    valid = {i for i, f in enumerate(facts) if usable_fact(f)}
    reasons = []
    if len(valid) != len(facts): reasons.append('unsourced_or_invalid_assertion')
    mode = selected.get('query', {}).get('mode', 'one_hop')
    if mode in ('compare', 'common', 'difference') and len(valid) != len(facts):
        return None, 'empty', reasons  # Never present a comparison with missing assertion conditions.
    def intact(group):
        indices = group.get('fact_indices')
        return isinstance(indices, list) and bool(indices) and all(type(i) is int and i in valid for i in indices)
    if mode in ('path', 'multi_hop'):
        key = 'paths' if mode == 'path' else 'chains'
        original = context.get(key) or []
        groups = [g for g in original if intact(g)]
        if len(groups) != len(original): reasons.append('incomplete_chain')
        context[key] = groups
        valid = {i for g in groups for i in g['fact_indices']}
    if not valid:
        return None, 'empty', reasons or ['no_sourced_facts']
    remap = {old: new for new, old in enumerate(sorted(valid))}
    context['facts'] = [facts[i] for i in sorted(valid)]
    for key in ('chains', 'paths'):
        context[key] = [{**g, 'fact_indices': [remap[i] for i in g['fact_indices']]}
                        for g in context.get(key, []) if intact(g)]
    # Comparisons retain all facts, so cell indices remain unchanged.
    context['sources'] = [e for f in context['facts'] for e in f.get('evidence', [])]
    selected['llm_context'] = context
    retrieval = selected.get('retrieval') or {}
    if retrieval.get('truncated'): reasons.append('result_limit')
    if retrieval.get('fallback_recommended'): reasons.append('upstream_incomplete')
    comparison = context.get('comparison') or {}
    # complete=False is a standing clinical disclaimer, not a measured coverage flag.
    if comparison and (comparison.get('truncated') or
            any(c.get('fact_count', 0) == 0 or c.get('query_limited') for c in comparison.get('coverage', [])) or
            any(row.get('classification') in ('left_only', 'right_only', 'needs_review', 'assertion_difference') for row in comparison.get('rows', []))):
        reasons.append('comparison_incomplete')
    anchors = retrieval.get('anchors') or {}
    if anchors and any(not group for group in anchors.values()): reasons.append('missing_anchor')
    predicates = {f.get('predicate') for f in context['facts']}
    for intent in selected.get('query', {}).get('intents', []):
        if intent in _DEFS and not predicates.intersection(_DEFS[intent][1]):
            reasons.append('missing_requested_intent')
    return selected, 'partial' if reasons else 'sufficient', list(dict.fromkeys(reasons))
