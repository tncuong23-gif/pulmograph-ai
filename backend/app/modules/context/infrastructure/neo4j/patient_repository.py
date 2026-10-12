from __future__ import annotations

import hashlib
import json
from typing import Any

from neo4j import AsyncDriver
from neo4j.exceptions import Neo4jError

from app.modules.context.application.text import token_set
from app.modules.context.domain.models import ClinicalFact, PatientContext
from app.modules.context.infrastructure.embedding import EmbeddingService, HashEmbeddingService


class Neo4jPatientRepository:
    VECTOR_INDEX = "clinical_statement_embedding"

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
            "CREATE CONSTRAINT patient_id_unique IF NOT EXISTS FOR (p:Patient) REQUIRE p.id IS UNIQUE",
            "CREATE CONSTRAINT clinical_concept_key_unique IF NOT EXISTS FOR (c:ClinicalConcept) REQUIRE c.key IS UNIQUE",
            "CREATE CONSTRAINT clinical_statement_id_unique IF NOT EXISTS FOR (s:ClinicalStatement) REQUIRE s.id IS UNIQUE",
            f"""
            CREATE VECTOR INDEX {self.VECTOR_INDEX} IF NOT EXISTS
            FOR (s:ClinicalStatement) ON s.embedding
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

    async def upsert_facts(self, *, patient_id: str, facts: list[ClinicalFact]) -> int:
        if not facts:
            return 0
        count = 0
        async with self.driver.session(database=self.database) as session:
            for fact in facts:
                statement_id = self._statement_id(patient_id, fact)
                concept_key = self._concept_key(fact)
                embedding = await self.embedding_service.embed(self._embedding_text(fact))
                cypher = """
                MERGE (p:Patient {id: $patient_id})
                MERGE (c:ClinicalConcept {key: $concept_key})
                ON CREATE SET c.type = $fact_type,
                              c.display = $concept_display,
                              c.concept_id = $concept_id,
                              c.concept_system = $concept_system
                SET c.display = CASE WHEN $concept_id IS NOT NULL THEN $concept_display ELSE c.display END,
                    c.concept_id = coalesce($concept_id, c.concept_id),
                    c.concept_system = coalesce($concept_system, c.concept_system)

                MERGE (st:ClinicalStatement {id: $statement_id})
                ON CREATE SET st.created_at = $recorded_at
                SET st.fact_type = $fact_type,
                    st.display = $display,
                    st.value_json = $value_json,
                    st.unit = $unit,
                    st.dose = $dose,
                    st.frequency = $frequency,
                    st.route = $route,
                    st.status = $status,
                    st.negated = $negated,
                    st.certainty = $certainty,
                    st.experiencer = $experiencer,
                    st.valid_from = $valid_from,
                    st.valid_to = $valid_to,
                    st.recorded_at = $recorded_at,
                    st.assertion = $assertion,
                    st.statement_type = $statement_type,
                    st.confidence = $confidence,
                    st.source_message_id = $source_message_id,
                    st.source_text = $source_text,
                    st.attributes_json = $attributes_json,
                    st.embedding = $embedding
                MERGE (p)-[:HAS_STATEMENT]->(st)
                MERGE (st)-[:ABOUT]->(c)

                WITH st
                OPTIONAL MATCH (t:Turn {id: $source_message_id})
                FOREACH (_ IN CASE WHEN t IS NULL THEN [] ELSE [1] END |
                    MERGE (st)-[:DERIVED_FROM]->(t)
                )
                RETURN st.id AS id
                """
                params = self._params(patient_id, statement_id, concept_key, fact)
                params["embedding"] = embedding
                result = await session.run(cypher, **params)
                record = await result.single()
                if record:
                    count += 1
        return count

    async def get_relevant_context(
        self,
        *,
        patient_id: str,
        query: str,
        limit: int = 50,
    ) -> PatientContext:
        query_embedding = await self.embedding_service.embed(query)
        candidate_limit = max(limit * 4, 40)
        vector_scores: dict[str, float] = {}
        candidate_ids: set[str] = set()

        vector_cypher = """
        CALL db.index.vector.queryNodes($index_name, $candidate_limit, $embedding)
        YIELD node, score
        MATCH (p:Patient {id: $patient_id})-[:HAS_STATEMENT]->(node)
        RETURN node.id AS id, score
        LIMIT $candidate_limit
        """
        recent_cypher = """
        MATCH (p:Patient {id: $patient_id})-[:HAS_STATEMENT]->(st:ClinicalStatement)
        RETURN st.id AS id
        ORDER BY st.recorded_at DESC
        LIMIT $candidate_limit
        """
        async with self.driver.session(database=self.database) as session:
            try:
                result = await session.run(
                    vector_cypher,
                    index_name=self.VECTOR_INDEX,
                    candidate_limit=candidate_limit,
                    embedding=query_embedding,
                    patient_id=patient_id,
                )
                for row in await result.data():
                    candidate_ids.add(row["id"])
                    vector_scores[row["id"]] = float(row["score"])
            except Neo4jError:
                pass

            recent_result = await session.run(
                recent_cypher,
                patient_id=patient_id,
                candidate_limit=candidate_limit,
            )
            for row in await recent_result.data():
                candidate_ids.add(row["id"])

            if not candidate_ids:
                return PatientContext(patient_id=patient_id)

            detail_cypher = """
            MATCH (p:Patient {id: $patient_id})-[:HAS_STATEMENT]->(st:ClinicalStatement)-[:ABOUT]->(c:ClinicalConcept)
            WHERE st.id IN $ids
            RETURN st, c
            ORDER BY st.recorded_at ASC
            """
            result = await session.run(
                detail_cypher,
                patient_id=patient_id,
                ids=list(candidate_ids),
            )
            rows = await result.data()

        q = query.casefold()
        q_tokens = token_set(query)
        scored: list[tuple[float, ClinicalFact]] = []
        total = max(1, len(rows))
        for idx, row in enumerate(rows):
            st = dict(row["st"])
            c = dict(row["c"])
            fact = ClinicalFact(
                fact_type=st["fact_type"],
                display=st["display"],
                concept_id=c.get("concept_id"),
                concept_system=c.get("concept_system"),
                value=self._loads(st.get("value_json")),
                unit=st.get("unit"),
                dose=st.get("dose"),
                frequency=st.get("frequency"),
                route=st.get("route"),
                status=st.get("status"),
                negated=bool(st.get("negated", False)),
                certainty=st.get("certainty", "confirmed"),
                experiencer=st.get("experiencer", "patient"),
                valid_from=st.get("valid_from"),
                valid_to=st.get("valid_to"),
                recorded_at=st["recorded_at"],
                assertion=st.get("assertion", "explicit"),
                statement_type=st.get("statement_type", "fact"),
                confidence=float(st.get("confidence", 1.0)),
                source_message_id=st["source_message_id"],
                source_text=st.get("source_text"),
                attributes=self._loads(st.get("attributes_json")) or {},
            )
            fact_tokens = token_set(fact.display)
            lexical = len(q_tokens & fact_tokens) / max(1, len(q_tokens | fact_tokens))
            clinical_type = 0.0
            if any(word in q for word in ("thuốc", "uống", "dùng", "ngưng", "tương tác")):
                clinical_type = max(
                    clinical_type,
                    1.0 if fact.fact_type.value in {"medication", "allergy"} else 0.0,
                )
            if any(word in q for word in ("bệnh", "chẩn đoán", "tình trạng", "triệu chứng")):
                clinical_type = max(
                    clinical_type,
                    1.0 if fact.fact_type.value in {"condition", "symptom"} else 0.0,
                )
            if any(word in q for word in ("xét nghiệm", "lab", "chỉ số")):
                clinical_type = max(
                    clinical_type,
                    1.0 if fact.fact_type.value in {"lab_result", "observation"} else 0.0,
                )
            recency = (idx + 1) / total
            vector = vector_scores.get(st["id"], 0.0)
            score = 0.50 * vector + 0.20 * lexical + 0.20 * clinical_type + 0.10 * recency
            scored.append((score, fact))

        selected = [fact for _, fact in sorted(scored, key=lambda item: item[0], reverse=True)[:limit]]
        return PatientContext(patient_id=patient_id, facts=selected)

    @staticmethod
    def _embedding_text(fact: ClinicalFact) -> str:
        chunks = [fact.fact_type.value, fact.display]
        if fact.status:
            chunks.append(f"status {fact.status}")
        if fact.dose:
            chunks.append(f"dose {fact.dose}")
        if fact.frequency:
            chunks.append(f"frequency {fact.frequency}")
        if fact.unit:
            chunks.append(f"unit {fact.unit}")
        if fact.experiencer != "patient":
            chunks.append(f"experiencer {fact.experiencer}")
        if fact.negated:
            chunks.append("negated")
        return " | ".join(chunks)

    @staticmethod
    def _statement_id(patient_id: str, fact: ClinicalFact) -> str:
        raw = "|".join(
            [
                patient_id,
                fact.source_message_id,
                fact.fact_type.value,
                fact.display.casefold(),
                fact.experiencer,
                str(fact.negated),
                str(fact.status),
                str(fact.dose),
            ]
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]

    @staticmethod
    def _concept_key(fact: ClinicalFact) -> str:
        canonical = fact.concept_id or fact.display.casefold()
        raw = f"{fact.fact_type.value}|{fact.concept_system or 'local'}|{canonical}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]

    @staticmethod
    def _params(
        patient_id: str,
        statement_id: str,
        concept_key: str,
        fact: ClinicalFact,
    ) -> dict[str, Any]:
        return {
            "patient_id": patient_id,
            "statement_id": statement_id,
            "concept_key": concept_key,
            "fact_type": fact.fact_type.value,
            "display": fact.display,
            "concept_display": (fact.attributes.get("terminology_match", {}) or {}).get("display") or fact.display,
            "concept_id": fact.concept_id,
            "concept_system": fact.concept_system,
            "value_json": json.dumps(fact.value, ensure_ascii=False, default=str)
            if fact.value is not None
            else None,
            "unit": fact.unit,
            "dose": fact.dose,
            "frequency": fact.frequency,
            "route": fact.route,
            "status": fact.status,
            "negated": fact.negated,
            "certainty": fact.certainty.value,
            "experiencer": fact.experiencer,
            "valid_from": fact.valid_from.isoformat() if fact.valid_from else None,
            "valid_to": fact.valid_to.isoformat() if fact.valid_to else None,
            "recorded_at": fact.recorded_at.isoformat(),
            "assertion": fact.assertion.value,
            "statement_type": fact.statement_type.value,
            "confidence": fact.confidence,
            "source_message_id": fact.source_message_id,
            "source_text": fact.source_text,
            "attributes_json": json.dumps(fact.attributes, ensure_ascii=False, default=str),
        }

    @staticmethod
    def _loads(value: str | None):
        if not value:
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
