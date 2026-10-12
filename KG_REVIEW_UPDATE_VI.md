# Cập nhật KG v13: medical embedding, duyệt tài liệu và nạp nhanh hơn

Bản nguồn ngày 11/10/2026, nâng từ v12. Gói đầy đủ gồm backend, frontend teal và các chức năng RAG, Context, giọng nói, truy vấn/so sánh KG trước đó. Đây là mã nguồn; không kèm CSDL, mật khẩu, môi trường Python/npm hay trọng số model đã tải.

## 1. Những thay đổi

- Embedding **tên/bí danh thực thể KG** chuyển sang [Dqdung205/medical_vietnamese_embedding](https://huggingface.co/Dqdung205/medical_vietnamese_embedding), vector 768 chiều. Khóa revision `b6b9d6ff9b2f2c7e910c352df19f0e6c9c0834de`; model dùng mã kiến trúc đi kèm repository (`trust_remote_code=True`).
- Nút **Giữ lại tất cả thực thể** chọn “Giữ là thực thể riêng” cho mọi ứng viên đang cần duyệt trong tài liệu, kể cả trang chưa hiển thị. Bạn có thể sửa từng lựa chọn trước khi bấm **Lưu duyệt tài liệu**.
- Lưu dấu **Đã duyệt**, thời điểm và số quyết định ở backend. Đã duyệt và đã nạp là hai trạng thái khác nhau.
- Encode theo lô, cache vector tên, truy vấn Qdrant theo lô, đối chiếu Neo4j theo nhóm; cache xem trước ngắn hạn. Lưu duyệt cập nhật ngay dòng tài liệu trong lượt hiện tại, không chạy lại cả lô.
- RAG, classifier và Context giữ cấu hình embedding riêng hiện có. Thay đổi này áp dụng cho KG.

## 2. Chọn gói và ghi đè

- **`medical-ai-kg-review-patch.zip`**: các file thay đổi từ **v12**; dùng khi dự án hiện tại đã có bản so sánh KG trong chat v12.
- **`medical-ai-integrated.zip`**: toàn bộ mã nguồn v13, gồm cả giao diện; dùng nếu chưa chắc phiên bản hiện tại.

1. Dừng backend; sao lưu dự án, `backend/.env`, dữ liệu nguồn và các CSDL.
2. Giải nén ZIP ra thư mục tạm. Mở thư mục `medical-ai-integrated` trong ZIP.
3. Chép nội dung bên trong vào `D:\medical_wed\banzip\medical-ai-integrated`, thay các file trùng tên. Không tạo thêm tầng `medical-ai-integrated\medical-ai-integrated`.
4. Giữ `.env` thực, `venv`, môi trường VieNeu, `models`, dữ liệu JSON cá nhân và Docker volumes. Không chép `.env.example` đè lên `.env`.
5. Danh sách file ghi đè nằm trong `KG_REVIEW_PATCH_FILES.txt`. Nếu từng sửa mã nguồn riêng, đối chiếu trước khi ghi đè các file đó.

Không cần xóa môi trường hoặc cài lại dự án. Cần cập nhật thư viện tương thích, tải model và tạo lại **chỉ mục tên thực thể KG** một lần theo mục 3.

## 3. Chuyển model trên Windows

Mở CMD:

```bat
cd /d D:\medical_wed\banzip\medical-ai-integrated\backend
venv\Scripts\activate
python -m pip install "sentence-transformers==3.3.1" "transformers==4.56.1"
python -m scripts.prepare_kg_embedding --activate
```

Chờ thông báo **`Embedding OK: 3 x 768`**. Script kiểm tra model trước rồi mới sửa các khóa KG trong `.env`, đồng thời tạo bản sao `.env.before-kg-medical-...`. Các cấu hình CSDL và dịch vụ khác được giữ nguyên.

Trọng số tải lần đầu khoảng **1,24 GB**; nên có tối thiểu khoảng 3 GB trống trên ổ chứa cache. Mặc định cache nằm tại `backend/models/hf-cache` — trên ổ D: nếu dự án ở D:. Nếu đã đặt `KG_ENTITY_CACHE_DIR`, script sử dụng đường dẫn đó; đổi khóa này trước khi tải nếu ổ đó thiếu chỗ. ZIP không chứa trọng số nên lần đầu vẫn cần mạng.

Cấu hình chính sau khi kích hoạt:

```dotenv
KG_ENTITY_EMBEDDING_ENABLED=1
KG_ENTITY_MODEL=Dqdung205/medical_vietnamese_embedding
KG_ENTITY_MODEL_REVISION=b6b9d6ff9b2f2c7e910c352df19f0e6c9c0834de
KG_ENTITY_TRUST_REMOTE_CODE=1
KG_ENTITY_COLLECTION=kg_entity_names_medical_vi_v1
KG_ENTITY_DEVICE=auto
KG_ENTITY_BATCH_SIZE=16
KG_ENTITY_QUERY_BATCH_SIZE=64
KG_ENTITY_MAX_SEQ_LENGTH=256
KG_ENTITY_CACHE_SIZE=4096
```

`256` là giới hạn token cho **tên/bí danh KG**, không phải độ dài chunk tài liệu RAG. Điểm gợi ý mặc định `KG_ENTITY_CANDIDATE_SCORE=0.70` chỉ chọn ứng viên cho người dùng duyệt; không tự gộp và không phải xác suất hai thực thể giống nhau. Cần hiệu chỉnh trên bộ dữ liệu của bạn nếu quá nhiều/ít ứng viên.

### Tạo chỉ mục mới một lần

Bật đúng các dịch vụ Neo4j, MongoDB và Qdrant đang dùng; giữ các URI/mật khẩu trong `.env`. Sau đó:

```bat
python -m scripts.kg.index_entities
```

Script đọc các thực thể hiện có từ Neo4j và ghi vector sang collection mới. **Không cần nạp lại các JSON đã nhập thành công**, không xóa Neo4j/MongoDB và không xóa collection vector cũ. Nếu KG chưa có dữ liệu, vẫn chạy để chuẩn bị collection rỗng sẵn sàng.

Đợi thông báo `Indexed ... names for ... Neo4j :Entity nodes ...` rồi khởi động backend:

```bat
python -m uvicorn app.main:app --host 127.0.0.1 --port 8100 --workers 1
```

Chạy một backend, một worker; không chạy thêm tiến trình nạp KG trong khi đang dựng lại chỉ mục. Những lần nạp bổ sung sau đó tự cập nhật vector theo tài liệu, không cần chạy lại toàn bộ index sau từng file.

### CPU / GPU

`auto` dùng khả năng thiết bị mà PyTorch nhận diện; cần bản PyTorch có CUDA và driver phù hợp để dùng GPU NVIDIA. Kiểm tra:

```bat
python -c "import torch; print('torch:', torch.__version__); print('CUDA:', torch.cuda.is_available())"
```

Ép CPU nếu cần:

```bat
python -m scripts.prepare_kg_embedding --device cpu --activate
```

Model này lớn hơn MiniLM; tối ưu theo lô giảm overhead, nhưng tốc độ thực vẫn phụ thuộc số tên, phần cứng, mạng CSDL và lần tải model đầu tiên. Nếu hết bộ nhớ khi encode, giảm `KG_ENTITY_BATCH_SIZE` xuống `8` hoặc `4`. Không cần cài lại frontend chỉ vì thay model.

## 4. Duyệt nhiều file

1. Mở `http://127.0.0.1:8100/data#kg/import` hoặc **Quản lý dữ liệu → KG → Nạp dữ liệu**.
2. Chọn nhiều JSON hoặc đặt file tại `backend/data/import/kg/`, rồi xem trước.
3. Với tài liệu cần duyệt, bấm **Xem / duyệt**.
4. Bấm **Giữ lại tất cả thực thể** nếu muốn giữ riêng tất cả ứng viên, hoặc chọn thực thể đã có cho từng mục. Có thể chỉnh riêng từng mục sau khi chọn tất cả.
5. Bấm **Lưu duyệt tài liệu**. Backend kiểm tra lại, ghi `entity_link_decisions` vào bản JSON nguồn và lưu dấu duyệt. Dòng tài liệu chuyển **Đã duyệt** kèm thời điểm và sẵn sàng chọn nạp ngay.
6. Chọn những tài liệu cần nạp, đánh dấu ô xác nhận, rồi bấm **Xác nhận nạp các file đã chọn**. Lưu duyệt không tự nạp dữ liệu.

Nút giữ tất cả áp dụng cho **các thực thể đang cần quyết định**, không nhân bản toàn bộ graph. Thực thể đã khớp chính xác theo tên/alias vẫn theo quy tắc liên kết hiện có; cùng một ID không được biến thành một ID mới. Lựa chọn `new` giữ ID đầu vào riêng khi ID đó chưa có. Đối với tài liệu không có ứng viên, vẫn có thể bấm **Lưu duyệt tài liệu** để ghi nhận đã kiểm tra.

Giao diện chia danh sách ứng viên thành 100 mục/trang; lựa chọn giữ tất cả bao gồm các trang sau. Nguồn cũ đang chọn ở trình duyệt được bỏ chọn sau khi lưu để tránh tải đè quyết định mới.

## 5. Duyệt một JSON tại KG Explorer

Mở `http://127.0.0.1:8100/modules/kg-explorer/duplicates`, chọn tab file JSON:

1. Chọn file → **Kiểm tra file**.
2. Chọn từng ứng viên hoặc **Giữ lại tất cả thực thể** → **Lưu duyệt tài liệu**.
3. **Tải JSON đã duyệt** để lưu các lựa chọn về máy; trình duyệt không tự ghi đè file gốc trên ổ đĩa.
4. Nếu muốn nạp, bấm import và xác nhận. Import sử dụng đúng nội dung vừa kiểm tra.

Dấu duyệt tài liệu được lưu ở backend, dùng chung với luồng nhiều file khi nội dung và cấu hình khớp. Đánh giá các **cặp thực thể đã tồn tại trong graph** ở tab bên cạnh vẫn là ghi chú trình duyệt/file xuất như trước; không tự gộp nút trong Neo4j.

## 6. Dấu duyệt, báo cáo và thay đổi dữ liệu

- Dấu duyệt nằm tại `backend/data/import_reports/kg/document_reviews.sqlite3` (hoặc dưới `BATCH_DATA_ROOT` nếu đã cấu hình). Giữ file này khi sao lưu/chuyển dự án.
- Dấu duyệt gắn với document ID, toàn bộ nội dung JSON và cấu hình model/quy tắc duyệt. Nội dung hoặc cấu hình đổi thì lần xem trước tiếp theo yêu cầu duyệt lại; dấu cũ không cấp quyền bỏ qua kiểm tra.
- Lịch sử lượt cũ phản ánh kết quả tại thời điểm lượt đó chạy. Để kiểm tra nguồn đã sửa hoặc cấu hình mới, hãy xem trước lại file liên quan.
- CSV/JSON báo cáo có `review_status`, `reviewed_at`, `review_decision_count`, `elapsed_seconds` cùng trạng thái nhập/lỗi. Thời gian không phải chỉ số riêng của model.
- Một tài liệu trước trong lô có thể tạo ứng viên mới cho tài liệu sau. Nếu thấy `ENTITY_LINK_REVIEW_REQUIRED`, xem trước và duyệt lại riêng tài liệu đó.
- Các file lỗi vẫn được báo riêng; file còn lại tiếp tục. Không bỏ các kiểm tra schema, ontology, evidence hay liên kết nguồn để tăng tốc.

## 7. Xử lý sự cố

| Hiện tượng | Cách xử lý |
| --- | --- |
| Chỉ mục thuộc model/cấu hình khác | Kiểm tra collection mới và chạy `python -m scripts.kg.index_entities`; không trộn vector MiniLM với model mới. Nếu đổi revision/max length, chọn tên collection mới. |
| Chỉ mục chưa sẵn sàng sau khi tác vụ bị ngắt | Chạy lại lệnh index đến khi hoàn tất; collection đang xây dựng không được dùng như chỉ mục hoàn chỉnh. |
| Không kết nối CSDL | Kiểm tra các container/dịch vụ và URI/mật khẩu hiện tại; script không đổi thông tin kết nối. |
| Không tải được model hoặc đầy ổ | Kiểm tra mạng và dung lượng thư mục cache, sửa `KG_ENTITY_CACHE_DIR` rồi chạy lại prepare. |
| Cảnh báo model được tạo bằng Sentence Transformers mới hơn | Cấu hình 3.3.1 + Transformers 4.56.1 đã chạy smoke test model thật. Chỉ tiếp tục nếu thấy `Embedding OK`; nếu có traceback thì xử lý lỗi trước khi index. |
| Trang vẫn hiện nút cũ | Khởi động lại backend rồi nhấn Ctrl+F5. Các màn hình quản lý dữ liệu được backend phục vụ. |

Nếu đang chạy frontend bằng Vite, dùng lệnh cũ `npm run dev` trong thư mục `frontend`. Nếu tự phục vụ bản build, chạy `npm run build` rồi triển khai lại `dist` theo cách đang dùng. Patch không thay dependency npm.

## 8. Cài mới và kiểm chứng

Nếu cài từ đầu, giải nén gói đầy đủ, làm theo hướng dẫn cài chung trong `README_VI.md` và hướng dẫn từng dịch vụ. Tạo `backend/.env` từ mẫu rồi điền cấu hình thực; cài `backend/requirements.txt`, thiết lập CSDL và các model/dịch vụ đã bật. Sau đó thực hiện prepare/index ở mục 3. Chỉ giải nén ZIP chưa đủ để các dịch vụ ngoài tự hoạt động.

Kết quả kiểm thử, phạm vi đo hiệu năng và giới hạn môi trường được ghi trong `KG_REVIEW_TEST_REPORT.md`.
