from __future__ import annotations

import asyncio
import time
from copy import deepcopy

from app.modules.kg_import.models import parse_import
from app.modules.kg_import.service import IMPORT_LOCK


class KGAdapter:
    def __init__(self, get_service):
        self.get_service = get_service

    def identity(self, raw):
        kg, issues = parse_import(raw)
        if kg is None:
            raise ValueError('; '.join(f'{i.code}: {i.message}' for i in issues))
        return kg.document.document_id

    async def process(self, raw, *, mode, job_id, sha, retry_import_id=None):
        def run():
            started = time.perf_counter()
            service = self.get_service()
            if mode == 'validate':
                issues = service.validate_payload(raw)
                return {'status': 'failed' if issues else 'completed', 'stage': 'validation',
                        'error': '; '.join(f'{i.code}: {i.message}' for i in issues)}
            if mode == 'retry' and retry_import_id:
                previous = service.get_status(retry_import_id)
                if previous['status'] in {'partial', 'failed'} and previous.get('stage') in {'mongodb', 'neo4j', 'finalize', 'vector'}:
                    result = service.retry(retry_import_id, raw)
                else:
                    result = service.import_kg(raw, 'upsert')
            else:
                result = service.preview_kg(raw) if mode == 'preview' else service.import_kg(raw, 'upsert')
            candidates = (result.plan or {}).get('entity_candidates', {})
            status = ('needs_review' if candidates else 'completed') if result.status == 'dry_run' else result.status
            out = {'status': status, 'stage': result.stage, 'import_id': result.import_id,
                   'statistics': result.statistics, 'retryable': result.retryable,
                   'error': '; '.join(f"{e['code']}: {e['message']}" for e in result.errors)}
            out['elapsed_seconds'] = round(time.perf_counter() - started, 3)
            if service.entity_index is None:
                out['warning'] = 'Chỉ mục vector KG đang tắt; lượt này chỉ xử lý MongoDB và Neo4j. Bật KG_ENTITY_EMBEDDING_ENABLED=1 để đồng bộ Qdrant.'
            if result.plan:
                out['statistics'] = {k: result.plan[k] for k in ['entities', 'relations', 'document_exists'] if k in result.plan}
                out['candidate_count'] = len(candidates)
            return out
        return await asyncio.to_thread(run)

    def review_profile(self):
        return self.get_service().review_profile()

    async def review(self, raw, *, refresh=False):
        # Refresh suggestions against the *current* Neo4j state. Existing review choices
        # can refer to targets that have since been deleted or not yet committed;
        # feeding them into preview blocks the user from repairing the decision.
        clean = deepcopy(raw)
        clean.pop('entity_link_decisions', None)
        clean.pop('entity_type_decisions', None)
        result = await asyncio.to_thread(lambda: self.get_service().preview_kg(clean, refresh=refresh))
        if result.status != 'dry_run':
            raise ValueError('; '.join(f"{e['code']}: {e['message']}" for e in result.errors))
        return {'module': 'kg', 'document_id': result.document_id, 'plan': result.plan,
                'entities': [{'id': e['id'], 'canonical_name': e['canonical_name']} for e in raw.get('entities', [])]}

    async def decisions(self, raw, choices):
        preview = await self.review(raw)
        candidates = preview['plan'].get('entity_candidates', {})
        if not isinstance(choices, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in choices.items()):
            raise ValueError('Lựa chọn phải là bảng ID thực thể.')
        if set(candidates) - set(choices):
            raise ValueError('Chọn cách xử lý cho tất cả thực thể cần duyệt trong tài liệu.')
        for eid, choice in choices.items():
            if eid not in candidates or choice not in {'new', *(c['entity_id'] for c in candidates[eid] if c.get('link_allowed', True))}:
                raise ValueError('Lựa chọn không nằm trong các ứng viên đã xem trước.')
        out = deepcopy(raw)
        # A new review replaces ALL prior selections. Merging with old selections
        # can retain deleted Neo4j IDs and trigger ENTITY_LINK_DECISION_INVALID.
        out.pop('entity_type_decisions', None)
        out['entity_link_decisions'] = dict(choices)
        for eid, choice in choices.items():
            if choice == 'new' and any(c.get('link_allowed') is False for c in candidates[eid]):
                out.setdefault('entity_type_decisions', {})[eid] = 'distinct'
        return out

    async def bootstrap(self):
        def run():
            with IMPORT_LOCK:
                service = self.get_service()
                if service.entity_index is None:
                    raise ValueError('Chỉ mục thực thể chưa bật. Kiểm tra KG_ENTITY_EMBEDDING_ENABLED trong .env.')
                service.invalidate_previews()
                getattr(service.entity_index, 'begin_build', service.entity_index.ensure_collection)()
                after, count = '', 0
                while True:
                    rows = service.graph.list_entities(after, 500)
                    if not rows:
                        break
                    count += service.entity_index.upsert_entities(rows)
                    after = rows[-1]['id']
                finish = getattr(service.entity_index, 'finish_build', None)
                if finish: finish()
                return {'status': 'completed', 'statistics': {'entity_names_indexed': count}}
        return await asyncio.to_thread(run)
