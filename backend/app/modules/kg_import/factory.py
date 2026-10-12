"""Builds the service from Settings. Create it ONCE at application startup and reuse it (connection pools)."""
from __future__ import annotations

from .config import Settings
from .ontology import Ontology
from .service import KGImportService


class Resources:
    """Owns the driver/client so they can be closed at shutdown."""

    def __init__(self, service: KGImportService, mongo_client, neo4j_driver, entity_index=None) -> None:
        self.service, self._mongo, self._neo, self._index = service, mongo_client, neo4j_driver, entity_index

    def close(self) -> None:
        self._mongo.close()
        self._neo.close()
        if self._index is not None:
            self._index.close()


def build_resources(settings: Settings, ontology: Ontology | None = None) -> Resources:
    from neo4j import GraphDatabase  # imported lazily so the core stays importable without drivers
    from pymongo import MongoClient

    from .adapters.mongo import MongoKGStore
    from .adapters.neo4j import Neo4jKGStore

    mongo = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000)
    driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_username, settings.neo4j_password),
                                  connection_timeout=5, max_transaction_retry_time=15)
    mstore = MongoKGStore(mongo[settings.mongodb_database], settings.limits.mongo_batch_size)
    gstore = Neo4jKGStore(driver, settings.neo4j_database, settings.limits.neo4j_batch_size)
    entity_index = None
    if settings.entity_embedding.enabled:
        from .entity_vector import QdrantEntityIndex
        entity_index = QdrantEntityIndex(settings.entity_embedding)
    service = KGImportService(ontology or Ontology.load(settings.ontology_path), mstore, gstore, mstore,
                              settings.limits, entity_index=entity_index)
    return Resources(service, mongo, driver, entity_index)
