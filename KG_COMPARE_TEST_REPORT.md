# Báo cáo kiểm thử so sánh Knowledge Graph — v12

Ngày: 11/10/2026. Baseline: medical-ai-integrated v11.

## Kết quả

| Kiểm tra | Kết quả |
| --- | --- |
| Toàn bộ backend, `python -m pytest -q` | **417 passed, 6 skipped**, 17 cảnh báo deprecation, 8,01 giây |
| Toàn bộ frontend, `npm test -- --reporter=dot` | **73 passed**, 15 file kiểm thử, 17,67 giây |
| TypeScript và Vite, `npm run build` | Thành công, 1.957 module; Vite build 3,49 giây |
| OpenAPI sinh từ ứng dụng | Schema response 1.2; mode auto + sáu mode thực tế |

Thời gian trên là thời gian kiểm thử/build trong môi trường phát triển; không phải độ trễ trả lời trên máy người dùng.

## Các tình huống mới đã kiểm tra

- Từ khóa tiếng Việt có/không dấu: so sánh, đối chiếu, điểm chung, giống nhau, khác nhau, điểm khác và câu yêu cầu cả chung lẫn khác.
- Đúng hai thực thể, cùng nhóm bệnh/thuốc; thiếu tiêu chí, thiếu tên, trùng ID, quá hai tên hoặc sai loại phải hỏi lại.
- Tiêu chí tường minh qua API, nhiều tiêu chí, `include_evidence=false`, schema và dữ liệu request không hợp lệ.
- Điểm chung chỉ khi cùng ID đặc điểm, quan hệ, chiều cạnh và toàn bộ tập thuộc tính nguồn.
- Hai thực thể cùng tên nhưng khác ID không tự gộp; hai predicate khác nhau không tự coi tương đương.
- Thuộc tính phủ định, đối tượng áp dụng, điều kiện và các nguồn khác nhau được giữ lại.
- Phủ định ở cả hai bên vẫn được giữ là phủ định trong facts. Phủ định một bên hoặc thuộc tính không trùng được đánh dấu cần đọc nguồn.
- Thuộc tính JSON không hợp lệ không được tự xác nhận là điểm chung.
- Một đặc điểm chỉ có ở một bên dùng trạng thái `not_found_in_retrieved_data` ở bên còn lại.
- Ngân sách truy xuất độc lập từng bên; lọc hàng sau đối chiếu; không cắt mất một nửa hàng chung rồi gọi đó là khác biệt.
- Gộp provenance của nhiều tài liệu cho cùng bộ ba, giữ nguồn riêng của từng bên, bảo toàn chiều quan hệ.
- Nhãn GENERAL có từ khóa so sánh được chuyển sang KG và giữ nhãn model gốc trong metadata. Luồng diagnostic/out-of-scope giữ nguyên.
- So sánh rỗng không gọi LLM hoặc dùng kết quả RAG để tự tạo hàng đối chiếu.
- Luồng chat thật trong TestClient: câu hỏi → yêu cầu xác nhận hai tên → xác nhận hợp lệ → tiếp tục đúng câu hỏi/mode, không phân lớp lại → lưu bảng và nguồn vào hội thoại.
- Chặn lựa chọn ID không thuộc nhóm đang xác nhận; các kiểm thử chống lựa chọn cũ/khác hội thoại của v11 tiếp tục đạt.
- Giao diện: bảng hai cột tên, trạng thái dữ liệu thiếu, bộ lọc, phủ định hiển thị trước khi mở chi tiết, nguồn chính xác theo ô, phục hồi bảng từ lịch sử.
- Văn bản nguồn/thuộc tính có HTML được hiển thị dưới dạng text, không chạy mã.
- Bảng có vùng cuộn ngang và điểm focus bàn phím cho màn hình hẹp.

## Môi trường và giới hạn xác minh

- Backend kiểm thử bằng Python 3.12; bộ dữ liệu so sánh là **dữ liệu tổng hợp phục vụ kiểm thử**, không phải khẳng định y khoa.
- Neo4j/MongoDB được thay bằng fixture ở các kiểm thử logic; các ca chat dùng API/TestClient và module ASGI thật với database/LLM giả lập.
- **6 kiểm thử tích hợp database thật được bỏ qua** vì chưa cấu hình dịch vụ tương ứng. Chưa chạy trên Neo4j/MongoDB, dữ liệu, Windows, Ollama, GPU hoặc micro thực tế của người dùng.
- Frontend được kiểm thử bằng JSDOM và biên dịch production. Chưa xác minh bố cục bằng trình duyệt thật trên máy Windows trong lượt này.
- Các cảnh báo backend liên quan API lifespan/on_event và alias AnyIO cũ; không có kiểm thử thất bại.
- Không thay dependency/lockfile, không huấn luyện lại classifier, không đổi schema database, không yêu cầu reindex do cập nhật này.
- Không đo/đảm bảo chất lượng câu văn do model LLM thật sinh ra. Bảng đối chiếu được tính từ KG ở backend; LLM chỉ nhận dữ liệu/bằng chứng và hướng dẫn bảo toàn giới hạn.
- Nhận diện vẫn dùng từ điển/bí danh và quy tắc, hỗ trợ quan hệ trực tiếp; chưa so sánh nhiều bước hoặc nhiều hơn hai thực thể.
- Mã truy vấn mới chỉ đọc dữ liệu, không thay đổi tài liệu, quan hệ hoặc dữ kiện bệnh nhân.

## Xác minh gói bàn giao

Gói đầy đủ được tạo từ toàn bộ file nguồn v11 cộng các file mới có chủ đích. Bản vá v11 → v12 được tính bằng đối chiếu nội dung file; danh sách ở `KG_COMPARE_PATCH_FILES.txt`. Kiểm tra CRC ZIP và mô phỏng giải nén bản vá lên v11 phải cho nội dung từng file giống bản đầy đủ v12. Các file cấu hình, dữ liệu, upload và model mô phỏng ngoài bản vá được giữ nguyên.

Gói mã nguồn không gồm môi trường Python/Node hoặc database. Hướng dẫn kiểm tra trên hệ thống thật: `KG_COMPARE_UPDATE_VI.md`, mục 5.
