# Bàn giao suy luận v0.2.0 — 11/10/2026

Tài liệu hiện hành cho code v0.2.0. Các bản nén/wheel v0.1.0 và tài liệu lịch sử không được coi là sản phẩm mới. Chỉ phục vụ nghiên cứu/học tập, không sử dụng để chẩn đoán hoặc điều trị thực tế.

## 1. Phạm vi

- Câu mô tả triệu chứng: `ask_symptoms` / CLI `ask-symptoms`.
- Nội dung bệnh án dạng `str`: `analyze_text` (Python API).
- Bệnh án TXT UTF-8: `analyze_file` / CLI `analyze-file`.
- Mảng chuỗi entity: `analyze_entities` / CLI `analyze-entities`, ví dụ `["ho", "sốt", "ran ẩm"]`.
- Ảnh X-quang JPEG/PNG cùng ca: `image_path` / `--image`, chọn bundle fusion. Image-only có ở API thấp tầng `LateFusionClassifier.predict(image_path=...)`, không ở `ask_symptoms`.
- Đầu ra: Top 5 trong 12 lớp, đồ thị riêng từng ca đối với các hàm analyze, thực thể/quan hệ, cảnh báo và tối đa 3 ca tham chiếu.
- Neo4j: xuất JSONL/Cypher offline; không kèm server Neo4j.
- **Không kèm giao diện web hoàn chỉnh.** `scripts/demo_server.py` là demo IE/đồ thị lịch sử, không phải facade phân lớp/truy vấn/fusion v0.2.0. Không đưa nó vào bản bàn giao suy luận.
- Không đóng gói môi trường `.venv`, dữ liệu train thô, notebook huấn luyện hoặc checkpoint trung gian vào bản giao suy luận.

## 2. Cấu trúc bản giao

```text
clinical-ie-handover-0.2.0/
├── HANDOVER.md, README.md, pyproject.toml
├── requirements.txt, requirements-vision.txt, requirements-test.txt
├── src/clinical_ie/                 # code và schema resource
├── models/
│   ├── clinical-ie-models-v1.3/
│   ├── classifier-bundle-v2/        # nền Text + Graph
│   └── classifier-fusion-v1/        # bản nền đóng băng + ConvNeXt-Tiny
├── data/reference-index-v1.1/       # 8.264 ca train, tóm tắt tham chiếu
├── examples/                       # TXT tổng hợp, JSON entity mẫu, script demo
└── docs/                           # tài liệu hiện hành
```

Trong repository gốc, cả bốn bundle trên nằm dưới `dist/`. Layout trên chỉ dùng khi giải nén bản giao; luôn truyền đường dẫn bundle tường minh. Classifier CLI mặc định tương đối `dist/classifier-bundle-v2` được giữ để tương thích repo; trong bản giao phải chỉ rõ `--classifier-bundle models/...`.

## 3. Môi trường

Python **3.12**. Runtime đã thử: macOS Apple Silicon, CPU/MPS. Chưa chứng nhận Linux/Windows/CUDA; không sao chép `.venv` từ máy này sang máy khác.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
# Cần thêm dòng này để dùng ảnh:
python -m pip install -r requirements-vision.txt
python -m pip check
```

Các phiên bản pin trong requirements là runtime nghiệm thu, đặc biệt scikit-learn/LightGBM cho bundle joblib và cặp torch/torchvision cho ảnh. Cài thư viện cần mạng; suy luận với bundle nội bộ chạy offline. Không cần `nbformat`/matplotlib/notebook runtime cho sản phẩm inference.

Kiểm thử core trong repo: `pip install -r requirements-test.txt`, rồi `python -m pytest -q`. Cấu hình pytest mặc định chỉ collect `tests/`. Test huấn luyện CNN tách riêng, dùng `dataset/img_xray/tools/requirements-training-test.txt` trong venv riêng và chạy `python -m unittest discover -s dataset/img_xray/tools -p 'test_*.py' -v`. Những test đó không thuộc gói inference và không được bỏ qua rồi báo đã chạy.

## 4. Khởi tạo và API

```python
from clinical_ie.api import ResearchAssistant

assistant = ResearchAssistant.from_bundles(
    ie_bundle="models/clinical-ie-models-v1.3",
    classifier_bundle="models/classifier-fusion-v1",
    index_bundle="data/reference-index-v1.1",
    device="cpu",  # auto / cpu / mps / cuda
)

query = assistant.ask_symptoms("Tôi ho, sốt và khó thở ba ngày.")
record = assistant.analyze_file("examples/synthetic_patient_case.txt")
text = assistant.analyze_text("Bệnh nhân ho và khó thở.", document_id="demo_text")
entities = assistant.analyze_entities(["ho", "sốt", "không đau ngực"], document_id="demo_entities")
# Tùy chọn ảnh CÙNG CA:
# entities = assistant.analyze_entities(["ho", "sốt"], image_path="xray.jpg")
print(entities.to_dict())
```

| Hàm | Đầu vào chính | Đầu ra / đặc điểm |
| --- | --- | --- |
| `from_bundles(ie_bundle, classifier_bundle, index_bundle, *, device="auto", allow_rule_fallback=False)` | Đường dẫn bundle | Nạp model offline; kiểm manifest, file bắt buộc, checksum; fail-closed |
| `ask_symptoms(question, *, image_path=None)` | Chuỗi triệu chứng | `QueryAnswer`, ý định theo bộ lọc hiện có, Top 5, tối đa 3 ca tương tự |
| `analyze_file(path, *, document_id=None, namespace="case", image_path=None)` | TXT UTF-8 | `AnalysisResult`, `input_type=medical_record_txt`; lọc prediagnosis, IE, đồ thị, phân lớp |
| `analyze_text(text, *, document_id=None, namespace="case", image_path=None)` | Bệnh án dạng chuỗi | Cùng chính sách với TXT, `input_type=medical_record_text` |
| `analyze_entities(entities, *, document_id=None, namespace="entity_case", image_path=None)` | `list[str]` | `AnalysisResult`, `input_type=entity_array`; quy trình ở mục 5 |
| `ClinicalPipeline.type_entity_strings(values, *, document_id)` | `list[str]` | `ExtractionResult`; chỉ nhận diện loại/span/qualifier từng chuỗi, không phân lớp, không nối quan hệ |
| `doctor(ie_bundle=None, classifier_bundle=None, index_bundle=None)` | Bundle cần kiểm | `PASS` hoặc `ERROR`, dependency theo chức năng; không thay thế smoke suy luận |
| `get_runtime_info()` | Không | Phiên bản/runtime và lỗi import dependency, gồm torchvision/Pillow |
| `export_graph_jsonl(graphs, path)` / `export_neo4j_cypher(graphs, output_dir)` | Danh sách graph dict | JSONL / bộ Cypher offline; không tự ghi vào server Neo4j |

Mỗi kết quả có `to_dict()` để ghi JSON. Giữ đối tượng assistant và tái sử dụng, không nạp model lại cho mỗi câu hỏi. Không bật `allow_rule_fallback` khi nghiệm thu mô hình neural; fallback chỉ dùng khi người gọi chủ động cho phép.

## 5. Quy ước mảng entity

Mảng gồm chuỗi không rỗng, tối đa 512 mục, mỗi mục tối đa 1.000 ký tự. Không nhận object/string JSON đơn thay mảng. Danh sách rỗng được nhận nhưng không có dự đoán nếu cũng không có ảnh.

1. Chuẩn hóa Unicode NFC và khoảng trắng đầu/cuối từng mục.
2. Joint model nhận từng mục độc lập trong batch, giữ ngưỡng đã lưu trong IE bundle. **Không chạy ViT5 sinh câu đơn** và không ghép các mục thành một câu/bệnh án.
3. Lấy thực thể có span hợp lệ trong chính mục đó; một mục có thể cho 0, 1 hoặc nhiều thực thể. Không bảo đảm tên tùy ý đều nhận diện được. Các quan hệ model trả khi nhận diện đều bị bỏ, kể cả trong cùng mục.
4. Qualifier dùng rule hiện có trên từng chuỗi; ví dụ `"không ho"` có thể cho entity `ho` phủ định. Chuỗi không ghi phủ định/tiền sử dùng mặc định PRESENT/CURRENT theo chính sách hiện có; không suy ra ngữ cảnh giữa các mục.
5. Dựng và gộp trùng graph bằng logic hiện tại, chỉ tạo các cạnh Case→Entity suy ra từ loại (HAS_SYMPTOM/HAS_SIGN/...), không tự tạo LOCATED_AT/HAS_DURATION/HAS_RESULT giữa các mục rời rạc. Anatomy/Time/Result có thể là node cô lập.
6. Gọi classifier với `text=""`, graph đã tạo: nhánh Text bị tắt, dùng fallback graph-only. Có ảnh thì fusion với điểm nền graph-only; cấu hình 70/30 vốn chọn trên bệnh án đầy đủ nên **chưa được tối ưu/benchmark riêng cho entity-array**.
7. Tìm ca tương tự bằng graph, không dùng danh sách chuỗi làm văn bản lâm sàng giả.

Các trường bổ sung trong `extracted_facts`:

- `input_entities`: mảng ban đầu.
- `entity_inputs`: một kết quả cho mỗi mục, gồm `input_index` (0-based), chuỗi chuẩn hóa, `status=recognized|unrecognized`, `num_entities`.
- `entities`: entity đã nhận diện, `input_index`, span start/end **cục bộ trong chuỗi chuẩn hóa tương ứng**, loại, score model và qualifier. Đây không phải offset trong một TXT gốc.
- `triples=[]`, `num_triples=0`: không tạo SPO học từ các mục; cạnh cấu trúc được xem trong `graph.edges`.
- `quarantined`: prediction không hợp lệ, không tự đổi sang nhãn khác.

Trùng chuỗi vẫn giữ provenance mỗi mục; graph gộp node theo khóa hiện có, không gộp ho có/ho phủ định. Nếu không nhận diện được entity nào và không có ảnh: `status=insufficient_information`, `top5=[]`, không trả Top 5 giả từ phân bố đều. Nếu có ảnh nhưng không có entity nhận diện được, nhánh thấp tầng dùng image-only và trả cảnh báo.

Chỉ truyền chứng cứ trước chẩn đoán; không truyền nhãn bệnh đích/kết luận vào mảng để tránh rò rỉ nhãn. Độ chính xác của loại thực thể và phân lớp trên các chuỗi rời rạc chưa có tập đánh giá riêng.

## 6. CLI demo sau giải nén

```bash
clinical-ie doctor \
  --ie-bundle models/clinical-ie-models-v1.3 \
  --classifier-bundle models/classifier-fusion-v1 \
  --index-bundle data/reference-index-v1.1

clinical-ie analyze-file --input examples/synthetic_patient_case.txt \
  --ie-bundle models/clinical-ie-models-v1.3 \
  --classifier-bundle models/classifier-fusion-v1 \
  --index-bundle data/reference-index-v1.1 --device cpu --output case_result.json

clinical-ie ask-symptoms --text "Tôi bị ho, sốt và khó thở ba ngày." \
  --ie-bundle models/clinical-ie-models-v1.3 \
  --classifier-bundle models/classifier-fusion-v1 \
  --index-bundle data/reference-index-v1.1 --device cpu --output query_result.json

clinical-ie analyze-entities --entities '["ho", "sốt", "ran ẩm", "không đau ngực"]' \
  --ie-bundle models/clinical-ie-models-v1.3 \
  --classifier-bundle models/classifier-fusion-v1 \
  --index-bundle data/reference-index-v1.1 --device cpu --output entities_result.json

# Hoặc thay --entities bằng --input examples/entity_array.json.
# Thêm --image xray.jpg cho ảnh CÙNG CA, không chọn đồng thời --entities và --input.
```

Doctor lỗi bundle/dependency cần thiết trả ERROR và exit code 1, chỉ PASS trả 0. Manifest rỗng, thiếu file bắt buộc, checksum sai, sai loại bundle/thứ tự nhãn và đường dẫn thoát bundle bị từ chối. Doctor không nạp tất cả trọng số hoặc kiểm tra accuracy; luôn chạy thêm smoke bằng model thật.

## 7. Toàn vẹn và giới hạn

- Finder `.DS_Store` không phải payload; verifier/export không tính nó vào inventory và không đưa vào bản giao. Không bỏ qua tùy tiện những file lạ khác.
- Đã đồng bộ riêng checksum schema đồ thị sau khi đối chiếu từ vựng/số đếm; không sửa đồ thị, ảnh hoặc bộ chia. Kiểm tra bằng `scripts/verify_graph_export.py` trong repo.
- Phiên bản bundle IE/fusion/classifier/index không đổi vì không huấn luyện hoặc đổi weights; **phiên bản thư viện là 0.2.0**.
- Điểm phân lớp chưa hiệu chuẩn xác suất. Graph classifier là LightGBM, không phải GNN; Bayes weight 0 ở v2. Ca tương tự chỉ tham khảo, không thay thứ hạng phân lớp.
- Bộ lọc ý định truy vấn được giữ nguyên theo yêu cầu; vẫn có giới hạn đã ghi ở báo cáo rà soát, không tuyên bố đã sửa mục đó.
- Chỉ số fusion 48,55% macro-F1 trên cohort test đã có không phải chất lượng riêng của input entity; test nền đã từng được dùng chọn mô hình, lớp hiếm yếu và chưa chứng nhận độc lập theo bệnh nhân.
- Quyền phân phối dữ liệu tham chiếu/model và riêng tư cần được chủ dự án quyết định trước khi giao cho bên khác. Gói không chứa TXT thô hoặc ảnh train, nhưng index vẫn là dữ liệu nghiên cứu cần kiểm soát truy cập.
- Giữ nguyên artifact cũ để rollback; không đổi tên file cũ rồi coi là bản mới. Chỉ gọi archive mới là nghiệm thu sau khi build và chạy smoke từ bản giải nén.
