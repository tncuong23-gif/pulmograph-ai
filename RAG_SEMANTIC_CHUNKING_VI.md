# RAG — semantic chunking theo section

## Thay đổi

RAG live mặc định chia đoạn theo độ tương đồng ngữ nghĩa giữa các câu nguồn trong từng section. Dùng lại `intfloat/multilingual-e5-base` của dự án, không thêm model/LLM hoặc dependency. Giao diện teal, VieNeu và các luồng chat/đánh giá được giữ.

JSON đầu vào vẫn là schema `1.0`: `document.sections[].paragraphs[].sentences[]`, kèm `entities`, `relations`, `propositions`. ID và văn bản nguồn không được viết lại. Các section vẫn là danh sách hiện tại; bản này không bổ sung duyệt `children` lồng nhau.

## Cách chia

1. Thu thập các câu theo thứ tự trong mỗi section và ghi vị trí ký tự của từng câu/paragraph.
2. Câu vượt trần được chia thành các mảnh liên tiếp, giữ đủ ký tự và ID nguồn; ưu tiên dấu câu/khoảng trắng. Mảnh nguồn vẫn phải vừa ngân sách token và cửa sổ embedding.
3. E5 embedding câu/mảnh câu theo batch tối đa 32 đầu vào, dùng tiền tố `query:` cho phép so sánh ngữ nghĩa đối xứng. Vector dùng để tìm ranh giới chỉ ở bộ nhớ, không thêm collection database.
4. Ở ranh giới giữa các câu nguồn khác nhau, lấy trung bình vector của tối đa `window` câu ở mỗi phía, chuẩn hóa rồi tính khoảng cách `1 - cosine_similarity`.
5. Ngưỡng trong section là giá trị lớn hơn giữa percentile của các khoảng cách và `min_distance`. Tách khi khoảng cách đạt ngưỡng và đáp ứng mức tối thiểu mềm; không tự ép mọi section phải có điểm tách ngữ nghĩa.
6. Nếu một nhóm cùng chủ đề vượt trần, tách an toàn tại ranh giới câu/mảnh. Không ghép xuyên section. Semantic mode không overlap giữa các chunk; nội dung ghép lại đúng nguyên văn section, kể cả khoảng trắng và xuống dòng.
7. Embedding các chunk cuối với tiền tố `passage:` và tiêu đề tài liệu/section, lưu MongoDB/Qdrant như trước. Mệnh đề vẫn được embedding riêng theo ID/evidence gốc, không áp dụng thuật toán chia chunk này cho mệnh đề.

Trong JSON, mỗi `sentence` là một đơn vị nguồn. Các mảnh của cùng một sentence ID chỉ bị tách vì trần, không tự đánh dấu là chuyển chủ đề. Khả năng phát hiện chuyển ý phụ thuộc chất lượng câu nguồn và embedding; bản này không gọi LLM để tái viết hay phân tích tài liệu.

## Cập nhật dự án đang chạy

Dừng backend trước khi chép mã nguồn. Giữ `.env`, `venv`/`.venv`, `node_modules`, thư mục `data` và dữ liệu Docker. Các file runtime đổi/thêm từ bản VieNeu ngay trước bản này:

```text
backend/app/modules/rag/core.py                 chép đè
backend/app/modules/rag/chunking.py             thêm mới
backend/app/modules/rag/service.py              chép đè
backend/app/modules/rag/main.py                 chép đè
backend/app/modules/rag/static/index.html       chép đè
backend/app/modules/rag/static/app.js           chép đè
```

Chép các tài liệu/bộ kiểm thử đi kèm nếu muốn giữ đủ bộ nguồn. Không cần cài lại npm hoặc thư viện Python cho thay đổi chunking này. `.env.example` là mẫu; sửa các dòng RAG trong `.env` đang dùng, không ghi đè cấu hình database bằng mẫu:

```dotenv
RAG_MODE=live
RAG_CHUNK_METHOD=semantic
RAG_CHUNK_TOKENS=450
RAG_CHUNK_OVERLAP=80
RAG_SEMANTIC_PERCENTILE=90
RAG_SEMANTIC_MIN_DISTANCE=0.05
RAG_SEMANTIC_MIN_TOKENS=80
RAG_SEMANTIC_WINDOW=2
```

Không để các biến trùng tên. `RAG_CHUNK_OVERLAP` chỉ áp dụng khi chọn chế độ token. Trong semantic mode nó không tạo overlap. `RAG_CHUNK_TOKENS` là trần token nội dung; giới hạn thực tế còn tính tiêu đề, tiền tố và special tokens của model. Câu/proposition cuối vẫn được kiểm tra trước khi embedding, không cho model tự truncate âm thầm.

| Biến | Ý nghĩa và cách chỉnh |
|---|---|
| `RAG_CHUNK_METHOD` | `semantic` dùng E5 tìm điểm chuyển chủ đề; `token` dùng cửa sổ token cũ |
| `RAG_CHUNK_TOKENS` | Trần nội dung, mặc định 450; không phải độ dài bắt buộc của semantic chunk |
| `RAG_SEMANTIC_PERCENTILE` | 0–100, mặc định 90; giảm để xét nhiều điểm tách hơn, tăng để xét ít điểm hơn |
| `RAG_SEMANTIC_MIN_DISTANCE` | Sàn khoảng cách 0–2, mặc định 0.05; tăng để tránh tách các câu gần nhau |
| `RAG_SEMANTIC_MIN_TOKENS` | Mức tối thiểu mềm trước điểm tách và phần còn lại, mặc định 80; giảm nếu cần các chunk ngắn hơn |
| `RAG_SEMANTIC_WINDOW` | 1–8, mặc định 2; số vector ở mỗi phía để làm mượt ngữ cảnh |

Các giá trị mặc định là cấu hình khởi điểm, chưa được hiệu chỉnh bằng bộ đánh giá tài liệu y khoa của bạn. Đổi một biến rồi xem trước/đối chiếu chunk, không suy ra chất lượng từ số chunk tăng hay giảm.

`RAG_EMBEDDING_DEVICE=auto` dùng cơ chế CPU/CUDA hiện có của dự án. Việc model có chạy GPU phụ thuộc môi trường PyTorch và VRAM; thay đổi chunking không cài lại PyTorch. Classifier và RAG tiếp tục dùng chung E5 khi cấu hình model/revision/device trùng nhau.

Chạy lại backend:

```bat
python -m uvicorn app.main:app --host 127.0.0.1 --port 8100 --workers 1
```

## Kiểm tra trước khi nạp

Mở [giao diện RAG](http://127.0.0.1:8100/modules/rag/). Luồng xử lý phải ghi “Chia đoạn theo ngữ nghĩa”. API:

```bat
curl http://127.0.0.1:8100/modules/rag/api/v1/rag/health
```

Kiểm tra `chunking.method` bằng `semantic`. Nếu `RAG_MODE=demo`, encoder là vector từ khóa nên phương thức thực tế là `token` với `fallback_reason=encoder_not_semantic`; demo không được gọi là semantic chunking. Chọn live để dùng E5 thật.

Nạp một JSON bằng **Xem trước**. API tương đương, chạy từ CMD ở thư mục có `tai_lieu.json`:

```bat
curl -X POST "http://127.0.0.1:8100/modules/rag/api/v1/rag/import-json?mode=dry_run" -H "Content-Type: application/json" --data-binary "@tai_lieu.json"
```

Dry-run có tính embedding để quyết định ranh giới, nhưng chưa ghi MongoDB/Qdrant. Báo cáo có `chunking`, `chunking_summary`, preview tối đa 3 record. Các chunk có:

- `chunk_method`: kiểu chia thực tế.
- `boundary_reason`: `semantic`, `token_limit` hoặc `section_end`.
- `boundary_distance`, `semantic_threshold`: để kiểm tra điểm tách, không phải xác suất nội dung đúng.
- `source_spans`: `sentence_id`, `paragraph_id`, `start_char`, `end_char`; vị trí tính theo ký tự Python trong câu nguồn, không phải byte UTF-8.
- `sentence_ids`, `proposition_ids`: liên kết tới nguồn và mệnh đề.

Nếu phù hợp, nhấn **Import tài liệu** hoặc đổi `mode=commit`. JSON input API vẫn tối đa 8 MiB. Tài liệu/tiêu đề/proposition vượt giới hạn sẽ báo lỗi để sửa; không âm thầm xóa bớt nguồn.

## Reindex dữ liệu đã nạp

Đổi cấu hình không tự sửa database. Tài liệu cũ tiếp tục được truy vấn bằng cùng encoder, được đánh dấu “Cần reindex để áp dụng cấu hình mới” trong **Kho tài liệu**. Nếu đổi cả encoder, cơ chế kiểm tra model cũ vẫn yêu cầu reindex trước khi tìm kiếm.

1. Mở **Kho tài liệu**, kiểm tra tài liệu cần cập nhật.
2. Nhấn **Reindex** từng tài liệu. Hệ thống dùng JSON gốc đã lưu ở MongoDB, xây chunk/vector mới; không cần tạo lại JSON KG.
3. Khi hoàn tất, kiểm tra **Xem đoạn**, mở lại câu evidence và thử câu hỏi truy xuất. Nhãn “Cần reindex” phải hết.

Ví dụ API cho một tài liệu:

```bat
curl -X POST "http://127.0.0.1:8100/modules/rag/api/v1/rag/documents/DOC_000001/reindex"
```

Danh sách ID: `GET /modules/rag/api/v1/rag/documents?offset=0&limit=200`. API phân trang; giao diện hiện tối đa 200 tài liệu đầu. Để kiểm tra số còn lại, gọi `/stats` và xem `needs_reindex`. Muốn lưu bản JSON nguồn trước khi reindex, dùng `/documents/{id}/source`.

Mỗi import tạo snapshot mới và chỉ kích hoạt khi ghi xong. Nếu lỗi trước kích hoạt, snapshot đang hoạt động được giữ. Sau khi thành công, dữ liệu RAG của revision cũ được dọn theo cơ chế hiện có. Không ghi lại Neo4j/KG và không sửa Patient Graph.

Muốn quay về kiểu chia theo size: đặt `RAG_CHUNK_METHOD=token`, khởi động lại backend và reindex các tài liệu cần đổi. Import cùng JSON/cấu hình/model không đổi sẽ được skip; đổi thuật toán/ngưỡng tạo fingerprint mới để không skip nhầm.

## Đối chiếu chất lượng và thời gian

Semantic chunking thêm lượt embedding câu khi import/dry-run/reindex. Không chạy lượt này ở mỗi câu hỏi người dùng; truy vấn vẫn tìm vector đã lập chỉ mục. Chưa có benchmark E5/VRAM hoặc đánh giá retrieval trên kho thật của bạn. Cần so sánh câu hỏi, nguồn và evidence của hai cấu hình trên cùng tài liệu trước khi kết luận phương án nào tốt hơn.

Kiểm thử và giới hạn: [RAG_SEMANTIC_TEST_REPORT.md](RAG_SEMANTIC_TEST_REPORT.md). Model card E5 giải thích tiền tố, giới hạn và cách đọc điểm tương đồng: https://huggingface.co/intfloat/multilingual-e5-base .
