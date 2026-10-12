# Medical Context Graph Gateway — Context Resolver v2.3

> **Build nhận diện:** Context Resolver v2.3 · Context Need + Discourse Focus + Patient Assertion Gate. Khi chạy đúng bản này, `GET /health` có `"context_resolver_version": "2.3"` và tiêu đề `/ui` hiển thị **Context Resolver v2.3 · Context Need + Discourse Focus + Patient Gate**.


## Điểm mới ở v2.3 — chỉ phục hồi khi thực sự cần

V2.3 thêm `ContextNeedDetector` làm cổng trước Context Resolver:

- Câu đã tự đủ nghĩa: giữ nguyên **100%**, `resolution_status=not_needed`, không gọi Qwen để paraphrase.
- Câu có đại từ/tham chiếu (`nó`, `bệnh này`, `thuốc đó`, ...): mới chạy reference resolution.
- Câu tỉnh lược thiếu chủ thể (`Có nguy hiểm không?`, `Điều trị thế nào?`, `Còn triệu chứng?`): chỉ điền chủ thể khi có antecedent duy nhất đủ mạnh.
- Nếu thiếu ngữ cảnh hoặc có nhiều antecedent ngang nhau: `unresolved` và giữ nguyên câu.

Ví dụ:

```text
Viêm phổi có triệu chứng gì?
→ giữ nguyên, not_needed

COPD là gì?
Nó có triệu chứng gì?
→ COPD có triệu chứng gì?, resolved

Viêm phổi là gì?
Có nguy hiểm không?
→ Viêm phổi có nguy hiểm không?, resolved

Viêm phổi khác COPD thế nào?
Có nguy hiểm không?
→ giữ nguyên, unresolved
```

## Điểm mới ở v2.2

v2.2 sửa lỗi chuyển chủ đề hội thoại. Ví dụ:

```text
Viêm phổi là gì?
Nó có triệu chứng gì?            -> Viêm phổi có triệu chứng gì?
Viêm phổi có nguy hiểm không?
COPD là gì?                      -> topic switch sang COPD
Nó có triệu chứng gì?            -> COPD có triệu chứng gì?
```

Resolver không còn chỉ cộng một trọng số recency nhỏ. Nó dùng **priority tier**:

1. `Tier 1`: thực thể tương thích được người dùng nêu trực tiếp ở lượt gần nhất.
2. `Tier 2`: active topic được kế thừa từ reference đã resolve, hoặc explicit topic gần nhất của hội thoại khi không có user focus.
3. `Tier 3-4`: các discourse entity cũ hơn.
4. `Tier 5`: Patient Context fallback.

`HistoryMention.origin` phân biệt `explicit`, `resolved_reference`, `clinical_candidate`, `legacy_inferred`. Nếu lượt gần nhất chứa hai thực thể cùng loại, ví dụ `Viêm phổi khác COPD như thế nào?`, hệ thống giữ `unresolved` thay vì đoán.

Validator v2.2 cũng xây lại `normalized_question` từ câu gốc và **chỉ các reference đã được xác nhận**. Nếu Qwen chọn `Viêm phổi` nhưng `COPD` là Tier 1, lựa chọn đó bị bác; câu viết lại sai không được phép rò ra response.

`Patient Assertion Gate` của v2.1 vẫn được giữ nguyên: câu hỏi kiến thức không được ghi thành clinical fact của bệnh nhân.

---
## Patient Assertion Gate (v2.1)

Trước khi ghi Patient Graph, mọi candidate từ Clinical Extractor phải qua một lớp kiểm tra deterministic độc lập với LLM. Lớp này chặn câu hỏi kiến thức, câu hỏi chẩn đoán, giả định/plan, fact không có bằng chứng trực tiếp, và `display` dạng mệnh đề dài.

Ví dụ:

```text
"Viêm phổi có triệu chứng gì?"
  History: Viêm phổi [condition]
  Patient Graph: không ghi fact

"Tôi có bị viêm phổi không?"
  Patient Graph: không ghi condition=viêm phổi

"Tôi đang sốt, liệu tôi có bị viêm phổi không?"
  Patient Graph: chỉ ghi symptom=sốt

"Tôi bị ho và sốt ba ngày nay."
  Patient Graph: symptom=ho, symptom=sốt
```

## Kiến trúc

```text
User question
    |
    +----> History hybrid retrieval --------+
    |                                       |
    +----> Patient hybrid retrieval --------+
                                            |
                                            v
                              Qwen 2.5:7b Question Resolver
                                            |
                                            v
                                  normalized_question
                                            |
                                            v
                              Qwen 2.5:7b Clinical Extractor
                                            |
                                            v
                               Terminology Normalizer
                           SNOMED / LOINC / RxNorm
                                            |
                                            v
                               Clinical Fact Validator
                                  /                 \
                                 v                   v
                           History Graph        Patient Graph
```

Chi tiết: `docs/ARCHITECTURE.md`.


## Context Resolver v2

Bản này tách rõ **discourse memory** khỏi **patient facts**. Một thực thể xuất hiện trong câu hỏi vẫn được lưu làm `Mention` để phục hồi đồng tham chiếu, nhưng chỉ clinical assertion hợp lệ mới được ghi vào Patient Graph.

Ví dụ:

```text
Turn 1: Viêm phổi là gì?
        -> History Mention: condition = Viêm phổi
        -> Patient Graph: không ghi chẩn đoán viêm phổi

Turn 2: Nó có triệu chứng gì?
        -> candidate: Viêm phổi [condition]
        -> normalized_question: Viêm phổi có triệu chứng gì?
```

Context window được ghép từ hai nguồn:

```text
recent window (mặc định 6 turn gần nhất)
+
relevant history (hybrid retrieval)
```

Resolver xếp hạng antecedent theo loại thực thể, độ gần, confidence và provenance. Nếu hai candidate cùng loại gần ngang nhau, hệ thống giữ `unresolved` thay vì đoán. Response `/v1/context/resolve` có thêm các trường debug tương thích ngược:

```json
{
  "resolution_status": "resolved",
  "resolution_method": "ollama_qwen_hybrid",
  "candidate_entities": [
    {
      "canonical_name": "Viêm phổi",
      "entity_type": "condition",
      "source_message_id": "M001",
      "score": 0.93
    }
  ]
}
```

Có thể điều chỉnh cửa sổ gần nhất trong `.env`:

```env
HISTORY_LIMIT=20
RECENT_HISTORY_LIMIT=6
```

## Local LLM: Qwen 2.5 7B + Ollama

Implementation:

```text
app/infrastructure/llm/ollama_structured.py
```

Hai task độc lập:

```text
OllamaStructuredQuestionResolver
OllamaStructuredClinicalExtractor
```

Ollama nhận Pydantic JSON Schema qua trường `format`. Response sau đó được Pydantic validate lần nữa trước khi đi vào application layer.

LLM không sinh Cypher và không ghi trực tiếp vào Neo4j:

```text
Qwen output
   -> Pydantic validation
   -> terminology normalization
   -> assertion validation
   -> repository
   -> Neo4j
```

Nếu Ollama không khả dụng hoặc output không hợp schema, có thể bật `LLM_FALLBACK_TO_RULES=true` để fallback sang rule-based implementation.

## Chạy local nhanh nhất

Yêu cầu:

- Python 3.11+
- Ollama

Pull model:

```bash
ollama pull qwen2.5:7b
```

Đảm bảo Ollama chạy ở:

```text
http://localhost:11434
```

Tạo environment:

```bash
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

Cấu hình local mặc định:

```env
GRAPH_BACKEND=memory
NLP_BACKEND=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_TIMEOUT_SECONDS=120
OLLAMA_TEMPERATURE=0
LLM_FALLBACK_TO_RULES=true

EMBEDDING_BACKEND=hash
TERMINOLOGY_MODE=off
```

Chạy test:

```bash
pytest -q
```

Chạy API:

```bash
uvicorn app.main:app --reload
```

Swagger:

```text
http://localhost:8000/docs
```

## Chạy toàn bộ bằng Docker Compose

Start Ollama + Neo4j trước:

```bash
docker compose up -d ollama neo4j
```

Pull Qwen vào Ollama container:

```bash
docker compose exec ollama ollama pull qwen2.5:7b
```

Sau đó chạy API:

```bash
docker compose up -d api
```

Trong Docker network, API dùng:

```env
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=qwen2.5:7b
```

Neo4j Browser:

```text
http://localhost:7474
```

API:

```text
http://localhost:8000
```

## NLP backends

### Qwen local — mặc định

```env
NLP_BACKEND=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_TIMEOUT_SECONDS=120
OLLAMA_TEMPERATURE=0
```

### Rule-only

Dùng khi test không muốn gọi LLM:

```env
NLP_BACKEND=rule
```

### OpenAI — tùy chọn

Adapter cũ vẫn được giữ:

```env
NLP_BACKEND=openai
OPENAI_API_KEY=...
OPENAI_MODEL=...
```

`NLP_BACKEND=auto` chọn OpenAI nếu có `OPENAI_API_KEY`, nếu không chọn Ollama.

## Embeddings

Qwen 2.5 7B được dùng cho reasoning/extraction, **không dùng làm embedding model**.

Mặc định project vẫn chạy local hoàn toàn bằng deterministic hash vectors:

```env
EMBEDDING_BACKEND=hash
HASH_EMBEDDING_DIMENSIONS=256
```

Điều này giữ nguyên đường đi hybrid vector retrieval nhưng không cung cấp semantic embedding mạnh như model embedding chuyên dụng. Nếu cần, project vẫn hỗ trợ OpenAI embeddings:

```env
EMBEDDING_BACKEND=openai
OPENAI_API_KEY=...
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_EMBEDDING_DIMENSIONS=1536
```

Có thể bổ sung local embedding adapter riêng sau mà không thay đổi repository contract.

## History Graph

```text
(Session)-[:HAS_TURN]->(Turn)-[:MENTIONS]->(Mention)-[:REFERS_TO]->(DiscourseEntity)
(Turn)-[:NEXT]->(Turn)
```

Hybrid score baseline:

```text
vector similarity
+ lexical overlap
+ entity continuity
+ recency
```

## Patient Graph

```text
(Patient)-[:HAS_STATEMENT]->(ClinicalStatement)-[:ABOUT]->(ClinicalConcept)
(ClinicalStatement)-[:DERIVED_FROM]->(Turn)
```

`ClinicalStatement` lưu:

```text
fact_type
status
negated
certainty
experiencer
valid_from / valid_to
recorded_at
assertion
statement_type
confidence
source_message_id
source_text
dose / frequency / route
```

## Terminology normalization

Implementation:

```text
app/infrastructure/terminology/normalizer.py
```

Routing:

| Clinical fact | Terminology |
|---|---|
| Medication | RxNorm |
| Condition | SNOMED CT |
| Symptom | SNOMED CT |
| Procedure | SNOMED CT |
| Allergy | SNOMED CT |
| Family history | SNOMED CT |
| Lab result | LOINC |
| Observation | LOINC |

Bật remote normalization:

```env
TERMINOLOGY_MODE=remote
TERMINOLOGY_MIN_CONFIDENCE=0.75
RXNORM_BASE_URL=https://rxnav.nlm.nih.gov
SNOMED_FHIR_BASE_URL=https://your-snowstorm.example/fhir
LOINC_USERNAME=...
LOINC_PASSWORD=...
```

Lưu ý: bật terminology remote có thể gửi clinical string ra ngoài process boundary.

## API chính

### `POST /v1/context/resolve`

```json
{
  "patient_id": "pt_123",
  "session_id": "sess_456",
  "message_id": "msg_789",
  "question": "Có cần ngưng không?",
  "timestamp": "2026-09-26T03:30:00+07:00"
}
```

Ví dụ response:

```json
{
  "normalized_question": "Tôi có cần ngưng sử dụng amoxicillin không?",
  "resolved_subject": "patient",
  "resolved_references": [],
  "context_turn_ids": ["msg_previous"],
  "resolution_confidence": 0.96,
  "patient_graph_updated": false,
  "stored_fact_count": 0
}
```

### `POST /v1/history/turns`

Ghi assistant/downstream response vào History Graph.

### `GET /v1/history`

```text
/v1/history?patient_id=pt_123&session_id=sess_456&query=thuốc&limit=20
```

### `GET /v1/patients/{patient_id}/context`

```text
/v1/patients/pt_123/context?query=thuốc đang dùng
```

## Quy tắc an toàn dữ liệu

Project cố ý không ghi mọi entity được nhắc tới vào Patient Graph.

```text
"Nếu tôi uống aspirin thì sao?"
```

Aspirin là `hypothesis`, không phải active medication.

```text
"Mẹ tôi bị tiểu đường."
```

Lưu `family_history`, `experiencer=mother`.

```text
"Tôi không bị tiểu đường."
```

Giữ `negated=true`.

Qwen chỉ sinh structured candidate facts. Validator và repository mới quyết định fact nào được ghi vào Patient Graph.

## Test Console UI

Project includes a lightweight browser UI for manually testing the context pipeline without a separate frontend build.

Start the API, for example on port 8001:

```bash
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

Then open:

- Test Console: `http://localhost:8001/ui`
- Swagger: `http://localhost:8001/docs`
- Health: `http://localhost:8001/health`

The Test Console can:

- Submit requests to `POST /v1/context/resolve`
- Display normalized question, subject, confidence, stored fact count, and raw JSON
- Add assistant/system/user turns via `POST /v1/history/turns`
- Query conversation history using `GET /v1/history`
- Query patient clinical context using `GET /v1/patients/{patient_id}/context`
- Re-check backend health automatically

The UI uses relative API URLs, so it works unchanged when the FastAPI server is moved from port 8000 to another port such as 8001.
