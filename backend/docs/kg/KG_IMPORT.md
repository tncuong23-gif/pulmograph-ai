# KG Import module

`JSON -> parse -> validate -> normalize -> plan -> MongoDB -> Neo4j -> finalize`

* Neo4j holds only the graph: `(:Entity {id})-[:TYPE {id}]->(:Entity)`.
* MongoDB holds `documents, sections, paragraphs, sentences, propositions, evidence, imports`.
* Relation -> provenance: `r.source_document_id`, `r.source_proposition_ids`, `r.evidence_ids` in Neo4j;
  the full text/location lives in Mongo `evidence` (`evidence_id`) -> `sentence_id` -> `paragraph_id` -> `section_id`.

## Install (Windows CMD)
```
pip install -r requirements-kg-import.txt
copy .env.example .env
```
Set the variables in your shell (CMD): `set NEO4J_PASSWORD=...` (PowerShell: `$env:NEO4J_PASSWORD="..."`).

## Start databases (Docker Desktop, CMD)
```
docker run -d --name kg-mongo -p 27017:27017 mongo:7
docker run -d --name kg-neo4j -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/change-me-please neo4j:5
```

## Constraints / indexes (idempotent)
```
python -m scripts.setup_neo4j_constraints --mongo
```

## Validate / import / dry-run / retry
```
python -m scripts.validate_kg examples/kg_import.json
python -m scripts.import_kg examples/kg_import.json --mode upsert --dry-run
python -m scripts.import_kg examples/kg_import.json --mode upsert
python -m scripts.import_kg examples/kg_import.json --retry IMP_XXXXXXXXXXXX
```
API (CMD):
```
curl -X POST "http://localhost:8000/api/v1/kg/import-json?mode=upsert" ^
  -H "Content-Type: application/json" --data-binary "@examples/kg_import.json"
curl "http://localhost:8000/api/v1/kg/import-json?mode=upsert&dry_run=true" ...   (POST, same body)
curl http://localhost:8000/api/v1/kg/imports/IMP_XXXXXXXXXXXX
curl -X POST http://localhost:8000/api/v1/kg/imports/IMP_XXXXXXXXXXXX/retry ^
  -H "Content-Type: application/json" --data-binary "@examples/kg_import.json"
curl http://localhost:8000/api/v1/kg/health
```

## Input format
See `examples/kg_import.json`. Required: `schema_version`, `document{document_id,title}`, `entities[{id,type,canonical_name}]`.
Optional: `aliases`, `properties`, `relations[{id,type,source,target,proposition_ids,confidence,properties}]`,
`document.sections[].paragraphs[].sentences[]`, `propositions[{id,text,evidence[{sentence_id|text}]}]`.
By default (`Limits.require_provenance=True`) every relation must cite propositions that have evidence.
A relation endpoint may be an entity already in the graph (from another document).

## Modes
| mode | behaviour |
|---|---|
| insert | any existing document/entity/relation/Mongo record -> HTTP 409, nothing written |
| upsert | create or update; unchanged items are skipped (content hash); never duplicates |
| replace | upsert + remove THIS document's stale relations, Mongo records, and entity links (an entity is deleted only if no other document links it and it has no relations) |

Relation ids are global and owned by one document; re-using an id with different type/endpoints, or from another
document, is rejected (`RELATION_IDENTITY_CONFLICT`, `RELATION_OWNED_BY_OTHER_DOCUMENT`).

## Status codes
200 completed/dry_run - 400 malformed JSON - 409 conflict / not retryable - 413 too large - 422 validation - 500 write failure.

## Failure semantics (no cross-database transaction)
* Neo4j write = one transaction (atomic). Mongo = keyed idempotent upserts tagged with `import_id`.
* New document + failure in a write stage -> Mongo records of that import are deleted -> `failed`, `compensated=true`.
* Existing document (upsert/replace) or compensation failure -> `partial`. Both are `retryable`; `retry` re-runs the remaining stages.
* Replace: Mongo new records are written first, stale ones deleted only after Neo4j succeeds.

## Verification queries
```
MATCH (n) RETURN labels(n), count(n);
MATCH ()-[r]->() RETURN type(r), count(r);
MATCH (e:Entity) WITH e.id AS id, count(*) AS c WHERE c > 1 RETURN id, c;
MATCH (a:Entity)-[r]->(b:Entity) RETURN a.canonical_name, type(r), b.canonical_name, r.source_document_id, r.evidence_ids LIMIT 50;
```
Mongo (mongosh): `db.documents.countDocuments()`, `db.propositions.countDocuments()`, `db.evidence.countDocuments()`,
`db.imports.find({}, {import_id:1,status:1,stage:1})`, `db.evidence.getIndexes()`.

## Wiring into an existing app
```python
from kg_import.config import Settings
from kg_import.factory import build_resources
from kg_import.api import create_router
res = build_resources(Settings.from_env())        # once, at startup; res.close() at shutdown
app.include_router(create_router(lambda: res.service, Settings.from_env().limits.max_body_bytes))
```
If you already have Mongo/Neo4j repositories or an ontology source, implement the Protocols in `kg_import/ports.py`
and `Ontology.from_dict(...)` over them instead of using the bundled adapters.
