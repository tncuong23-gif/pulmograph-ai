# Cập nhật so sánh Knowledge Graph trong chat — v12

Ngày: 11/10/2026. Bản cập nhật dựa trên **medical-ai-integrated v11**.

## 1. Chức năng mới

| Chế độ | Ví dụ câu hỏi |
| --- | --- |
| So sánh tổng hợp (`compare`) | So sánh COPD và viêm phổi về triệu chứng. |
| Điểm chung (`common`) | COPD và viêm phổi có triệu chứng nào giống nhau? |
| Điểm khác (`difference`) | COPD và viêm phổi khác nhau về triệu chứng thế nào? |
| So sánh thuốc | Thuốc A và Thuốc B khác nhau về tác dụng phụ và chống chỉ định thế nào? |

Thay tên trong ví dụ bằng tên/bí danh có trong KG của bạn. Các ví dụ là mẫu câu hỏi, không khẳng định kho dữ liệu đã có đủ thông tin về các bệnh/thuốc này.

- Nhận diện hai thực thể và tối đa sáu tiêu chí từ câu hỏi; tên thiếu rõ ràng cần xác nhận.
- Nếu chỉ hỏi “So sánh COPD và viêm phổi”, hệ thống hỏi thêm tiêu chí. Gửi lại câu đầy đủ, ví dụ “So sánh COPD và viêm phổi về triệu chứng”.
- Bảng trong chat có hai cột bệnh/thuốc, đặc điểm, kết quả đối chiếu và điều kiện/nguồn từng bên.
- Ở chế độ tổng hợp có nút lọc Tất cả / Điểm chung / Điểm khác hoặc cần kiểm tra.
- Mở **Điều kiện và nguồn** ở từng ô để đọc phủ định, đối tượng áp dụng và trích đoạn bằng chứng.
- Bảng và nguồn được lưu cùng tin nhắn; mở lại hội thoại vẫn xem được.
- Giữ các truy vấn trực tiếp, ba preset nhiều bước và truy vấn đường liên kết của v11.

## 2. Hiểu đúng kết quả

**Chỉ tìm thấy ở một bên không có nghĩa bên còn lại không có đặc điểm đó.**

| Nhãn trong bảng | Ý nghĩa |
| --- | --- |
| Ghi nhận tương ứng ở cả hai | Cùng ID đặc điểm, quan hệ, chiều cạnh và tập thuộc tính nguồn. Cần đọc điều kiện/phủ định; đây không phải chứng minh hai bệnh/thuốc tương đương. |
| Mới tìm thấy ở bên trái/phải | Chưa tìm thấy quan hệ tương ứng ở bên còn lại trong phần dữ liệu truy xuất. |
| Thuộc tính nguồn khác nhau | Điều kiện, đối tượng, phủ định hoặc thuộc tính khác không trùng nhau; cần kiểm tra nguồn trước khi diễn giải. |
| Thuộc tính nguồn chưa hợp lệ | Không đủ điều kiện tự xác nhận điểm chung. |

Hệ thống không gộp các thực thể chỉ vì giống tên; không tự đồng nhất hai loại quan hệ. Thuộc tính nguồn giữ nguyên từ dữ liệu nạp. Khi nguồn không có thuộc tính, không suy ra quan hệ áp dụng cho mọi đối tượng. Nếu nguồn mâu thuẫn trong văn bản nhưng chưa được biểu diễn trong thuộc tính, cơ chế so sánh không tự phát hiện được mâu thuẫn đó.

Mỗi bên được truy xuất riêng để dữ liệu nhiều ở một bên không chiếm hết lượt đọc của bên còn lại. Mặc định trả tối đa 30 bộ ba; hàng đối chiếu luôn giữ đủ bằng chứng hai bên hoặc bỏ cả hàng. Bảng có cảnh báo nếu chạm giới hạn. Dữ liệu KG và số kết quả truy xuất đều có thể chưa đầy đủ.

## 3. Chọn gói tải về

- **medical-ai-kg-compare-patch.zip**: chỉ các file mới/thay đổi từ **v11 → v12**. Dùng để ghi đè dự án v11 đang chạy.
- **medical-ai-integrated.zip**: mã nguồn backend và frontend đầy đủ của v12, bao gồm giao diện teal và các cập nhật trước.

Gói mã nguồn không chứa database/volume Docker của bạn, môi trường `venv`/`node_modules` hoặc toàn bộ trọng số mô hình dịch vụ ngoài. Nếu cài mới, vẫn làm theo `README_VI.md` và chuẩn bị các dịch vụ/model tương ứng.

**Nếu v11 đang chạy được, cập nhật này không yêu cầu cài lại thư viện, sửa .env, nạp lại tài liệu hoặc chạy lại index.** Nếu bạn đang ở bản cũ hơn v11 hoặc đã sửa mã riêng, đối chiếu bản đầy đủ và sao lưu thay đổi riêng trước khi ghép.

## 4. Ghi đè trên Windows bằng CMD

Các đường dẫn dưới đây theo dự án đang dùng:

```text
D:\medical_wed\banzip\medical-ai-integrated
```

1. Dừng backend và frontend bằng `Ctrl+C` ở hai cửa sổ đang chạy.
2. Sao lưu mã hiện tại, ít nhất `backend\app` và `frontend\src`, cùng những file bạn tự sửa. Giữ nguyên dữ liệu/database đang có.
3. Giải nén **medical-ai-kg-compare-patch.zip** vào:

```text
D:\medical_wed\banzip\kg-compare-update
```

Sau giải nén phải thấy:

```text
D:\medical_wed\banzip\kg-compare-update\medical-ai-integrated\backend
D:\medical_wed\banzip\kg-compare-update\medical-ai-integrated\frontend
```

4. Ghi đè bằng CMD:

```bat
robocopy "D:\medical_wed\banzip\kg-compare-update\medical-ai-integrated" "D:\medical_wed\banzip\medical-ai-integrated" /E /R:1 /W:1
```

Không thêm `/MIR` hoặc `/PURGE`. Mã thoát robocopy từ 0–7 không phải lỗi sao chép; từ 8 trở lên cần kiểm tra. Bản vá không chứa `.env`, môi trường Python/Node, model, database, thư mục dữ liệu nạp hoặc file tải lên.

5. Chạy lại backend:

```bat
cd /d D:\medical_wed\banzip\medical-ai-integrated\backend
venv\Scripts\activate
python -m uvicorn app.main:app --host 127.0.0.1 --port 8100 --workers 1
```

Nếu môi trường của bạn tên `.venv`, thay lệnh kích hoạt bằng `.venv\Scripts\activate`.

6. Chạy frontend ở cửa sổ CMD khác:

```bat
cd /d D:\medical_wed\banzip\medical-ai-integrated\frontend
npm run dev -- --port 5174 --strictPort
```

Mở `http://localhost:5174/chat`, nhấn `Ctrl+F5`. Nếu đang phục vụ frontend từ `dist`, chạy `npm run build` rồi dùng bản build mới theo cách phục vụ hiện tại. Không cần chạy `npm install` chỉ cho bản vá này.

Giữ cấu hình live hiện có: `VITE_USE_MOCK_API=false`, `VITE_API_BASE_URL=http://127.0.0.1:8100`; backend CORS phải cho phép địa chỉ frontend đang dùng. Không sao chép `.env.example` đè lên `.env` của bạn.

## 5. Kiểm tra sau cập nhật

1. Mở `http://127.0.0.1:8100/modules/kg/health/ready`; cần trả `ready` khi Neo4j/MongoDB sẵn sàng.
2. Mở `http://127.0.0.1:8100/modules/kg/api/v1/kg/meta`; cần có `schema_version: "1.2"` và các mode `compare`, `common`, `difference`.
3. Hỏi trong chat ba câu ở mục 1, dùng hai bệnh/thuốc đã nạp.
4. Kiểm tra bảng, mở nguồn từng bên, thử lọc điểm chung/điểm khác.
5. Thử câu thiếu tiêu chí; hệ thống phải hỏi lại. Thử tên mơ hồ; hệ thống phải yêu cầu xác nhận trước truy xuất.

Có thể kiểm tra API trực tiếp bằng **PowerShell**:

```powershell
$kgBody = @{
    question = "So sánh COPD và viêm phổi về triệu chứng"
    mode = "compare"
    intents = @("symptom")
    limit = 30
    include_evidence = $true
} | ConvertTo-Json -Depth 5

$kgResult = Invoke-RestMethod -Method Post `
    -Uri "http://127.0.0.1:8100/modules/kg/api/v1/kg/query" `
    -ContentType "application/json; charset=utf-8" `
    -Body ([System.Text.Encoding]::UTF8.GetBytes($kgBody))

$kgResult | ConvertTo-Json -Depth 30
```

Đây là truy vấn chỉ đọc. Nếu `status` là `needs_clarification`, đọc `clarification.message`. Nếu `no_facts`, đọc `llm_context.comparison.no_result_reason` và cảnh báo; không coi là khẳng định không có điểm chung/khác biệt.

## 6. Định tuyến và giới hạn hiện tại

- So sánh hỗ trợ **quan hệ trực tiếp** giữa đúng hai bệnh hoặc hai thuốc/nhóm thuốc, theo tiêu chí đã nêu. Chưa so sánh các chuỗi nhiều bước hoặc nhiều hơn hai thực thể.
- Khi nhãn phân lớp là `GENERAL_MEDICAL_QUERY` nhưng có từ khóa so sánh, bộ điều phối chuyển sang KG, giữ nhãn gốc trong `metadata.classifier.original_label` và lý do ở `routing_override`.
- Luồng RAG+KG vẫn truy xuất cả hai. Nếu bảng so sánh không có hàng phù hợp, trả thông báo trực tiếp; không dùng LLM để tự tạo kết quả so sánh.
- `DIAGNOSTIC_ASSESSMENT` và `OUT_OF_SCOPE` giữ nguyên. Nếu classifier dự đoán nhầm vào các nhãn này, cần xem metadata và hiệu chỉnh classifier riêng.
- Nhận diện tên dùng từ điển/bí danh và quy tắc hiện có; không phải mô hình hiểu ngôn ngữ tùy ý. Có thể phải hỏi lại với tên và tiêu chí rõ hơn.
- Không đưa ra tỷ lệ giống nhau, xếp hạng thuốc tốt hơn hoặc chẩn đoán cá nhân từ số lượng quan hệ.
- Tên và bí danh có cache 30 giây. Sau khi nạp thêm dữ liệu, chờ cache cập nhật hoặc khởi động lại backend.
- Phản hồi lời nói tiếp tục qua luồng giọng nói hiện có; bảng đối chiếu và nguồn xem trong chat. Nếu cần xác nhận tên, thực hiện trong chat.

## 7. File thay đổi và kiểm thử

Danh sách chính xác: `KG_COMPARE_PATCH_FILES.txt`.

Mã chính:

- `backend/app/modules/kg_query/comparison.py`: đối chiếu theo tiêu chí, ngân sách hai phía, giữ nguồn và thuộc tính.
- `backend/app/modules/kg_query/question_analysis.py`, `retrieval_api.py`, `service.py`: nhận diện chế độ, xác thực và API.
- `backend/app/services/orchestrator.py`, `kg_chat.py`, `ollama.py`: định tuyến, lưu bảng, thông báo dữ liệu thiếu và hướng dẫn LLM.
- `frontend/src/components/chat/KGComparisonTable.tsx`, `KGQueryDetails.tsx`, `kg-query.css`, `frontend/src/types/index.ts`: bảng đối chiếu trong giao diện.

Xem `KG_COMPARE_TEST_REPORT.md` để biết kiểm thử đã chạy và những phần cần kiểm tra trên hệ thống thật của bạn. API đầy đủ ở `backend/docs/kg/API_INTEGRATION.md` và `retrieval-openapi.json`.
