# Giao diện teal — 09/10/2026

## Thay đổi

- Đồng bộ trang giới thiệu, hội thoại, sidebar, cài đặt, khung xác nhận và trợ lý giọng nói bằng bảng màu teal chung; có chế độ sáng và tối.
- Thay bốn ảnh bằng phiên bản teal nền trong suốt: logo, phổi kết nối tri thức, phân tích bệnh án và màn hình chào chat. Tên ảnh mới giúp trình duyệt tránh dùng lại ảnh cũ trong cache.
- Giữ các bản sửa khung chat bị nhân đôi: một khung nhập chính ổn định, ẩn khi mở hội thoại giọng nói và đóng modal giọng nói khi đổi trang.
- Gói có frontend và backend đầy đủ. Không cần thư mục `frontend-patch`.
- Tích hợp bản sửa dependency đã kiểm chứng: Vitest `4.1.11`, source-map-js `1.2.2`, loại tinypool khỏi cây dependency. Không dùng `npm audit fix --force`.

## Bảng màu

| Thành phần | Sáng | Tối |
| --- | --- | --- |
| Màu thương hiệu | `#008B8B` | `#50C4C0` |
| Nút chính, chữ trắng | `#007878` | `#007878` |
| Nút khi hover | `#006868` | `#006868` |
| Nền trang | `#F5FAF9` | `#101C20` |
| Sidebar | `#EAF5F3` | `#0C171B` |
| Bề mặt | `#FFFFFF` | `#17292D` |
| Tiêu đề | `#164E52` | `#EDF8F7` |
| Chữ chính | `#334155` | `#D9E8E7` |
| Chữ phụ | `#566E70` | `#A8BFBD` |
| Chú thích | `#5A7073` | `#91ABAA` |
| Nhấn nhẹ | `#E0F2F1` | `#183E42` |
| Chữ teal, liên kết | `#006D70` | `#9CE4DE` |
| Viền | `#D3E5E2` | `#355154` |

Chữ trắng trên nền nút `#007878` có độ tương phản khoảng **5,31:1**. Màu `#008B8B` dùng cho thương hiệu và điểm nhấn. Chế độ tối dùng teal sáng hơn cho chữ và biểu tượng để dễ đọc. Logo giữ nền trắng; ô nhập chuyển theo chế độ giao diện. Đỏ và vàng được giữ cho lỗi và cảnh báo.

## Ảnh trong mã nguồn

| File | Nơi dùng |
| --- | --- |
| `frontend/public/assets/logo-teal.png` | Logo dùng chung và favicon |
| `frontend/public/assets/lung-knowledge-teal.png` | Minh họa chính trang giới thiệu |
| `frontend/public/assets/record-analysis-teal.png` | Khu vực giới thiệu phân tích bệnh án |
| `frontend/public/assets/chat-welcome-teal.png` | Màn hình chào chat |

SVG dự phòng `lung-graph.svg` cũng dùng teal. Các ảnh PNG cũ đã được thay khỏi gói. Xem `ASSET_PROMPTS_TEAL.md` để biết prompt và chế độ chỉnh sửa ảnh.

## Cập nhật và chạy trên Windows

1. Dừng frontend, giải nén vào dự án của bạn sau khi giữ một bản sao bản đang chạy.
2. Giữ các file `.env` thực tế, dữ liệu và cấu hình dịch vụ hiện tại. ZIP chỉ kèm `.env.example`.
3. Dùng Node.js đáp ứng yêu cầu Vitest: **20.x, 22.x, hoặc từ 24.0.0 trở lên** theo engines của phiên bản kèm gói. Bản này được kiểm thử bằng Node.js **24.19.0**.
4. Chạy trong thư mục `frontend`:

```bat
npm ci
npm test
npm audit
npm run dev
```

Để tạo bản production: `npm run build`. Sau khi cập nhật, tải lại trang bằng `Ctrl + F5`. Thông báo deprecated `whatwg-encoding` từ dependency không làm quá trình cài đặt thất bại.

## Kiểm chứng bản này

- `npm test -- --run`: **26/26 passed**, gồm các kiểm thử hồi quy chỉ có một khung nhập hội thoại.
- `npm run build`: TypeScript và Vite production build thành công.
- `npm audit --json`: **0 lỗ hổng được báo tại thời điểm kiểm tra**.
- Bản xem trước biên dịch từ frontend, dùng API demo: kiểm tra bằng JSDOM việc mở chat, gửi tin, chỉ có một composer, chuyển sáng/tối, lưu lựa chọn theme và trở về trang giới thiệu. Không phát sinh yêu cầu mạng.
- Kiểm tra alpha: cả bốn PNG có nền trong suốt. Các cặp chữ chính, tiêu đề, chữ phụ, chú thích, liên kết trên nền chọn và chữ trắng trên nút được kiểm tra độ tương phản tối thiểu 4,5:1 ở cả hai theme.

Chưa kiểm tra bố cục bằng trình duyệt desktop/mobile trong môi trường này. Kiểm tra JSDOM không thay thế kiểm tra hiển thị thực tế. Bản xem trước dùng dữ liệu demo; cần chạy cùng backend và dịch vụ của bạn để kiểm tra giọng nói, tải bệnh án, RAG/KG và các kết nối thật. Backend không thay đổi trong lần cập nhật màu teal này; kết quả backend trước đó nằm trong `VOICE_TEST_REPORT.md` và `TEST_REPORT.md`.
