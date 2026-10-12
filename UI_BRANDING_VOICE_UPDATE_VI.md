# Cập nhật giao diện PulmoGraph AI và nút giọng nói

## Những thay đổi

- Đổi tên tiếng Anh trong sidebar thành **PulmoGraph AI** và **Lung Disease Knowledge Assistant**.
- Đổi tiêu đề header thành **Trợ lý ảo truy vấn thông tin từ dữ liệu bệnh phổi**.
- Ẩn badge kết nối trên header. Sidebar không hiển thị giá trị placeholder “Chưa kết nối” khi Knowledge Base chưa sẵn sàng. Cảnh báo lỗi kết nối thực tế và trạng thái trong Cài đặt vẫn được giữ để người dùng biết khi backend ngừng hoạt động.
- Thay logo bằng SVG người dùng cung cấp ở `frontend/public/favicon.svg`; cập nhật logo hiển thị, favicon, PNG dự phòng và biểu tượng chào mừng.
- Chuyển nút **Trò chuyện bằng giọng nói** vào hàng thao tác dưới textarea, cạnh các nút **Thêm bệnh án** và **Thêm ảnh X-quang**. Trên điện thoại, dùng nút icon (vẫn có tên truy cập/tooltip).
- Giữ luồng mở hội thoại giọng nói và giao diện VoiceAssistant cũ, chỉ đổi nơi đặt nút mở.
- Khi đang gửi yêu cầu hoặc đang có tệp đính kèm chờ gửi, nút giọng nói tạm thời bị khóa để tránh làm mất tệp chưa gửi.
- Không thay đổi xử lý backend và logic nhận biết ba luồng Clinical IE (TXT / X-quang / TXT+X-quang).

## Cách cài đặt

1. Sao lưu thư mục `medical-ai-integrated` hiện có.
2. Giải nén **gói vá** vào thư mục cha chứa `medical-ai-integrated`, giữ nguyên cấu trúc và cho phép ghi đè tệp trùng tên. Hoặc dùng ZIP toàn bộ dự án đã cập nhật.
3. Khởi động lại frontend (`npm run dev` tại thư mục `frontend`) và refresh trình duyệt bằng `Ctrl+F5` để làm mới favicon và assets.
4. Backend cần chạy để nhận câu hỏi, phân tích tệp và cung cấp chức năng giọng nói. Không sửa `.env`, dữ liệu hay module backend trong lần cập nhật này.

## Kiểm tra

- Kiểm tra tĩnh cú pháp TS/TSX cho các tệp sửa: **đạt**.
- Kiểm tra có logo SVG, tiêu đề, nút giọng nói trong ChatInput, không còn nút giọng nói ở phía trên: **đạt**.
- Chưa chạy được `npm run build` / Vitest tại môi trường đóng gói do gói npm chưa cài đầy đủ (lỗi tải dependency). Nên kiểm tra lại tại máy phát triển có thể `npm ci`.
- Việc ẩn badge kết nối **không phải** sửa lỗi kết nối backend; hãy xem cảnh báo nếu API không chạy.
