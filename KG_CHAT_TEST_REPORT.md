# Báo cáo kiểm thử KG chat v11

Ngày: **11/10/2026**. Nền đối chiếu: ZIP v10, SHA-256 `fbb2b66c668e67f66f37d4b5f3a4eb9022628f18ba729fafc61de0e38004c63d`.

## Kết quả

| Kiểm tra | Kết quả |
| --- | --- |
| Backend: `python -m pytest tests -q` | **378 passed, 6 skipped**, 17 cảnh báo deprecation; 4,39 giây trong môi trường kiểm thử |
| Frontend: `npm run test` | **67 passed**, 14 file; 14,96 giây |
| Frontend: `npm run build` | Thành công, TypeScript và Vite, 1.956 module |
| Dependencies dự án | Không thay requirements, package.json hoặc package-lock.json |

Thời gian trên là thời gian chạy bộ kiểm thử, **không phải độ trễ phản hồi hệ thống thực**. 6 test tích hợp Neo4j/MongoDB thật được bỏ qua vì chưa có cấu hình database kiểm thử. Các cảnh báo có sẵn chủ yếu thuộc lifespan FastAPI và alias AnyIO.

## Các tình huống đã kiểm tra

- 25 nhóm ý định có câu hỏi mẫu riêng; tránh nhận sai “chống chỉ định” thành điều trị và “chẩn đoán phân biệt” thành chẩn đoán thông thường.
- Tên/bí danh, tên thiếu dấu, COVID19/COVID-19, cụm dài nhất; thực thể trực tiếp trong câu hỏi ưu tiên hơn chủ đề ngữ cảnh cũ.
- Tên gần giống và bí danh trùng cần xác nhận. Tên trùng cả cách viết/loại yêu cầu rà soát dữ liệu. Tên chưa biết không tự gán về chủ đề cũ.
- Ba preset nhiều bước; giữ thuốc nối trực tiếp khi bước thành viên nhóm là tùy chọn; loại nhánh thiếu tác dụng phụ/chống chỉ định cuối chuỗi.
- Path giữ cả cạnh và văn bản nguồn; giữ chiều thật của quan hệ; tôn trọng giới hạn số bước. Thiếu một đầu không tự đổi thành truy vấn vùng lân cận.
- Hạn mức kết quả không cắt đôi chuỗi/đường; điều kiện và phủ định trong assertion vẫn được giữ.
- Bộ điều phối chuyển dữ liệu đường liên kết cho LLM và nguồn cho frontend. Không gọi LLM khi cần làm rõ hoặc khi luồng KG chưa có kết quả.
- Xác nhận gắn với tin nhắn mới nhất và hội thoại đang xử lý. ID ngoài danh sách, lựa chọn cũ, khác hội thoại và dữ liệu giả mạo bị chặn. Thực thể đã bị xóa cần chọn lại.
- Xác nhận tiếp tục câu hỏi ban đầu, không phân lớp lại câu xác nhận; luồng RAG+KG giữ kết quả cả hai module.
- Giao diện yêu cầu lựa chọn rõ ràng, khóa nút khi bận, khóa lựa chọn cũ, khôi phục từ lịch sử, hiển thị ID nguồn và trích đoạn dưới dạng văn bản.
- Các bộ hồi quy hiện có cho dữ liệu, import, RAG, Patient Graph, bệnh án và âm thanh vẫn đạt.

## Giới hạn

- Neo4j driver được thay bằng bộ giả lập chỉ hiểu các mẫu Cypher đã dùng; kiểm thử này không xác thực câu Cypher trên server Neo4j thật.
- MongoDB, LLM, classifier trong các ca tích hợp mới dùng giả lập hoặc fixture kiểm soát. Không đánh giá khả năng phân lớp/soạn câu trả lời của mô hình thật.
- Quan hệ trong fixture mới là **dữ liệu giả lập**, không phải kết luận lâm sàng và không được nạp vào database người dùng.
- Frontend được kiểm tra bằng JSDOM và build; chưa có kiểm tra ảnh chụp trình duyệt thật, GPU hoặc micro/TTS trên máy Windows.
- Chưa đo độ chính xác với giọng nói miền Nam hoặc độ trễ toàn hệ thống trên phần cứng người dùng. Planner không thêm lượt gọi LLM, nhưng tổng thời gian vẫn phụ thuộc các dịch vụ khác.
- Quy tắc không phủ mọi cách diễn đạt, fuzzy chỉ gợi ý có giới hạn, cache tên 30 giây và tối đa 20.000 thực thể. `related` không bảo đảm tìm được mọi thông tin cần cho câu hỏi.

## Kiểm tra sau triển khai

Theo `KG_CHAT_UPDATE_VI.md`: kiểm tra readiness, meta ba mode, thử câu hỏi trên dữ liệu đã nạp và mở Nguồn bằng chứng. Đối chiếu câu trả lời với nội dung nguồn trước khi dùng trong đánh giá hệ thống.

## Kiểm tra gói phân phối

Gói ghi đè được mô phỏng áp dụng lên ZIP v10 và so sánh từng byte với mã nguồn gói đầy đủ. Kiểm tra CRC của hai ZIP và bảo toàn các file cấu hình, môi trường, dữ liệu, model giả lập ngoài bản vá. Danh sách file cập nhật nằm trong `KG_CHAT_PATCH_FILES.txt`.
