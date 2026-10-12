from __future__ import annotations

import hashlib
import json

from neo4j import AsyncDriver
from neo4j.exceptions import Neo4jError

from app.modules.context.application.text import token_set
from app.modules.context.domain.models import HistoryMention, HistoryTurn, Role
from app.modules.context.infrastructure.embedding import EmbeddingService, HashEmbeddingService


class Neo4jHistoryRepository:
    VECTOR_INDEX = "history_turn_embedding"

    def __init__(
        self,
        driver: AsyncDriver,
        database: str = "neo4j",
        embedding_service: EmbeddingService | None = None,
    ) -> None:
        self.driver = driver
        self.database = database
        self.embedding_service = embedding_service or HashEmbeddingService()

    async def initialize(self) -> None:
        statements = [
            "CREATE CONSTRAINT context_import_key_unique IF NOT EXISTS FOR (i:ContextImport) REQUIRE i.key IS UNIQUE",
            "CREATE CONSTRAINT session_key_unique IF NOT EXISTS FOR (s:Session) REQUIRE s.key IS UNIQUE",
            "CREATE CONSTRAINT turn_id_unique IF NOT EXISTS FOR (t:Turn) REQUIRE t.id IS UNIQUE",
            "CREATE CONSTRAINT mention_id_unique IF NOT EXISTS FOR (m:Mention) REQUIRE m.id IS UNIQUE",
            "CREATE CONSTRAINT discourse_entity_id_unique IF NOT EXISTS FOR (e:DiscourseEntity) REQUIRE e.id IS UNIQUE",
            f"""
            CREATE VECTOR INDEX {self.VECTOR_INDEX} IF NOT EXISTS
            FOR (t:Turn) ON t.embedding
            OPTIONS {{indexConfig: {{
                `vector.dimensions`: {self.embedding_service.dimensions},
                `vector.similarity_function`: 'cosine'
            }}}}
            """,
        ]
        async with self.driver.session(database=self.database) as session:
            for statement in statements:
                await (await session.run(statement)).consume()

    async def close(self) -> None:
        return None

    async def add_turn(self, turn: HistoryTurn) -> None:
        session_key = f"{turn.patient_id}:{turn.session_id}"
        embedding = await self.embedding_service.embed(turn.normalized_text or turn.original_text)
        query = """
        MERGE (s:Session {key: $session_key})
        ON CREATE SET s.id = $session_id, s.patient_id = $patient_id, s.created_at = $created_at
        SET s.updated_at = $created_at

        MERGE (t:Turn {id: $message_id})
        SET t.patient_id = $patient_id,
            t.session_id = $session_id,
            t.role = $role,
            t.original_text = $original_text,
            t.normalized_text = $normalized_text,
            t.created_at = $created_at,
            t.metadata_json = $metadata_json,
            t.embedding = $embedding
        MERGE (s)-[:HAS_TURN]->(t)

        WITH s, t
        OPTIONAL MATCH (s)-[:HAS_TURN]->(prev:Turn)
        WHERE prev.id <> t.id AND prev.created_at < t.created_at
        WITH t, prev ORDER BY prev.created_at DESC
        WITH t, head(collect(prev)) AS previous
        FOREACH (_ IN CASE WHEN previous IS NULL THEN [] ELSE [1] END |
            MERGE (previous)-[:NEXT]->(t)
        )
        """
        params = {
            "session_key": session_key,
            "session_id": turn.session_id,
            "patient_id": turn.patient_id,
            "message_id": turn.message_id,
            "role": turn.role.value,
            "original_text": turn.original_text,
            "normalized_text": turn.normalized_text,
            "created_at": turn.created_at.isoformat(),
            "metadata_json": json.dumps(turn.metadata, ensure_ascii=False, default=str),
            "embedding": embedding,
        }
        async with self.driver.session(database=self.database) as session:
            await (await session.run(query, **params)).consume()
            for index, mention in enumerate(turn.mentions):
                entity_id = mention.entity_id or self._entity_id(
                    turn.patient_id, turn.session_id, mention.entity_type, mention.canonical_name
                )
                mention_id = f"{turn.message_id}:{index}"
                mention_query = """
                MATCH (t:Turn {id: $message_id})
                MERGE (m:Mention {id: $mention_id})
                SET m.text = $text,
                    m.entity_type = $entity_type,
                    m.canonical_name = $canonical_name,
                    m.start = $start,
                    m.end = $end,
                    m.confidence = $confidence,
                    m.origin = $origin
                MERGE (t)-[:MENTIONS]->(m)
                MERGE (e:DiscourseEntity {id: $entity_id})
                ON CREATE SET e.patient_id = $patient_id,
                              e.session_id = $session_id,
                              e.type = $entity_type,
                              e.canonical_name = $canonical_name
                SET e.last_seen_at = $created_at
                MERGE (m)-[:REFERS_TO]->(e)
                """
                await (
                    await session.run(
                        mention_query,
                        message_id=turn.message_id,
                        mention_id=mention_id,
                        text=mention.text,
                        entity_type=mention.entity_type,
                        canonical_name=mention.canonical_name,
                        start=mention.start,
                        end=mention.end,
                        confidence=mention.confidence,
                        origin=mention.origin,
                        entity_id=entity_id,
                        patient_id=turn.patient_id,
                        session_id=turn.session_id,
                        created_at=turn.created_at.isoformat(),
                    )
                ).consume()

    async def get_relevant_turns(
        self,
        *,
        patient_id: str,
        session_id: str,
        query: str,
        limit: int,
    ) -> list[HistoryTurn]:
        session_key = f"{patient_id}:{session_id}"
        query_embedding = await self.embedding_service.embed(query)
        vector_scores: dict[str, float] = {}
        candidate_ids: set[str] = set()

        # Neo4j 5-compatible vector procedure. If the index is still populating or unavailable,
        # retrieval safely falls back to recent graph candidates.
        vector_cypher = """
        CALL db.index.vector.queryNodes($index_name, $candidate_limit, $embedding)
        YIELD node, score
        WHERE node.patient_id = $patient_id AND node.session_id = $session_id
        RETURN node.id AS id, score
        LIMIT $candidate_limit
        """
        recent_cypher = """
        MATCH (s:Session {key: $session_key})-[:HAS_TURN]->(t:Turn)
        RETURN t.id AS id
        ORDER BY t.created_at DESC
        LIMIT $candidate_limit
        """
        candidate_limit = max(limit * 4, 24)
        async with self.driver.session(database=self.database) as session:
            try:
                result = await session.run(
                    vector_cypher,
                    index_name=self.VECTOR_INDEX,
                    candidate_limit=candidate_limit,
                    embedding=query_embedding,
                    patient_id=patient_id,
                    session_id=session_id,
                )
                for row in await result.data():
                    candidate_ids.add(row["id"])
                    vector_scores[row["id"]] = float(row["score"])
            except Neo4jError:
                pass

            recent_result = await session.run(
                recent_cypher,
                session_key=session_key,
                candidate_limit=candidate_limit,
            )
            for row in await recent_result.data():
                candidate_ids.add(row["id"])

            if not candidate_ids:
                return []

            detail_cypher = """
            MATCH (t:Turn)
            WHERE t.id IN $ids
              AND t.patient_id = $patient_id
              AND t.session_id = $session_id
            OPTIONAL MATCH (t)-[:MENTIONS]->(m:Mention)-[:REFERS_TO]->(e:DiscourseEntity)
            WITH t, collect({
                text: m.text,
                entity_type: e.type,
                canonical_name: e.canonical_name,
                entity_id: e.id,
                start: m.start,
                end: m.end,
                confidence: m.confidence,
                origin: coalesce(m.origin, 'legacy_inferred')
            }) AS mentions
            RETURN t, mentions
            ORDER BY t.created_at ASC
            """
            details = await session.run(
                detail_cypher,
                ids=list(candidate_ids),
                patient_id=patient_id,
                session_id=session_id,
            )
            rows = await details.data()

        parsed: list[tuple[HistoryTurn, float]] = []
        q_tokens = token_set(query)
        total = max(1, len(rows))
        for rank, row in enumerate(rows):
            node = dict(row["t"])
            mentions: list[HistoryMention] = []
            for raw in row.get("mentions", []):
                if raw.get("canonical_name"):
                    mentions.append(HistoryMention(**raw))
            turn = HistoryTurn(
                patient_id=node["patient_id"],
                session_id=node["session_id"],
                message_id=node["id"],
                role=Role(node["role"]),
                original_text=node["original_text"],
                normalized_text=node.get("normalized_text"),
                created_at=node["created_at"],
                mentions=mentions,
                metadata=json.loads(node.get("metadata_json") or "{}"),
            )
            text_tokens = token_set(turn.normalized_text or turn.original_text)
            lexical = len(q_tokens & text_tokens) / max(1, len(q_tokens | text_tokens))
            entity_continuity = 0.0
            for mention in mentions:
                mention_tokens = token_set(mention.canonical_name)
                if mention.canonical_name.casefold() in query.casefold():
                    entity_continuity = max(entity_continuity, 1.0)
                elif q_tokens & mention_tokens:
                    entity_continuity = max(entity_continuity, 0.65)
            recency = (rank + 1) / total
            vector = vector_scores.get(turn.message_id, 0.0)
            score = 0.45 * vector + 0.20 * lexical + 0.20 * entity_continuity + 0.15 * recency
            parsed.append((turn, score))

        selected = sorted(parsed, key=lambda item: item[1], reverse=True)[:limit]
        selected.sort(key=lambda item: item[0].created_at)
        return [turn for turn, _ in selected]

    async def get_recent_turns(
        self,
        *,
        patient_id: str,
        session_id: str,
        limit: int,
    ) -> list[HistoryTurn]:
        if limit <= 0:
            return []
        session_key = f"{patient_id}:{session_id}"
        cypher = """
        MATCH (s:Session {key: $session_key})-[:HAS_TURN]->(t:Turn)
        OPTIONAL MATCH (t)-[:MENTIONS]->(m:Mention)-[:REFERS_TO]->(e:DiscourseEntity)
        WITH t, collect({
            text: m.text,
            entity_type: e.type,
            canonical_name: e.canonical_name,
            entity_id: e.id,
            start: m.start,
            end: m.end,
            confidence: m.confidence,
            origin: coalesce(m.origin, 'legacy_inferred')
        }) AS mentions
        ORDER BY t.created_at DESC
        LIMIT $limit
        RETURN t, mentions
        ORDER BY t.created_at ASC
        """
        async with self.driver.session(database=self.database) as session:
            result = await session.run(cypher, session_key=session_key, limit=limit)
            rows = await result.data()

        turns: list[HistoryTurn] = []
        for row in rows:
            node = dict(row["t"])
            mentions = [
                HistoryMention(**raw)
                for raw in row.get("mentions", [])
                if raw.get("canonical_name")
            ]
            turns.append(
                HistoryTurn(
                    patient_id=node["patient_id"],
                    session_id=node["session_id"],
                    message_id=node["id"],
                    role=Role(node["role"]),
                    original_text=node["original_text"],
                    normalized_text=node.get("normalized_text"),
                    created_at=node["created_at"],
                    mentions=mentions,
                    metadata=json.loads(node.get("metadata_json") or "{}"),
                )
            )
        return turns

    @staticmethod
    def _entity_id(patient_id: str, session_id: str, entity_type: str, canonical_name: str) -> str:
        raw = f"{patient_id}|{session_id}|{entity_type.casefold()}|{canonical_name.casefold()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
