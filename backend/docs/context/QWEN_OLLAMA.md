# Qwen 2.5 7B via Ollama

## Model setup

```bash
ollama pull qwen2.5:7b
ollama run qwen2.5:7b
```

Project configuration:

```env
NLP_BACKEND=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_TIMEOUT_SECONDS=120
OLLAMA_TEMPERATURE=0
LLM_FALLBACK_TO_RULES=true
```

## Structured request

Both resolver and extractor call:

```text
POST /api/chat
```

with:

```json
{
  "model": "qwen2.5:7b",
  "stream": false,
  "format": {"...": "Pydantic JSON Schema"},
  "options": {"temperature": 0}
}
```

The returned `message.content` must validate against the same Pydantic model before it can enter the application pipeline.

## Why two calls

Context resolution and clinical extraction are intentionally separate. This reduces the risk that a context-reconstruction assumption is silently persisted as a patient clinical fact.
