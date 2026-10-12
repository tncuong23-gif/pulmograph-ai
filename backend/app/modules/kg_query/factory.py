"""Build the query service from app.modules.kg_import Settings. Create once at startup, reuse, close at shutdown."""
from __future__ import annotations

from app.modules.kg_import.config import Settings
from app.modules.kg_import.ontology import Ontology

from .service import KGQueryService, QueryLimits


class QueryResources:
    def __init__(self, service: KGQueryService, mongo_client, neo4j_driver) -> None:
        self.service, self._mongo, self._neo = service, mongo_client, neo4j_driver

    def close(self) -> None:
        if self._mongo is not None:
            self._mongo.close()
        self._neo.close()


def build_query_resources(settings: Settings, ontology: Ontology | None = None, *, with_evidence: bool = True,
                          limits: QueryLimits | None = None) -> QueryResources:
    from neo4j import GraphDatabase  # lazy: the package stays importable without the drivers

    driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_username, settings.neo4j_password),
                                  connection_timeout=5)
    mongo, store = None, None
    if with_evidence:
        from pymongo import MongoClient
        from .evidence import MongoEvidenceStore
        mongo = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000)
        store = MongoEvidenceStore(mongo[settings.mongodb_database])
    service = KGQueryService(driver, ontology or Ontology.load(settings.ontology_path), database=settings.neo4j_database,
                             limits=limits, evidence_store=store)
    return QueryResources(service, mongo, driver)
