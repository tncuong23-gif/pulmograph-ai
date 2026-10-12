# Tài liệu bản giao diện trước

Tài liệu này ghi lại bản V2 trước khi chuyển sang teal. Bảng màu, tên ảnh và kiểm chứng mới nhất nằm trong [UI_TEAL_UPDATE_VI.md](UI_TEAL_UPDATE_VI.md); các ảnh V2 dưới đây đã được thay bằng ảnh teal.

---

# Cập nhật giao diện và khung hội thoại

## Các thay đổi

1. Gom `/chat` và `/chat/:conversationId` vào cùng một route và giữ một khung nhập khi chuyển từ hội thoại mới sang hội thoại đã lưu. Khi mở trợ lý giọng nói, khung nhập chữ được ẩn; đóng trợ lý sẽ khôi phục một khung nhập. Đổi hội thoại sẽ xóa tệp đang chọn của phiên trước.
2. Logo dùng nền trắng với viền xanh nhạt. Nút, trạng thái, tiêu đề và điểm nhấn chuyển từ xanh lá sang xanh dương–indigo.
3. Trang giới thiệu, chat và trợ lý giọng nói dùng chung biến màu, bao gồm chế độ tối. Điều chỉnh minh họa và khoảng cách ở màn hình chào để dành chỗ cho ô nhập.
4. Thêm hai ảnh trang trí được tạo mới: phổi kết nối tri thức cho trang giới thiệu và bong bóng hội thoại cho màn hình chào chat. Giữ logo phổi và ảnh phân tích bệnh án hiện có.

Ảnh người dùng cung cấp thể hiện hai khung nhập. Mã nguồn kiểm tra chỉ có một vị trí `ChatInput`; chưa tái hiện trực tiếp lỗi từ ảnh trong trình duyệt. Bản này củng cố vòng đời khung nhập và có kiểm thử hồi quy cho các thao tác chuyển trang, gửi, tạo hội thoại và mở/đóng trợ lý.

## Cập nhật dự án đang chạy

Dừng frontend, giải nén gói vào dự án hiện tại, sau đó chạy từ thư mục `frontend`:

```bat
npm ci
npm run dev -- --port 5174
```

Nếu phục vụ bản production, chạy `npm run build` và dùng bản `dist` vừa tạo. Tải lại trang bằng Ctrl+F5 để nhận mã và ảnh mới.

Gói không kèm thư mục `frontend-patch` cũ. Nếu máy đang có thư mục đó, không dùng nó để ghi đè bản mới. `.env` thực tế, cơ sở dữ liệu SQLite, môi trường Python, `node_modules` và `dist` được giữ ngoài gói cập nhật.

## Kiểm chứng

- Frontend: **26/26 kiểm thử qua**, gồm 2 kiểm thử mới chạy dưới React StrictMode.
- Build production và TypeScript: thành công.
- Kiểm thử mới xác nhận một `.chat-composer` và một `#chat-question` khi chuyển từ landing sang chat, gửi tạo session, tạo hội thoại mới; không có khung nhập chữ khi trợ lý mở và khôi phục đúng một khung khi đóng, lặp ba lần.
- Tệp bệnh án đang chọn không đi theo sang hội thoại mới.
- Không sửa backend trong lần cập nhật giao diện này; kết quả 58 kiểm thử backend của lần cập nhật trước được ghi ở `VOICE_TEST_REPORT.md`.
- Chưa kiểm chứng hình ảnh desktop/mobile bằng trình duyệt trong môi trường này. Kiểm thử frontend dùng API giả lập; cần chạy dự án với dịch vụ thật của bạn để kiểm tra toàn bộ trải nghiệm.

## Ảnh được tạo mới

Chế độ: tạo ảnh mới, nền trong suốt. Không dùng ảnh tham chiếu. Bảng màu xanh dương `#2563eb`, indigo `#4f46e5`, xanh nhạt `#a5b4fc`, trắng; không dùng xanh lá.

| Tệp | Vị trí |
|---|---|
| `frontend/public/assets/lung-knowledge-v2.png` | Minh họa chính của trang giới thiệu |
| `frontend/public/assets/chat-welcome-v2.png` | Minh họa màn hình chào chat |

Mô tả tạo ảnh phổi: minh họa 3D mềm mại, cặp phổi bằng kính xanh với mạng nút và kết nối tri thức, một tài liệu y khoa nhỏ, nền trong suốt, bố cục vuông, ánh sáng tinh tế, không chữ, không biểu trưng, không chi tiết giải phẫu gây khó chịu.

Mô tả tạo ảnh chat: hai bong bóng hội thoại kính xanh–trắng kết hợp phổi nhỏ và nút kết nối, bố cục ngang gọn, minh họa 3D mềm mại cùng phong cách ảnh phổi, nền trong suốt, không chữ và không biểu trưng.
