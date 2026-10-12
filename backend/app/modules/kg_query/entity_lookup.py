"""Read-only entity dictionary with a short TTL and explicit fuzzy confirmation.

Aliases must come from KG. No hand-written medical synonym merge is performed.
Accent-insensitive input is accepted only when the user omitted accents and the
dictionary match is unique. Fuzzy candidates are never used as query anchors.
"""
from __future__ import annotations

from collections import defaultdict
from difflib import get_close_matches
import threading
import time

from .models import Anchor, EntityRef
from .question_analysis import text_key

CATALOG_QUERY = '''
MATCH (e:Entity)
RETURN e.id AS id, e.canonical_name AS name, e.entity_type AS type,
       coalesce(e.aliases, []) AS aliases
ORDER BY e.id LIMIT $limit
'''
IDS_QUERY = '''
MATCH (e:Entity) WHERE e.id IN $ids
RETURN e.id AS id, e.canonical_name AS name, e.entity_type AS type
ORDER BY e.id
'''
_LOCK = threading.Lock()
GENERIC = {text_key(name, accents=False) for name in ('bệnh', 'thuốc', 'triệu chứng', 'điều trị', 'dấu hiệu', 'bệnh nhân')}


def candidate(row, matched_by):
    return {k: row[k] for k in ('id', 'name', 'type')} | {'matched_by': matched_by}


class EntityLookup:
    def __init__(self, service, *, ttl=30.0, max_entities=20000):
        self.service, self.ttl, self.max_entities = service, ttl, max_entities
        self.lock = threading.Lock()
        self.expiry = 0.0
        self.exact, self.plain = {}, {}
        self.fuzzy = {}
        self.truncated = False

    def refresh(self):
        with self.lock:
            if time.monotonic() < self.expiry:
                return
            rows = self.service._read(CATALOG_QUERY, limit=self.max_entities + 1)
            exact, plain = defaultdict(dict), defaultdict(dict)
            self.truncated = len(rows) > self.max_entities
            for row in rows[:self.max_entities]:
                names = [(row['name'], 'exact_name')] + [(n, 'alias') for n in row.get('aliases', [])]
                for name, kind in names:
                    if not isinstance(name, str) or not name.strip() or len(name) > 160:
                        continue
                    key = text_key(name)
                    # Preserve exact-name precedence for the same node.
                    exact[key].setdefault(row['id'], candidate(row, kind))
                    plain[text_key(name, accents=False)].setdefault(row['id'], candidate(row, 'accent_insensitive'))
            self.exact = {k: list(v.values()) for k, v in exact.items()}
            self.plain = {k: list(v.values()) for k, v in plain.items()}
            fuzzy = defaultdict(list)
            for name in self.plain:
                tokens = name.split()
                if len(name) >= 5 and len(tokens) <= 12:
                    fuzzy[(len(tokens), tokens[0][:2])].append(name)
            self.fuzzy = dict(fuzzy)
            self.expiry = time.monotonic() + self.ttl

    def matches(self, name):
        key = text_key(name)
        if key in self.exact:
            return self.exact[key]
        # Accents deliberately supplied by the user must not be discarded.
        if key == text_key(name, accents=False):
            return self.plain.get(key, [])
        return []

    def suggestions(self, text):
        words = text_key(text, accents=False).split()[:160]
        # Fuzzy matching is only a proposal. Restrict phrase count and token lengths.
        options = {}
        lengths = sorted({length for length, _ in self.fuzzy})
        for length in lengths:
            for start in range(min(len(words) - length + 1, 80)):
                phrase = ' '.join(words[start:start + length])
                if len(phrase) < 5:
                    continue
                pool = self.fuzzy.get((length, words[start][:2]), [])[:200]
                for near in get_close_matches(phrase, pool, n=2, cutoff=0.86):
                    for row in self.plain[near]:
                        options.setdefault(row['id'], {**row, 'matched_by': 'fuzzy'})
                        if len(options) >= 5:
                            return list(options.values())
        return list(options.values())

    def named(self, mentions):
        self.refresh()
        return [{'mention': name, 'candidates': self.matches(name) or self.suggestions(name)} for name in mentions]

    def detect(self, question):
        self.refresh()
        words = text_key(question).split()
        spans = []
        for start in range(len(words)):
            for end in range(min(len(words), start + 20), start, -1):
                name = ' '.join(words[start:end])
                if text_key(name, accents=False) in GENERIC:
                    continue
                matches = self.matches(name)
                if matches:
                    spans.append((start, end, name, matches))
                    break
        chosen = []
        for start, end, name, rows in sorted(spans, key=lambda x: (-(x[1]-x[0]), x[0])):
            if any(start < other[1] and end > other[0] for other in chosen):
                continue
            chosen.append((start, end, name, rows))
        groups, seen = [], set()
        for _, _, name, rows in sorted(chosen):
            key = tuple(sorted(r['id'] for r in rows))
            if key not in seen:
                groups.append({'mention': name, 'candidates': rows})
                seen.add(key)
        return groups

    def confirmed(self, ids):
        rows = {row['id']: row for row in self.service._read(IDS_QUERY, ids=ids)}
        if set(ids) != set(rows):
            return [], 'Thực thể đã chọn không còn trong KG. Vui lòng hỏi lại để cập nhật danh sách.'
        # Distinct IDs can have identical display names; never collapse endpoints
        # by using that shared display name as the anchors dictionary key.
        names = [rows[i]['name'] for i in ids]
        return [{'mention': rows[i]['name'] if names.count(rows[i]['name']) == 1 else f"{rows[i]['name']} [{i}]",
                 'candidates': [candidate(rows[i], 'user_confirmed')]} for i in ids], None


def get_lookup(service):
    with _LOCK:
        lookup = service.__dict__.get('_question_entity_lookup')
        if lookup is None:
            lookup = EntityLookup(service)
            service._question_entity_lookup = lookup
        return lookup


def resolved_anchors(groups):
    return {g['mention']: [Anchor(EntityRef(r['id'], r['name'], r['type']), r['matched_by'])
                            for r in g['candidates']]
            for g in groups if len(g['candidates']) == 1 and g['candidates'][0]['matched_by'] != 'fuzzy'}
