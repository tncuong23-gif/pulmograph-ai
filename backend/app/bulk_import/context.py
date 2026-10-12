"""Reviewed Context JSON imports. Real Neo4j writes share ONE transaction.

The existing repositories are bound to that transaction, with embeddings prepared
before entering it. A malformed record or failed write cannot leave half a file.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.context.domain.models import ClinicalFact, HistoryTurn
from app.modules.context.infrastructure.neo4j.patient_repository import Neo4jPatientRepository
from app.modules.rag.batch import now


class ImportTurn(HistoryTurn):
    model_config = ConfigDict(extra='forbid')


class ImportFact(ClinicalFact):
    model_config = ConfigDict(extra='forbid')


class ContextFile(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal['1.0']
    patient_id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$')
    session_id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$')
    history: list[ImportTurn] = Field(min_length=1, max_length=2000)
    facts: list[ImportFact] = Field(default_factory=list, max_length=1000)

    @model_validator(mode='after')
    def check_sources(self):
        turns = {}
        for turn in self.history:
            if turn.patient_id != self.patient_id or turn.session_id != self.session_id:
                raise ValueError('Mỗi file chỉ chứa một patient_id/session_id; lịch sử phải khớp hai ID này.')
            if not turn.message_id.strip() or len(turn.message_id) > 128 or turn.message_id in turns:
                raise ValueError('message_id trống, quá dài hoặc trùng trong file.')
            if not turn.original_text.strip() or len(turn.original_text) > 20000:
                raise ValueError('Mỗi lượt hội thoại cần nội dung từ 1 đến 20.000 ký tự.')
            if turn.role.value not in {'user', 'assistant'}:
                raise ValueError('Lịch sử nhập chỉ nhận vai trò user hoặc assistant.')
            if turn.created_at.tzinfo is None:
                raise ValueError('Thời gian lịch sử cần múi giờ, ví dụ +07:00 hoặc Z.')
            turns[turn.message_id] = turn
        facts = set()
        for fact in self.facts:
            turn = turns.get(fact.source_message_id)
            if turn is None or turn.role.value != 'user':
                raise ValueError('Nguồn của dữ kiện phải là một lượt user có trong history của file.')
            if fact.statement_type.value != 'fact' or fact.assertion.value == 'inferred':
                raise ValueError('Không nạp câu hỏi, giả định hoặc dữ kiện suy diễn vào Patient Graph.')
            if not fact.source_text or fact.source_text not in turn.original_text:
                raise ValueError('source_text của dữ kiện phải trích đúng từ lượt user nguồn.')
            if fact.recorded_at.tzinfo is None or any(d and d.tzinfo is None for d in (fact.valid_from, fact.valid_to)):
                raise ValueError('Thời gian dữ kiện cần múi giờ.')
            if fact.valid_from and fact.valid_to and fact.valid_from > fact.valid_to:
                raise ValueError('valid_from phải trước hoặc bằng valid_to.')
            identity = Neo4jPatientRepository._statement_id(self.patient_id, fact)
            if identity in facts:
                raise ValueError('Có dữ kiện trùng định danh trong file; giữ một bản đã kiểm tra.')
            facts.add(identity)
        return self


class CachedEmbedding:
    def __init__(self, original, values):
        self.dimensions, self.values = original.dimensions, values

    async def embed(self, text):
        return self.values[text]


class BoundSession:
    def __init__(self, tx):
        self.tx = tx

    async def __aenter__(self):
        return self.tx

    async def __aexit__(self, *args):
        return False


class BoundDriver:
    def __init__(self, tx):
        self.tx = tx

    def session(self, **kwargs):
        return BoundSession(self.tx)


class ContextAdapter:
    def __init__(self, get_container):
        self.get_container = get_container

    def identity(self, raw):
        data = ContextFile.model_validate(raw)
        return f'{data.patient_id}:{data.session_id}'

    async def _existing(self, data, runner=None):
        container = self.get_container()
        ids = [t.message_id for t in data.history]
        if container.driver is None:
            return {t.message_id: t.model_dump(mode='json') for values in container.history_repository._turns.values()
                    for t in values if t.message_id in ids}
        async def read(tx):
            found = {}
            for offset in range(0, len(ids), 500):
                result = await tx.run('UNWIND $ids AS id MATCH (t:Turn {id: id}) RETURN t', ids=ids[offset:offset+500])
                for row in await result.data():
                    value = dict(row['t'])
                    found[value['id']] = value
            return found
        if runner is not None:
            return await read(runner)
        async with container.driver.session(database=container.settings.neo4j_database) as session:
            return await session.execute_read(read)

    @staticmethod
    def _check_existing(data, existing):
        for turn in data.history:
            old = existing.get(turn.message_id)
            if old and any(old.get(key) != getattr(turn, key) for key in
                           ('patient_id', 'session_id', 'original_text', 'role')):
                raise ValueError(f'message_id {turn.message_id} đã thuộc bệnh nhân/phiên hoặc nội dung khác. Không ghi đè.')

    async def review(self, raw):
        data = ContextFile.model_validate(raw)
        existing = await self._existing(data)
        self._check_existing(data, existing)
        return {'module': 'context', 'patient_id': data.patient_id, 'session_id': data.session_id,
                'history': [t.model_dump(mode='json') for t in data.history],
                'facts': [f.model_dump(mode='json') for f in data.facts],
                'statistics': {'history': len(data.history), 'existing_history': len(existing), 'facts': len(data.facts)},
                'storage': self.get_container().settings.graph_backend}

    async def process(self, raw, *, mode, job_id, sha, retry_import_id=None):
        data = ContextFile.model_validate(raw)
        if mode == 'validate':
            return {'status': 'completed', 'stage': 'validation',
                    'statistics': {'history': len(data.history), 'facts': len(data.facts)}}
        if mode == 'preview':
            review = await self.review(raw)
            return {'status': 'completed', 'statistics': review['statistics'], 'storage': review['storage']}
        return await self._commit(data, job_id, sha)

    async def _commit(self, data, job_id, sha):
        container = self.get_container()
        history, patient = container.history_repository, container.patient_repository
        stamp = now()
        turns = [t.model_copy(deep=True) for t in sorted(data.history, key=lambda t: t.created_at)]
        facts = [f.model_copy(deep=True) for f in data.facts]
        for turn in turns:
            turn.metadata.update(batch_import_job=job_id, batch_import_confirmed_at=stamp)
            # Discourse identities remain scoped to this patient/session.
            for mention in turn.mentions:
                mention.entity_id = None
        for fact in facts:
            fact.attributes.update(confirmation_status='user_confirmed', confirmed_at=stamp,
                                   confirmation_source='batch_import', import_job_id=job_id)
        self._check_existing(data, await self._existing(data))
        hv, pv = {}, {}
        for turn in turns:
            text = turn.normalized_text or turn.original_text
            if text not in hv:
                hv[text] = await history.embedding_service.embed(text)
        for fact in facts:
            text = patient._embedding_text(fact)
            if text not in pv:
                pv[text] = await patient.embedding_service.embed(text)
        hcache, pcache = CachedEmbedding(history.embedding_service, hv), CachedEmbedding(patient.embedding_service, pv)
        stats = {'history': len(turns), 'facts': len(facts)}
        if container.driver is None:
            # Work on independent copies; publish only after the entire file succeeds.
            from app.modules.context.infrastructure.memory import InMemoryHistoryRepository, InMemoryPatientRepository
            markers = getattr(container, '_batch_import_hashes', set())
            if sha in markers:
                return {'status': 'skipped', 'statistics': stats, 'storage': 'memory'}
            new_history, new_patient = InMemoryHistoryRepository(hcache), InMemoryPatientRepository(pcache)
            new_history._turns, new_history._vectors = deepcopy(history._turns), deepcopy(history._vectors)
            new_patient._facts, new_patient._vectors = deepcopy(patient._facts), deepcopy(patient._vectors)
            existing = await self._existing(data)
            self._check_existing(data, existing)
            for turn in turns:
                if turn.message_id not in existing:
                    await new_history.add_turn(turn)
            # Memory mode mirrors Neo4j upsert for an explicitly reconfirmed fact.
            identities = {new_patient._identity(f) for f in facts}
            new_patient._facts[data.patient_id] = [f for f in new_patient._facts[data.patient_id]
                                                  if new_patient._identity(f) not in identities]
            await new_patient.upsert_facts(patient_id=data.patient_id, facts=facts)
            history._turns, history._vectors = new_history._turns, new_history._vectors
            patient._facts, patient._vectors = new_patient._facts, new_patient._vectors
            container._batch_import_hashes = markers | {sha}
            return {'status': 'completed', 'statistics': stats, 'storage': 'memory'}
        from app.modules.context.infrastructure.neo4j.history_repository import Neo4jHistoryRepository
        async def write(tx):
            marker = await (await tx.run('MATCH (i:ContextImport {key:$key}) RETURN i.key AS key', key=sha)).single()
            if marker:
                return {'status': 'skipped', 'statistics': stats, 'storage': 'neo4j'}
            existing = await self._existing(data, tx)
            self._check_existing(data, existing)
            bound = BoundDriver(tx)
            hrepo = Neo4jHistoryRepository(bound, container.settings.neo4j_database, hcache)
            prepo = Neo4jPatientRepository(bound, container.settings.neo4j_database, pcache)
            for turn in turns:
                if turn.message_id not in existing:
                    await hrepo.add_turn(turn)
            await prepo.upsert_facts(patient_id=data.patient_id, facts=facts)
            await (await tx.run('''MERGE (i:ContextImport {key:$key})
                SET i.patient_id=$patient, i.session_id=$session, i.job_id=$job, i.confirmed_at=$stamp''',
                key=sha, patient=data.patient_id, session=data.session_id, job=job_id, stamp=stamp)).consume()
            return {'status': 'completed', 'statistics': stats, 'storage': 'neo4j'}
        async with container.driver.session(database=container.settings.neo4j_database) as session:
            return await session.execute_write(write)
