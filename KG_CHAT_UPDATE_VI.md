# Cập nhật KG trong chat — v11

Ngày: **11/10/2026**. Bản nền: **medical-ai-integrated v10** đã có giao diện Quản lý dữ liệu thống nhất.

## 1. Những gì đã hoàn thiện

| Phần | Hành vi trong bản v11 |
| --- | --- |
| Nhận diện thực thể | Dùng tên và bí danh trong KG; chuẩn hóa hoa/thường, khoảng trắng, COVID19/COVID-19; hỗ trợ tên thiếu dấu khi xác định rõ |
| Tên mơ hồ hoặc gần đúng | Hỏi lại và cho chọn ngay trong chat; chỉ truy vấn sau khi xác nhận |
| Ý định câu hỏi | Quy tắc cho 25 nhóm ý định cụ thể; `related` là nhóm dự phòng |
| Truy vấn trực tiếp | Lấy các quan hệ gắn với thực thể, theo nhóm ý định |
| Truy vấn nhiều bước | Ba chuỗi: thuốc điều trị bệnh, tác dụng phụ của thuốc điều trị bệnh, chống chỉ định của thuốc điều trị bệnh |
| Tìm đường liên kết | Cần hai thực thể xác định được; mặc định tối đa 3 bước, API cho phép 1–4 |
| Bằng chứng | Giữ chiều quan hệ, mã nguồn, trích đoạn, điều kiện/phủ định; không trả chuỗi thiếu bước cuối như một câu trả lời hoàn chỉnh |
| Giao diện | Hiện kiểu truy vấn và mục Nguồn bằng chứng; bước xác nhận và nguồn được lưu trong lịch sử |
| Theo dõi thời gian | API có `timings_ms` và `elapsed_ms`; log backend có `kg.query` |

Đây là nhận diện bằng từ điển và quy tắc, **không bảo đảm hiểu mọi cách diễn đạt**. Truy vấn so sánh/điểm chung/điểm khác chưa nằm trong đợt này.

**Bộ phân lớp E5-SVM vẫn quyết định luồng KG, RAG hoặc RAG+KG.** Cải tiến này có hiệu lực khi câu hỏi vào luồng `RELATIONAL_QUERY` hoặc `CLINICAL_EXPLANATION_MANAGEMENT`; không đổi mô hình phân lớp và không tự chuyển tất cả câu hỏi bệnh học sang KG.

## 2. Chọn đúng gói

- **`medical-ai-kg-chat-patch.zip`**: chỉ các file thêm/sửa so với v10, dùng để ghi đè dự án đang chạy.
- **`medical-ai-integrated.zip`**: mã nguồn dự án đầy đủ, gồm frontend Teal và các chức năng của v10 cùng cập nhật này. Các dịch vụ/mô hình tải riêng trước đây vẫn cần được cấu hình khi cài mới.
- **`KG_CHAT_PATCH_FILES.txt`**: danh sách chính xác các file trong bản ghi đè, nằm trong cả hai ZIP.
- **`KG_CHAT_TEST_REPORT.md`**: kết quả kiểm thử và giới hạn đã xác minh.

Bản ghi đè **không đổi dependencies**, không cần `pip install` hoặc `npm install` lại nếu v10 đang chạy được. Không cần nạp lại dữ liệu, chạy lại index hay thay mật khẩu Neo4j cho cập nhật này.

Nếu dự án của bạn đã sửa riêng các file trong danh sách hoặc xuất phát từ bản khác v10, hãy đối chiếu thay đổi trước khi ghi đè. Không dùng một bản cũ để ghi đè lên mã bạn vừa sửa ở nơi khác.

## 3. Ghi đè trên Windows

Các ví dụ dưới đây dùng đường dẫn dự án:

```text
D:\medical_wed\banzip\medical-ai-integrated
```

### Bước 1 — Dừng hai tiến trình

Nhấn **Ctrl+C** trong cửa sổ backend và frontend. Giữ các database Docker và dịch vụ AI đang chạy.

Sao lưu `backend\app`, `frontend\src` và các file bạn tự chỉnh sửa sang một thư mục riêng trước khi ghi đè. Các bản sao lưu này dùng để quay lại mã cũ nếu cần.

### Bước 2 — Giải nén bản ghi đè

Giải nén `medical-ai-kg-chat-patch.zip` vào:

```text
D:\medical_wed\banzip\kg-chat-update
```

Sau khi giải nén phải thấy:

```text
D:\medical_wed\banzip\kg-chat-update\medical-ai-integrated\backend
D:\medical_wed\banzip\kg-chat-update\medical-ai-integrated\frontend
```

Sao chép **nội dung** thư mục `medical-ai-integrated` trong gói ghi đè vào thư mục dự án hiện tại, chọn thay thế file trùng tên. Có thể dùng **CMD**:

```bat
robocopy "D:\medical_wed\banzip\kg-chat-update\medical-ai-integrated" "D:\medical_wed\banzip\medical-ai-integrated" /E /R:1 /W:1
```

Lệnh này chỉ chép các file có trong gói, không xóa file khác ở đích. Không thêm `/MIR` hoặc `/PURGE`. Mã kết thúc Robocopy từ 0 đến 7 không phải lỗi thất bại; từ 8 trở lên cần xem lại thông báo.

Gói ghi đè không chứa `.env`, `venv`, `.venv`, `node_modules`, model, dữ liệu nhập, lịch sử hội thoại hay volume database.

### Bước 3 — Chạy lại backend

Mở **CMD**:

```bat
cd /d D:\medical_wed\banzip\medical-ai-integrated\backend
venv\Scripts\activate
python -m uvicorn app.main:app --host 127.0.0.1 --port 8100 --workers 1
```

Nếu môi trường hiện tại tên `.venv`, dùng `.venv\Scripts\activate` thay cho `venv\Scripts\activate`. Tiếp tục dùng môi trường Python đang chạy v10; mã hiện tại của dự án cần Python 3.11 trở lên.

### Bước 4 — Chạy lại frontend

Mở **CMD khác**:

```bat
cd /d D:\medical_wed\banzip\medical-ai-integrated\frontend
npm run dev -- --port 5174 --strictPort
```

Mở <http://localhost:5174/chat>, nhấn **Ctrl+F5**. Nếu trước đây bạn chạy frontend bằng bản build, chạy `npm run build` rồi triển khai lại nội dung `dist` bằng cách đang sử dụng.

Bản cập nhật giữ cấu hình kết nối hiện có. Frontend cần đang dùng chế độ live và backend cổng 8100; CORS cần cho phép origin frontend như trong hướng dẫn chạy dự án trước đó.

## 4. Kiểm tra sau khi cập nhật

### Kiểm tra dịch vụ và tính năng

- Trạng thái hệ thống: <http://127.0.0.1:8100/api/v1/status>.
- KG sẵn sàng: <http://127.0.0.1:8100/modules/kg/health/ready>.
- Khả năng API: <http://127.0.0.1:8100/modules/kg/api/v1/kg/meta>.
- Swagger của KG: <http://127.0.0.1:8100/modules/kg/docs>.

Trong `meta`, `query_modes` phải có:

```json
["one_hop", "multi_hop", "path"]
```

`automatic_intents` có 25 nhóm; `presets` có 3 chuỗi. Metadata cho biết khả năng của mã nguồn, không chứng minh database đang đầy đủ bằng chứng.

### Thử bằng khung chat

Dùng tên thực thể có trong KG của bạn:

| Câu hỏi mẫu | Kỳ vọng khi vào luồng KG và nhận diện tên thành công |
| --- | --- |
| COPD có triệu chứng gì? | Quan hệ trực tiếp |
| COPD dùng thuốc nào? | Chuỗi quan hệ → thuốc điều trị |
| Thuốc điều trị COPD có tác dụng phụ gì? | Chuỗi quan hệ → tác dụng phụ |
| Chống chỉ định của thuốc điều trị COPD? | Chuỗi quan hệ → chống chỉ định |
| Mối liên hệ giữa COPD và viêm phổi? | Đường liên kết |
| Benh phoi tac nghen man tinh co trieu chung gi? | Nhận diện tên thiếu dấu nếu KG có tên/bí danh tương ứng và không nhập nhằng |

Kết quả có thể là “chưa tìm thấy” khi graph thiếu cạnh hoặc bằng chứng. Đó không phải kết luận y khoa rằng mối liên hệ không tồn tại.

Nếu có nhiều tên phù hợp, chọn một tên cho từng ô rồi bấm **Xác nhận và truy vấn**. Hệ thống tiếp tục câu hỏi trước đó; không cần nhập lại toàn bộ câu. Nếu tên trùng cả cách viết và loại, mở **Quản lý dữ liệu → Knowledge Graph → Rà soát trùng** để kiểm tra dữ liệu.

Trong chế độ giọng nói, thông báo sẽ chỉ cách kết thúc bảng giọng nói để chọn tên trong chat. Bản này không tự suy đoán lựa chọn thực thể từ câu trả lời bằng âm thanh.

### Kiểm tra trực tiếp API, không phụ thuộc nhãn E5-SVM

Trong **PowerShell**, dùng UTF-8 để gửi tiếng Việt:

```powershell
$kgPayload = @{ question = "Mối liên hệ giữa COPD và viêm phổi?"; mode = "auto" } | ConvertTo-Json
$kgResult = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8100/modules/kg/api/v1/kg/query" -ContentType "application/json; charset=utf-8" -Body ([System.Text.Encoding]::UTF8.GetBytes($kgPayload))
$kgResult | ConvertTo-Json -Depth 25
```

Xem các trường `status`, `query.mode`, `query.preset`, `retrieval.fact_count`, `llm_context.sources` và `clarification`. Khi cần hỏi lại, không có các cạnh truy vấn được dùng để soạn câu trả lời.

Backend ghi log dạng:

```text
kg.query mode=path preset=None status=ok facts=... elapsed_ms=...
```

`elapsed_ms` chỉ đo phần KG; thời gian phản hồi toàn chat còn gồm xử lý ngữ cảnh, phân lớp, LLM và âm thanh. Bản này không thêm lượt gọi LLM cho bước lập kế hoạch KG.

## 5. Khi kết quả khác mong đợi

| Hiện tượng | Cách kiểm tra |
| --- | --- |
| `query_modes` vẫn chỉ có one_hop | Đã chép đúng thư mục chưa, đã dừng/chạy lại đúng tiến trình backend chưa? |
| Chat không hiện nhãn KG | Kiểm tra `message.metadata.route`; câu hỏi có thể được classifier đưa vào RAG |
| API báo 503 | Xem trạng thái Neo4j/MongoDB, URI/cổng/mật khẩu và `/modules/kg/health/ready` |
| `needs_clarification` | Đọc thông điệp; chọn ứng viên hoặc viết lại tên/thu hẹp câu hỏi |
| Có quan hệ thuốc nhưng không trả tác dụng phụ | Chuỗi phải có bằng chứng đến bước tác dụng phụ; không dùng phần đầu chuỗi để suy đoán |
| Không thấy thực thể vừa nhập | Từ điển cache 30 giây; chờ tối đa khoảng 30 giây hoặc khởi động lại backend |
| Lựa chọn báo cũ/409 | Tải lại hội thoại, dùng bước xác nhận mới nhất hoặc hỏi lại |
| Graph vượt 20.000 thực thể | Bộ nhận diện tự động dừng có thông báo; dùng KG Explorer. Mở rộng bằng entity linker có chỉ mục là công việc tiếp theo |

Không cần sửa ontology, gộp node tự động hoặc xóa database để cài bản cập nhật.

## 6. Phạm vi kiểm chứng

Xem **KG_CHAT_TEST_REPORT.md**. Đã kiểm tra logic, API, lưu/khôi phục bước xác nhận, giao diện và build. Chưa chạy với Neo4j/MongoDB/Ollama thật trên máy Windows của bạn; không cam kết độ chính xác y khoa hay thời gian phản hồi thực tế từ số kiểm thử tự động.
