# Bản vá: Tự nhận biết luồng phân tích Clinical IE

Ngày cập nhật: 12/10/2026.

## Hoạt động sau khi sửa

| Dữ liệu trong một lần nhấn Gửi | Luồng |
|---|---|
| 1 bệnh án `.txt` | `text` |
| 1 ảnh X-quang `.jpg`, `.jpeg`, `.png` | `xray` |
| TXT + ảnh X-quang | `text_xray` |
| Văn bản gõ trong ô chat + ảnh X-quang | `text_xray` |
| Chỉ nhập câu hỏi, không đính kèm tệp | Chat thông thường qua phân lớp câu hỏi |

- Xóa hoàn toàn checkbox **Phân tích văn bản bệnh án** và dòng hướng dẫn điều khiển chế độ; xóa cả checkbox **xác nhận văn bản và ảnh thuộc cùng ca**.
- Đã bỏ thuộc tính `disabled` vô tình chặn input chọn ảnh X-quang.
- Khi có tệp, frontend chuyển tới `/api/v1/clinical/analyze` (backend 8100). Frontend không gửi `same_case` nữa.
- Backend đọc nội dung được nộp, tự suy ra `modality`, rồi truyền `same_case=true` cho Clinical IE nội bộ nếu và chỉ nếu có cả nội dung văn bản và ảnh. Không cần phân lớp câu hỏi cho bất kỳ lần nộp tệp nào.
- Chỉ TXT và chỉ ảnh: `same_case=false` và chỉ chạy nhánh tương ứng.
- File chỉ được gửi sau khi nhấn Gửi. Kết quả được lưu vào lịch sử nếu phân tích hoàn tất.

**Chú ý:** TXT và ảnh gửi cùng lượt được hệ thống mặc định xem là cùng một ca. Không gửi chung tệp của hai người bệnh khác nhau. Chỉ hỗ trợ TXT UTF-8 và ảnh JPEG/PNG ở Clinical IE; các định dạng PDF/DOCX/DICOM hiện chưa được nhánh này hỗ trợ.

## Cách áp dụng patch

1. Dừng ứng dụng frontend và backend đang chạy.
2. Giải nén tệp ZIP bản vá vào thư mục gốc chứa `medical-ai-integrated`, chấp nhận ghi đè các file trùng tên; **không xóa** thư mục gốc cũ.
3. Giữ nguyên `.env`, môi trường ảo (`venv`, `.venv-clinical`), trọng số mô hình và CSDL đang dùng.
4. Khởi động lại backend `8100` và dịch vụ Clinical IE `8002`. Ở `frontend` chạy `npm run dev`; nếu dùng bản build thì cần chạy `npm run build` trước khi triển khai. Nếu chưa cài thư viện frontend, chạy `npm ci`.

## Kiểm tra nhanh

1. Tải duy nhất một TXT, nhấn Gửi → kết quả có `modality=text`.
2. Tải duy nhất một JPEG hoặc PNG hợp lệ, nhấn Gửi → kết quả có `modality=xray`.
3. Tải TXT và ảnh, nhấn Gửi → kết quả có `modality=text_xray` và không yêu cầu tick.
4. Chỉ nhập câu hỏi bình thường → không gọi API Clinical IE.

**Xác minh tại môi trường sửa:** 25/25 test backend Clinical IE đạt. Kiểm thử chạy frontend chưa hoàn tất do npm không thể tải toàn bộ dependencies từ registry tại môi trường này (thiếu cache); cần chạy `npm ci && npm test && npm run build` trên máy phát triển. Những kiểm thử backend dùng suy luận mô phỏng; điều này không xác nhận chất lượng hoặc tính sẵn sàng của trọng số mô hình trên máy thật.
