"""Bootstrap/refresh the separate Qdrant entity-name index from Neo4j.

    python -m scripts.kg.index_entities

Safe to repeat. Existing Neo4j nodes/relations are never modified.
"""
from __future__ import annotations

from app.modules.kg_import.config import Settings, BACKEND_ROOT
from app.modules.kg_import.factory import build_resources


def main() -> int:
    from dotenv import load_dotenv
    from ._common import utf8_stdout
    utf8_stdout()
    load_dotenv(BACKEND_ROOT / ".env")
    settings = Settings.from_env()
    if not settings.entity_embedding.enabled:
        print("Set KG_ENTITY_EMBEDDING_ENABLED=1 before indexing entities.")
        return 2
    resources = build_resources(settings)
    try:
        index = resources.service.entity_index
        print(f"Preparing {settings.entity_embedding.model} -> {settings.entity_embedding.collection}", flush=True)
        index.begin_build()
        after, entities, names = "", 0, 0
        while True:
            page = resources.service.graph.list_entities(after, 200)
            if not page:
                break
            names += index.upsert_entities(page)
            entities += len(page)
            after = page[-1]["id"]
            print(f"Indexed {entities} entities / {names} names; last id: {after}", flush=True)
        index.finish_build()
        print(f"Indexed {names} names for {entities} Neo4j :Entity nodes in '{settings.entity_embedding.collection}'.")
        return 0
    finally:
        resources.close()


if __name__ == "__main__":
    raise SystemExit(main())
