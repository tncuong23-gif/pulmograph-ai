# Medical AI — Frontend hoàn chỉnh

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

## Luồng bệnh án — chọn trước, bấm Gửi sau

1. Bấm Tải bệnh án và chọn file: chỉ giữ file trong trình duyệt; chưa gọi API upload. Thẻ file hiện Chờ gửi; ô text bị khóa. Có thể gỡ file trước khi gửi.
2. Bấm nút Gửi: frontend xóa file khỏi khung soạn thảo, ghi tên bệnh án trong cuộc trò chuyện và hiện cùng hiệu ứng Medical AI đang trả lời như câu hỏi text.
3. Frontend POST multipart đến backend /api/v1/files/medical-record. Backend hiện có gọi Clinical IE /api/v1/analyze-file rồi Qwen; không qua context/phân lớp.
4. Frontend theo dõi GET /api/v1/files/{id}. Khi xong, analysisAnswer xuất hiện dưới dạng tin nhắn Medical AI với định dạng Markdown, không nằm trong thẻ file.
5. Ô nhập mở lại sau khi xử lý xong. Nếu lỗi, hiển thị Thử lại trong cuộc trò chuyện. Nếu đã có ID file đang xử lý, thử lại tiếp tục kiểm tra ID đó thay vì tải lại file.

Luồng bệnh án dùng API upload hiện có; luồng chẩn đoán text mới cần backend đã cập nhật. Frontend chỉ gọi backend 8100.
Phân tích X-quang chưa được hỗ trợ nên nút này được vô hiệu hóa.

### Phạm vi lưu trữ hiện tại

Backend hiện tại lưu file, trạng thái và analysisAnswer trong dữ liệu attachment.
Các tin nhắn phân tích bệnh án hiển thị trong cuộc trò chuyện được giữ trong bộ nhớ frontend của phiên mở trang;
chưa ghi các tin nhắn này vào lịch sử hội thoại backend. Tải lại trang sẽ mất phần hiển thị đó,
nhưng không xóa kết quả attachment đã lưu ở backend. Đổi cuộc trò chuyện trong cùng phiên không hủy việc chờ kết quả.
Tích hợp lưu tin nhắn bệnh án lâu dài cần bổ sung hợp đồng API backend; bản cập nhật này không thay đổi backend.

## Build và kiểm thử

```bat
npm run build
npm run preview
npm test
```

Bản dist đi kèm được build với backend http://127.0.0.1:8100. Chạy npm run preview để xem;
không mở dist/index.html trực tiếp bằng file://. Nếu đổi địa chỉ backend phải build lại.
Kiểm thử dùng môi trường mô phỏng riêng, không đổi cấu hình live của ứng dụng.

Đã kiểm tra: TypeScript và production build thành công; 17 kiểm thử đạt, gồm chọn file không gọi upload, gửi file mới bắt đầu xử lý, xóa thẻ file,
hiện hiệu ứng chờ, hiển thị câu trả lời, thử lại và không gọi API chat cho bệnh án.
Kiểm thử API dùng phản hồi giả lập; chưa chạy với Clinical IE/Ollama/CSDL trên máy Windows của bạn.

## Chẩn đoán có xác nhận

Khi backend phân lớp DIAGNOSTIC_ASSESSMENT, frontend mở khung kiểm tra dữ kiện, cho phép chọn lại thông tin Patient Graph, sửa/bổ sung thông tin, trả lời câu hỏi KG và xác nhận gửi đánh giá. Ô chat thường bị khóa trong lượt này. Câu trả lời bổ sung dùng API assessments, không gọi API chat/phân lớp.

Trạng thái đã xác nhận được lưu tại backend, khôi phục khi tải lại trang. Khi đang chạy, frontend polling hội thoại mỗi 2 giây. Thay đổi chưa nhấn xác nhận trong form vẫn chỉ ở trình duyệt.

Xem ../DIAGNOSTIC_WORKFLOW_VI.md để cập nhật cả backend và frontend, cùng các giới hạn Patient Graph/KG.
