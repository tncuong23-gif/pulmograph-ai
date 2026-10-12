"""Create Neo4j constraints/indexes. Idempotent: safe to run any number of times.

    python -m scripts.kg.setup_neo4j_constraints
    python -m scripts.kg.setup_neo4j_constraints --mongo   (also create MongoDB indexes)
"""
import argparse
import logging

from neo4j import GraphDatabase

from app.modules.kg_import.config import Settings
from app.modules.kg_import.ontology import Ontology
from scripts.kg._common import utf8_stdout


def main() -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--mongo", action="store_true", help="also create MongoDB indexes")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    st = Settings.from_env()
    ontology = Ontology.load(st.ontology_path)

    from app.modules.kg_import.adapters.neo4j import Neo4jKGStore
    driver = GraphDatabase.driver(st.neo4j_uri, auth=(st.neo4j_username, st.neo4j_password))
    try:
        store = Neo4jKGStore(driver, st.neo4j_database)
        store.ping()
        for name in store.ensure_constraints(ontology.relation_names()):
            print(f"[neo4j] ensured: {name}")
    finally:
        driver.close()

    if args.mongo:
        from pymongo import MongoClient
        from app.modules.kg_import.adapters.mongo import MongoKGStore
        client = MongoClient(st.mongodb_uri, serverSelectionTimeoutMS=5000)
        try:
            MongoKGStore(client[st.mongodb_database]).ensure_indexes()
            print("[mongo] indexes ensured")
        finally:
            client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
