# Medical RAG Import + Web Demo — v1.0.1

> Bản tích hợp hiện tại đã bổ sung semantic chunking. Hướng dẫn cập nhật và reindex: [RAG_SEMANTIC_CHUNKING_VI.md](../../../RAG_SEMANTIC_CHUNKING_VI.md). Phần mô tả token chunking bên dưới được giữ để tra cứu chế độ `RAG_CHUNK_METHOD=token`.

FastAPI + MongoDB + Qdrant, có giao diện tiếng Việt để import JSON từ module KG, tìm kiếm và truy ngược bằng chứng. Không sửa dữ liệu Neo4j.

## Sửa lỗi thiếu metadata (v1.0.1)

`document.document_type` và `document.language` không còn bắt buộc. Khi thiếu, null hoặc chuỗi trắng:

- document_type = `unknown` (chưa xác định).
- language = `und` (chưa xác định).

API vẫn validate/import được và trả cảnh báo. Nếu đã có giá trị hợp lệ, hệ thống giữ nguyên. Không tự đoán loại tài liệu/ngôn ngữ từ nội dung. Metadata dạng sai kiểu (số, array, object) vẫn báo lỗi. Bộ lọc language=vi sẽ không match tài liệu language=und; thêm metadata vào JSON rồi import lại nếu muốn lọc theo ngôn ngữ.

Cập nhật bản cũ: dừng server, chép đè thư mục `app` và `examples/input.schema.json` từ gói này, giữ nguyên `.env`, `.venv`, `data` và Docker volumes, rồi khởi động server lại. GET `/api/v1/rag/health` phải trả `version: "1.0.1"`.

## Chạy demo trên Windows

Cài Python 3.10–3.12 (khuyến nghị 3.10/3.11), giải nén, vào `medical-rag` rồi nhấp đúp **start-demo.bat**. Lần đầu cần mạng để cài thư viện. Khi terminal báo `Application startup complete`, mở http://127.0.0.1:8000. Nếu trình duyệt mở trước server, nhấn tải lại.

Hoặc chạy bằng CMD, thay đường dẫn phù hợp:

```bat
cd /d D:\medical-rag
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
set RAG_MODE=demo
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Không cần kích hoạt venv vì lệnh gọi trực tiếp Python trong venv. Dừng bằng Ctrl+C. Đổi port thành 8001 nếu 8000 đã được dùng.

1. Chọn `examples/DOC_000001.json` trên trang web.
2. Nhấn **Kiểm tra dữ liệu → Xem trước → Import tài liệu**.
3. Mở **Tra cứu tri thức**, nhập `COPD có triệu chứng khó thở`, chọn **Mệnh đề**.
4. Nhấn ID câu bên dưới kết quả để xem nguồn.
5. **Kho tài liệu** hỗ trợ xem chunk, reindex và xóa có xác nhận.

Demo dùng SQLite tại `data/demo.sqlite3` và vector hashing từ khóa/cosine. **Demo không phải tìm kiếm ngữ nghĩa**, không dùng HNSW và không dùng để đánh giá chất lượng embedding. Các thao tác nhập/xóa/cập nhật/truy nguồn vẫn thực hiện thật và giữ dữ liệu sau khi khởi động lại. Không tự import file mẫu khi mở server.

## Chạy MongoDB + Qdrant + E5

Bật Docker Desktop. Trong thư mục dự án:

```bat
docker compose up -d
.venv\Scripts\python.exe -m pip install -r requirements-full.txt
copy .env.example .env
```

Trong `.env` đặt:

```dotenv
RAG_MODE=live
MONGO_URI=mongodb://localhost:27017
MONGO_DB=medical_rag
QDRANT_URL=http://localhost:6333
EMBEDDING_DEVICE=cpu
```

Sau đó chạy:

```bat
set RAG_MODE=live
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

`start-demo.bat` luôn dùng chế độ demo, không dùng file này để chạy live. Biến môi trường CMD ưu tiên hơn `.env`.

- Lần đầu cần tải model từ Hugging Face; server chỉ sẵn sàng khi tải xong và tạo index thành công.
- Model mặc định: `intfloat/multilingual-e5-base`, revision cố định trong `.env.example`, 768 chiều, cosine, vector chuẩn hóa.
- E5 dùng prefix `query: ` và `passage: ` cho cả tiếng Việt. Chunking dùng chính tokenizer của model, tính cả prefix, tiêu đề và special tokens trong giới hạn 512.
- Không cắt ngầm dữ liệu vượt giới hạn. Tiêu đề/mệnh đề quá dài trả lỗi để sửa dữ liệu đầu vào.
- Mặc định CPU. Chỉ đặt `EMBEDDING_DEVICE=cuda` khi PyTorch trong venv đã nhận GPU (`torch.cuda.is_available()` là True).
- Demo/live dùng kho riêng. Chuyển live cần import JSON lại.
- `docker compose stop` dừng DB mà giữ volumes. Docker chỉ bind cổng localhost.

## Chức năng và hợp đồng dữ liệu

Input giữ cấu trúc `schema_version: "1.0"`, `document`, `entities`, `relations`, `propositions`. Có schema tham khảo tại `examples/input.schema.json`. Trường bổ sung trong JSON được giữ lại, không ép các loại entity/relation sang ontology khác.

- Validate schema, ID trùng, entity/source/target, proposition_ids và evidence.sentence_id.
- `dry_run`: tạo chunk/báo cáo nhưng không ghi DB và không encode vector. Live vẫn tải model/tokenizer để đếm token đúng.
- Không gộp các section; tách text dài, ưu tiên dấu kết câu gần ranh giới.
- Target 450 token, overlap tối đa 80, giảm overlap cho chunk nhỏ để tránh lặp vô hạn.
- Giữ text nguồn và `source_spans`: sentence_id, paragraph_id, start_char, end_char. Offsets theo ký tự Unicode Python, end-exclusive; câu được nối bằng xuống dòng.
- `embedding_text` của chunk = tiêu đề tài liệu + tiêu đề mục + text; proposition được embed riêng.
- Hai Qdrant collections: `medical_rag_chunks`, `medical_rag_propositions`.
- Proposition nhận entity_ids/relation_ids từ các relation tham chiếu nó.
- Search lọc metadata và trả nội dung cùng ID nguồn; không có LLM sinh câu trả lời, BM25 hoặc reranker trong bản này.

File mẫu có 112 sections, 439 paragraphs, 439 sentences, 114 entities, 128 relations và 128 propositions. Cấu hình demo mặc định tạo 125 chunks + 128 propositions. Số chunk live có thể khác vì tokenizer E5 khác bộ đếm demo.

## Index tự tạo khi khởi động live

| MongoDB collection | Index |
|---|---|
| rag_documents | document_id unique |
| rag_sources | revision unique; document_id |
| rag_sentences | (revision, sentence_id) unique; (document_id, revision) |
| medical_rag_chunks | (revision, logical_id) unique; (document_id, revision); (revision, chunk_index); section_id; sentence_ids; proposition_ids |
| medical_rag_propositions | (revision, logical_id) unique; (document_id, revision); proposition_id; evidence_sentence_ids; entity_ids; relation_ids |

MongoDB giữ JSON nguồn, câu nguồn tách riêng và bản ghi chunk/proposition. Evidence lookup dùng index của rag_sentences. Chunk listing lọc/phân trang/sắp xếp trong MongoDB. Không tạo index content_hash vì hash được so sánh sau lookup revision.

Qdrant dùng vector cosine và cơ chế vector index mặc định. Tập nhỏ có thể được query planner quét trực tiếp thay vì HNSW. Payload keyword indexes:

- Chung: revision, document_id, language, document_type.
- Chunks: section_id, sentence_ids, proposition_ids.
- Propositions: proposition_id, evidence_sentence_ids, entity_ids, relation_ids.

## Import lại và phục hồi lỗi

Fingerprint bao gồm JSON đã validate, model/revision, cấu hình chunking và phiên bản chunker.

1. File/fingerprint không đổi: không encode và không thêm bản sao.
2. File thay đổi: tạo snapshot với revision mới, ghi đầy đủ MongoDB và Qdrant.
3. Chỉ sau khi ghi thành công mới đổi `rag_documents.active_revision` bằng một thao tác atomic.
4. Search chỉ lọc các revision active, không thấy dữ liệu staging/lỗi giữa chừng.
5. Sau activate mới dọn bản cũ. Nếu dọn lỗi, trả warning; import lại sẽ thử dọn tiếp.
6. Delete bỏ active pointer trước rồi dọn toàn bộ dữ liệu theo document; nếu lỗi dọn, gọi DELETE lại.

Logical chunk ID: `DOC_ID_CHUNK_000001`. Qdrant point ID là UUIDv5 từ **revision + logical_id** để bản mới không ghi đè vector đang hoạt động. Reindex chủ động tạo revision mới; IDs nguồn được giữ nguyên.

`actions.insert/update/skip/delete` mô tả thay đổi bản ghi logic. Bản v1 encode lại tất cả vector của snapshot khi tài liệu thay đổi để các snapshot độc lập; `vectors_written` báo số vector thực ghi. Import file không đổi thì không encode.

Đổi embedding cùng số chiều: reindex tất cả tài liệu trước khi search; hệ thống chặn trộn model. Đổi số chiều cần collection/database mới qua cấu hình/mã nguồn, không tự xóa collection cũ.

## API

Swagger: http://127.0.0.1:8000/docs

| Method | Path sau /api/v1/rag | Chức năng |
|---|---|---|
| GET | /health | Kết nối và chế độ |
| POST | /validate | Kiểm tra JSON |
| POST | /import-json?mode=dry_run | Xem trước |
| POST | /import-json | Import |
| GET | /documents?offset=0&limit=50 | Danh sách |
| GET | /documents/{id} | Metadata |
| GET | /documents/{id}/source | JSON nguồn |
| GET | /documents/{id}/chunks?offset=0&limit=20 | Chunk; thêm sentence_id để lọc |
| GET | /documents/{id}/evidence/{sentence_id} | Câu nguồn và các chunk liên quan |
| POST | /documents/{id}/reindex | Tạo lại chỉ mục |
| DELETE | /documents/{id} | Xóa dữ liệu RAG |
| GET | /stats | Thống kê active |
| POST | /search | Tìm kiếm |

CMD:

```bat
curl -X POST "http://127.0.0.1:8000/api/v1/rag/import-json?mode=dry_run" -H "Content-Type: application/json" --data-binary "@examples/DOC_000001.json"
curl -X POST "http://127.0.0.1:8000/api/v1/rag/import-json" -H "Content-Type: application/json" --data-binary "@examples/DOC_000001.json"
curl -X POST "http://127.0.0.1:8000/api/v1/rag/search" -H "Content-Type: application/json" --data-binary "@examples/search.json"
```

Search body: query, kind (`chunk`/`proposition`/`all`), top_k (1–50), filters. Filter hỗ trợ document_id, section_id, language, document_type, sentence_ids, evidence_sentence_ids, proposition_id, entity_ids, relation_ids. Chọn field phù hợp bản ghi: entity_ids có ở proposition. Field thiếu không match.

`kind=all` trộn kết quả cosine cùng model rồi lấy top K; chưa phải hybrid lexical–semantic/RRF. Điểm tương đồng không phải xác suất chính xác.

## Mã nguồn và kiểm thử

- app/core.py: schema, validation, tokenizer/encoder, chunking, offsets, hash/UUID.
- app/storage.py: SQLite, MongoDB/Qdrant, index, staging, queries.
- app/service.py: điều phối import, snapshot, search, delete.
- app/main.py: FastAPI và phục vụ giao diện.
- app/static/: HTML/CSS/JS, không cần Node/Vite, không phụ thuộc CDN.
- tests/: kiểm thử core/API, file mẫu, adapter Qdrant local + mongomock.

```bat
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest -q
```

Xem TEST_REPORT.md để biết phạm vi đã kiểm chứng.

Bản v1 dành cho demo/nghiên cứu cục bộ: **một Uvicorn process, một worker**, không chạy hai instance cùng ghi DB. Lock trong tiến trình giữ import/delete/search nhất quán; chưa có distributed lock/job queue/authentication. Import và reindex chạy đồng bộ, các thao tác DB liên quan chờ lock. Triển khai nhiều người dùng cần bổ sung các thành phần này.

JSON tối đa 8 MiB; Mongo source kiểm tra BSON tối đa 15 MiB. UI hiển thị tối đa 200 tài liệu/chunk một lần; API hỗ trợ phân trang. Chưa benchmark tải hoặc đánh giá chất lượng retrieval y khoa.

Nguồn kỹ thuật:
- https://qdrant.tech/documentation/manage-data/indexing/
- https://qdrant.tech/documentation/concepts/points/
- https://huggingface.co/intfloat/multilingual-e5-base
