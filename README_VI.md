> **Rà soát mới nhất 12/10/2026:** 463 kiểm thử backend đạt, 87 frontend đạt, build thành công. Đã sửa lỗi đóng gói, truy vấn mẫu KG, nguồn và retry Clinical. Đọc [VERIFIED_UPDATE_VI.md](VERIFIED_UPDATE_VI.md) trước khi cập nhật.

> **Bằng chứng và nguồn đánh số:** bộ lọc trước Ollama, nguồn [1]/[2] có thẻ xem nhanh/bảng đọc nguồn, lưu nguồn theo tin nhắn/job. Xem [EVIDENCE_SOURCES_UPDATE_VI.md](EVIDENCE_SOURCES_UPDATE_VI.md) để ghi đè và đọc giới hạn kiểm chứng.

> **Xác nhận bệnh nhân theo từng bước (12/10/2026):** câu vừa khai → chọn dữ kiện Patient Graph riêng → hỏi bổ sung từ KG → xem lại trước khi đánh giá. Xem [PATIENT_REVIEW_UPDATE_VI.md](PATIENT_REVIEW_UPDATE_VI.md) để ghi đè và xử lý lượt cũ.

> **Clinical IE v14:** ba luồng văn bản/TXT, X-quang và kết hợp; API và giao diện đã nối. **Thiếu hai trọng số NLP trong module bàn giao**, cần bổ sung trước khi dùng TXT/kết hợp. Đọc [CLINICAL_MULTIMODAL_UPDATE_VI.md](CLINICAL_MULTIMODAL_UPDATE_VI.md) để ghi đè và chạy dịch vụ mới.

> **KG v13 (11/10/2026):** model `Dqdung205/medical_vietnamese_embedding`, giữ tất cả ứng viên theo tài liệu, dấu Đã duyệt bền vững và nạp theo lô tối ưu. **Cần kích hoạt model và tạo chỉ mục KG mới một lần.** Xem [KG_REVIEW_UPDATE_VI.md](KG_REVIEW_UPDATE_VI.md), [KG_REVIEW_TEST_REPORT.md](KG_REVIEW_TEST_REPORT.md). Patch áp dụng trên v12; không cần cài lại dự án.

> **So sánh KG trong chat v12 (11/10/2026):** so sánh hai bệnh/thuốc theo tiêu chí, tìm điểm chung hoặc khác biệt trong dữ liệu; bảng đối chiếu, điều kiện/phủ định và nguồn ở từng bên. Hướng dẫn ghi đè v11: [KG_COMPARE_UPDATE_VI.md](KG_COMPARE_UPDATE_VI.md). Kiểm thử: [KG_COMPARE_TEST_REPORT.md](KG_COMPARE_TEST_REPORT.md). Không cần cài lại thư viện hoặc nạp/index lại dữ liệu chỉ vì cập nhật này.

> **KG trong chat v11 (11/10/2026):** nhận diện tên/bí danh, xác nhận tên mơ hồ, chọn 1-hop / multi-hop / path và xem nguồn trong chat. Hướng dẫn cập nhật: [KG_CHAT_UPDATE_VI.md](KG_CHAT_UPDATE_VI.md). Kiểm thử: [KG_CHAT_TEST_REPORT.md](KG_CHAT_TEST_REPORT.md).

> **Giao diện quản lý dữ liệu thống nhất (10/10/2026):** mở **Quản lý dữ liệu** trong frontend hoặc `http://127.0.0.1:8100/data`. Hướng dẫn ghi đè: [DATA_WORKSPACE_UPDATE_VI.md](DATA_WORKSPACE_UPDATE_VI.md). Kết quả kiểm tra: [DATA_WORKSPACE_TEST_REPORT.md](DATA_WORKSPACE_TEST_REPORT.md).

# Bản cập nhật trang giới thiệu và trợ lý giọng nói

**Nạp nhiều file KG và Context (10/10/2026):** [BATCH_IMPORT_KG_CONTEXT_VI.md](BATCH_IMPORT_KG_CONTEXT_VI.md) hướng dẫn ghi đè, xem trước/xác nhận, báo cáo từng file, retry riêng bước vector và JSON nguồn Context. Mở mục **Quản lý dữ liệu → KG / Context & Patient → Nạp dữ liệu** trong frontend; `/imports` vẫn hoạt động. Kết quả kiểm thử: [BATCH_IMPORT_TEST_REPORT.md](BATCH_IMPORT_TEST_REPORT.md).

**Giọng nói v2 (mới nhất):** [VOICE_V2_UPDATE_VI.md](VOICE_V2_UPDATE_VI.md) hướng dẫn ghi đè, dùng PhoWhisper cho tiếng Việt, nhận dạng lại kỹ hơn, phát trọn câu ngắn, cache phát lại và VieNeu GPU. [VOICE_V2_TEST_REPORT.md](VOICE_V2_TEST_REPORT.md) ghi kết quả kiểm thử và các giới hạn chưa đo trên máy thực. Bản vá v2 là bản cộng dồn.

**Cập nhật giọng nói trước v2: STT và bộ đệm phát.** Xem [VOICE_QUALITY_UPDATE_VI.md](VOICE_QUALITY_UPDATE_VI.md) để ghi đè các file vào dự án hiện có mà không cài lại. STT mặc định `large-v3-turbo`/CPU/int8, có cảnh báo cần kiểm tra transcript; bộ phát chuẩn bị trước tối đa hai câu và nối PCM theo đồng hồ âm thanh. Báo cáo: [VOICE_QUALITY_TEST_REPORT.md](VOICE_QUALITY_TEST_REPORT.md).

**RAG mới nhất: nạp thư mục theo yêu cầu và tải nhiều JSON một lượt.** Không tự nạp khi backend khởi động; bỏ qua tài liệu không đổi, tiếp tục sau file lỗi và xuất báo cáo JSON/CSV. Xem [RAG_BATCH_IMPORT_VI.md](RAG_BATCH_IMPORT_VI.md) để cập nhật và chạy trên Windows; kết quả kiểm thử: [RAG_BATCH_TEST_REPORT.md](RAG_BATCH_TEST_REPORT.md).

**RAG: semantic chunking theo từng section.** Xem [RAG_SEMANTIC_CHUNKING_VI.md](RAG_SEMANTIC_CHUNKING_VI.md) để cập nhật cấu hình, kiểm tra chunk và reindex tài liệu cũ. Báo cáo ở thời điểm thêm semantic: [RAG_SEMANTIC_TEST_REPORT.md](RAG_SEMANTIC_TEST_REPORT.md). Gói tiếp tục gồm giao diện teal và VieNeu-TTS cục bộ.

**Giao diện mới nhất: teal.** Xem [UI_TEAL_UPDATE_VI.md](UI_TEAL_UPDATE_VI.md) để biết bảng màu, ảnh mới, cách cài frontend và kết quả kiểm thử. Gói có backend/frontend đầy đủ và bản sửa dependency npm đã kiểm chứng.

**Giọng nói mới nhất: VieNeu-TTS v3 Turbo chạy cục bộ.** Xem [VOICE_VIENEU_GUIDE_VI.md](VOICE_VIENEU_GUIDE_VI.md) để cài môi trường TTS riêng và cập nhật `.env`. Lời thoại được soạn trong cùng lượt LLM và phát từng câu ngay khi có âm thanh. Kết quả kiểm tra ở [VOICE_TEST_REPORT.md](VOICE_TEST_REPORT.md).

---

> Cập nhật luồng chẩn đoán tương tác: đọc **DIAGNOSTIC_WORKFLOW_VI.md** trước khi nâng cấp. Gói có backend và frontend đầy đủ, đã nối xác nhận dữ kiện, Patient Graph và câu hỏi KG.

# Medical AI — Backend tích hợp Context, RAG và KG

## Bản này làm gì?

Đây là backend hoàn chỉnh, gồm backend điều phối + model phân lớp E5_SVM_seed456.joblib + mã nguồn Context v2.3 + Medical RAG + KG Import/Query/Explorer.
Context, RAG và KG chạy cùng tiến trình Python trên cổng **8100**. Backend gọi các ứng dụng ASGI trực tiếp trong bộ nhớ qua HTTPX ASGITransport; không mở server riêng ở 8003/8004/8005.

Clinical IE vẫn chạy riêng ở cổng **8002**. Bản v14 có mã nguồn engine, adapter HTTP và checkpoint ảnh; còn thiếu hai trọng số NLP nêu trong hướng dẫn v14. Ollama, Neo4j, MongoDB và Qdrant cũng tiếp tục là các dịch vụ riêng.

Gói `medical-ai-record-only-mode-fix(1).zip` là bản vá 11 file, không phải backend đầy đủ. Bản này đã ghép bản vá đó lên backend gốc và bản vá Clinical IE của dự án trước, nên không cần chép các bản vá backend cũ nữa. Hai gói Context đính kèm giống nhau từng byte; chỉ dùng một bản.

## 1. Chuẩn bị

- Python **3.11 trở lên**, hướng dẫn dưới dùng **3.12**. Module Context sử dụng `enum.StrEnum`, không chạy trực tiếp bằng Python 3.10.
- Các CSDL hiện có phải được khởi động. Gói mã nguồn không chứa dữ liệu nằm trong Docker volumes hoặc các CSDL đang chạy trên máy bạn.
- Ollama đã có `qwen2.5:7b`.
- Clinical IE v14: cài môi trường riêng bằng `backend/install_clinical_windows.bat`, rồi chạy `backend/start_clinical_windows.bat`. Xem hướng dẫn v14 về các trọng số còn thiếu.

Giải nén thành ví dụ `D:\medical_wed\medical-ai-integrated`. Hãy giữ backend cũ để đối chiếu cấu hình/dữ liệu.

## 2. Cài backend

Mở CMD:

```bat
cd /d D:\medical_wed\medical-ai-integrated\backend
py -3.12 -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
copy .env.example .env
notepad .env
```

Có thể dùng `setup_windows.bat` thay cho các bước tạo môi trường và cài thư viện.
Model E5 được tải khi khởi tạo RAG live hoặc lần đầu chạy classifier; lần đầu cần mạng hoặc model đã có trong cache.

**Điền URI, tên database và mật khẩu đúng với các module cũ.** Các cổng trong `.env.example` chỉ là giá trị mẫu. Không chép nguyên `.env` cũ vì các module có các biến trùng tên.

## 3. Chuyển cấu hình từ các module cũ

| Module | Tên trong `.env` cũ | Tên trong `.env` backend mới |
|---|---|---|
| Context | `GRAPH_BACKEND` | `CONTEXT_GRAPH_BACKEND` |
| Context | `NEO4J_URI` | `CONTEXT_NEO4J_URI` |
| Context | `NEO4J_USER` | `CONTEXT_NEO4J_USER` |
| Context | `NEO4J_PASSWORD`, `NEO4J_DATABASE` | `CONTEXT_NEO4J_PASSWORD`, `CONTEXT_NEO4J_DATABASE` |
| Context | `NLP_BACKEND` | `CONTEXT_NLP_BACKEND` |
| Context | `OLLAMA_BASE_URL`, `OLLAMA_MODEL` | `CONTEXT_OLLAMA_BASE_URL`, `CONTEXT_OLLAMA_MODEL` |
| Context | `EMBEDDING_BACKEND` | `CONTEXT_EMBEDDING_BACKEND` |
| RAG | `RAG_MODE` | `RAG_MODE` |
| RAG | `MONGO_URI`, `MONGO_DB` | `RAG_MONGO_URI`, `RAG_MONGO_DB` |
| RAG | `QDRANT_URL`, `QDRANT_API_KEY` | `RAG_QDRANT_URL`, `RAG_QDRANT_API_KEY` |
| RAG | `EMBEDDING_MODEL`, `EMBEDDING_REVISION`, `EMBEDDING_DEVICE` | Thêm tiền tố `RAG_` vào từng tên |
| RAG | `CHUNK_TOKENS`, `CHUNK_OVERLAP`, `DEMO_DB` | Thêm tiền tố `RAG_` vào từng tên |
| KG | `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE` | Thêm tiền tố `KG_` vào từng tên |
| KG | `MONGODB_URI`, `MONGODB_DATABASE`, `QDRANT_URL` | Thêm tiền tố `KG_` vào từng tên |
| KG | `KG_ONTOLOGY_PATH` | Giữ tên; đường dẫn mới `examples/kg/kg_ontology.example.json` |
| KG | Các biến `KG_ENTITY_*` | Giữ tên |
| Backend | `CLINICAL_IE_BASE_URL`, `OLLAMA_*` | Giữ tên |

Tất cả biến Context đều dùng tiền tố `CONTEXT_`, kể cả các tùy chọn chưa liệt kê trong bảng.
`CONTEXT_BASE_URL`, `RAG_BASE_URL`, `KG_BASE_URL` cũ không còn được sử dụng trong cấu hình backend tích hợp.

Nếu module RAG cũ đang dùng `RAG_MODE=demo`, dữ liệu nằm trong SQLite `DEMO_DB`. Chuyển file đó và cấu hình `RAG_MODE=demo`, `RAG_DEMO_DB=<đường dẫn>`, hoặc nhập lại tài liệu qua RAG live. Không dùng các vector lexical demo làm vector E5.

Nếu muốn giữ lịch sử/attachments của backend: khi backend cũ đã dừng, sao lưu và chép thư mục `data` của backend cũ vào `backend/data` mới. SQLite được bổ sung cột khi cần. Cột `stored_path` của file upload cũ có thể là đường dẫn tuyệt đối; cần giữ file tại vị trí đó hoặc cập nhật đường dẫn trước khi sử dụng. Không tự sửa/xóa dữ liệu CSDL của các module.

## 4. Chạy

```bat
python -m uvicorn app.main:app --host 127.0.0.1 --port 8100 --workers 1
```

Hoặc chạy `run_backend.bat`. Dùng **1 worker** để tránh nạp nhiều bản model.

| Địa chỉ | Chức năng |
|---|---|
| http://127.0.0.1:8100/ | Trang liên kết quản lý backend |
| http://127.0.0.1:8100/docs | API website |
| http://127.0.0.1:8100/api/v1/status | Trạng thái dependencies |
| http://127.0.0.1:8100/modules/context/ui | Kiểm tra Context, History, Patient |
| http://127.0.0.1:8100/modules/context/docs | API Context |
| http://127.0.0.1:8100/modules/rag/ | Nhập và tìm kiếm tài liệu RAG |
| http://127.0.0.1:8100/modules/rag/docs | API RAG |
| http://127.0.0.1:8100/modules/kg-explorer/ | KG Explorer, import và rà soát thực thể |
| http://127.0.0.1:8100/modules/kg/docs | API KG Retrieval + Import + Validate |

API Context vẫn có `/v1/context/resolve` và `/v1/history/turns` nhưng thêm `/modules/context` phía trước khi gọi từ ngoài.
API RAG thêm `/modules/rag`; API KG thêm `/modules/kg`.
Ví dụ: `POST http://127.0.0.1:8100/modules/kg/api/v1/kg/query`.

Nếu một module khởi tạo lỗi, log có `module.startup_failed name=...`. Module đó trả HTTP 503; backend vẫn phục vụ các module đã khởi tạo thành công. Sửa cấu hình/kết nối và khởi động lại backend. `mode=live` trong status cho biết đang dùng backend thật; `health=degraded` báo dependency chưa sẵn sàng. `ragMode` báo riêng RAG live/demo.

## 5. Kết nối website hiện có

Dùng thư mục `frontend` đầy đủ trong gói này. Chạy `npm ci` rồi `npm run dev` từ thư mục đó. Gói không kèm `frontend-patch` cũ; không chép bản vá đó lên mã nguồn mới. Xem `UI_TEAL_UPDATE_VI.md` về màu sắc, ảnh và kiểm thử khung nhập hội thoại.
Điền vào `.env` frontend:

```dotenv
VITE_USE_MOCK_API=false
VITE_API_BASE_URL=http://127.0.0.1:8100
VITE_CHAT_TIMEOUT_MS=600000
VITE_FILE_PROCESSING_TIMEOUT_MS=600000
```

Khởi động lại Vite hoặc build lại frontend. Trang http://127.0.0.1:8100/ là trang quản lý backend; trang chat vẫn chạy ở cổng frontend.
Bệnh án chỉ được upload/xử lý khi nhấn Gửi. File được gỡ khỏi khung soạn sau khi gửi; giao diện hiển thị biểu tượng đang xử lý. Khi đang chọn file, ô nhập text bị khóa.

## 6. Luồng xử lý

| Đầu vào/nhãn | Luồng |
|---|---|
| Chat text | Context → E5/SVM → module theo nhãn → Qwen → website |
| `DIAGNOSTIC_ASSESSMENT` | Xác nhận dữ kiện → câu hỏi KG → xác nhận snapshot → Clinical IE `/api/v1/ask-symptoms` → Qwen |
| `GENERAL_MEDICAL_QUERY` | RAG search |
| `RELATIONAL_QUERY` | KG query |
| `CLINICAL_EXPLANATION_MANAGEMENT` | RAG + KG |
| `OUT_OF_SCOPE` | Phản hồi ngoài phạm vi |
| Văn bản/TXT, X-quang hoặc kết hợp (v14) | Backend `/api/v1/clinical/analyze` → dịch vụ Clinical IE `/api/v1/analyze` → trình bày JSON; bỏ qua Context và phân lớp |

Backend vẫn dùng `conversationId` cho cả `patient_id` và `session_id`, đúng với thiết kế hiện tại. Mỗi cuộc trò chuyện có phạm vi dữ liệu riêng; chưa có ánh xạ tài khoản thật sang bệnh nhân dùng chung nhiều phiên.

## 7. Nguồn thực thể trong graph Context — kết luận từ source

Mã `app/modules/context/application/service.py` gọi clinical extractor (Qwen khi NLP backend là Ollama), đưa `clinical_candidates` vào `RuleBasedDiscourseEntityExtractor`, rồi lưu lượt người dùng ngay trong `/v1/context/resolve`.
Trong source gốc, các clinical candidates được đưa vào History **trước** Patient Assertion Gate. Gate bảo vệ Patient Graph, nhưng không loại các candidate đó khỏi History. Vì vậy Qwen có thể tạo các tên triệu chứng không có trong câu hỏi và chúng vẫn được lưu thành Mention/DiscourseEntity.

Bản này chỉ nhận clinical candidate vào History khi tên của nó có vị trí thực trong câu gốc, lưu `text/start/end/origin`. Tham chiếu đã phân giải được ghép riêng qua `resolved_reference`. Bổ sung nhận diện dạng “Các dấu hiệu của covid19” để lưu chủ đề `covid19`. Kiểm thử đã giả lập Qwen sinh `ho/sốt/mất khứu giác` cho câu hỏi trên và xác nhận chỉ chủ đề `covid19` đi vào History, không ghi fact bệnh nhân.

Repository Neo4j tạo chuỗi `Session → HAS_TURN → Turn → MENTIONS → Mention → REFERS_TO → DiscourseEntity`.
Backend gửi câu trả lời cuối qua `/v1/history/turns`; endpoint đó trích xuất discourse bằng luật từ chính nội dung câu trả lời, không chạy clinical extractor để ghi Patient Graph.

Thay đổi áp dụng cho lượt mới. Dữ liệu sai đã lưu trước đó không được tự xóa; hãy thử một cuộc trò chuyện mới để đối chiếu.
Chưa có dữ liệu Neo4j thực tế của bạn để xác nhận các node trong ảnh cũ thuộc lượt nào. Có thể xem nguồn bằng:

```cypher
MATCH (t:Turn)-[:MENTIONS]->(m:Mention)-[:REFERS_TO]->(e:DiscourseEntity)
WHERE t.id = 'e16b2c8d-60b3-4e52-9158-28ba19427731'
RETURN t.original_text, t.normalized_text, t.role, t.session_id,
       m.text, m.origin, m.start, m.end, e.canonical_name;
```

## 8. Xem kết quả phân lớp và truy xuất

- Console: `context.resolve`, `chat.stage stage=classification route=...`, `retrieval.result` có document/chunk IDs và scores.
- Bật `TRACE_PIPELINE=true` trong `.env` rồi khởi động lại để log thêm câu gốc/câu đã chuẩn hóa. Tắt lại sau khi kiểm tra vì log có thể chứa nội dung người dùng.
- Response chat: `message.metadata.classifier`, `resolved_question`, `context_resolution`, `sources` trên luồng trả lời thông thường.
- Context vẫn có thể gọi Qwen clinical extractor ngay cả khi câu hỏi không cần phân giải; `not_needed` chỉ bỏ qua Qwen question resolver. Đây là lý do Context vẫn có thể mất thời gian ở câu hỏi tự đủ nghĩa.

Việc ghép module không bổ sung tài liệu COVID vào RAG. Nếu CSDL chỉ có tài liệu COPD, cần nhập tài liệu đúng chủ đề. Đã tăng ràng buộc prompt không tóm tắt tài liệu lạc đề, và khi RAG trả rỗng backend không gọi Qwen sinh câu trả lời; chất lượng chọn tài liệu vẫn cần kiểm tra trên kho thật của bạn.

## 9. CPU/GPU và bộ nhớ

`CLASSIFIER_DEVICE=auto` và `RAG_EMBEDDING_DEVICE=auto` chọn CUDA khi PyTorch hỗ trợ CUDA, ngược lại CPU. E5 được dùng chung khi model/revision/device trùng nhau. Phần SVM của scikit-learn vẫn chạy CPU; Qwen do Ollama quản lý GPU.

```bat
python -c "import torch; print(torch.__version__); print(torch.cuda.is_available())"
```

Bản PyTorch hậu tố `+cpu` sẽ không chạy CUDA. GPU 8 GB phải chia bộ nhớ cho E5 và Ollama; nếu hết VRAM, đặt cả hai embedding device về `cpu` để dành GPU cho Qwen. Chưa kiểm thử GPU/VRAM trên máy bạn.

## 10. Kiểm thử

Chi tiết trong `TEST_REPORT.md`. Chạy lại:

```bat
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Kiểm thử tự dùng Context memory, RAG SQLite lexical và các dependency giả lập. Không chạy vào CSDL thật của bạn.
Mã KG lập chỉ mục thực thể giữ tại `backend/scripts/kg`; sau khi cấu hình đúng có thể chạy `python -m scripts.kg.index_entities`.
