# Báo cáo kiểm thử Clinical IE v14

Ngày: 11/10/2026. Nền tích hợp: Medical AI Integrated v13, SHA-256 ZIP `88bab67670bfed819db73bc497035853f67be825e613db7e50ba56c80d85a8d0`.

## Kết quả

| Kiểm tra | Kết quả |
| --- | --- |
| Backend `python -m pytest tests -q` | 452 đạt, 6 bỏ qua, 21 cảnh báo |
| Frontend `npm test` | 79 đạt trong 16 tệp |
| Kiểm tra lại giao diện/upload sau sửa giải phóng URL ảnh | 15 đạt trong 2 tệp |
| `npm run build` | TypeScript và Vite production thành công |
| Kiểm tra checksum 3 bundle | 22 tệp khớp, 0 sai checksum, 2 trọng số NLP thiếu |
| Mã/tài sản vendor được chọn | Giữ nguyên byte so với module bàn giao |

Các cảnh báo backend chủ yếu về API deprecated hiện có; 6 bài bỏ qua thuộc các điều kiện môi trường của bộ test cũ. Kết quả test này không chứng minh dịch vụ ML/CSDL trên máy Windows đã hoạt động.

## Các tình huống tích hợp đã kiểm tra

- Nhập văn bản, TXT UTF-8 có BOM, ảnh PNG, văn bản + ảnh và TXT + ảnh.
- Gửi kết hợp một POST multipart; trình duyệt không gán `Content-Type: application/json` cho FormData.
- Xác nhận cùng ca trước khi gửi cả hai nguồn; từ chối nếu thiếu xác nhận.
- Từ chối dữ liệu trống, TXT lỗi encoding, ảnh giả, file sai loại và văn bản quá dài trước suy luận.
- Không gửi file ngay khi chọn; hiển thị đang trả lời; không gọi bộ phân lớp chat cho ca Clinical tường minh.
- HTTPX ModuleClient gọi đúng adapter, kiểm tra đường dẫn legacy ask-symptoms.
- Backend trả job 202, theo dõi kết quả, lưu JSON và hai tin nhắn vào SQLite, đọc lại bằng store mới.
- Gửi lại cùng mã/nội dung không phân tích lần hai; đổi nội dung cùng mã bị 409.
- Job lỗi có thể thử lại; timeout hoặc upstream trả sai modality không được lưu như kết quả thành công.
- Luồng chỉ ảnh không nạp assistant NLP, không tự tạo graph/thực thể; luồng kết hợp truyền cùng ảnh vào assistant.
- Dịch vụ bận từ chối ca thứ hai bằng 409; ảnh tạm được xóa sau khi hàm xử lý hoàn tất.
- Thiếu model trả 503 và nêu file thiếu; không tự chuyển sang rule fallback.
- Luồng chẩn đoán xác nhận, KG, RAG và các regression test cũ tiếp tục đạt.

## Giới hạn

Bộ suy luận và phản hồi model được giả lập trong các bài kiểm tra hợp đồng API/giao diện. Không có Torch/LightGBM của module trong môi trường test và không có hai trọng số NLP trong ZIP đầu vào; chưa chạy inference neural đầy đủ. Chưa thử checkpoint ConvNeXt với ảnh bệnh nhân thật, chưa benchmark CPU/GPU, chưa kiểm định chất lượng chẩn đoán, chưa kiểm tra CUDA/VRAM trên máy người dùng. Không có số liệu tốc độ hoặc độ chính xác mới để công bố.

Các bản ZIP chỉ đóng gói mã nguồn, cấu hình mẫu và tài sản model được cung cấp. Venv, node_modules, dist, .env riêng, dữ liệu phát sinh và CSDL cá nhân không được đóng gói. Bản vá được đối chiếu bằng cách áp vào nội dung ZIP v13 và so sánh từng tệp với bản đầy đủ.
