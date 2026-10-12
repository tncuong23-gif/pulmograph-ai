# Báo cáo kiểm tra giao diện Quản lý dữ liệu

Ngày 10/10/2026. Cơ sở cập nhật: `medical-ai-integrated.zip` v9, SHA-256 `4279094d57ad6f35c4b3bf1ae2f8f855148490d6b8a609d4aa39cc63b3a04366`.

## Kết quả thực hiện

| Kiểm tra | Kết quả |
| --- | --- |
| Backend: `python -m pytest -q -rs` | 326 đạt, 6 bỏ qua, 18 cảnh báo; 5,58 giây |
| Frontend: `npm test` | 62 đạt trong 13 file; 16,70 giây |
| Frontend: `npm run build` | TypeScript và Vite thành công; 1.954 module |
| Cú pháp JavaScript portal, embed và hai màn hình nạp | `node --check` thành công |
| Cú pháp các module Python thay đổi | `compileall` thành công |

Sáu bài bỏ qua thuộc bộ kiểm thử tích hợp MongoDB/Neo4j thật do chưa cấu hình các dịch vụ này trong môi trường kiểm thử. Cảnh báo hiện có gồm FastAPI `on_event`, alias BlockingPortal của AnyIO và cảnh báo tài nguyên socket; không có kiểm thử thất bại ở lần chạy cuối.

Môi trường: Linux, Python 3.12; bộ kiểm thử frontend dùng Vitest 4.1.11 và JSDOM. Các thư viện phục vụ kiểm thử được cài trong môi trường riêng. File requirements, package.json và package-lock.json của dự án không thay đổi.

## Các hành vi mới được kiểm tra

- Truy cập trang `/data`, `/data/`, các asset cho phép; không cung cấp file Python qua đường dẫn asset.
- Cache thống kê; một nguồn lỗi không che khuất nguồn còn lại; lỗi trả về không chứa thông tin kết nối nhạy cảm.
- Context memory và Neo4j đếm dữ liệu không gọi embedding và không lấy nội dung hội thoại.
- KG sử dụng dịch vụ truy vấn, session chỉ đọc và truy vấn đếm có thời hạn; không dùng dịch vụ nạp để xem thống kê.
- Không truy cập Qdrant khi chưa bật chỉ mục tên thực thể; không tải model từ trang Tổng quan.
- RAG đang nạp không bị trang Tổng quan gọi thống kê chờ khóa embedding.
- Báo cáo gộp giữ cả module và mã lượt; bỏ nội dung từng file, nguồn và dữ liệu lâm sàng khỏi API tổng hợp.
- Điều hướng RAG/KG/Context giữ nguyên iframe và giá trị đang nhập; đổi tab không nạp lại cả màn hình.
- Chỉ nhận thông điệp từ cửa sổ cha/con đúng origin; từ chối mã lượt không hợp lệ.
- Chọn một báo cáo mở đúng lượt đó thay vì tự chọn lượt mới nhất; mở báo cáo không phát sinh yêu cầu nạp.
- Bộ lọc cần kiểm tra và liên kết tải file lỗi trỏ đúng module/lượt.
- Menu trên màn hình nhỏ có trạng thái truy cập được bằng bàn phím và đóng bằng Escape.
- Liên kết trở về hội thoại chỉ chấp nhận frontend origin trong cấu hình.
- Module không mở được có thông báo và nút thử lại.
- Context nhúng xóa thông tin bệnh nhân/phiên mẫu; chặn gửi/phân tích hoặc lưu turn khi thiếu mã; giữ mã đã nhập khi đổi tab.
- Luồng KG/Context nạp nhiều file, duyệt, lựa chọn và xác nhận cũ tiếp tục đạt kiểm thử. Khóa thao tác trong lần tải lịch sử đầu tránh việc chọn file bị mất do khởi tạo chưa hoàn tất.

## Kiểm tra đóng gói

Bản đầy đủ được dựng từ danh sách file v9 và các file bổ sung đã kiểm soát. Bản vá chỉ chứa file mới hoặc khác v9, có manifest `DATA_WORKSPACE_PATCH_FILES.txt`.

Quy trình đóng gói kiểm tra CRC của hai ZIP, đối chiếu phạm vi thay đổi và mô phỏng chép bản vá lên v9. Kết quả mô phỏng phải khớp từng byte với toàn bộ file mã nguồn của bản đầy đủ. Các file giả lập đại diện cho `.env`, dữ liệu nguồn RAG/KG/Context, môi trường Python, `node_modules` và model đã tải phải được giữ nguyên.

## Giới hạn

- Chưa chạy trên Windows hoặc kết nối với CSDL thật trên máy người dùng. Cổng, tài khoản và mật khẩu CSDL vẫn cần đúng theo cấu hình hiện có.
- Kiểm tra giao diện lần này gồm DOM, thao tác điều hướng, trạng thái, sự kiện và build; chưa xác minh hiển thị trực quan trên trình duyệt thực hoặc các kích cỡ màn hình bằng ảnh chụp.
- Không đo lại độ chính xác PhoWhisper, tốc độ LLM hay chất lượng âm thanh VieNeu/GPU. Bản này gộp giao diện quản lý CSDL; các chức năng giọng nói và RAG trước đó được giữ lại.
- Không truy cập hay ghi dữ liệu người dùng trong quá trình kiểm thử. Các test ghi dữ liệu dùng bộ nhớ tạm, dữ liệu mẫu, mock hoặc kho thử nghiệm cục bộ.
