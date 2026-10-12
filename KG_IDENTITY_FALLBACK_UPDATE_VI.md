# Cập nhật định danh KG và chuyển luồng RAG — 12/10/2026

## Những thay đổi đã hoàn thành

- Trước đây lựa chọn giữ thực thể mới có thể bỏ qua đối chiếu tên chính xác, khiến cùng tên/cùng loại sinh nhiều ID. Nay tên chuẩn trùng trong cùng loại được liên kết về ID đã có; quan hệ và mệnh đề được đổi tham chiếu đồng bộ. Thuộc tính có xung đột sẽ chặn nhập để kiểm tra. Không thay toàn bộ ID hiện hữu bằng ID mới.
- Các ứng viên cùng tên hoặc tên–bí danh khác loại được đưa ra duyệt riêng. Không tự gộp Disease với Symptom hoặc đổi loại để ép nhập. Nếu thực sự cùng khái niệm nhưng gán sai loại, sửa loại trong JSON theo ontology rồi xem trước lại. Chỉ chọn giữ riêng khi chúng thực sự là hai khái niệm khác nhau.
- Nút giữ tất cả bỏ qua các mục khác loại. Lựa chọn giữ mới đã lưu từ bản cũ không tự được coi là xác nhận khác khái niệm. Bản cập nhật đổi phiên bản chính sách duyệt; hãy xem trước/duyệt lại các hồ sơ đang chờ.
- Tìm ứng viên bằng embedding có thể tìm xuyên loại. Đây là đề xuất để duyệt, không tự gộp theo độ tương đồng. Số ứng viên bị giới hạn; không bảo đảm tìm hết mọi cặp đồng nghĩa. Trong cùng một tài liệu mới, đối chiếu trực tiếp chủ yếu dựa trên tên/bí danh.
- Lưu ánh xạ ID đầu vào → ID chuẩn theo tài liệu; giữ nguồn, bằng chứng và mệnh đề. Truy vấn không mở rộng thực thể chỉ vì hai node có chung một bí danh.
- Màn hình rà soát trùng hiển thị thêm các cặp khác loại. Đã kèm thay đổi tên tiếng Anh ngang logo từ bản vá giao diện trước.

## Quy tắc chuyển luồng

| Kết quả KG | Xử lý |
| --- | --- |
| Có bằng chứng hợp lệ và đủ cấu trúc yêu cầu | Dùng KG |
| Rỗng, lỗi, không tìm thấy thực thể hoặc toàn bộ bằng chứng không dùng được | Truy xuất RAG |
| Còn bằng chứng hợp lệ nhưng thiếu nhánh, bị giới hạn kết quả hoặc thiếu phần yêu cầu | Giữ phần KG hợp lệ và bổ sung RAG |
| Cả KG và RAG không có bằng chứng dùng được | Trả lời chưa đủ bằng chứng; không yêu cầu LLM tự bịa |

Mỗi yêu cầu chỉ thử RAG một lần trong luồng này. Fact không có văn bản nguồn, nguồn không khớp mệnh đề hoặc thuộc tính được đánh dấu không hợp lệ bị loại. Chuỗi suy luận hỏng không được nối lại theo phỏng đoán. Kiểm tra này đánh giá nguồn/cấu trúc, chưa chứng minh từng kết luận y khoa được nguồn hỗ trợ đầy đủ.

Các bước xác nhận bệnh nhân, câu hỏi chẩn đoán và trường hợp thực thể thực sự mơ hồ vẫn được giữ. RAG cần được nạp tài liệu, cấu hình đúng và đang hoạt động; chuyển luồng không bảo đảm luôn có câu trả lời.

## Ghi đè bản đang chạy

Bản vá `medical-ai-integrated-kg-identity-patch.zip` dành cho **bản verified-full đã bàn giao ngay trước cập nhật này**. Nếu đang dùng bản cũ hơn hoặc đã sửa mã riêng, dùng bản đầy đủ trong thư mục riêng và đối chiếu trước khi thay.

1. Dừng backend/frontend, sao lưu mã nguồn và dữ liệu hiện tại.
2. Giải nén bản vá, chép nội dung trong thư mục `medical-ai-integrated` vào thư mục dự án cùng tên; cập nhật cả backend và frontend.
3. Giữ nguyên `.env`, venv, node_modules, dữ liệu CSDL, uploads và các mô hình riêng. Bản vá không đổi dependencies hay embedding, không yêu cầu cài lại hoặc tạo lại chỉ mục nếu chỉ mục hiện tại tương thích với cấu hình đang dùng.
4. Chạy lại backend trong CMD:

```bat
cd /d D:\medical_wed\banzip\medical-ai-integrated\backend
call venv\Scripts\activate.bat
python -m uvicorn app.main:app --host 127.0.0.1 --port 8100 --workers 1
```

5. Trong cửa sổ khác:

```bat
cd /d D:\medical_wed\banzip\medical-ai-integrated\frontend
npm run dev
```

Nếu triển khai bản build, chạy `npm run build` rồi dùng `dist` mới. Làm mới trang trình duyệt để tải mã mới. Dùng một worker backend cho cơ chế khóa nhập hiện tại.

## Dữ liệu trùng đã có trong CSDL

Bản vá ngăn các trường hợp trùng trong quy trình nhập mới và hỗ trợ phát hiện; **không tự sửa/gộp dữ liệu cũ trên máy của bạn**. Trước khi xử lý dữ liệu cũ, trong thư mục backend với venv đã kích hoạt, chạy báo cáo chỉ đọc:

```bat
python -m scripts.kg.audit_identity --output data/import_reports/kg/identity-audit.json
```

Đối chiếu thêm ứng viên embedding khi Qdrant/chỉ mục thực thể sẵn sàng:

```bat
python -m scripts.kg.audit_identity --semantic --output data/import_reports/kg/identity-audit-semantic.json
```

Báo cáo mặc định nhóm theo tên chuẩn trùng; tùy chọn semantic bổ sung ứng viên gần nghĩa. Lệnh không gộp hoặc xóa node. Cần duyệt loại, thuộc tính, quan hệ và nguồn trước khi chọn ID chuẩn và lập phương án chuyển dữ liệu. Không xóa node trùng chỉ bằng tên vì có thể mất quan hệ/bằng chứng. Có thể gửi báo cáo để chuẩn bị bước sửa dữ liệu cũ.

## Kiểm thử và phạm vi gói

- Backend: 485 đạt, 25 bỏ qua; kiểm thử nhóm duyệt sau chỉnh tổ chức: 11 đạt.
- Frontend: 88 đạt; TypeScript và production build thành công.
- Có kiểm thử nhập lại cùng tên, giữ mới, khác loại, xung đột thuộc tính, ánh xạ nguồn, KG rỗng/thiếu, RAG lỗi và không gọi LLM khi thiếu bằng chứng.
- Chưa chạy tích hợp CSDL/Ollama/GPU trên máy Windows của bạn. Các bài bỏ qua cần CSDL thực hoặc bộ dữ liệu mở rộng; các bài luồng sử dụng dịch vụ giả lập.

Bản đầy đủ gồm backend, frontend và tài nguyên có sẵn, không chứa `.env` riêng, CSDL, venv, node_modules hay dist. Cài mới vẫn cần dependencies và dịch vụ. Hai trọng số Clinical NLP `joint/final_model/model.safetensors` và `simplifier/final_model/model.safetensors` dưới `backend/clinical_service/vendor/clinical-ie/models/clinical-ie-models-v1.3/` chưa có trong nguồn được cung cấp; cần giữ/tải đúng trọng số để chạy TXT/kết hợp. Xem các hướng dẫn cài đặt đi kèm và `VERIFIED_UPDATE_VI.md` cho giới hạn từ bản trước; số liệu kiểm thử ở tài liệu này là mới nhất.

Danh sách tệp thay đổi: `KG_IDENTITY_PATCH_FILES.txt`.
