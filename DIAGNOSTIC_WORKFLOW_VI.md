# Luồng chẩn đoán có xác nhận — bản cập nhật 2026-09-30

## Đã nối vào dự án

Câu hỏi text → Context → E5/SVM → nếu `DIAGNOSTIC_ASSESSMENT` thì mở lượt đánh giá:

1. Backend lấy dữ kiện mới do Context trích xuất và dữ kiện liên quan trong Patient Graph của cuộc trò chuyện.
2. Giao diện hiển thị bản nháp. Dữ kiện cũ mặc định **Loại bỏ**, chỉ dùng khi người dùng chọn lại. Người dùng có thể sửa tên, loại, Có/Không/Không biết, hiện tại/tiền sử, bệnh nhân/người thân, chi tiết; thêm dữ kiện nếu bộ trích xuất bỏ sót.
3. Người dùng xác nhận các dữ kiện được chọn thuộc cùng một bệnh nhân. Backend lưu bản xác nhận và nguồn trong SQLite.
4. Backend ánh xạ tên sang KG bằng tên/alias khớp duy nhất. Kết quả mơ hồ không tự chọn. KG có thể gợi ý câu hỏi bổ sung có bằng chứng đọc được. Không có câu hỏi không có nghĩa dữ kiện đã đủ.
5. Hiển thị lần lượt tối đa 5 câu hỏi. Có, Không, Không biết và Bỏ qua là các lựa chọn khác nhau. Câu trả lời đi vào API assessment, **không phân lớp lại**. Có thể kết thúc hỏi bổ sung sớm.
6. Hiển thị bản dữ kiện cuối. Chỉ khi người dùng xác nhận và nhấn **Gửi đánh giá**, backend mới đóng băng snapshot, đồng bộ các khẳng định vào Patient Graph và gọi Clinical IE `/api/v1/ask-symptoms`.
7. Qwen trình bày kết quả từ snapshot và phản hồi Clinical IE. Kết quả dự đoán không được ghi thành bệnh đã xác định trong Patient Graph.

Trong lúc đánh giá, ô chat thường và nút gửi file bị khóa để tránh gửi câu trả lời bổ sung qua mô hình phân lớp. Muốn sửa bản dữ kiện sau bước xác nhận đầu: hủy lượt và gửi lại câu hỏi.

## Cập nhật bản đang chạy trên Windows

Gói này chứa **backend và frontend đầy đủ**. Clinical IE/engine và CSDL thật vẫn dùng bản đang chạy trên máy bạn.

1. Dừng backend và frontend bằng Ctrl+C. Sao lưu thư mục dự án và `backend/data` khi backend đã dừng.
2. Giải nén gói mới vào một thư mục riêng, ví dụ `D:\medical-ai-integrated-v2`.
3. Nếu đã dùng **backend tích hợp**: giữ cấu hình `.env` hiện tại, model riêng, dữ liệu `data` và các file upload. Không ghi đè bằng `.env.example`. Nếu cập nhật tại thư mục cũ, thay `backend/app`, `backend/tests`, `backend/scripts` và mã frontend từ gói mới; giữ `.venv`, `.env`, `data`, `uploads`, `models`, Docker volumes. Không chỉ chép `kg_query` như bản cập nhật KG trước.
4. Nếu chuyển sang đường dẫn mới, kiểm tra `DATABASE_PATH`, `UPLOAD_DIR`, đường dẫn model trong `.env` và `stored_path` của file cũ. Không xóa file SQLite cũ. Schema được bổ sung tự động khi khởi động.
5. Khởi động các CSDL, Ollama và Clinical IE như trước. Chạy backend trong môi trường đã cài thư viện:

```bat
cd /d D:\medical-ai-integrated-v2\backend
.venv\Scripts\activate
python -m uvicorn app.main:app --host 127.0.0.1 --port 8100 --workers 1
```

Nếu thư mục mới chưa có môi trường Python, dùng phần cài đặt trong `README_VI.md`. Không chuyển nguyên `.venv` sang đường dẫn khác.

6. Mở CMD khác, cấu hình frontend `.env`:

```dotenv
VITE_USE_MOCK_API=false
VITE_API_BASE_URL=http://127.0.0.1:8100
VITE_CHAT_TIMEOUT_MS=600000
VITE_FILE_PROCESSING_TIMEOUT_MS=600000
```

```bat
cd /d D:\medical-ai-integrated-v2\frontend
npm ci
npm run dev
```

Mở http://localhost:5173. Backend: http://127.0.0.1:8100/docs. Không cần dependency backend mới cho tính năng này. Giữ `--workers 1`.

## Kiểm tra hoạt động

- Tạo cuộc trò chuyện mới, nhập câu hỏi mô tả triệu chứng và yêu cầu hỗ trợ chẩn đoán.
- Console phải có `route=DIAGNOSTIC_ASSESSMENT`; nếu classifier trả nhãn khác thì luồng tương ứng vẫn chạy.
- Trước khi xác nhận cuối: không có lần gọi `/api/v1/ask-symptoms` từ luồng chat này.
- Khung “Kiểm tra dữ kiện” xuất hiện. Nếu bản nháp trống, thêm dữ kiện thủ công; không tự suy ra triệu chứng từ tên bệnh.
- Chọn dữ kiện → xác nhận → trả lời/bỏ qua câu hỏi KG → kiểm tra bản cuối → Gửi đánh giá.
- Tải lại trang trong quá trình này: dữ kiện đã gửi và bước hiện tại được khôi phục từ backend. Những chỉnh sửa trong form chưa nhấn xác nhận chưa được lưu.
- Nếu backend khởi động lại lúc đang chẩn đoán, lượt được chuyển sang trạng thái lỗi có nút thử lại với cùng snapshot. Backend không tự gọi lại mô hình khi khởi động.
- Nếu Qwen lỗi sau khi Clinical IE đã trả lời, thử lại sẽ dùng lại kết quả Clinical IE đã lưu.
- Nếu Patient Graph lỗi, snapshot vẫn tồn tại ở SQLite. Sau khi có kết quả, nút **Thử đồng bộ Patient Graph** chỉ đồng bộ dữ kiện đã xác nhận, không gọi lại Clinical IE.

## API và trạng thái

| API | Chức năng |
|---|---|
| POST `/api/v1/chat/message` | Trả `message` và `assessment` khi mở lượt chẩn đoán |
| GET `/api/v1/conversations/{id}` | Lịch sử + assessment mới nhất, dùng để khôi phục và polling |
| GET `/api/v1/assessments/{id}` | Xem snapshot, facts, câu trả lời, sự kiện và trạng thái lưu |
| POST `/api/v1/assessments/{id}/actions` | confirm, answer, finish_questions, diagnose, cancel, retry_graph_sync |

Mỗi action có `action_id` duy nhất và `version` lấy từ phản hồi gần nhất. Gửi lại cùng action_id không áp dụng lại. Version cũ trả HTTP 409; frontend tải trạng thái mới nhất. Trạng thái gồm confirming → questioning/ready → running → completed/failed; có nhánh cancelled.

Các thay đổi workflow và message liên quan được ghi trong cùng transaction SQLite. Metadata của tin nhắn được giữ sau khi tải lại trang. Backend lưu bảng `assessments`; không cần tạo bảng bằng tay.

Context `/v1/context/resolve` mặc định chỉ trả `draft_facts`, `patient_facts` và lưu History. HTTP API từ chối `persist_patient_facts=true`; việc ghi Patient Graph diễn ra qua snapshot đã xác nhận. Hàm Python nội bộ vẫn giữ tùy chọn ghi cũ để kiểm thử tương thích, nhưng backend không dùng tùy chọn này.

## Ý nghĩa lưu trữ

- **History**: câu gốc, câu chuẩn hóa, các lượt xác nhận/hỏi đáp, câu trả lời; mention trong History không đồng nghĩa với bệnh nhân mắc bệnh.
- **Snapshot trong SQLite**: dữ kiện chính xác đã xác nhận cho một lượt, gồm phủ định, chưa biết, thời điểm, chủ thể, nguồn, chi tiết, câu hỏi/bằng chứng KG và audit sự kiện. Đây là nguồn sự thật của lượt đánh giá, không tin KG ID hoặc cờ xác nhận tự gửi tùy ý từ trình duyệt.
- **Patient Graph**: các khẳng định Có/Không do người dùng xác nhận, nguồn là turn của snapshot. `certainty=unknown`, `status=user_reported/historical`, `attributes.clinically_verified=false`: xác nhận của người dùng không có nghĩa xác thực y khoa. Không biết/Bỏ qua không bị lưu thành “không có triệu chứng”. Chi tiết đã xác nhận nằm trong `attributes.details`; dữ liệu gốc và nguồn cũ được giữ để đối chiếu.
- Bản cập nhật không xóa dữ kiện cũ. Dữ kiện cũ hoặc mâu thuẫn phải được chọn/sửa khi xác nhận lại; không tự dùng toàn bộ Patient Graph.
- Vẫn dùng `conversationId` làm phạm vi patient/session. Chưa có tài khoản thật hoặc hồ sơ bệnh nhân xuyên nhiều cuộc trò chuyện. Không tự ghép dữ liệu giữa các cuộc trò chuyện.

## Phạm vi KG và giới hạn cần biết

- KG chỉ gợi ý câu hỏi về triệu chứng và các nhóm nguy cơ/phơi nhiễm đã hỗ trợ. Không dùng thứ hạng KG như xác suất bệnh.
- Chỉ ánh xạ exact/alias duy nhất. Dữ kiện chưa ánh xạ vẫn được giữ trong snapshot và gửi bằng văn bản, nhưng không dùng làm seed KG.
- Bộ lọc hiển thị yêu cầu nguồn bằng chứng và thuộc tính quan hệ hợp lệ, không có điều kiện trong `properties`. Gợi ý có điều kiện bị bỏ qua. Nguồn vẫn hiển thị để người dùng kiểm tra; đây chưa phải thẩm định mức phù hợp y khoa. Điều kiện ẩn trong văn bản nguồn chưa được máy đánh giá đầy đủ.
- KG không sẵn sàng/không có câu hỏi phù hợp: thông báo và cho người dùng xem lại, chủ động gửi bản dữ kiện hiện có. Không tạo câu hỏi giả thay thế.
- Clinical IE hiện nhận `{text: ...}`, chưa có hợp đồng structured facts. Backend viết rõ Có/Không/Chưa biết, hiện tại/tiền sử, bệnh nhân/người thân trong văn bản; gửi nguyên snapshot riêng cho Qwen. Cần đánh giá mô hình Clinical IE thực tế để biết nó xử lý các cờ này chính xác đến đâu; kiểm thử bộ điều phối không chứng minh chất lượng chẩn đoán.
- Gói này dành cho cấu hình local hiện có; chưa bổ sung đăng nhập, phân quyền bệnh nhân hoặc cơ chế hàng đợi nhiều worker.

## File bệnh án

Luồng cũ được giữ: chọn file tại giao diện → **nhấn Gửi** mới upload tới backend → backend gọi `/api/v1/analyze-file` → Qwen tóm tắt. Bỏ qua phân lớp. Không gọi trực tiếp Clinical IE từ trình duyệt. Chưa đưa các thực thể từ bệnh án qua luồng xác nhận text này; không tự ghi chúng thành dữ kiện Patient Graph.

## Kiểm thử

Xem `TEST_REPORT.md`. Kiểm thử API/state/UI dùng dependency giả lập hoặc Context memory; chưa chạy bộ CSDL, GPU và mô hình thật trên máy Windows của bạn.
