# Nạp RAG từ thư mục và tải nhiều JSON — cách 2

> Giao diện chung mới: **Quản lý dữ liệu** tại `http://127.0.0.1:8100/data`. Các chức năng bên dưới có trong nhóm tương ứng; xem [DATA_WORKSPACE_UPDATE_VI.md](DATA_WORKSPACE_UPDATE_VI.md) để cập nhật.

## 1. Cách hoạt động

Backend **không tự nạp dữ liệu khi khởi động**. Bạn chủ động bấm **Nạp từ thư mục**
hoặc chạy lệnh. Một tác vụ xử lý tuần tự các file, dùng chung encoder và kết nối
CSDL của backend đang chạy. Giao diện tải nhiều file cũng dùng tác vụ này.

| Thư mục trong dự án | Công dụng |
| --- | --- |
| `backend/data/import/rag/` | JSON nguồn RAG; hỗ trợ thư mục con |
| `backend/data/import/kg/` | Nguồn KG; quy trình riêng tại `BATCH_IMPORT_KG_CONTEXT_VI.md` |
| `backend/data/import/context/` | Nguồn Context; xem trước và xác nhận theo `BATCH_IMPORT_KG_CONTEXT_VI.md` |
| `backend/data/import_reports/rag/` | Báo cáo và tiến độ từng lượt RAG, tạo khi sử dụng |

Các thư mục đầu vào chứa file nguồn, không thay thế volume MongoDB/Qdrant/Neo4j.
Gói có sẵn thư mục và hướng dẫn; bạn chép bộ JSON của mình vào `rag/`.
Các tài liệu từng nạp từ giao diện/API cũ chưa tự có bản sao trong thư mục này:
dùng JSON gốc, hoặc lấy JSON nguồn bằng API `GET /modules/rag/api/v1/rag/documents/{document_id}/source`.

Mỗi file là **một JSON object tài liệu schema 1.0** có `document.sections`,
`paragraphs`, `sentences`; giữ cấu trúc nguồn và evidence như bản semantic trước.
Không nhận mảng nhiều tài liệu trong một file. Tối đa **8 MiB mỗi file**, **10.000 file mỗi lượt**.
Tên đường dẫn tương đối tối đa 240 ký tự, không dùng tên thiết bị Windows như
`NUL.json`, không dùng đường dẫn tuyệt đối hoặc symlink. Đuôi `.JSON` cũng được hỗ trợ.

## 2. Cập nhật dự án đang chạy

Tắt backend trước khi thay mã nguồn; sao lưu `.env`, `backend/data/` và CSDL hiện có.
Giữ nguyên `.env`, JSON của bạn, môi trường ảo, `node_modules` và volume CSDL.
Không xóa dữ liệu khi chép bản mới. Riêng chức năng nạp hàng loạt không thêm dependency,
không cần cài lại Python/npm hoặc tải lại E5.

Các file chạy cần thêm/thay:

| File | Thao tác |
| --- | --- |
| `backend/app/modules/rag/batch.py` | Thêm |
| `backend/app/modules/rag/main.py` | Thay |
| `backend/app/modules/rag/static/index.html` | Thay |
| `backend/app/modules/rag/static/app.js` | Thay |
| `backend/app/modules/rag/static/style.css` | Thay |
| `backend/scripts/rag/__init__.py` | Thêm |
| `backend/scripts/rag/import_folder.py` | Thêm |
| `backend/data/import/rag/README.md` | Thêm, giữ JSON của bạn |
| `backend/data/import/kg/README.md` | Thêm |
| `backend/data/import/context/README.md` | Thêm |

Nếu bản đang chạy còn trước semantic chunking, cập nhật thêm các file trong
`RAG_SEMANTIC_CHUNKING_VI.md`. ZIP mới đã chứa cả hai thay đổi.

Chạy backend với **một worker**; tác vụ và bộ khóa được quản lý trong một tiến trình.
Không mở hai backend cùng dùng thư mục báo cáo này. Chức năng chưa hỗ trợ nhiều worker.

```bat
cd /d D:\medical_wed\banzip\medical-ai-integrated\backend
venv\Scripts\activate
python -m uvicorn app.main:app --host 127.0.0.1 --port 8100 --workers 1
```

Giữ các dịch vụ MongoDB, Qdrant và dịch vụ khác của hệ thống đang chạy như trước.
Để dùng E5 semantic thực tế, `.env` giữ `RAG_MODE=live` và `RAG_CHUNK_METHOD=semantic`.
Demo vẫn dùng vector từ khóa, không phải semantic E5.

## 3. Nạp toàn bộ thư mục

1. Chép các JSON vào `backend/data/import/rag/`; có thể phân thư mục con.
2. Mở `http://127.0.0.1:8100/modules/rag/`.
3. Trong **Nhập dữ liệu**, bấm **Nạp từ thư mục**.
4. Xem tiến độ, số hoàn tất/không đổi/lỗi và chi tiết từng file.

Tác vụ chụp danh sách file theo thứ tự tên, rồi đọc từng file. Không sửa hoặc di
chuyển file đầu vào khi lượt nạp đang chạy. Các file thêm sau khi chụp danh sách
sẽ được xử lý ở lượt tiếp theo.

- Thành công: semantic chunking theo section, embedding và ghi CSDL; tài liệu sẵn sàng tìm kiếm.
- Không đổi: cùng nội dung chuẩn hóa, encoder và cấu hình chunking thì bỏ qua tạo vector.
- Đã sửa hoặc đổi cấu hình: tạo bản mới của tài liệu đó, kích hoạt khi ghi hoàn tất.
- Lỗi JSON/schema/evidence/embedding/CSDL: ghi lỗi rồi xử lý file tiếp theo.
- Hai file hợp lệ cùng `document_id` trong một lượt: file thành công đầu tiên được giữ;
  file tiếp theo báo trùng, tránh ghi đè theo thứ tự tên. ID được chuẩn hóa khoảng trắng.

Một lượt chỉ ghi vào RAG, không import vào KG hoặc Context, không thay Patient Graph.
Không cần bấm Reindex sau khi Import thành công. Không xây dựng lại toàn bộ kho khi
bổ sung một tài liệu. File lỗi có bản cũ thì bản cũ vẫn hoạt động nếu bản mới chưa kích hoạt.

## 4. Tải một hoặc nhiều file qua giao diện

Chọn nhiều JSON hoặc kéo thả chúng vào ô tải file. Giao diện hỗ trợ:

- **Kiểm tra dữ liệu**: kiểm tra schema và liên kết nguồn từng file.
- **Xem trước**: chạy luồng chunking nhưng chưa ghi CSDL; báo số chunk/mệnh đề từng file.
- **Nạp các file đã chọn**: nạp một lượt vào CSDL.

File được tải và lưu lần lượt ở `backend/data/import/rag/`. Kiểm tra/Xem trước
**cũng lưu file đầu vào**, nhưng không ghi tài liệu/vector vào CSDL. File đã tải
thành công nhưng JSON bên trong lỗi vẫn được giữ để bạn sửa; các file khác tiếp tục.
File vượt giới hạn hoặc không lưu được sẽ xuất hiện lỗi trong báo cáo.

Tải lại **cùng tên file** sẽ thay file nguồn tại thư mục gốc `rag/`; hệ thống chỉ
cập nhật tài liệu trong CSDL khi nạp thành công. Không chọn hai file trùng tên trong
cùng lượt. Nếu đổi `document_id`, đó là tài liệu khác; hệ thống không tự xóa ID cũ.

Chọn một file cũng dùng được: sửa file lỗi, giữ tên và `document_id`, rồi tải lên
và bấm nạp. Chỉ file đã chọn được xử lý. Với file lỗi nằm trong thư mục con, chép
bản sửa đúng vị trí đó rồi dùng lệnh `--file`, hoặc nạp lại thư mục.
Một bản sửa tải lên thư mục gốc với tên khác không tự xóa bản lỗi trong thư mục con.

Khi có tác vụ đang chạy, không khởi động lượt thứ hai hoặc tải đè file từ API/UI.
Bạn có thể đóng trang; tác vụ tiếp tục trên backend. Mở lại RAG sẽ theo dõi tác vụ
đang chạy. Mục **Các lượt nạp gần đây** cho phép xem lại và tải báo cáo sau khi hoàn tất.

## 5. Chạy lệnh từ CMD Windows

Mở cửa sổ CMD thứ hai, kích hoạt môi trường backend; backend trên cổng 8100 phải đang chạy.

Nạp toàn bộ thư mục:

```bat
cd /d D:\medical_wed\banzip\medical-ai-integrated\backend
venv\Scripts\activate
python -m scripts.rag.import_folder
```

Kiểm tra hoặc xem trước trước khi ghi:

```bat
python -m scripts.rag.import_folder --mode validate
python -m scripts.rag.import_folder --mode dry_run
```

Nạp riêng file đã sửa (đường dẫn tính từ `backend/data/import/rag/`):

```bat
python -m scripts.rag.import_folder --file DOC_000005.json
python -m scripts.rag.import_folder --file "ho_hap/DOC_000005.json" --file DOC_000006.json
```

Dùng dấu `/` cho thư mục con trong `--file`. Nếu thay cổng, thêm `--base-url`:

```bat
python -m scripts.rag.import_folder --base-url http://127.0.0.1:8100 --reports-dir data\reports_downloaded
```

Lệnh in tiến độ và liên kết báo cáo. `--reports-dir` tải thêm báo cáo về thư mục
chỉ định, không đổi vị trí lưu JSON nguồn. Mã thoát: `0` hoàn tất không có file lỗi,
`1` lượt hoàn tất nhưng có file lỗi, `2` không thể chạy hoặc tác vụ bị dừng.
Đóng CMD không hủy tác vụ đã gửi; backend vẫn tiếp tục.

## 6. Báo cáo và xử lý lỗi

Mỗi lượt có một mã UUID, lưu tại `backend/data/import_reports/rag/`:

| File | Nội dung |
| --- | --- |
| `<job_id>.json` | Trạng thái, tổng số, tiến độ, kết quả và lỗi từng file |
| `<job_id>.csv` | Tất cả file, ID tài liệu, trạng thái, lỗi, cảnh báo, số chunk/mệnh đề |
| `<job_id>.errors.csv` | Chỉ file lỗi; UTF-8 BOM để mở tiếng Việt bằng Excel |

Báo cáo được cập nhật trong lúc nạp; tải sau khi hoàn tất để có kết quả đầy đủ.
Không đưa vector hoặc toàn bộ nội dung tài liệu vào báo cáo. Chi tiết lỗi kết nối
hạ tầng nằm trong log backend; báo cáo chỉ ghi loại lỗi và hướng kiểm tra.

Nếu backend dừng, file đã hoàn tất vẫn được giữ trong CSDL. Các tác vụ chưa kết thúc
được đánh dấu **interrupted** khi mở lại chức năng; không tự chạy tiếp. Bạn bấm nạp lại
hoặc chạy lại lệnh: tài liệu không đổi được bỏ qua, file chưa xong được thử lại.
File lỗi không tự bị chuyển hoặc xóa; sửa hoặc loại khỏi thư mục nếu không muốn thử lại.

## 7. API

Tiền tố khi chạy backend tích hợp: `/modules/rag/api/v1/rag`.

| Phương thức / đường dẫn | Chức năng |
| --- | --- |
| `PUT /batch/uploads/{filename}` | Lưu một JSON, body là byte file, không phải multipart |
| `POST /batch/jobs` | Tạo tác vụ, trả HTTP 202 và job_id |
| `GET /batch/jobs` | Lượt gần đây và active_job_id |
| `GET /batch/jobs/{job_id}` | Tiến độ và kết quả từng file |
| `GET /batch/jobs/{job_id}/report?kind=json` | Tải JSON |
| `GET /batch/jobs/{job_id}/report?kind=csv` | Tải CSV đầy đủ |
| `GET /batch/jobs/{job_id}/report?kind=errors` | Tải CSV lỗi |

Body nạp thư mục:

```json
{"source": "directory", "mode": "commit"}
```

Body nạp riêng file đã nằm trong thư mục RAG:

```json
{"source": "files", "mode": "commit", "files": [{"filename": "DOC_000005.json"}]}
```

`mode` nhận `commit`, `dry_run`, `validate`. HTTP 409 nghĩa là đã có tác vụ đang chạy;
HTTP 413 nghĩa là file tải lên quá lớn. Upload chỉ lưu nguồn, chưa ghi CSDL. API
`/import-json` cũ vẫn hoạt động và không tự lưu JSON vào thư mục đầu vào mới.

## 8. Phạm vi kiểm chứng

Xem `RAG_BATCH_TEST_REPORT.md`. Đã kiểm tra luồng hàng loạt, phục hồi tiến độ, báo cáo,
giao diện JSDOM và các kiểm thử hồi quy. Chưa đo tốc độ trên bộ JSON thực của bạn,
GPU/E5 thật hoặc CSDL trên máy Windows của bạn. Không gộp dữ liệu KG/Context vào lượt RAG.
