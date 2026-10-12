# Ghi chú bàn giao giao diện

## Hướng thiết kế

Medical AI sử dụng phong cách y khoa hiện đại: nền trắng ngà, xanh ngọc trầm, điểm nhấn xanh lá nhạt; thẻ nội dung có viền nhẹ, khoảng cách rộng và chữ có dấu tiếng Việt đồng nhất.

Logo SVG hiển thị sắc nét ở nhiều kích thước. Hình minh họa phổi từ dự án gốc được đặt trong bố cục mới. Không sử dụng hình ảnh từ bên thứ ba hoặc bổ sung các con số chứng thực không có dữ liệu.

## Các màn hình

| Khu vực | Thay đổi |
| --- | --- |
| Trang giới thiệu | Hero mới, giới thiệu ba khả năng, hướng dẫn ba bước, phần lưu ý y khoa và điều hướng nội trang |
| Thanh bên | Nhận diện, điều hướng chính, trạng thái chọn hội thoại, lịch sử và tình trạng kết nối |
| Màn hình chào | Biểu trưng, nội dung chào, bốn gợi ý giữ nguyên câu hỏi và hướng dẫn thêm bệnh án |
| Chat | Typography, Markdown, bảng dữ liệu, tin nhắn, thanh công cụ và ô soạn thảo |
| Tệp đính kèm | Thẻ tệp, trạng thái chờ/xử lý/lỗi và điều khiển xóa/thử lại |
| Xác nhận dữ kiện | Phân cấp tiêu đề, nhóm trường, checkbox, trạng thái cảnh báo và nút xác nhận |
| Trợ lý giọng nói | Cửa sổ, biểu trưng, trạng thái nghe/đọc và các điều khiển |
| Cài đặt | Nhóm thông tin hệ thống, lựa chọn sáng/tối, ngôn ngữ và ghi chú |

## Ranh giới kỹ thuật

Các tệp trong `src/api`, `src/context`, `src/hooks`, `src/types`, `src/config`, `src/lib`, `src/mocks` được giữ nguyên theo byte. Các thành phần điều khiển đánh giá, giọng nói, input, tin nhắn, tệp đính kèm và lịch sử cũng giữ nguyên mã xử lý.

`ChatContainer.tsx` chỉ thêm nhãn trình bày vào thanh công cụ, không đổi callback hay các điều kiện trạng thái. `Header.tsx` bổ sung nút đổi giao diện bằng `setTheme` hiện có. `Sidebar.tsx` bổ sung các liên kết đến route có sẵn. Nội dung giải thích upload trong Cài đặt được chỉnh để mô tả đúng hành vi gốc: nhấn Gửi mới tải bệnh án lên.

Giữ nguyên `App.tsx`, các route, package, lockfile và cấu hình API ví dụ. Không thêm endpoint, thay đổi dữ liệu trả về, chuyển đổi field, timeout hoặc điều kiện xác nhận y khoa.

## Cấu trúc thiết kế

- `src/product.css`: token màu, kiểu hiển thị của ứng dụng, dark mode và breakpoint. Nạp sau stylesheet gốc để giữ hành vi bố cục có sẵn.
- `src/pages/landing.css`: giao diện trang giới thiệu.
- `src/fonts.css`, `public/fonts/`: font Be Vietnam Pro, giấy phép đi kèm ở `public/fonts/LICENSE.txt`.
- `public/assets/medical-mark.svg`: logo và favicon mới.
- Các điều chỉnh TSX chỉ nằm trong thành phần hiển thị và nội dung dẫn đường.

Các breakpoint chính: 1550, 1200/1199, 1023, 950, 767, 700 và 370px. Chat giữ một khung nhập; vùng nội dung dài có thể cuộn độc lập. Có kích thước điều khiển cho thiết bị cảm ứng và `prefers-reduced-motion`.

## Kiểm chứng và giới hạn

- Build TypeScript + Vite thành công.
- 33 bài kiểm thử frontend hiện có đạt: chat, chọn/gửi/tải bệnh án, retry, timeout, xác nhận đánh giá, luồng voice/stream, lịch sử, theme và điều hướng.
- Đối chiếu 27 tệp được bảo toàn: không có thay đổi. Chi tiết hash ở `INTEGRITY_REPORT.json`.
- Bốn bài RAG workspace thuộc phần giao diện backend không có đủ tệp trong ZIP gốc; giữ nguyên, không vô hiệu hóa trong cấu hình test.
- Không có backend thật trong môi trường này để kiểm thử end-to-end.
- Không xác nhận kiểm thử trực quan bằng trình duyệt: trình duyệt từ xa không truy cập được dev server, và chính sách trình duyệt không cho mở file cục bộ. Không sử dụng hình minh họa giả làm ảnh chụp kết quả chạy.

## Đưa vào dự án hiện tại

Giữ lại `.env`/`.env.local` đang hoạt động. Thay mã nguồn frontend bằng nội dung bàn giao, chạy `npm ci`, rồi `npm run build` hoặc `npm run dev` như trước. Không chép bất kỳ thay đổi nào sang backend. Với máy khác hoặc tên miền khác, giữ cấu hình API phù hợp của hệ thống hiện tại.
