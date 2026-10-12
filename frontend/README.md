# PulmoGraph AI — Frontend trợ lý dữ liệu bệnh phổi

Bản cập nhật từ frontend.zip của bạn, dùng với backend medical-ai-integrated cổng 8100.
Bao gồm toàn bộ mã nguồn, package-lock.json, cấu hình live, kiểm thử và dist đã build.
Không bao gồm node_modules; không cần chép thêm frontend-patch.

## Cài đặt trên Windows CMD

Giải nén vào thư mục mới, ví dụ D:\medical-ai-frontend. Mở CMD trong thư mục frontend chứa package.json:

```bat
npm ci
npm run dev
```

Mở địa chỉ Local do Vite in ra (thông thường http://localhost:5173).
Giữ backend cổng 8100, Clinical IE và Ollama đang chạy.
Tính năng chẩn đoán tương tác yêu cầu backend đi kèm bản cập nhật này; không dùng cùng backend cũ chưa có API assessments.

## Cấu hình có sẵn

File .env đã giữ địa chỉ backend bạn cung cấp:

```dotenv
VITE_USE_MOCK_API=false
VITE_API_BASE_URL=http://127.0.0.1:8100
VITE_CHAT_TIMEOUT_MS=600000
VITE_FILE_PROCESSING_TIMEOUT_MS=600000
```

Frontend mặc định gọi API thật. Chỉ bật mô phỏng khi VITE_USE_MOCK_API=true.
Sau khi sửa .env, dừng frontend bằng Ctrl+C và chạy lại. Kiểm tra .env.local hoặc biến môi trường trong cửa sổ CMD nếu cấu hình bị ghi đè.
Mở đúng địa chỉ Vite vừa in ra, tránh xem frontend cũ đang chạy ở cổng khác.

## Ba luồng Clinical IE v14

Xem [hướng dẫn v14](../CLINICAL_MULTIMODAL_UPDATE_VI.md) để cài dịch vụ, bổ sung hai trọng số NLP còn thiếu và chạy ba luồng:

- Chỉ chọn file bệnh án TXT UTF-8: tự chạy luồng `text`.
- Chỉ chọn ảnh X-quang JPEG/PNG: tự chạy luồng `xray`.
- Chọn TXT + ảnh, hoặc nhập văn bản rồi chọn ảnh: tự chạy luồng `text_xray`; không cần checkbox xác nhận.
- Không chọn file, chỉ nhập câu hỏi: luồng chat thông thường, phân lớp câu hỏi như trước.

Chọn file chưa gọi API. Khi gửi, cả ca được gửi trong một POST multipart `/api/v1/clinical/analyze` tới backend 8100; polling `/api/v1/files/{id}`. Không gọi bộ phân lớp câu hỏi cho các lượt này. Kết quả thành công được lưu ở lịch sử backend, có thể xem lại sau khi tải lại trang.

Mỗi lượt một TXT và một ảnh; giới hạn 20 MB/file. Không nhận PDF/DOCX/DICOM/WebP. Chat thường khi không có tệp vẫn hoạt động như trước. Mọi tệp trong cùng lượt gửi được xem là cùng một ca bệnh, vì vậy cần chọn đúng dữ liệu của cùng người bệnh. Mô phỏng frontend không giả lập thành công cho Clinical IE; dùng API thật để phân tích.

## Build và kiểm thử

```bat
npm run build
npm run preview
npm test
```

ZIP chứa mã nguồn; chạy `npm run build` để tạo dist. Nếu đổi địa chỉ backend phải build lại. Không mở dist/index.html bằng file://.

Bản v14: 79 kiểm thử frontend đạt; TypeScript và production build thành công. Kiểm thử Clinical dùng phản hồi giả lập; chưa kiểm tra suy luận neural hoặc CSDL thật trên Windows của bạn. Xem báo cáo v14 trong thư mục gốc.

## Chẩn đoán có xác nhận

Khi backend phân lớp DIAGNOSTIC_ASSESSMENT, frontend mở khung kiểm tra dữ kiện, cho phép chọn lại thông tin Patient Graph, sửa/bổ sung thông tin, trả lời câu hỏi KG và xác nhận gửi đánh giá. Ô chat thường bị khóa trong lượt này. Câu trả lời bổ sung dùng API assessments, không gọi API chat/phân lớp.

Trạng thái đã xác nhận được lưu tại backend, khôi phục khi tải lại trang. Khi đang chạy, frontend polling hội thoại mỗi 2 giây. Thay đổi chưa nhấn xác nhận trong form vẫn chỉ ở trình duyệt.

Xem ../DIAGNOSTIC_WORKFLOW_VI.md để cập nhật cả backend và frontend, cùng các giới hạn Patient Graph/KG.
