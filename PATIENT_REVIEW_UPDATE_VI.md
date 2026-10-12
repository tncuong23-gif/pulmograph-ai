# Cập nhật xác nhận dữ kiện bệnh nhân theo từng bước

Bản vá áp dụng trên **medical-ai-integrated(1).zip bạn gửi ngày 12/10/2026**. Cập nhật backend và frontend cùng lúc; không áp lên một nhánh khác chỉ dựa vào tên ZIP giống nhau.

## Hành vi sau cập nhật

1. **Xác nhận dữ kiện vừa khai:** chỉ dữ kiện trong câu hiện tại. Ví dụ “Tôi bị ho khan thì bị gì?” hiển thị “ho khan”; không kéo sốt, chóng mặt, khó thở từ hồ sơ vào bước này. Người dùng có thể sửa, thêm hoặc không dùng một dòng trước khi xác nhận.
2. **Kiểm tra Patient Graph:** dữ kiện cũ được tổng hợp và hỏi riêng, mặc định **Không dùng lần này**. Chọn lại thông tin còn áp dụng rồi xác nhận, hoặc bấm **Không dùng dữ kiện cũ, tiếp tục**. Dữ kiện tương đương với bước 1 không được hỏi lại. Khi không có dữ kiện cũ cần kiểm tra, hệ thống đi thẳng sang bước tiếp theo.
3. **Khai thác thông tin từ KG:** chỉ dùng dữ kiện đã xác nhận ở các bước trước để gợi ý câu hỏi. Trả lời Có, Không, Không biết hoặc Bỏ qua. Gợi ý chưa trả lời không được ghi thành triệu chứng.
4. **Xem lại và gửi đánh giá:** kiểm tra bản tổng hợp cuối, sau đó mới gửi Clinical IE.

Bước 2 không tự chọn toàn bộ hồ sơ, không gọi KG trước khi người dùng quyết định. Câu hỏi chat thường và ba luồng tải TXT/X-quang giữ cách xử lý của dự án đầu vào.

## Các lỗi đã sửa

- Tách `drafts` của câu vừa khai khỏi `history_drafts` của Patient Graph; bổ sung trạng thái `confirming_history` và thao tác `confirm_history`.
- Tổng hợp các bản ghi tương đương theo tên chuẩn hóa, loại dữ kiện, chủ thể, Có/Không, thời điểm và chi tiết lâm sàng. Lưu các nguồn tương ứng trong `source_refs`, có thể xem các lần ghi nhận trên giao diện.
- Dòng cùng tên nhưng khác thời điểm, chủ thể, phủ định hoặc giá trị/liều vẫn được phân biệt. Không gộp các dữ kiện mâu thuẫn thành một kết luận.
- Không nối `status: user_reported` hoặc `status: historical` vào ghi chú. Làm sạch chuỗi kỹ thuật bị nối lặp khi dựng danh sách; giá trị, đơn vị, liều, tần suất và ghi chú người dùng vẫn được giữ.
- Không tự gán tất cả dữ kiện Patient Graph thành tiền sử. Đọc thời điểm đã lưu; trường hợp chưa có thời điểm rõ ràng được nhắc kiểm tra trên giao diện.
- Giữ mô tả “ho khan” nếu có trong câu gốc và nhận diện rõ. KG vẫn có thể ánh xạ tên chuẩn “ho”; Clinical IE nhận mô tả đã xác nhận.
- Xử lý câu vừa có khai triệu chứng vừa hỏi chẩn đoán như “Tôi bị ho khan thì bị gì?”; câu giả định và câu chỉ hỏi “Tôi có bị ho khan không?” không được tự biến thành dữ kiện.
- Kiểm tra ID theo từng bước ở backend: không thể đưa ID của dữ kiện cũ vào bước xác nhận câu mới hoặc ngược lại.
- Không ghi lại các dữ kiện Patient Graph được chọn nguyên trạng như một bản ghi mới trong mỗi lượt đánh giá. Nếu người dùng sửa nội dung, trạng thái hoặc thời điểm thì đó là một lần khai mới và được lưu.
- Không tiếp tục lồng toàn bộ `original_fact` của các vòng trước vào metadata Patient Graph mới. Giữ nguồn tham chiếu và xác nhận trong bản dữ kiện tại backend.

## Ghi đè trên Windows

1. Dừng backend và frontend bằng Ctrl+C. Sao lưu SQLite đang dùng và `.env` của bạn.
2. Giải nén `medical-ai-integrated-patient-review-patch.zip`. Chép **nội dung bên trong** thư mục `medical-ai-integrated` vào thư mục dự án đang chạy, đồng ý ghi đè. Không tạo thêm tầng thư mục.
3. Bản vá không có `.env`, venv, node_modules hoặc dữ liệu CSDL. Không cần cài lại thư viện, nạp lại RAG hay tạo lại index KG.
4. Chạy lại backend và frontend:

```bat
cd /d D:\medical_wed\banzip\medical-ai-integrated\backend
call venv\Scripts\activate.bat
python -m uvicorn app.main:app --host 127.0.0.1 --port 8100 --workers 1
```

```bat
cd /d D:\medical_wed\banzip\medical-ai-integrated\frontend
npm run dev
```

Nếu dùng giao diện đã build, chạy `npm run build`, triển khai dist mới và tải lại trang. Không dùng dist của phiên bản cũ. Các dịch vụ Clinical IE, Ollama và CSDL vẫn cần chạy theo cấu hình hiện có.

Gói `medical-ai-integrated-patient-review-full.zip` chứa mã nguồn cộng dồn từ ZIP bạn gửi cùng cập nhật này. Cấu hình riêng, dữ liệu phát sinh, thư mục môi trường và build cũ được loại khỏi gói mã nguồn. Để sửa dự án đang chạy, ưu tiên bản vá nhỏ; giữ nguyên thư mục dữ liệu và môi trường của bạn.

## Dữ liệu cũ và lượt đánh giá đang mở

- Lượt cũ **chưa xác nhận** ở trạng thái `confirming` được tách danh sách khi backend khởi động. Version tăng để tab cũ phải tải lại dữ liệu, không gửi xác nhận với danh sách lỗi thời.
- Không sửa ngầm bản dữ kiện đã xác nhận hoặc snapshot đã gửi Clinical IE. Nếu lượt cũ đã xác nhận danh sách sai/trùng, hãy **hủy lượt đó và gửi lại câu hỏi** để dùng quy trình mới. Nếu lượt đang chạy, chờ hoàn tất trước khi mở lượt mới.
- Không xóa lịch sử hoặc gộp vật lý các node Patient Graph. Các bản ghi cũ được tổng hợp ở lớp xác nhận; nguồn và dấu thời gian vẫn có thể kiểm tra.
- Với dữ kiện từng bị phiên bản cũ chuyển sai sang “tiền sử”, cần kiểm tra và sửa thời điểm khi chọn dùng lại. Không suy đoán thời điểm thật chỉ từ trạng thái cũ.
- Bỏ qua dữ kiện ở bước 2 chỉ có nghĩa không dùng trong lần đánh giá này, không xóa khỏi Patient Graph.

## Kiểm tra nhanh

1. Trong hội thoại đã có dữ kiện cũ, gửi “Tôi bị ho khan thì bị gì?”. Bước 1 chỉ có dữ kiện mới phù hợp; không tự thêm sốt/chóng mặt/khó thở.
2. Xác nhận bước 1. Bước 2 mặc định dữ kiện cũ chưa chọn; các dòng tương đương đã được tổng hợp và không còn chuỗi status nối lặp trong ghi chú.
3. Bấm không dùng dữ kiện cũ, hoặc chọn riêng một dữ kiện rồi xác nhận. KG mới được hỏi ở bước tiếp theo.
4. Câu hỏi KG về sốt chưa phải dữ kiện sốt. Trả lời “Không biết” giữ nguyên CHƯA BIẾT; Bỏ qua không thêm dòng vào bản dữ kiện.
5. Tải lại trang ở bước 2 để kiểm tra khả năng khôi phục, sau đó tiếp tục theo đúng bước.

Giọng nói ở bước 2 hướng dẫn chọn dữ kiện cũ trong bảng; có thể nói **“Bỏ qua dữ kiện cũ”**. Câu xác nhận dữ kiện vừa đọc ở bước 1 không tự xác nhận toàn bộ hồ sơ ở bước 2.

## Kết quả kiểm thử và giới hạn

- 60 bài backend trọng tâm về quy trình xác nhận, Context, Patient Graph và giọng nói đạt.
- 83 bài frontend đạt; TypeScript và production build thành công.
- Kiểm thử toàn backend trên ZIP gốc: 374 đạt, 59 lỗi, 25 bỏ qua. Sau cập nhật: 388 đạt, **cùng 59 lỗi**, 25 bỏ qua; không có tên bài lỗi mới. 57 lỗi do thiếu `backend/examples/kg/kg_import.json`; 2 lỗi do bộ test KG tham chiếu quan hệ/loại không có trong ontology hiện tại. Bản vá không thay ontology để làm các bài này đạt.
- Phần Clinical IE/KG/CSDL thật được giả lập trong kiểm thử luồng; chưa chạy trên Neo4j và GPU của máy bạn. Không có tuyên bố mới về độ chính xác chẩn đoán hoặc tốc độ suy luận.

Danh sách file: `PATIENT_REVIEW_PATCH_FILES.txt`. Bản vá được đối chiếu bằng cách áp vào nguồn ZIP đầu vào rồi so sánh với gói mã nguồn đầy đủ đã loại dữ liệu riêng.
