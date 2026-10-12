"""Regression: a re-review must not reuse stale Neo4j targets."""
import asyncio
from copy import deepcopy

from app.bulk_import.kg import KGAdapter


class FakeService:
    def __init__(self):
        self.received = []

    def preview_kg(self, payload, refresh=False):
        self.received.append(deepcopy(payload))
        assert 'entity_link_decisions' not in payload
        assert 'entity_type_decisions' not in payload
        class Result:
            status = 'dry_run'
            document_id = 'DOC_X'
            plan = {'entity_candidates': {
                'INCOMING': [{'entity_id': 'EXISTING', 'link_allowed': True}]
            }}
            errors = []
        return Result()


def test_re_review_replaces_stale_decisions():
    service = FakeService()
    adapter = KGAdapter(lambda: service)
    raw = {
        'document': {'document_id': 'DOC_X'},
        'entities': [{'id': 'INCOMING', 'canonical_name': 'Example'}],
        'entity_link_decisions': {'INCOMING': 'DELETED', 'OTHER': 'STALE'},
        'entity_type_decisions': {'OTHER': 'distinct'},
    }
    out = asyncio.run(adapter.decisions(raw, {'INCOMING': 'EXISTING'}))
    assert out['entity_link_decisions'] == {'INCOMING': 'EXISTING'}
    assert 'entity_type_decisions' not in out
    assert raw['entity_link_decisions']['OTHER'] == 'STALE'
    assert len(service.received) == 1


def test_re_review_rejects_missing_candidate():
    service = FakeService()
    adapter = KGAdapter(lambda: service)
    raw = {'entities': [{'id': 'INCOMING', 'canonical_name': 'Example'}],
           'entity_link_decisions': {'INCOMING': 'DELETED'}}
    try:
        asyncio.run(adapter.decisions(raw, {'INCOMING': 'DELETED'}))
    except ValueError as exc:
        assert 'không nằm trong' in str(exc)
    else:
        raise AssertionError('stale candidate was accepted')
