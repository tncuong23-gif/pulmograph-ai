# Báo cáo kiểm thử KG v13

Ngày: 11/10/2026. Nguồn nền: gói đầy đủ v12; bản này cập nhật embedding KG, thao tác duyệt tài liệu và quy trình nạp. Không xác nhận hiệu năng trên máy Windows của người dùng.

## Kiểm thử bản đóng gói

| Hạng mục | Kết quả |
| --- | --- |
| Toàn bộ pytest backend | **427 passed, 6 skipped**, 21 warnings; 5,08 giây |
| Toàn bộ Vitest frontend | **75 passed / 16 files**; 15,20 giây |
| TypeScript `tsc -b` | Thành công |
| Vite production build | Thành công, 1.957 module, 2,93 giây |

Backend chạy Python 3.12 với dependency môi trường kiểm thử; Qdrant local dùng qdrant-client 1.13.2. Frontend dùng Vitest 4.1.11 và Vite 6.4.3 trong môi trường hiện có. Các cảnh báo backend chủ yếu là API lifespan/deprecation từ dependency và ứng dụng có sẵn; 6 kiểm thử bị skip không được tính là đã đạt.

Lệnh tái lập trong từng thư mục:

```bat
:: backend (sau khi cài dependency kiểm thử)
python -m pytest -q
:: frontend
npm test
npm run build
```

## Các rủi ro được kiểm tra trực tiếp

- Lưu quyết định `new` cập nhật ngay lượt xem trước; nạp được mà không xem trước lại cả lô.
- Quan hệ của thực thể giữ riêng tiếp tục trỏ đúng ID đầu vào; giữ riêng cả khi tên khớp chính xác với ID khác.
- Dấu duyệt tồn tại sau khi đóng/mở store; nội dung hoặc profile đổi và ứng viên mới làm mất hiệu lực dấu duyệt.
- File nguồn đổi sau duyệt không thể nạp dựa trên SHA256 của lượt cũ.
- Không ghi dấu duyệt khi thiếu lựa chọn, lựa chọn không hợp lệ hoặc thực thể đã chọn không còn tồn tại lúc kiểm tra lại.
- Cache xem trước trả bản sao, tránh sửa dữ liệu cache; import thật kiểm tra lại và làm mất hiệu lực cache.
- Qdrant local: 145 truy vấn tên thực thể chia thành 3 lần batch (64/64/17), lọc đúng loại thực thể. Lượt lặp lại dùng vector cache nhưng vẫn truy vấn CSDL mới.
- Cache có giới hạn; từ chối vector NaN. Collection khác model/không có thông tin profile hợp lệ bị từ chối; collection đang xây dựng không được báo sẵn sàng.
- API duyệt một file dùng chung dấu duyệt backend; token import chỉ dùng một lần và gắn với nội dung đã xem trước.
- Giao diện: giữ tất cả 105 ứng viên gồm trang chưa hiển thị, đổi riêng một ứng viên, lưu toàn bộ lựa chọn; không tự chọn nạp hoặc tự xác nhận.
- Giao diện: lưu lỗi không hiển thị Đã duyệt và có thể thử lại; tài liệu không có ứng viên vẫn cần thao tác lưu để ghi nhận duyệt.
- KG Explorer gửi quyết định cùng bản payload đã xem trước, rồi import payload được backend trả lại sau duyệt.

Các kiểm thử mới nằm trong `backend/tests/test_kg_review_workflow.py`, `frontend/tests/bulk-import.test.ts` và `frontend/tests/kg-file-review.test.ts`.

## Smoke test model thật và phép đo mẫu

Trong lượt kiểm chứng model trước khi khôi phục phiên làm việc, model thật tại revision `b6b9d6ff9b2f2c7e910c352df19f0e6c9c0834de` đã tải và encode thành công ba tên tiếng Việt thành **3 × 768**. Cấu hình: Python 3.12, PyTorch 2.8.0+cpu, Sentence Transformers 3.3.1, Transformers 4.56.1. Có cảnh báo model được tạo bằng Sentence Transformers 5.1.0, sau đó smoke test vẫn hoàn tất.

Đo riêng bước embedding 64 tên thực thể khác nhau từ dữ liệu ví dụ KG, CPU 4 threads:

| Cách encode | Thời gian |
| --- | ---: |
| Mỗi tên một lời gọi encode | 3,742 giây |
| Theo lô 16 tên | 0,850 giây |
| Tỷ số thời gian trên mẫu | khoảng 4,4 lần |

Chênh lệch tuyệt đối lớn nhất giữa vector hai cách chạy: khoảng `2,07e-7`; đầu ra hữu hạn, 768 chiều. Đây là phép đo mẫu cho **bước embedding**, không phải cam kết tăng tốc toàn bộ import 4,4 lần. Bộ kiểm thử bản khôi phục cuối cùng đã chạy lại đầy đủ; phép đo model thật này không chạy lại sau khi khôi phục phiên.

## Giới hạn

- Chưa chạy đầu cuối với Neo4j/MongoDB/Qdrant Docker thật trên máy Windows của người dùng; các luồng ghi CSDL dùng store giả lập trong test, riêng truy vấn vector có Qdrant local.
- Chưa đo GPU, tập tài liệu thực lớn, tốc độ mạng CSDL hoặc độ chính xác liên kết thực thể trên bộ nhãn y khoa của người dùng.
- Kiểm thử frontend dùng jsdom và production build; chưa xác nhận bằng trình duyệt trực quan trên Windows.
- Không dùng ngưỡng cosine như xác suất hay tự động gộp thực thể. Mọi ứng viên chưa quyết định vẫn cần duyệt.
- Cần hoàn thành prepare/index một lần trên máy triển khai trước khi sử dụng collection mới.
