# Kiểm thử nạp RAG hàng loạt

## Kết quả

- Backend: **264 passed, 6 skipped**, 17 cảnh báo. Bộ mới `test_rag_batch.py` có **21 kiểm thử**.
- Frontend: **37 passed / 10 files**, Vitest 4.1.11; bộ RAG Workspace có **4 kiểm thử**.
- TypeScript/Vite build thành công (1.954 modules); `node --check` trang RAG và
  biên dịch Python cho các file mới đều thành công.
- Không đổi dependency Python/npm hoặc model embedding. Giữ semantic chunking, teal UI,
  VieNeu-TTS và các luồng chẩn đoán/Patient Graph hiện có.

## Các tình huống được kiểm tra

- JSON lỗi cú pháp, thiếu schema, evidence không tồn tại: tiếp tục nạp file hợp lệ phía sau.
- Thư mục con, JSON viết hoa, thứ tự ổn định; không nạp file khác đuôi JSON.
- Nạp lại cùng cấu hình/nội dung: bỏ qua và giữ active_revision.
- Nạp riêng một file đã sửa: chỉ xử lý file đó.
- Validate/dry_run không ghi tài liệu/vector vào CSDL.
- ID tài liệu trùng sau chuẩn hóa khoảng trắng: báo lỗi, không ghi đè tài liệu đầu.
- Tên thiết bị Windows, traversal, symlink, file mất, file quá lớn và lỗi upload.
- Lỗi ghi CSDL: tiếp tục file tiếp theo, giữ bản tài liệu đang hoạt động.
- Chỉ một tác vụ đang chạy; API tiến độ đọc được khi import đang chờ.
- Dừng backend: đánh dấu interrupted, giữ pending; mở lại không tự nạp JSON.
- CSV UTF-8 BOM, JSON bền vững, CSV lỗi riêng; tránh thực thi công thức khi mở CSV.
- TestClient: upload giới hạn 8 MiB, nạp HTTP 202, tải báo cáo, 404/422, không tự nạp.
- CLI: gửi danh sách file đến backend tích hợp, tải ba báo cáo, mã thoát 1 khi có file lỗi.
- JSDOM: chọn nhiều file, lỗi upload, tiến độ, liên kết báo cáo, bấm nạp thư mục,
  xem trước một file, reindex cũ, theo dõi lại tác vụ ngay cả khi health đang chờ.

## Lệnh

```bat
cd backend
python -m pytest -q -rs --disable-warnings
cd ..\frontend
npm test
npm run build
node --check ..\backend\app\modules\rag\static\app.js
```

## Giới hạn

6 kiểm thử bị bỏ qua yêu cầu MongoDB/Neo4j thật chưa được cấu hình ở môi trường kiểm thử.
Các kiểm thử batch dùng DemoStore SQLite và DemoEncoder; kiểm thử semantic trước dùng
vector kiểm soát, cùng Qdrant cục bộ và mongomock. Không tải E5/VieNeu thật trong lượt này,
không benchmark chất lượng truy hồi, tốc độ GPU hoặc nhập kho dữ liệu thật của người dùng.
Giao diện kiểm tra qua JSDOM; không thay thế kiểm tra trực quan trên trình duyệt Windows.
Chỉ hỗ trợ backend chạy một worker.
