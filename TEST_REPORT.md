# Kiểm thử luồng chẩn đoán tích hợp — 2026-09-30

## Backend

- Toàn bộ suite: `python -m pytest tests -q -rs --disable-warnings`: **190 passed, 7 skipped**, 17 warnings.
- Sau khi bổ sung kiểm thử đồng bộ graph và giả mạo ID dữ kiện, chạy riêng `python -m pytest tests/test_assessment_workflow.py -q --disable-warnings`: **11 passed**. 9 bài trong nhóm này cũng nằm trong lần chạy toàn bộ phía trên; không cộng hai số thành tổng.
- 6 bài bỏ qua cần MongoDB/Neo4j thật; 1 module test RAG bỏ qua do môi trường kiểm thử này thiếu mongomock. requirements-dev.txt có mongomock để chạy trên máy đã cài đủ.
- Warnings từ lifecycle/thư viện hiện có; không có lỗi test trong các lần chạy trên.

Đã kiểm tra chặn Clinical IE/Patient Graph trước xác nhận, ghi bản xác nhận, khôi phục từ SQLite, trả lời bổ sung không qua classifier, phủ định, chưa biết, bỏ qua, giới hạn hỏi lại, provenance, dữ kiện gia đình/tiền sử, xung đột, version cũ, action idempotency, cùng lúc gọi run không sinh hai kết quả, KG offline, điều kiện KG bị lọc, lỗi LLM và dùng lại Clinical IE, khởi động lại backend, hủy lượt, đồng bộ lại Patient Graph không chạy lại chẩn đoán, ID dữ kiện giả mạo bị từ chối.

HTTP integration test dùng FastAPI TestClient: nhãn 0 mở assessment, gửi lại message không phân lớp lần hai, chat mới bị chặn khi assessment chưa xong, confirm/diagnose qua API, tải lại hội thoại thấy kết quả và metadata. Các test cũ về Context, KG, RAG và upload vẫn được chạy trong suite.

Các test ghi facts trực tiếp của Context được sửa để opt-in persist_patient_facts=True ở hàm Python nội bộ; test HTTP kiểm tra mặc định không ghi và từ chối bật cờ này. Test đường chẩn đoán cũ được cập nhật để yêu cầu dừng trước Clinical IE/Qwen.

## Frontend

- Suite cũ: `npm test`: **17 passed**.
- Khung xác nhận: `npm test -- --run tests/assessment.test.tsx`: **3 passed**.
- Khôi phục/polling luồng qua giao diện App: `npm test -- --run tests/assessment-integration.test.tsx`: **1 passed**.
- `npm run build`: đạt TypeScript và Vite production build.

Các nhóm frontend trên không trùng nhau, tổng **21 tests**. Test mới xác nhận dữ kiện cũ mặc định bị loại, bắt buộc checkbox trước khi gửi, sửa dữ kiện hủy tick xác nhận, unknown khác absent, có thể bỏ qua, không cho sửa khi running, khôi phục lượt đang chờ, gửi action tới API assessment và polling nhận kết quả mà không gọi chat classifier.

## Phạm vi kết luận

- Sử dụng Context memory, SQLite thật cho state và dependency giả lập cho KG/Clinical IE/Qwen trong kiểm thử workflow.
- Chưa kiểm chứng kết nối Neo4j/MongoDB/Qdrant, dữ liệu y khoa, Clinical IE, Ollama, CUDA và hiệu năng trên máy Windows của bạn.
- Chưa đánh giá độ chính xác y khoa, độ đầy đủ KG hay khả năng mô hình Clinical IE hiểu phủ định/thời điểm trong văn bản.
- Gói có frontend hoàn chỉnh và dist mới; không chỉ là bản vá giao diện.
