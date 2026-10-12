# Nạp nhiều file vào KG và Context

> **KG v13:** xem [KG_REVIEW_UPDATE_VI.md](KG_REVIEW_UPDATE_VI.md) để cập nhật model/dependency và tạo chỉ mục mới. Các bước ghi đè gói batch cũ bên dưới là lịch sử; v13 dùng `medical-ai-kg-review-patch.zip`.

> Giao diện chung mới: **Quản lý dữ liệu** tại `http://127.0.0.1:8100/data`. Các chức năng bên dưới có trong nhóm tương ứng; xem [DATA_WORKSPACE_UPDATE_VI.md](DATA_WORKSPACE_UPDATE_VI.md) để cập nhật.

Bản cập nhật ngày 10/10/2026, bổ sung trên bản có Voice v2/PhoWhisper. Gói đầy đủ chứa cả frontend teal, các chức năng giọng nói và RAG trước đó.

## 1. Phạm vi

| Luồng | Nguồn mặc định | Nơi ghi |
| --- | --- | --- |
| RAG hiện có | `backend/data/import/rag/` | MongoDB và Qdrant của RAG |
| KG mới | `backend/data/import/kg/` | MongoDB, Neo4j của KG; Qdrant tên thực thể khi đã bật |
| Context mới | `backend/data/import/context/` | Neo4j của Context: History và Patient Graph |

Nạp theo **cách 2**: người dùng bấm nút hoặc chạy CLI. Khởi động backend không tự nạp. Một file là một JSON object; hỗ trợ `.json`/`.JSON`, thư mục con, tối đa 20 MiB/file và 10.000 file/lượt cho hai luồng mới. Các nguồn này tách biệt với Docker volumes.

RAG vẫn sử dụng quy trình và giới hạn riêng tại [RAG_BATCH_IMPORT_VI.md](RAG_BATCH_IMPORT_VI.md).

## 2. Ghi đè vào dự án đang chạy

1. Dừng backend và frontend; sao lưu cấu hình, thư mục dữ liệu và CSDL đang dùng.
2. Giải nén `medical-ai-batch-import-patch.zip` vào một thư mục tạm.
3. Mở thư mục `medical-ai-integrated` bên trong ZIP. Chép các thư mục `backend`, `frontend` và các tài liệu đi kèm vào **thư mục gốc hiện có**:

   `D:\medical_wed\banzip\medical-ai-integrated`

4. Chọn thay thế các file trùng tên. Đừng tạo thêm một tầng `medical-ai-integrated/medical-ai-integrated`.
5. Danh sách chính xác nằm trong `BATCH_IMPORT_PATCH_FILES.txt`.

Bản vá dành cho bản nguồn mới nhất trước cập nhật này, đã có Voice v2/PhoWhisper. Nếu dùng bản cũ hơn, dùng ZIP đầy đủ để cập nhật mã nguồn và đối chiếu các hướng dẫn cập nhật trước đó.

ZIP không chứa `.env` thực, CSDL, dữ liệu nhập của bạn, `venv`, `.venv-vieneu`, `node_modules` hoặc các trọng số tải về. Các file này được giữ tại dự án đang chạy. Không chép `.env.example` đè `.env`. Bản cập nhật này không thay dependency Python/npm; môi trường hiện có không cần cài lại.

### Cấu hình để KG ghi đủ cả ba CSDL

Trong `backend/.env`, đặt đúng một dòng:

```dotenv
KG_ENTITY_EMBEDDING_ENABLED=1
```

Giữ URI, mật khẩu, tên database/collection đang dùng. Các khóa liên quan:

```dotenv
KG_QDRANT_URL=http://127.0.0.1:6333
KG_ENTITY_COLLECTION=kg_entity_names_medical_vi_v1
KG_ENTITY_MODEL=Dqdung205/medical_vietnamese_embedding
```

Trên bản cũ, khóa bật vector có thể đang là `0`. Khi tắt, báo cáo nêu rõ KG chỉ xử lý MongoDB và Neo4j; không báo đã đồng bộ Qdrant.

Context ghi bền vững khi `CONTEXT_GRAPH_BACKEND=neo4j` và các khóa `CONTEXT_NEO4J_*` kết nối đúng CSDL Context. `memory` chỉ dành cho thử nghiệm; báo cáo hiển thị chế độ này và dữ liệu mất khi tiến trình dừng. Dùng cấu hình embedding hiện có của Context.

### Khởi động

CMD backend:

```bat
cd /d D:\medical_wed\banzip\medical-ai-integrated\backend
venv\Scripts\activate
python -m uvicorn app.main:app --host 127.0.0.1 --port 8100 --workers 1
```

Nếu ổ C: thiếu chỗ cho bộ nhớ đệm model, đặt trước khi khởi động backend, trong cùng cửa sổ CMD:

```bat
set "HF_HOME=D:\AI_Cache\huggingface"
set "HF_HUB_CACHE=D:\AI_Cache\huggingface\hub"
```

Chạy **một backend, một worker** với thư mục dữ liệu này. Tác vụ đang chạy chặn lượt mới và tải đè file trong cùng module. Khi dừng nhẹ nhàng, backend chờ file hiện tại hoàn tất, đánh dấu phần còn lại gián đoạn.

Frontend ở CMD khác:

```bat
cd /d D:\medical_wed\banzip\medical-ai-integrated\frontend
npm run dev
```

Nếu phục vụ bản build: chạy `npm run build`, cập nhật `dist`, rồi tải lại trang. Thanh bên có nút **Nạp dữ liệu**, dùng địa chỉ backend cấu hình bởi `VITE_API_BASE_URL`. Nếu frontend dùng địa chỉ API tương đối, reverse proxy cần chuyển `/imports`, `/imports-assets/` và `/api/v1/imports/` về backend.

## 3. Giao diện

- KG: `http://127.0.0.1:8100/imports?module=kg`
- Context: `http://127.0.0.1:8100/imports?module=context`
- Liên kết RAG vẫn mở giao diện RAG hiện có.

Thực hiện:

1. **KG lần đầu:** bật vector như trên, khởi động lại backend, bấm **Chuẩn bị / đồng bộ chỉ mục KG**. Thao tác tạo collection khi chưa có và bổ sung tên thực thể đã tồn tại trong Neo4j. Nếu collection sai số chiều, xử lý cấu hình/model trước khi nạp; chức năng không tự xóa collection cũ.
2. Chọn nhiều JSON, kéo thả, hoặc chép nguồn vào thư mục rồi bấm **Xem trước toàn bộ thư mục**.
3. Xem kết quả từng file. **Kiểm tra** chỉ kiểm tra định dạng; **Xem trước** còn đối chiếu dữ liệu hiện có. Hai thao tác chưa ghi tài liệu, quan hệ, lịch sử hay dữ kiện vào CSDL. Upload lưu bản nguồn để xem trước; chuẩn bị chỉ mục là thao tác riêng có ghi vector.
4. Bấm **Xem / duyệt** với KG hoặc **Xem dữ kiện** với Context. Chọn các file hợp lệ, đánh dấu ô xác nhận, rồi bấm **Xác nhận nạp các file đã chọn**.
5. Xem tiến độ và tải báo cáo. Đóng trang không hủy tác vụ; mở lại sẽ theo dõi lượt đang chạy.

File lỗi không làm dừng các file còn lại. Hai file cùng định danh tài liệu KG hoặc cùng cặp bệnh nhân/phiên Context trong một lượt được báo trùng; giữ một bản nguồn phù hợp. Dùng ID ổn định khi bổ sung dữ liệu để tránh tạo bản sao ngoài ý muốn.

Nguồn được kiểm tra SHA256 giữa xem trước và ghi. Nếu file đổi, phải xem trước và xác nhận lại. Sự thay đổi trong CSDL sau xem trước cũng được kiểm tra lại lúc ghi.

### KG: duyệt thực thể tương đồng

Khi có ứng viên tương đồng ngữ nghĩa, file được đánh dấu **Cần duyệt**. Chọn thực thể đã có hoặc **Giữ là thực thể riêng**, rồi lưu lựa chọn. Hệ thống ghi `entity_link_decisions` vào JSON nguồn; không tự gộp từ điểm tương đồng.

Từ v13, có thể chọn **Giữ lại tất cả thực thể**, chỉnh từng mục nếu cần rồi bấm **Lưu duyệt tài liệu**. Dòng tài liệu được cập nhật **Đã duyệt** và sẵn sàng chọn nạp ngay trong lượt hiện tại; không cần xem trước lại cả lô. Bản JSON cũ đang chọn ở trình duyệt được bỏ chọn để tránh tải đè lựa chọn vừa lưu.

Trong một lô, tài liệu trước có thể tạo thực thể khiến tài liệu sau cần duyệt thêm lúc nạp. Khi đó file sau được báo lỗi `ENTITY_LINK_REVIEW_REQUIRED`; xem trước lại file đó, duyệt và nạp bổ sung.

### Nạp lại file lỗi

- **JSON/schema/evidence sai:** sửa nguồn rồi upload riêng file đó, xem trước và xác nhận lại. Với file trong thư mục con, ghi đúng vị trí cũ hoặc dùng API upload đường dẫn tương đối; upload trình duyệt thông thường lưu ở thư mục gốc của module.
- **Lỗi hạ tầng, nguồn chưa đổi:** xử lý kết nối, đánh dấu xác nhận và bấm **Thử lại các file lỗi / ghi một phần**.
- **KG lỗi riêng Qdrant:** trạng thái `partial`, bước `vector`. Thử lại import này chỉ đồng bộ các thực thể của import sang Qdrant, không ghi lại MongoDB/Neo4j. Khi thành công, file chuyển hoàn tất.
- **Nguồn đổi sau lỗi:** xem trước lại bản đã sửa; nút thử lại từ lượt cũ sẽ từ chối nguồn không trùng SHA256.

KG bổ sung vector cùng từng file, không cần chạy lại toàn bộ index sau mỗi file thành công. Luồng mới dùng `upsert` để nạp bổ sung; không có chế độ xóa/thay toàn bộ tài liệu trên giao diện hàng loạt.

## 4. Định dạng nguồn KG

Dùng schema JSON KG hiện tại, có `document`, `entities`, `relations`, `propositions`, evidence và các trường theo schema của dự án. Tham khảo `backend/examples/kg/kg_import.json` và các ví dụ KG đi kèm. Kết quả truy vấn RAG/KG hoặc JSON trả lời của Clinical IE không phải file nguồn import này.

Kiểm tra ontology, ID tham chiếu và evidence trước khi nạp; lỗi được ghi theo từng file. Mỗi tài liệu cần `document.document_id` ổn định. Không tự suy diễn bằng chứng bị thiếu.

## 5. Định dạng nguồn Context

Mẫu hoàn chỉnh: `backend/examples/context/context_import.example.json`.
Schema máy đọc: `backend/examples/context/context_import.schema.json`.

```json
{
  "schema_version": "1.0",
  "patient_id": "DEMO_PATIENT_001",
  "session_id": "DEMO_SESSION_001",
  "history": [
    {
      "patient_id": "DEMO_PATIENT_001",
      "session_id": "DEMO_SESSION_001",
      "message_id": "DEMO_MESSAGE_001",
      "role": "user",
      "original_text": "Tôi bị ho.",
      "created_at": "2026-10-10T10:00:00+07:00"
    }
  ],
  "facts": [
    {
      "fact_type": "symptom",
      "display": "ho",
      "source_message_id": "DEMO_MESSAGE_001",
      "source_text": "Tôi bị ho.",
      "recorded_at": "2026-10-10T10:00:00+07:00"
    }
  ]
}
```

Đây là dữ liệu giả để minh họa. File mẫu nằm trong `examples`, không tự xuất hiện trong thư mục nạp.

Quy tắc:

- Một file chứa một cặp `patient_id` / `session_id`; ID dùng chữ Latin, số, `_`, `.`, `-`, tối đa 128 ký tự, bắt đầu bằng chữ/số.
- `history`: 1–2.000 lượt user/assistant; ID và bệnh nhân/phiên phải khớp; thời gian có múi giờ. Một lượt tối đa 20.000 ký tự.
- `facts`: 0–1.000 dữ kiện; có thể để `[]` để chỉ nhập lịch sử. Lịch sử không được tự đưa qua LLM để tạo dữ kiện mới trong luồng import.
- Mỗi dữ kiện phải tham chiếu lượt `user` trong cùng file; `source_text` là đoạn trích đúng của lượt nguồn. Câu hỏi/giả định và dữ kiện đánh dấu suy diễn bị từ chối.
- Giữ nguyên phủ định, mức độ chắc chắn, giá trị, đơn vị và thời gian đã nhập. Chỉ sau thao tác xác nhận, backend mới ghi dấu xác nhận và mã lượt nạp vào dữ kiện. `certainty="confirmed"` trong JSON không thay thế xác nhận của người dùng.
- Trùng `message_id` với bệnh nhân/phiên hoặc nội dung khác bị chặn. Lượt hội thoại đã có và khớp nội dung được giữ; dữ kiện được upsert sau xác nhận.
- Neo4j ghi toàn bộ một file Context trong một transaction, sau khi chuẩn bị embeddings. Nếu ghi lỗi, file được rollback. Import thành công có dấu vết trong node `ContextImport`; nạp lại đúng nguồn sẽ bỏ qua.

**Gắn với chat hiện có:** backend tích hợp hiện dùng `conversationId` làm cả `patient_id` và `session_id`. Muốn nguồn thuộc cuộc trò chuyện hiện có, dùng đúng ID đó. Nhập Context nạp vào đồ thị ngữ cảnh, không khôi phục danh sách tin nhắn SQLite trên giao diện chat. Dữ kiện vẫn đi qua bước xác nhận của luồng đánh giá trước khi gửi sang chẩn đoán.

## 6. CLI Windows

Chạy trong `backend`, với venv đã kích hoạt và backend đang chạy:

```bat
python -m scripts.import_batches kg --mode index
python -m scripts.import_batches kg --mode preview
python -m scripts.import_batches context --mode preview
```

Nạp riêng các file đã đặt trong thư mục nguồn:

```bat
python -m scripts.import_batches kg --file "ho_hap/DOC_000005.json" --file DOC_000006.json --mode preview
```

Sau khi xem báo cáo và dữ liệu nguồn, thay `MA_LUOT_XEM_TRUOC` bằng `job_id` vừa in:

```bat
python -m scripts.import_batches kg --mode commit --job MA_LUOT_XEM_TRUOC --confirm
```

Context dùng tương tự với module `context`; `--confirm` xác nhận các dữ kiện trong những file được chọn. Có thể thêm `--file` để chỉ nạp một phần file hợp lệ của lượt xem trước.

Thử lại lỗi hạ tầng:

```bat
python -m scripts.import_batches kg --mode retry --job MA_LUOT_NAP --confirm
```

Tùy chọn: `--base-url http://127.0.0.1:8100`, `--reports-dir data\reports_downloaded`.
Mã thoát: `0` hoàn tất không có lỗi/cần duyệt, `1` có file lỗi/ghi một phần/cần duyệt, `2` tác vụ không hoàn tất hoặc không gọi được backend. CLI theo dõi tác vụ; đóng CLI không tự hủy lượt đã gửi.

## 7. Báo cáo và phục hồi

Trong `backend/data/import_reports/kg/` và `context/`:

- `jobs.sqlite3`: nhật ký bền vững, cập nhật theo từng file.
- `<job_id>.json`: báo cáo toàn lượt, bao gồm hash nguồn và kết quả từng file.
- `<job_id>.csv`: bảng đầy đủ, UTF-8 BOM.
- `<job_id>.errors.csv`: file lỗi, ghi một phần hoặc cần duyệt.

Báo cáo không chứa toàn bộ lời thoại, dữ kiện hoặc vector; chi tiết xem trước được đọc từ file nguồn khi cần. Lỗi kết nối chi tiết nằm trong log backend. Lỗi tải file cũng được ghi vào lượt kiểm tra/xem trước và không làm hệ thống vô tình nạp bản nguồn cũ cùng tên.

Sau khi backend bị ngắt, tác vụ đang chạy được đánh dấu `interrupted` khi mở lại chức năng; không tự chạy tiếp. Bấm thử lại hoặc xem trước lại nguồn. Với ghi một phần giữa MongoDB/Neo4j, kết quả import KG giữ `import_id` để thực hiện quy trình retry hiện có. MongoDB, Neo4j và Qdrant không có transaction chung; báo cáo không coi ghi một phần là hoàn tất.

`BATCH_DATA_ROOT` có thể đổi thư mục dữ liệu của hai luồng mới; mặc định là `backend/data`. Giữ nguyên đường dẫn khi nâng cấp để còn lịch sử tác vụ. Tùy chọn này không thay cấu hình thư mục của RAG.

## 8. API

Tiền tố: `/api/v1/imports/kg` hoặc `/api/v1/imports/context`.

| API | Công dụng |
| --- | --- |
| `PUT /uploads/{filename}` | Lưu byte JSON; có thể dùng đường dẫn tương đối trong thư mục module |
| `POST /jobs` | Tạo lượt `validate`, `preview`, `commit`, `retry`; riêng KG có `index` |
| `GET /jobs` | Lượt gần đây và lượt đang chạy |
| `GET /jobs/{id}` | Tiến độ và kết quả |
| `GET /jobs/{id}/items/{position}/preview` | Xem nội dung đã được pin theo hash |
| `POST /jobs/{id}/items/{position}/decisions` | KG: lưu lựa chọn thực thể bằng `{"choices":{"ID":"new"}}` hoặc ID ứng viên |
| `GET /jobs/{id}/report?kind=json` | Tải JSON; `csv` và `errors` tải CSV |

Xem trước: `{"mode":"preview","source":"directory"}`.
Xác nhận: `{"mode":"commit","previous_job_id":"UUID","confirmed":true,"files":["a.json"]}`.
Thử lại: `{"mode":"retry","previous_job_id":"UUID_LUOT_NAP","confirmed":true}`.

HTTP 409: đang có tác vụ; 413: upload quá lớn; 422: thiếu xác nhận, nguồn hoặc yêu cầu không hợp lệ. HTTP 202 chỉ là tiếp nhận tác vụ; cần đọc kết quả từng file để biết đã nạp thành công hay chưa.

Kết quả kiểm thử và giới hạn: [BATCH_IMPORT_TEST_REPORT.md](BATCH_IMPORT_TEST_REPORT.md).
