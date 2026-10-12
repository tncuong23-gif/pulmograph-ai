# Production configuration

## Local/private LLM mode

Recommended LLM configuration for this project:

```env
GRAPH_BACKEND=neo4j
NLP_BACKEND=ollama
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_TIMEOUT_SECONDS=120
OLLAMA_TEMPERATURE=0
LLM_FALLBACK_TO_RULES=true

EMBEDDING_BACKEND=hash
TERMINOLOGY_MODE=off
```

For a host-native deployment where API and Ollama run on the same machine:

```env
OLLAMA_BASE_URL=http://localhost:11434
```

For the supplied Docker Compose network:

```env
OLLAMA_BASE_URL=http://ollama:11434
```

Pull the model before serving traffic:

```bash
ollama pull qwen2.5:7b
```

or in Compose:

```bash
docker compose exec ollama ollama pull qwen2.5:7b
```

## Resource note

The Ollama `qwen2.5:7b` artifact is several GB and should be treated as a separate inference service. CPU-only execution works but latency will depend strongly on hardware. GPU acceleration is recommended when low latency or concurrent requests matter.

## Structured-output validation

The model response is constrained by JSON Schema and then validated again using Pydantic. Do not bypass the application validator or allow model-generated Cypher to write directly to Patient Graph.

## Embeddings

Qwen 2.5 7B is not used as the embedding model. The default local configuration uses deterministic hash vectors.

For production-grade semantic retrieval, use a dedicated embedding model and keep the same embedding model/dimension for both indexing and querying. If you change dimensions in an existing Neo4j deployment, rebuild vector indexes and backfill embeddings.

Default index names:

```text
history_turn_embedding
clinical_statement_embedding
```

## SNOMED CT / LOINC / RxNorm

Terminology remote calls are disabled by default in private/local mode.

When enabled, point SNOMED at a terminology server your organization is authorized to use and provide LOINC credentials. RxNorm uses NLM RxNav by default.

## External data boundary

With `NLP_BACKEND=ollama`, prompts stay within the Ollama endpoint you configure. However, enabling remote terminology normalization or OpenAI embeddings can still send clinical strings outside that boundary. Review privacy, security, data residency, logging, backups and access controls for the actual deployment.

## Operational recommendations

Keep Ollama reachable only from trusted application networks, do not expose port 11434 publicly without an access-control layer, and bound request size/history retrieval so a user cannot force arbitrarily large prompts.

Monitor at least:

```text
Ollama request latency
structured-output validation failures
rule fallback rate
context resolution confidence
clinical facts rejected by validator
Neo4j query latency
vector-index availability
```
