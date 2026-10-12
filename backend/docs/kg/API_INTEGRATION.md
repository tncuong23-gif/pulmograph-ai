# KG Retrieval API — tích hợp chat v12, schema 1.2

Module truy xuất chỉ đọc Neo4j/MongoDB, trả sự kiện và bằng chứng. Bộ điều phối gọi LLM để soạn câu trả lời. Trong dự án tích hợp, dùng backend cổng **8100**; không cần khởi chạy thêm KG server.

## Địa chỉ

| Method | Địa chỉ tích hợp | Công dụng |
| --- | --- | --- |
| POST | `/modules/kg/api/v1/kg/query` | Nhận câu hỏi; chọn một trong sáu kiểu truy vấn |
| GET | `/modules/kg/api/v1/kg/meta` | Kiểu truy vấn, ba preset, 25 nhóm ý định có quy tắc nhận diện và các quan hệ thực sự có trong ontology |
| GET | `/modules/kg/health/ready` | Kiểm tra Neo4j/MongoDB |
| GET | `/modules/kg/docs` | Swagger |

Các path bên trong ASGI module bỏ tiền tố `/modules/kg`.

## Request

```json
{"question": "COPD có triệu chứng gì?"}
```

| Trường | Quy tắc |
| --- | --- |
| `question` | Bắt buộc, 1–2000 ký tự |
| `mentions` | 1–2 tên/bí danh do caller chỉ định; vẫn phải giải nghĩa qua KG |
| `context_mentions` | 1–2 gợi ý chủ đề từ module ngữ cảnh; chỉ dùng nếu câu hỏi dùng đại từ và chưa tìm được thực thể trực tiếp |
| `entity_ids` | 1–2 ID đã chọn; kiểm tra lại sự tồn tại trong Neo4j; không dùng đồng thời với `mentions` |
| `mode` | `auto` (mặc định), `one_hop`, `multi_hop`, `path`, `compare`, `common`, `difference` |
| `intents` | 1–6 nhóm ý định từ meta; dành cho one-hop hoặc so sánh; `auto` chọn so sánh khi có từ khóa so sánh, còn lại giữ one-hop |
| `preset` | `drugs_for_disease`, `drug_adverse_effects`, `drug_contraindications`; dùng cùng `auto` hoặc `multi_hop` |
| `max_hops` | Số nguyên 1–4; mặc định 3; áp dụng cho path |
| `limit` | Số nguyên 1–200; mặc định 30; ngân sách bộ ba trả về |
| `include_evidence` | Mặc định true; false trả ID nguồn nhưng không đọc văn bản bằng chứng |

`multi_hop` chỉ định tường minh phải kèm preset. Không dùng `intents` đồng thời với preset hoặc mode path/multi_hop. Không nhận Cypher hoặc chuỗi bước tùy ý từ caller; trường lạ bị trả HTTP 422. Hai tên chưa rõ không được tự rút thành một tên.

```json
{"question": "Thuốc điều trị COPD có tác dụng phụ gì?", "mode": "auto"}
```

```json
{"question": "Mối liên hệ giữa COPD và viêm phổi?", "mode": "path", "mentions": ["COPD", "viêm phổi"], "max_hops": 3}
```

```json
{"question": "Thuốc nào điều trị COPD?", "mode": "multi_hop", "mentions": ["COPD"], "preset": "drugs_for_disease"}
```

## Phân tích câu hỏi

- Nhận diện từ **tên và bí danh đã lưu**, ưu tiên cụm dài nhất, chuẩn hóa hoa/thường, khoảng trắng và ranh giới chữ/số (`COVID19`, `COVID-19`, `COVID 19`).
- Tên viết thiếu dấu được đối chiếu với từ điển. Chỉ dùng kết quả rõ ràng; nhiều ứng viên cần người dùng chọn. Dấu người dùng đã nhập không bị bỏ để tự thay một tên khác.
- Khớp gần đúng chỉ tạo đề xuất. Hệ thống không tự dùng thực thể fuzzy làm điểm bắt đầu truy vấn. Đề xuất fuzzy có giới hạn và có thể bỏ sót lỗi chính tả; không thay thế một mô hình nhận dạng tiếng nói.
- Tên trùng cả cách viết và loại được yêu cầu kiểm tra trong giao diện duyệt trùng KG, thay vì đưa ra lựa chọn không phân biệt được.
- Cache tên/bí danh 30 giây, tối đa 20.000 thực thể. Khi vượt giới hạn, chat báo cần dùng KG Explorer; không coi một phần từ điển là toàn bộ KG.
- Bộ quy tắc có ví dụ nhận diện cho **25 nhóm ý định**; không nhận diện được dùng `related`. Đây là quy tắc từ khóa có kiểm soát, không phải bộ hiểu ngôn ngữ tùy ý.
- Multi-hop tự động hiện giới hạn ở ba preset. Path yêu cầu câu hỏi về đường liên kết/mối liên hệ và hai thực thể xác định được.
- So sánh dùng `compare` (tổng hợp), `common` (điểm chung) hoặc `difference` (khác biệt trong dữ liệu/cần kiểm tra). Cần đúng hai ID khác nhau, cùng nhóm bệnh hoặc cùng nhóm thuốc, và 1–6 tiêu chí rõ ràng. Thiếu tiêu chí yêu cầu hỏi lại; không dùng `related` để tự so sánh tất cả quan hệ.

## Response

Các trường chính:

| Trường | Nội dung |
| --- | --- |
| `schema_version` | `1.2` cho kết quả truy xuất |
| `status` | `ok`, `no_entity`, `no_facts`, `needs_clarification` |
| `query` | Tên đã nhận diện, intent, mode thực tế, preset, max_hops, phương pháp nhận diện và cờ xác nhận thực thể |
| `retrieval` | Anchor, số bộ ba, khuyến nghị fallback, `complete: false`, cờ cắt kết quả |
| `clarification` | Lý do, thông điệp, nhóm ứng viên và `can_confirm`; null khi không cần hỏi lại |
| `llm_context` | `facts`, `sources`, `chains`, `paths`, `interpretation`; thêm `comparison` cho truy vấn so sánh hợp lệ |
| `timings_ms` | Thời gian nhận diện thực thể, lập kế hoạch, truy xuất bằng chứng |
| `elapsed_ms` | Tổng thời gian bên trong KG; không bao gồm ngữ cảnh, classifier, LLM hoặc TTS |
| `warnings` | Giới hạn nguồn hoặc kết quả |

Mỗi `fact` giữ `subject`, `predicate`, `object`, `hop`, `relation_ids`, `doc_ids`, `proposition_ids`, `evidence_ids`, `evidence`, `confidence`, `assertions` và `confidence_semantics`. Bằng chứng là dữ liệu, không phải chỉ dẫn cho LLM. Phải giữ điều kiện, phủ định và phạm vi áp dụng trong `assertions[].properties`; không biến confidence của nguồn thành xác suất mắc bệnh.

`llm_context.sources` loại trùng theo cặp `(doc_id, evidence_id)`. Không tạo trích đoạn nếu MongoDB thiếu bản ghi.

Mỗi phần tử của `chains` có `fact_indices`. Mỗi phần tử của `paths` có `nodes` và `fact_indices`. Các chỉ số bắt đầu từ **0** và tham chiếu `llm_context.facts`; đọc theo đúng thứ tự trong danh sách. Ví dụ hình dạng, chỉ minh họa cấu trúc:

```json
{"chains": [{"fact_indices": [0, 1, 2]}], "paths": []}
```

Ngân sách trả về giữ nguyên một chuỗi/đường hoàn chỉnh hoặc bỏ cả chuỗi/đường đó, không cắt mất cạnh giữa. Chuỗi tác dụng phụ/chống chỉ định phải đến đúng bước cuối; không có bước cuối trả `no_facts`. Preset liệt kê thuốc vẫn giữ thuốc nối trực tiếp với bệnh khi bước thành viên nhóm thuốc là tùy chọn.

Đường đi giữ chiều thật của từng quan hệ, kể cả khi hướng đi qua đồ thị ngược chiều cạnh. Đường nối hai thực thể không tự chứng minh quan hệ nhân quả giữa hai đầu. Không tìm thấy dữ liệu không chứng minh quan hệ không tồn tại. `complete` luôn false vì KG và kết quả truy xuất đều có giới hạn.

## So sánh, điểm chung và điểm khác

```json
{"question":"So sánh triệu chứng COPD và viêm phổi"}
```

```json
{"question":"COPD và viêm phổi có triệu chứng nào giống nhau?","mode":"common","intents":["symptom"]}
```

```json
{"question":"Đối chiếu hai thuốc đã chọn","mode":"difference","entity_ids":["ID_THUOC_A","ID_THUOC_B"],"intents":["adverse_effect","contraindication"]}
```

Hai ID trong ví dụ cuối là chỗ điền ID thật. Planner dùng quan hệ **trực tiếp**; không nhận preset multi-hop cùng comparison. Tác dụng phụ/chống chỉ định của thuốc điều trị hai bệnh cần nêu hai thuốc cụ thể hoặc truy vấn từng bệnh bằng preset cũ.

`llm_context.comparison` có `mode`, `entities`, `criteria`, `rows`, `coverage`, `notice`, `counts_in_retrieved_data`, `returned_rows`, `complete`, `truncated`, `matching` và `no_result_reason`. Mỗi hàng:

- `criterion`, `criterion_label`: tiêu chí và nhãn.
- `feature`: thực thể đích gồm id/name/type; `predicate`, `direction`: quan hệ và chiều so với chủ thể.
- `classification`, `label`: kết quả đối chiếu.
- `cells`: đúng hai ô, theo thứ tự `entities`, mỗi ô có `entity_id`, `status`, `fact_indices` tham chiếu `llm_context.facts` từ 0.

| classification | Diễn giải |
| --- | --- |
| `common` | Cùng ID đích, quan hệ, chiều cạnh và toàn bộ tập thuộc tính assertion hợp lệ. Vẫn phải giữ phủ định và điều kiện trong nguồn. |
| `left_only` / `right_only` | Chỉ tìm thấy ở một bên trong phần dữ liệu truy xuất. Ô còn lại có status `not_found_in_retrieved_data`, không phải phủ định y khoa. |
| `assertion_difference` | Có quan hệ tương ứng ở hai bên nhưng tập thuộc tính khác nhau; cần đọc nguồn. Không tự kết luận mâu thuẫn. |
| `needs_review` | Thuộc tính nguồn không hợp lệ hoặc thiếu assertion; không đủ điều kiện ghi là điểm chung. |

Chỉ đối chiếu ID chuẩn đã có, không gộp hai ID trùng tên, không tự đồng nhất loại/chiều quan hệ, không tính tỷ lệ giống nhau, không xếp hạng hiệu quả thuốc. Cùng thuộc tính phủ định vẫn là hàng tương ứng trong dữ liệu; không được diễn đạt thành triệu chứng/tác dụng phụ hiện diện.

Mỗi bên/mỗi tiêu chí có ngân sách truy xuất riêng: tối đa `min(per_query_rows, max(30, limit+1))` hàng cho mỗi truy vấn chiều cạnh. Chạm giới hạn đặt `query_limited` trong coverage và `truncated` ở kết quả. So sánh được tính trước ngân sách bộ ba đầu ra. Hàng nào vượt `limit` bị bỏ **cả hàng**, không bỏ riêng một bên. Bằng chứng văn bản được đọc sau khi chọn hàng, vẫn theo `evidence_per_fact` hiện tại.

`common` chỉ trả hàng common; `difference` trả các hàng còn lại; `compare` trả tổng hợp. Nếu không có hàng, `no_result_reason` phân biệt `no_data`, `no_matching_rows`, `result_limit`. Không tự chuyển kết quả rỗng thành khẳng định hai bệnh giống hệt nhau hoặc hoàn toàn khác nhau.

## Tiếp tục sau xác nhận trong chat

Frontend gửi vào **backend chính**, không gọi module trực tiếp:

```json
{
  "conversationId": "conversation-id",
  "message": {"id": "new-message-id", "role": "user", "content": "Tôi xác nhận tên đã chọn."},
  "kg_confirmation": {"message_id": "pending-assistant-message-id", "entity_ids": ["selected-kg-id"]}
}
```

Backend đối chiếu với **tin nhắn xác nhận mới nhất của cùng hội thoại**, kiểm tra một lựa chọn cho mỗi nhóm và khôi phục câu hỏi/nhãn phân lớp đã lưu. Không nhận sự kiện/bằng chứng do frontend tự gửi. Không phân lớp lại câu “Tôi xác nhận…”. Lựa chọn cũ hoặc khác hội thoại trả 409; ID ngoài danh sách trả 422; ID đã bị xóa trong KG yêu cầu hỏi lại.

`metadata.kg_query`, `metadata.kg_clarification`, `metadata.kg_comparison` và `metadata.sources` được lưu cùng tin nhắn. `kg_comparison` chứa comparison và mảng `facts` để giao diện khôi phục bảng, thuộc tính/phủ định và nguồn theo từng bên.

## HTTP và điều phối

- `needs_clarification`: hỏi lại trực tiếp, chưa gọi LLM soạn câu trả lời.
- `no_facts` với luồng KG: thông báo chưa đủ bằng chứng, không gọi LLM để đoán.
- `no_facts` với luồng RAG+KG: có thể dùng kết quả RAG nếu thực sự có tài liệu, kèm ghi chú thiếu nguồn KG. Riêng so sánh rỗng trả thông báo giới hạn trực tiếp, không nhờ LLM/RAG tự tạo hàng so sánh.
- 422: request không hợp lệ; sửa request trước khi thử lại.
- 503: cấu hình/database chưa sẵn sàng. Envelope lỗi vẫn dùng `schema_version: "1.0"` và mã `INVALID_REQUEST`/`DEPENDENCY_UNAVAILABLE` để tương thích.

Bộ phân lớp **E5-SVM vẫn được giữ nguyên**. Khi dự đoán `GENERAL_MEDICAL_QUERY` nhưng câu hỏi có từ khóa so sánh, bộ điều phối chuyển sang `RELATIONAL_QUERY`, lưu `classifier.original_label` và `routing_override: kg_comparison_cue`. KG vẫn xác thực tên và tiêu chí trước truy xuất. `CLINICAL_EXPLANATION_MANAGEMENT` tiếp tục lấy RAG+KG; `DIAGNOSTIC_ASSESSMENT` và `OUT_OF_SCOPE` giữ luồng cũ. Nếu model phân lớp nhầm vào hai nhãn này, quy tắc so sánh không ghi đè; cần kiểm tra/hiệu chỉnh classifier riêng.

## Kiểm thử

Chạy trong `backend`, với môi trường có requirements-dev:

```bat
python -m pytest tests/test_kg_comparison.py tests/test_kg_chat_query.py tests/test_kg_chat_confirmation.py tests/upstream/kg/test_retrieval_api.py tests/upstream/kg/test_query.py -q
```

Xem `KG_COMPARE_TEST_REPORT.md` ở thư mục gốc để biết phạm vi kiểm thử và phần chưa chạy với database/LLM thật.
