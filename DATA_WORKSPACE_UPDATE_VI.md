# Giao diện Quản lý dữ liệu thống nhất

Bản cập nhật ngày 10/10/2026, bổ sung trên bản đã có nạp nhiều file KG và Context (bản đầy đủ v9).

Mở **Quản lý dữ liệu** ở thanh bên của frontend hoặc truy cập **http://127.0.0.1:8100/data** khi backend đang chạy. Trang này dùng chung màu Teal `#008B8B` và logo với giao diện hội thoại.

## 1. Các chức năng đã gộp

| Mục | Chức năng |
| --- | --- |
| Tổng quan | Trạng thái từng nguồn, thống kê dữ liệu và các lượt nạp gần đây |
| RAG | Nạp nhiều JSON, nạp từ thư mục, tra cứu có bằng chứng, xem tài liệu/đoạn, reindex và xóa theo luồng hiện có |
| Knowledge Graph | Nạp nhiều JSON, xem trước/xác nhận, duyệt thực thể gần nghĩa, chuẩn bị chỉ mục vector, khám phá đồ thị, rà soát trùng và xem trước/import một file JSON |
| Context & Patient | Nạp dữ liệu có xác nhận, xem History và Patient Context, kiểm tra xử lý ngữ cảnh và thêm turn vào History |
| Lịch sử & báo cáo | Tổng hợp lượt nạp RAG/KG/Context; lọc nguồn, trạng thái, mã lượt; mở đúng lượt và tải báo cáo JSON/CSV/file lỗi |

Chỉ có một thanh điều hướng chính. Các màn hình hiện có được mở trong cùng trang và giữ trạng thái khi đổi tab: file đã chọn, truy vấn, mã bệnh nhân/phiên và kết quả đang xem. Tải lại toàn bộ trang hoặc đóng trình duyệt sẽ mất trạng thái giao diện chưa lưu.

Không tự nạp dữ liệu khi mở trang hoặc khởi động backend. Các bước xem trước, lựa chọn và xác nhận của bản trước tiếp tục được áp dụng.

## 2. Ghi đè vào dự án đang dùng

Dùng **medical-ai-data-workspace-patch.zip** nếu dự án đã có bản nạp nhiều file KG/Context v9. Nếu đang dùng bản cũ hơn, dùng mã nguồn trong **medical-ai-integrated.zip** để có đủ những cập nhật trước đó và đối chiếu cấu hình theo README.

1. Dừng backend và frontend bằng `Ctrl+C`. Chờ lượt nạp đang chạy kết thúc trước khi dừng backend.
2. Sao lưu mã nguồn đã tùy chỉnh, `.env`, thư mục `backend/data` và dữ liệu CSDL đang dùng.
3. Giải nén bản vá vào thư mục tạm. Bên trong có thư mục `medical-ai-integrated`.
4. Mở thư mục đó, chép **nội dung bên trong** vào:

   ```text
   D:\medical_wed\banzip\medical-ai-integrated\
   ```

5. Chọn ghi đè các file trùng tên. Không tạo thêm thư mục `medical-ai-integrated` lồng bên trong dự án cũ.
6. Danh sách chính xác các file cập nhật ở `DATA_WORKSPACE_PATCH_FILES.txt`. Nếu bạn đã sửa riêng một file trong danh sách, đối chiếu thay đổi trước khi ghi đè.

Bản cập nhật này không thay đổi dependency, schema CSDL hoặc yêu cầu thêm biến môi trường. Với bản v9 đã chạy được, không cần cài lại `venv`, VieNeu hay `node_modules`, và không phải nạp lại dữ liệu chỉ để có giao diện mới.

Các ZIP không chứa `.env` đang dùng, Docker volumes, dữ liệu người dùng, `venv`, `node_modules`, cache hoặc trọng số STT/TTS đã tải. Việc chép file cập nhật không xóa những thư mục đó trong dự án đích.

## 3. Chạy lại trên Windows

Cửa sổ CMD cho backend:

```bat
cd /d D:\medical_wed\banzip\medical-ai-integrated\backend
venv\Scripts\activate
python -m uvicorn app.main:app --host 127.0.0.1 --port 8100 --workers 1
```

Cửa sổ CMD khác cho frontend:

```bat
cd /d D:\medical_wed\banzip\medical-ai-integrated\frontend
npm run dev
```

Nếu bạn phục vụ frontend bằng bản build, chạy `npm run build` và triển khai lại thư mục `dist` theo cách đang sử dụng. Giao diện `/data` được backend phục vụ trực tiếp, chỉ cần khởi động lại backend và làm mới trình duyệt. Có thể nhấn `Ctrl+F5` nếu trình duyệt còn giữ giao diện cũ.

Ollama, Clinical IE, Neo4j, MongoDB, Qdrant và VieNeu vẫn khởi động theo hướng dẫn của bản trước. Giao diện quản lý chung không khởi chạy hoặc thay cấu hình các dịch vụ này.

## 4. Đọc trang Tổng quan

- **Sẵn sàng:** đã đọc được thông tin nguồn trong lần kiểm tra đó.
- **Chưa kết nối:** chưa đọc được module/CSDL. Xem log backend và cấu hình kết nối tương ứng. Số chưa đọc được hiển thị `—`, không hiển thị thành `0`.
- **Đang xử lý:** RAG đang nạp; tạm hoãn thống kê để tránh chờ khóa xử lý embedding.
- **Chế độ demo / Bộ nhớ tạm:** phân biệt rõ dữ liệu thử nghiệm với CSDL live. Context memory sẽ mất khi tiến trình dừng.
- KG thể hiện trạng thái Neo4j, kho tài liệu MongoDB và chỉ mục Qdrant tên thực thể. Nếu chưa bật embedding hoặc collection chưa có, trang nêu rõ để bạn xử lý ở mục nạp KG.

Thống kê được cache trong 10 giây. Sau khi nạp xong, đợi khoảng 10 giây rồi bấm **Làm mới**. Mở Tổng quan không tạo collection, chạy lại index hay tải model embedding. Thống kê sử dụng kết nối cấu hình riêng của từng module như trước.

## 5. Nạp và kiểm tra dữ liệu

Nguồn mặc định:

```text
backend/data/import/rag/
backend/data/import/kg/
backend/data/import/context/
```

Trong nhóm cần dùng, mở **Nạp dữ liệu**, chọn nhiều file hoặc nguồn thư mục. Các giới hạn và định dạng JSON vẫn theo:

- `RAG_BATCH_IMPORT_VI.md` cho RAG.
- `BATCH_IMPORT_KG_CONTEXT_VI.md` cho KG và Context.

Với KG/Context, xem trước, kiểm tra từng file rồi lựa chọn/xác nhận trước khi nạp. Khi có thực thể gần nghĩa, chọn cách xử lý rồi xem trước lại file đã duyệt. Nếu dùng Qdrant tên thực thể trên KG đã có dữ liệu, thực hiện bước chuẩn bị chỉ mục theo hướng dẫn bản trước.

Mục **Rà soát trùng** của đồ thị lưu nhận xét trong trình duyệt/file xuất; đánh dấu một cặp không tự gộp hoặc xóa các nút đang tồn tại. Luồng nạp có bước duyệt riêng.

## 6. Context & Patient

- Mục **Lịch sử & dữ kiện** có ô Patient ID và Session ID. Điền đúng mã trước khi tải History; tải Patient Context cần Patient ID.
- Mục **Kiểm tra ngữ cảnh** dùng cùng mã đang nhập. Giao diện nhúng không điền sẵn bệnh nhân/phiên mẫu để tránh ghi nhầm.
- **Gửi & phân tích** thực hiện luồng Context hiện có và có thể lưu History. Đây không phải chỉ là thao tác xem thử JSON; hãy dùng mã bệnh nhân/phiên phù hợp.
- **Lưu vào History** ghi turn khi bạn chủ động bấm nút. Nạp dữ kiện vào Patient Graph vẫn cần xem trước và xác nhận theo luồng nạp.
- Hội thoại của frontend hiện ánh xạ conversation ID sang Patient ID và Session ID của Context. Dữ liệu History/Patient khác với danh sách hội thoại lưu trong SQLite của backend; trang này không nhập hay khôi phục dữ liệu hội thoại SQLite.

## 7. Lịch sử, lỗi và báo cáo

Trang báo cáo tổng hợp tối đa 30 lượt mới nhất mỗi nguồn và chia 15 lượt/trang. Bạn có thể lọc **Cần kiểm tra** để tìm lượt lỗi, ghi một phần, cần duyệt hoặc gián đoạn.

**Mở lượt** chuyển đến đúng lượt đã chọn, không tự chạy lại việc nạp. Tải JSON/CSV/file lỗi từ hàng báo cáo. Lượt KG/Context bị lỗi có thể thử lại bằng thao tác và xác nhận trong màn hình nạp. Với RAG, sửa rồi tải bổ sung file lỗi theo luồng hiện có.

Khi đang ở Tổng quan hoặc Lịch sử & báo cáo và có lượt đang chạy, danh sách tự làm mới mỗi 5 giây. Các màn hình nạp giữ cơ chế theo dõi tiến trình riêng. Tác vụ đã khởi chạy trên backend tiếp tục chạy khi đổi tab hoặc đóng trang, miễn backend còn hoạt động.

Báo cáo hiện có vẫn nằm ở `backend/data/import_reports/`. Nếu một module chưa sẵn sàng, các module khác vẫn có thể hiển thị báo cáo của chúng.

## 8. Địa chỉ cũ và triển khai

Các địa chỉ cũ tiếp tục hoạt động và có liên kết về trang quản lý chung:

- `/imports?module=kg` và `/imports?module=context`
- `/modules/rag/`
- `/modules/kg-explorer/` và `/modules/kg-explorer/duplicates`
- `/modules/context/ui`

Ba API tổng hợp mới chỉ nhận GET: `/api/v1/data/config`, `/api/v1/data/overview`, `/api/v1/data/jobs`. Các thao tác ghi sử dụng API của module hiện có.

Frontend dùng `VITE_API_BASE_URL` đang cấu hình để mở `/data`. Liên kết **Trở về hội thoại** chỉ dùng origin frontend được cho phép trong `CORS_ORIGINS`. Nếu vào `/data` trực tiếp, liên kết trở về mặc định dẫn đến trang dịch vụ backend.

Nếu đặt sau reverse proxy, chuyển tiếp cùng origin các đường dẫn `/data`, `/data-assets/`, `/api/v1/data/`, `/imports`, `/imports-assets/`, `/api/v1/imports/` và `/modules/` đến backend. Nếu có CSP hoặc X-Frame-Options, cho phép nhúng cùng origin (`frame-src 'self'`, `SAMEORIGIN`); chính sách `DENY` sẽ chặn các màn hình module.

Kết quả kiểm tra và giới hạn xác minh: `DATA_WORKSPACE_TEST_REPORT.md`.
