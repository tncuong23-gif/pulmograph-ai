# KG Query module (`kg_query/`)

`question -> validated question analysis -> QuerySpec -> KGQueryService.run() -> facts + evidence -> answer`

Read-only. It only reads the graph written by `kg_import` (`(:Entity)-[:TYPE {id, evidence_ids, ...}]->(:Entity)`)
and the MongoDB `evidence` collection. It never writes anything.

## Why there is no "one query per question"
Questions are reduced to **(entity mention(s), intent)**. An *intent* is a named group of ontology relation types
(`kg_query/intents.py`); Cypher is generated from the group, and the direction of every relation is inferred from the
ontology domain/range and the anchor's entity type. So coverage grows by editing a list, not by writing Cypher.

| Question shape | How it is answered |
|---|---|
| "COPD có triệu chứng gì?" | 1 mention + `intents:["symptom"]` |
| "Thuốc nào điều trị COPD?" | `intents:["treatment"]`, `target_types:["Medication","DrugClass"]` |
| "Thuốc điều trị COPD có tác dụng phụ gì?" | `chain:"drug_adverse_effects"` (treatment -> membership -> adverse_effect) |
| "COPD liên quan gì đến suy tim?" | 2 mentions + `path:true` (shortest paths, max 3 hops) |
| "So sánh triệu chứng COPD và viêm phổi" | HTTP planner `mode:compare`; two entities + symptom criterion, direct relations |
| "COPD và viêm phổi có triệu chứng nào giống nhau/khác nhau?" | HTTP planner `mode:common` / `difference`; computed comparison rows referencing facts |
| anything else / unclear intent | `intents:["related"]` = every relation type (never returns nothing for lack of a template) |
| entity not found / no facts | `status` = `no_entity` / `no_facts` -> route to vector/hybrid search |

## QuerySpec (what the question-analysis step should emit)
```json
{"mentions": ["COPD"], "intents": ["risk_factor"], "target_types": null, "anchor_types": ["Disease"]}
{"mentions": ["COPD"], "chain": "drug_adverse_effects"}
{"mentions": ["COPD", "suy tim"], "path": true, "max_hops": 3}
```
Unknown intents / entity types are repaired (and reported in `notes`), never fatal. `python -m scripts.kg.query_kg intents`
prints the intent list (paste `describe_intents()` into the analysis prompt) and the relations no specific intent covers.

## Entity resolution
The integrated chat API uses a strict dictionary/alias resolver with explicit confirmation for ambiguous or fuzzy names; see `API_INTEGRATION.md`. The following legacy resolver remains available to the Explorer and direct service callers:

`exact normalized_name -> alias -> full-text (names+aliases, accent-folding) -> CONTAINS`; first stage with hits wins.
Nodes of the same type that share a name/alias with a hit are added (`alias_sibling`), because the same disease imported
under two spellings is two nodes. This is a workaround: the real fix is entity merging at import time.

## Comparisons (v12 HTTP API / chat)

The HTTP planner dispatches `compare`, `common`, and `difference` to `comparison.compare` rather than to the legacy
QuerySpec/Explorer CLI. It independently retrieves each side and criterion, compares canonical target IDs, predicates,
edge direction, and complete sets of valid assertion properties, then budgets whole rows. Different IDs or predicates
are not merged by name. One-sided rows mean *not found in the retrieved data*, never clinical absence. Qualifiers and
negation remain in the referenced facts; invalid or different properties are marked for review. Results are bounded,
incomplete and read-only. See `API_INTEGRATION.md` for the schema, budgets, source mapping and clarification workflow.

## Results
* `facts`: one per (subject, predicate, object); the same triple in several documents is merged (`doc_ids`, `evidence_ids`).
* `answers` (1-hop): facts merged per (predicate, answer entity) across anchor nodes.
* `chains` (multi-hop): chains must reach the last required step; optional membership also retains directly linked drugs. Incomplete chains are not returned as evidence. `paths`: shortest only, no detour through another anchor; their edges also appear in `facts`.
* `evidence`: text fetched from Mongo by `(document_id, evidence_id)`, at most `QueryLimits.evidence_per_fact` per fact.

## Setup / use
```
python -m scripts.kg.setup_query_indexes              # full-text index (once)
python -m scripts.kg.query_kg find "COPD"
python -m scripts.kg.query_kg ask "COPD" -i symptom
python -m scripts.kg.query_kg chain "COPD" drug_adverse_effects
python -m scripts.kg.query_kg path "COPD" "suy tim"
python -m unittest tests.upstream.kg.test_query
```
```python
from app.modules.kg_import.config import Settings
from app.modules.kg_query.factory import build_query_resources
from app.modules.kg_query import QuerySpec
res = build_query_resources(Settings.from_env())       # once, at startup; res.close() at shutdown
result = res.service.run(QuerySpec.from_dict(spec_dict_from_llm, PRESET_CHAINS))
```

## Extending
* New relation type in the ontology -> add its name to an intent in `_DEFS` (the test fails on typos).
* New multi-hop question type -> add a preset to `PRESET_CHAINS` (max 3 steps).

## Testing note
`tests/fake_neo4j.py` is an in-memory stand-in that understands only these Cypher templates; it tests the Python logic on
the real example files but does not validate Cypher syntax. Run `scripts/query_kg.py` against a real Neo4j 5.x once.
