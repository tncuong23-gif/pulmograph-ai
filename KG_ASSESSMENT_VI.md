# KG: kiểm tra độ phủ và đề xuất câu hỏi bổ sung

## Phạm vi bản cập nhật

Đã triển khai phần KG của kế hoạch Patient Graph + Knowledge Graph. Gồm API kiểm tra độ phủ,
ánh xạ khái niệm và đề xuất câu hỏi có bằng chứng. Tất cả truy vấn mới chỉ đọc CSDL.
Không cần nhập lại dữ liệu KG và không đổi cấu trúc các node hiện có.

Phần backend/frontend nay đã nối các API này vào quy trình xác nhận dữ kiện và hỏi bổ sung.
Đọc **DIAGNOSTIC_WORKFLOW_VI.md** để cập nhật và sử dụng toàn bộ luồng. Không chỉ chép thư mục kg_query.
API KG vẫn chỉ đọc CSDL; backend quản lý bản xác nhận và việc ghi Patient Graph.

## Xuất báo cáo KG thật

Trong cửa sổ CMD khác, kích hoạt môi trường của backend, ở thư mục backend chạy:

```bat
python scripts\audit_kg_assessment.py --output kg_assessment_coverage.json
```

Script đọc từng trang qua backend 8100 và lưu JSON. Nó thống kê theo từng node bệnh:
triệu chứng, dấu hiệu, xét nghiệm, hình ảnh, nguy cơ, tiêu chí, chẩn đoán phân biệt, dấu hiệu cấp cứu;
số cạnh có/thiếu tham chiếu bằng chứng. Thống kê giữ số cạnh theo tài liệu, không biến thành trọng số chẩn đoán.

Phạm vi loại node trong phiên bản đầu: Disease, DiseaseSubtype, Syndrome, AcuteCondition.
Báo cáo trả audited_entity_types để không hiểu nhầm là đã bao phủ mọi loại trong ontology.
Nếu nhãn mô hình được ánh xạ đến một loại khác, cần kiểm tra ngữ nghĩa và mở rộng danh sách này có chủ đích.

Báo cáo không khẳng định dữ liệu đủ về y khoa, không xác nhận bằng chứng còn đọc được,
và không suy ra thiếu cạnh là không có quan hệ. API đề xuất câu hỏi sẽ kiểm tra nội dung bằng chứng riêng.
Nên chạy khi không có đợt import đang thay đổi graph.

### So với các nhãn của mô hình chẩn đoán

Cần danh sách nhãn đầy đủ của mô hình chẩn đoán Clinical IE và ánh xạ đã kiểm tra tới ID thực thể KG.
Không sử dụng 5 nhãn của E5_SVM vì đó là phân lớp ý định câu hỏi.

Tạo JSON có dạng label -> danh sách ID KG. Ví dụ dưới đây chỉ minh họa, không phải ID thật:

```json
{"nhan_benh_A": ["ID_BENH_A_TRONG_KG"], "nhan_chua_anh_xa": []}
```

```bat
python scripts\audit_kg_assessment.py --model-map model_disease_map.json --output kg_assessment_coverage.json
```

Script kiểm tra ID tồn tại trong phạm vi node bệnh được audit. Nó không tự chứng nhận ý nghĩa ánh xạ đúng.
Các nhãn không phải bệnh, chẳng hạn nhóm bình thường, cần được xem xét riêng thay vì tạo bệnh giả trong KG.

## API mới

Swagger: http://127.0.0.1:8100/modules/kg/docs

| Phương thức | Đường dẫn trên backend 8100 | Chức năng |
|---|---|---|
| POST | /modules/kg/api/v1/kg/assessment/coverage | Độ phủ từng trang |
| POST | /modules/kg/api/v1/kg/assessment/map | Tìm ID thực thể và báo mơ hồ |
| POST | /modules/kg/api/v1/kg/assessment/followups | Đề xuất câu hỏi từ dữ kiện xác nhận |

### 1. Kiểm tra độ phủ

```json
{"page_size": 30, "after_id": ""}
```

Gửi next_after_id của phản hồi vào after_id để lấy trang tiếp theo, đến khi null.
Có thể thêm disease_ids để kiểm tra một nhóm ID. missing_or_non_disease_ids báo ID không nằm trong phạm vi.

### 2. Ánh xạ

```json
{"mentions": ["ho", "khó thở"]}
```

Chỉ một kết quả trùng tên/alias chính xác mới được trả resolved. Nhiều kết quả hoặc chỉ khớp gần đúng
sẽ trả needs_confirmation và danh sách lựa chọn; hệ thống không tự chọn kết quả đầu tiên.
Resolved ở đây là khớp khái niệm, không phải xác nhận bệnh nhân có triệu chứng đó.

### 3. Đề xuất câu hỏi

Thay KG_ENTITY_ID bằng ID thật từ bước ánh xạ; thời điểm là lúc thực tế người dùng xác nhận:

```json
{
  "patient_id": "patient-001",
  "assessment_id": "assessment-001",
  "facts": [{
    "fact_id": "fact-001",
    "kg_entity_id": "KG_ENTITY_ID",
    "presence": "present",
    "confirmation_status": "user_confirmed",
    "confirmed_at": "2026-09-30T18:00:00+07:00",
    "source_id": "message-001",
    "timeframe": "current"
  }],
  "asked_entity_ids": [],
  "max_questions": 3
}
```

- presence gồm present, absent, unknown; timeframe gồm current, history.
- Yêu cầu có dữ kiện hiện tại khẳng định để tìm bệnh liên quan; dữ kiện cũ không tự coi là hiện tại.
- Chặn present và absent mâu thuẫn cho cùng thực thể, cùng khoảng thời gian khai báo.
- Không hỏi lại thực thể đã có trong facts, kể cả unknown, hoặc trong asked_entity_ids.
- Cần đọc được nội dung bằng chứng từ MongoDB. Chỉ có ID bằng chứng là chưa đủ.
- Quan hệ có thuộc tính JSON hỏng hoặc cờ phủ định/giả định rõ ràng không được dùng làm bằng chứng khẳng định.
- Mọi properties của từng cạnh nguồn được trả riêng trong basis[].assertions; chưa có bộ máy tự đánh giá mọi điều kiện.
- Phiên bản đầu đề xuất câu hỏi triệu chứng và một số nhóm nguy cơ/phơi nhiễm; chưa tự yêu cầu xét nghiệm hay diễn giải ngưỡng.
- Thứ tự dựa trên số bệnh ứng viên có quan hệ trong graph, không phải độ lợi thông tin được hiệu chỉnh hay xác suất bệnh.
- Quá 500 cạnh hoặc 30 bệnh ứng viên: trả needs_narrower_scope thay vì im lặng cắt bớt.
- Không có câu hỏi không có nghĩa đủ dữ kiện hoặc loại trừ được bệnh; diagnostic_ready luôn false trong API này.

API này kiểm tra hợp đồng confirmation_status, không chứng minh người nào đã xác nhận.
Khi tích hợp chính thức, backend phải lấy facts từ snapshot đã xác nhận của đúng bệnh nhân,
không tin dữ liệu tùy ý do trình duyệt gửi. Backend tích hợp đã lưu xác nhận lâu dài trong SQLite; chưa thêm xác thực tài khoản người dùng.

## Bảo toàn điều kiện và bằng chứng

API query hiện có được bổ sung assertions theo từng relation_id/document_id, gồm properties,
proposition_ids, evidence_ids và confidence nguồn. Không gộp mất điều kiện của hai tài liệu khác nhau.
Trường confidence cũ được giữ để tương thích, kèm confidence_semantics;
không được hiển thị thành xác suất mắc bệnh. Một triple nhiều nguồn vẫn có các assertion riêng.

## Kiểm thử

```bat
python -m pytest tests/test_kg_assessment.py tests/upstream/kg -q
```

Kết quả trong môi trường phát triển: 108 passed, 6 skipped.
6 kiểm thử với CSDL thật bị bỏ qua do chưa cấu hình dịch vụ. Các kiểm thử logic dùng dữ liệu giả lập;
chưa kiểm chứng Cypher trên Neo4j và dữ liệu Windows thực tế của bạn.

## Việc tiếp theo sau khi có báo cáo thật

Đối chiếu nhãn Clinical IE, sửa ánh xạ/thiếu bằng chứng, chọn phạm vi bệnh thử nghiệm;
sau đó kiểm tra chất lượng câu hỏi trên luồng xác nhận đã tích hợp.
Không tự đưa kết quả dự đoán của mô hình trở lại Patient Graph như bệnh đã xác định.
