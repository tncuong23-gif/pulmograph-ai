# Bản rà soát và sửa lỗi — 12/10/2026

Bản này tiếp tục từ `medical-ai-integrated-evidence-ui-full.zip` phiên bản đã bàn giao. Bao gồm backend, frontend, giao diện teal, xác nhận dữ kiện theo từng bước và nguồn đánh số. Không cần nạp lại dữ liệu hoặc tạo lại chỉ mục chỉ vì các thay đổi trong bản rà soát này.

## Các lỗi đã sửa

1. **Thiếu tệp trong gói:** khôi phục `backend/examples/kg/kg_import.json` và mô hình định tuyến mặc định `backend/models/E5_SVM_seed456.joblib` từ bản v14 trước đó. Mô hình giữ nguyên, không huấn luyện lại. Tệp JSON là ví dụ, không tự nạp vào CSDL.
2. **Cấu hình truy vấn KG:** bỏ ba tên quan hệ không có trong ontology đi kèm (`HAS_SIGN`, `HAS_LAB_FINDING`, `TRANSMITTED_BY`) và loại `MedicationClass` khỏi nhóm loại thuốc mặc định. Không sửa ontology hoặc dữ liệu đã nạp. Các quan hệ hợp lệ khác trong cùng nhóm vẫn được sử dụng.
3. **Khung xem nhanh nguồn:** đặt rõ cạnh trên/dưới tự động để tooltip xuất hiện dưới nút không bị kéo giãn bởi CSS mặc định.
4. **Thử lại Clinical IE:** khi phân tích đã thành công nhưng Ollama lỗi, lần thử lại dùng kết quả đã lưu và không cần đọc lại ảnh gốc hoặc chạy lại suy luận.
5. **Ngân sách bằng chứng:** nguồn trùng có tiêu đề dài cũng phải qua kiểm tra giới hạn; không thể vượt ngân sách bằng cách thay metadata của nguồn cũ.
6. **Tham chiếu KG lỗi:** nếu chuỗi/path/ô so sánh có chỉ số fact không hợp lệ, loại toàn bộ nhóm KG với thông báo, giữ nguồn RAG hợp lệ. Không sửa hoặc nối lại chuỗi theo phỏng đoán.
7. **Trích dẫn không tồn tại:** loại cả số nguồn dài hơn ba chữ số, kèm thông báo giới hạn nguồn.
8. **Cấu hình mẫu:** bổ sung lại `.env.example` đúng vị trí cho backend/frontend, dùng giá trị mẫu. Không thay `.env` đang chạy.

## Kết quả kiểm thử

| Kiểm tra | Kết quả |
| --- | --- |
| Backend, toàn bộ bộ kiểm thử | **463 đạt, 0 lỗi, 25 bỏ qua** |
| Frontend | **87 đạt, 0 lỗi**, 17 tệp kiểm thử |
| TypeScript và Vite production build | Thành công |
| 59 lỗi tái hiện từ gói trước | Đã xử lý; giữ các kiểm thử, không đánh dấu bỏ qua để che lỗi |

25 bài bỏ qua thuộc các kiểm thử cần CSDL thực hoặc bộ tài liệu KG mở rộng chưa được cung cấp. Các kiểm thử luồng Ollama/Clinical dùng dịch vụ giả lập; chưa đo suy luận hoặc độ trễ trên GPU Windows của bạn. Vẫn có cảnh báo deprecation từ thư viện, không có lỗi kiểm thử.

Kiểm thử giao diện kiểm tra hover, bàn phím, mở/đóng nguồn và xử lý văn bản an toàn trong DOM. Chưa kiểm tra trực quan trên trình duyệt thật. Kiểm tra số trích dẫn chỉ xác minh nguồn tồn tại, chưa xác minh nội dung y khoa của từng nhận định được nguồn chứng minh.

## Ghi đè dự án đang chạy

1. Dừng backend/frontend. Sao lưu `.env`, SQLite và thư mục `backend/models` hiện có.
2. Dùng `medical-ai-integrated-verified-patch.zip` nếu đang ở bản patient-review hoặc evidence-ui đã bàn giao. Bản vá cộng dồn gồm cả phần lọc bằng chứng trước đó.
3. Giải nén, chép **nội dung bên trong** thư mục `medical-ai-integrated` vào thư mục dự án, đồng ý ghi đè mã nguồn. Cập nhật cả backend và frontend.
4. Giữ `.env`, venv, node_modules, dữ liệu MongoDB/Neo4j/Qdrant/SQLite, thư mục upload, các mô hình đã tải và trọng số riêng. **Nếu bạn đã thay mô hình định tuyến `E5_SVM_seed456.joblib` bằng bản huấn luyện riêng, không ghi đè tệp đó bằng bản mặc định trong ZIP.**
5. `.env.example` chỉ để tham khảo. Không chép nó đè lên `.env` đang hoạt động. Bản vá này không đổi dependencies, embedding hay cấu hình kết nối.
6. Khởi động lại backend:

```bat
cd /d D:\medical_wed\banzip\medical-ai-integrated\backend
call venv\Scripts\activate.bat
python -m uvicorn app.main:app --host 127.0.0.1 --port 8100 --workers 1
```

Nếu môi trường của bạn tên `.venv`, thay dòng kích hoạt thành `call .venv\Scripts\activate.bat`.

Chạy frontend trong cửa sổ khác:

```bat
cd /d D:\medical_wed\banzip\medical-ai-integrated\frontend
npm run dev
```

Nếu dùng frontend build, chạy `npm run build` và triển khai `dist` mới. Ollama, Clinical IE, VieNeu và CSDL vẫn cần chạy theo cấu hình hiện tại.

## Kiểm tra trên máy sau cập nhật

- Gửi câu hỏi có tài liệu RAG/KG. Kiểm tra `[1]`, `[2]`, rê chuột rồi bấm mở nguồn; tải lại trang và kiểm tra nguồn còn đúng.
- Gửi câu “Tôi bị ho khan thì bị gì?”. Bước xác nhận mới chỉ hiển thị dữ kiện vừa khai; dữ kiện Patient Graph được chọn ở bước riêng.
- Thử TXT, ảnh, rồi cả hai. Các luồng Clinical chỉ hoạt động khi dịch vụ và trọng số tương ứng đã sẵn sàng.
- Khi Ollama không sẵn sàng sau phân tích Clinical, chạy lại Ollama rồi thử lại; kết quả phân tích đã lưu được dùng lại.

## Phạm vi gói đầy đủ và giới hạn

`medical-ai-integrated-verified-full.zip` là mã nguồn đầy đủ của bản hiện tại cùng các tài nguyên đã có. Không chứa `.env` riêng, CSDL người dùng, bản ghi âm thử, venv, node_modules hoặc dist. Cài mới vẫn cần cài dependencies, cấu hình dịch vụ và tải các mô hình theo hướng dẫn dự án.

**Hai trọng số NLP trong module Clinical được bàn giao vẫn thiếu:**

```text
backend/clinical_service/vendor/clinical-ie/models/clinical-ie-models-v1.3/joint/final_model/model.safetensors
backend/clinical_service/vendor/clinical-ie/models/clinical-ie-models-v1.3/simplifier/final_model/model.safetensors
```

Nếu máy bạn chưa có hai tệp đúng phiên bản này, luồng TXT/kết hợp chưa thể chạy suy luận đầy đủ. Bản sửa không tạo trọng số thay thế. Việc 463 kiểm thử đạt không đồng nghĩa các dịch vụ thực trên máy đã được xác nhận hoạt động.

Mô hình định tuyến mặc định được khôi phục có SHA256:
`bbc98ad8ce29bcf3bef98c761e56d615cab55d5a1e877dc1b79f99989a0f0015`.

Xem `VERIFIED_PATCH_FILES.txt` để biết toàn bộ tệp bản vá. Hướng dẫn trong tệp này và kết quả kiểm thử trên đây thay thế số liệu kiểm thử cũ trong các báo cáo lịch sử.
