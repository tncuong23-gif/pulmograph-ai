"""Reviewable facts: preserve assertions and provenance, consolidate repeated records."""
from __future__ import annotations
import copy
import re
import unicodedata
from uuid import uuid4


def normalized(value):
    return ' '.join(unicodedata.normalize('NFC', str(value or '')).casefold().split())


def clean_details(value):
    # Remove only machine statuses known to have been appended by the old workflow.
    text = re.sub(r'status\s*:\s*(?:user_reported|historical|unknown)(?=\s|;|$|status\s*:)', '', str(value or ''), flags=re.I)
    parts = [p.strip(' ;\t\r\n') for p in text.split(';')]
    return '; '.join(dict.fromkeys(p for p in parts if p))[:1000]


def identity(fact):
    original = fact.get('original_fact') or {}
    return (fact.get('fact_type'), normalized(fact.get('canonical_display') or original.get('display') or fact.get('display')),
            fact.get('experiencer', 'patient'))


def clinical_key(fact):
    return (*identity(fact), fact.get('presence'), fact.get('timeframe'), ' '.join(unicodedata.normalize('NFC', clean_details(fact.get('details'))).split()))


def sources(fact):
    return fact.get('source_refs') or [{'source_id': fact.get('source_id'), 'source_text': fact.get('source_text'),
                                      'recorded_at': fact.get('recorded_at')}]


def consolidate(facts):
    result, positions = [], {}
    for incoming in facts:
        fact = copy.deepcopy(incoming)
        fact['details'] = clean_details(fact.get('details'))
        key = clinical_key(fact)
        if key in positions:
            existing = result[positions[key]]
            for source in sources(fact):
                if source not in existing['source_refs']: existing['source_refs'].append(source)
            # A current assertion outranks an old equivalent assertion in this review.
            continue
        fact['source_refs'] = copy.deepcopy(sources(fact))
        positions[key] = len(result)
        result.append(fact)
    return result


def history_candidates(history, current):
    # Equivalent old statements are represented by the freshly reviewed statement.
    # Keep a different time, presence, subject or meaningful clinical detail visible.
    def overlaps(old, new):
        return (identity(old) == identity(new) and old['presence'] == new['presence']
                and old['timeframe'] == new['timeframe']
                and (not clean_details(old.get('details')) or normalized(old.get('details')) == normalized(new.get('details'))))
    return [old for old in consolidate(history) if not any(overlaps(old, new) for new in current)]


def make_drafts(raw_facts, origin, question=''):
    drafts = []
    for raw in raw_facts or []:
        if not isinstance(raw, dict) or not raw.get('display'): continue
        attrs = raw.get('attributes') or {}
        display = str(raw['display'])[:160]
        source_text = raw.get('source_text') or ''
        if origin == 'current_message':
            # An old/invented entity cannot enter the "just declared" step.
            if not re.search(r'(?<!\w)'+re.escape(normalized(display))+r'(?!\w)', normalized(question)):
                continue
            local = source_text if source_text and normalized(source_text) in normalized(question) else question
            if normalized(display) == 'ho':
                if len(re.findall(r'(?<!\w)ho(?!\w)', question, flags=re.I)) == 1:
                    local = question
                matches = re.findall(r'(?<!\w)ho\s+(?:khan|có\s+đờm|ra\s+máu)(?!\w)', local, flags=re.I)
                if len(matches) == 1: display = matches[0]
        timeframe = attrs.get('timeframe')
        if timeframe not in {'current','history'}:
            timeframe = 'history' if raw.get('status') in {'historical','history'} else 'current'
        details = [clean_details(attrs.get('details'))]
        for key, label in [('value','giá trị'),('unit','đơn vị'),('dose','liều'),('frequency','tần suất'),('valid_from','từ'),('valid_to','đến')]:
            if raw.get(key) is not None: details.append(f'{label}: {raw[key]}')
        original = {k: copy.deepcopy(raw[k]) for k in ('display','fact_type','concept_id','negated','experiencer','status','source_message_id','source_text','recorded_at') if k in raw}
        original['attributes'] = {'details':clean_details(attrs.get('details')), 'timeframe':timeframe}
        draft = {'id':str(uuid4()), 'display':display,'canonical_display':str(attrs.get('canonical_display') or raw['display']),
                 'fact_type':str(raw.get('fact_type','symptom')),
                 'presence':'absent' if raw.get('negated') else 'present',
                 'timeframe':timeframe,'details':clean_details('; '.join(details)),
                 'experiencer':'patient' if raw.get('experiencer','patient') == 'patient' else 'family',
                 'origin':origin,'source_id':raw.get('source_message_id'), 'source_text':source_text,
                 'recorded_at':raw.get('recorded_at'),'original_fact':original,
                 'timeframe_needs_review': origin == 'patient_graph' and attrs.get('timeframe') not in {'current','history'}}
        drafts.append(draft)
    return consolidate(drafts)[:30]


def migrate_pending(state):
    """Split only unconfirmed legacy drafts. Never alter a frozen confirmed snapshot."""
    if state.get('workflow_version') == 2 or state.get('status') != 'confirming': return False
    current, history = [], []
    for f in state.get('drafts', []):
        raw = copy.deepcopy(f.get('original_fact') or {**f, 'negated':f.get('presence') == 'absent', 'attributes':{'details':f.get('details',''), 'timeframe':f.get('timeframe')}})
        if raw:
            target = history if f.get('origin') == 'patient_graph' else current
            target.extend(make_drafts([raw],f.get('origin','current_message'),state.get('question','')))
    state['drafts'] = consolidate(current)
    state['history_drafts'] = consolidate(history)
    state['workflow_version'] = 2
    return True
