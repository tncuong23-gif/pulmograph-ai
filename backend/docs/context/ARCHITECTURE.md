# Architecture

## Responsibility boundary

`MedicalContextService` không trả lời câu hỏi y khoa. Nó phục hồi câu hỏi thành dạng tự đủ nghĩa và cập nhật contextual/patient state.

```text
User message
   |
   +--> HistoryRepository.get_relevant_turns()
   |       vector similarity
   |       + lexical overlap
   |       + discourse/entity continuity
   |       + recency
   |
   +--> PatientRepository.get_relevant_context()
           vector similarity
           + fact-type relevance
           + lexical overlap
           + recency
   |
   v
Qwen 2.5:7b QuestionResolver (Ollama)
   |
   v
normalized_question
   |
   v
Qwen 2.5:7b ClinicalExtractor (Ollama)
   |
   v
TerminologyNormalizer
   |
   v
ClinicalAssertionValidator
   |
   +--> History Graph
   +--> Patient Graph
```

## Structured output with Ollama

Implementation:

```text
app/infrastructure/llm/ollama_structured.py
```

`OllamaStructuredClient` sends a Pydantic JSON Schema to Ollama `/api/chat` using `format=<schema>`. The response body is then validated with `model_validate_json()`.

The two LLM tasks remain isolated:

- `OllamaStructuredQuestionResolver`: subject/coreference/temporal restoration only.
- `OllamaStructuredClinicalExtractor`: extracts candidate assertions and classifies `fact`, `question`, `plan`, `hypothesis`.

Default model:

```text
qwen2.5:7b
```

Qwen never writes Cypher and never writes directly to the graph.

## Failure isolation

When `LLM_FALLBACK_TO_RULES=true`, connection errors, invalid JSON, schema validation errors, or other Ollama failures fall back to the conservative rule implementation.

This prevents a local model outage from breaking the context endpoint, while keeping the fallback behavior explicit in configuration.

## Terminology normalization

Routing:

```text
Medication                     -> RxNorm
Condition/Symptom/Procedure    -> SNOMED CT
Allergy/Family history         -> SNOMED CT
Lab result/Observation         -> LOINC
```

Terminology preferred labels do not overwrite user wording.

## Hybrid retrieval

### History

```text
0.45 * vector_similarity
+ 0.20 * lexical_overlap
+ 0.20 * entity_continuity
+ 0.15 * recency
```

### Patient context

```text
0.50 * vector_similarity
+ 0.20 * lexical_overlap
+ 0.20 * clinical_type_relevance
+ 0.10 * recency
```

The default local embedding implementation is hash-based. It preserves the vector pipeline without requiring another model. For stronger semantic retrieval, plug a dedicated local embedding model into the existing `EmbeddingService` interface.

## Patient graph

```text
(Patient)-[:HAS_STATEMENT]->(ClinicalStatement)-[:ABOUT]->(ClinicalConcept)
(ClinicalStatement)-[:DERIVED_FROM]->(Turn)
```

`ClinicalStatement` retains temporal state, negation, certainty, experiencer, assertion type, provenance, medication dose/frequency and confidence.

## Safety invariants

- a question is not stored as a fact;
- a hypothetical medication is not stored as an active medication;
- an inferred diagnosis is not stored as an explicit diagnosis;
- a relative's condition is represented as family history;
- negated statements stay negated;
- terminology mapping does not turn a low-confidence match into a clinical fact.
