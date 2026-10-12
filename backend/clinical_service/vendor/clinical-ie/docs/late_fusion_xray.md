# Kết hợp muộn Text + Graph v2 và ConvNeXt-Tiny

Ngày thực hiện: 2026-10-11. Chỉ phục vụ nghiên cứu, học tập, không dùng để chẩn đoán bệnh nhân thực tế.

## 1. Phần đã tích hợp

- Checkpoint đầu vào: `models/convnext_tiny_model.pt`, 27.829.356 tham số, chọn epoch 15 theo validation macro-F1.
- Metadata checkpoint khớp 12 nhãn và fingerprint của `dataset/img_xray/prepared_v1`.
- Bundle mới độc lập: `dist/classifier-fusion-v1`. Chứa bản sao nguyên vẹn Text + Graph v2 và checkpoint ảnh, cấu hình fusion, SHA-256 của từng thành phần. Không cần tải trọng số từ Internet khi chạy.
- Giữ nguyên `dist/classifier-bundle-v1`, `dist/classifier-bundle-v2`, checkpoint gốc, dữ liệu ảnh, tập chia, IE và phương pháp truy hồi. Benchmark cũ vẫn kiểm chứng được 16 hash nguồn.
- CLI/API nhận thêm `image_path`/`--image`. Không có ảnh: trả kết quả Text + Graph v2 nguyên trạng. CLI mặc định vẫn là Text + Graph v2; chọn bundle fusion rõ ràng khi cần ảnh.
- Không fine-tune lại bất kỳ nhánh nào. Không huấn luyện mô hình GNN mới. Nhánh Graph hiện tại là LightGBM trên đặc trưng đồ thị và đặc trưng lâm sàng từ văn bản, không phải GNN.

## 2. Phương pháp

Nhánh Text + Graph giữ nguyên trọng số nội bộ: Text = 0,5294117647, Graph = 0,4705882353, Bayes = 0. Giữ bias quyết định của v2 đã chọn trước đó.

Với ca có văn bản và đồ thị:

```text
p_TG = 0.5294117647 * p_Text + 0.4705882353 * p_Graph
s_TG = log(p_TG + 1e-9) + bias_v2
s_fusion = 0.70 * s_TG + 0.30 * log(max(p_Image, 1e-12))
```

Xếp hạng 12 lớp bằng `s_fusion`, trả Top 5. `softmax(s_fusion)` chỉ là trọng số quyết định chuẩn hóa. Không phải xác suất chẩn đoán đã hiệu chuẩn. Trường tương thích `all_probabilities` và `top5[].raw_probability` mang ý nghĩa trọng số này khi có ảnh; tên trường cũ được giữ để tránh phá hợp đồng đầu ra.

Đây là logarithmic opinion pooling, tương ứng tích có trọng số của phân bố quyết định hai nhánh. Không nối ảnh vào văn bản, không trộn embedding, không sửa đồ thị, không dùng nhãn bệnh làm đầu vào dự đoán.

Đã thử hai họ đơn giản: linear pooling và log pooling; mỗi họ có 21 trọng số ảnh từ 0 đến 1, bước 0,05. Chọn bằng macro-F1 validation; hòa điểm ưu tiên trọng số ảnh thấp hơn, rồi linear. Lựa chọn được lưu trong `selection.json` **trước khi chạy suy luận ảnh test**. Không đổi phương pháp/trọng số sau khi xem test.

### Tiền xử lý ảnh

Giống mã nguồn notebook Colab: grayscale → 3 kênh → resize toàn ảnh 224 × 224 bằng bilinear, antialias → ToTensor → normalize mean `[0.485, 0.456, 0.406]`, std `[0.229, 0.224, 0.225]`. Không center crop, không augmentation, không dùng ImageNet weights download. Model ở chế độ `eval()`, suy luận float32.

Checkpoint chỉ nạp bằng `torch.load(weights_only=True)`. Kiểm tra kiến trúc, nhãn, thông số tiền xử lý và nạp state_dict strict. Ảnh lỗi hoặc bundle sai checksum gây lỗi rõ ràng, không âm thầm bỏ ảnh rồi giả vờ fusion thành công.

### Thiếu dữ liệu

| Dữ liệu có sẵn | Hành vi |
| --- | --- |
| TXT/đồ thị, không ảnh | Text + Graph v2 nguyên trạng; không khởi tạo CNN |
| TXT/đồ thị và ảnh | Fusion theo cấu hình đã khóa |
| Chỉ ảnh qua API phân lớp thấp tầng | Image-only; `status=fallback_image_only`, không trộn phân bố đều của nhánh nền |
| Không có gì qua API thấp tầng | Giữ `insufficient_information` của v2 |
| Ảnh được truyền với bundle v2 | Báo lỗi yêu cầu bundle fusion |

API hỏi triệu chứng vẫn giữ nguyên kiểm tra intent và yêu cầu đủ thông tin. Truy hồi 3 ca tham chiếu vẫn dựa trên văn bản/đồ thị, **không dùng ảnh và không thay đổi điểm phân lớp**. Trọng số fusion được chọn trên bệnh án đầy đủ; hiệu quả trên mô tả triệu chứng ngắn kèm ảnh chưa được benchmark riêng.

## 3. Kết quả cùng cohort

Ghép bằng `doc_id` của manifest ảnh, không ghép theo thứ tự dòng và không ghép ngẫu nhiên cùng nhãn. Kiểm tra nhãn, split, checksum, unique doc_id/pixel hash trong và giữa ba split.

- Validation: 1.678 ca có đủ hai nhánh.
- Test: 1.682 ca có đủ hai nhánh. Text + Graph có 1.683 ca; một ca `Xepphoi` (`DOC_e85edd8ca5e500fa`) không còn ảnh trong prepared cohort sau chính sách loại ảnh trùng. Không xóa hay sửa ca đó; khi chạy không có ảnh vẫn dùng v2.
- Các hàng so sánh sau đều dùng **cùng 1.682 ca test**, không lấy accuracy Text + Graph của 1.683 ca để so với fusion của 1.682 ca.

| Mô hình | Macro-F1 | Accuracy | Balanced accuracy | Weighted-F1 | Top-5 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Text + Graph v2 | 43,22% | 67,36% | 44,80% | 67,42% | 96,91% |
| ConvNeXt-Tiny, chạy local | 31,83% | 58,50% | 34,25% | 58,86% | 97,92% |
| Linear fusion 50/50, đối chứng | 46,60% | 67,72% | 46,98% | 67,24% | 98,81% |
| Log fusion 50/50, đối chứng | 43,05% | 70,33% | 39,95% | 69,46% | 99,17% |
| **Log fusion 70/30, chọn bằng validation** | **48,55%** | **73,31%** | **46,21%** | **72,47%** | **99,05%** |

Validation macro-F1: v2 = 46,83%; image-only local = 39,37%; fusion chọn = 55,83%.

Test fusion tăng **5,33 điểm phần trăm macro-F1** và **5,95 điểm phần trăm accuracy** so với v2 trên cùng cohort. Bootstrap ghép cặp, phân tầng theo lớp, 1.000 lần: khoảng 95% của chênh lệch macro-F1 là **+0,90 đến +9,97 điểm phần trăm**. Đây là độ bất định lấy mẫu ca trong cohort, không đo bất định giữa seed, giữa bệnh nhân độc lập hay giữa bệnh viện. Khoảng trên validation là sau chọn cấu hình, không phải ước lượng cải thiện độc lập.

### Không phải mọi lớp đều tốt hơn

| Lớp | Ca test ghép cặp | F1 v2 | F1 fusion |
| --- | ---: | ---: | ---: |
| Binhthuong | 363 | 77,81% | 79,74% |
| COPD | 70 | 46,15% | 49,50% |
| Covid | 129 | 58,09% | 78,11% |
| Hen | 11 | 14,29% | 28,57% |
| Lao | 90 | 43,32% | 55,45% |
| Phuphoi | 6 | 11,76% | **0%** |
| Suyhohap | 130 | 38,91% | 42,45% |
| Trandich | 36 | 25,32% | 49,28% |
| Trankhi | 3 | 20,00% | **0%** |
| Uphoi | 5 | 6,45% | 20,00% |
| Viemphoi | 837 | 76,52% | 79,47% |
| Xepphoi | 2 | 100% | 100% |

Macro-F1 của nhóm hiếm định nghĩa sẵn (`Xepphoi`, `Trankhi`, `Uphoi`, `Phuphoi`, `Hen`) giảm từ 30,50% xuống 29,71%. Điểm tuyệt đối của các lớp chỉ có 2–6 ca rất không ổn định. Không thay trọng số theo kết quả test này. Muốn cải thiện tiếp phải bổ sung dữ liệu/validation độc lập hoặc OOF trên train trước một vòng đánh giá mới.

## 4. Giới hạn và kiểm chứng

1. Text + Graph v2 từng được chọn sau khi xem benchmark test. Vì vậy test hiện tại **đã bị lộ cho lựa chọn nhánh nền**, dù lựa chọn fusion mới không dùng test. Không trình bày đây là kết quả test độc lập tuyệt đối.
2. Validation cũng được dùng chọn epoch CNN và bias của v2. Chưa có nested validation hoặc cohort ngoài.
3. Dữ liệu ghép bằng định danh của dataset; không có chứng nhận split độc lập theo bệnh nhân, theo thời gian hay nhãn do chuyên gia kiểm chứng. Near-duplicate ảnh chưa được xác nhận toàn bộ. Đây là giới hạn dữ liệu gốc, không được coi checksum/disjoint doc_id là chứng minh độc lập bệnh nhân.
4. Macro-F1 CNN báo trong CSV Colab là 39,79%; chạy local là 39,37%. Accuracy và balanced accuracy validation trùng báo cáo Colab, nhưng một số chỉ số còn lệch. Đã chạy lại toàn bộ 1.678 ảnh trên CPU: **không có ca nào khác Top-1 so với MPS**, sai lệch logit tối đa khoảng 2,24e-5. Tiền xử lý và cách nạp state_dict khớp mã nguồn notebook. Chưa có file prediction và môi trường gốc từ Colab để kết luận nguyên nhân; CUDA/AMP/phiên bản thư viện là khả năng, không phải nguyên nhân đã xác minh. Benchmark dùng số thực đo local, không thay bằng metric trong metadata.
5. Benchmark dùng snapshot đồ thị đã trích trước đây. Kiểm thử toàn tuyến tái trích IE là kiểm thử vận hành một ca validation, **không phải benchmark end-to-end mới trên toàn bộ tập**. Đồ thị tái trích có thể khác snapshot.
6. Đã kiểm tra batch/API nền trên toàn bộ 3.360 cặp validation + test; kiểm thử wrapper fusion cũng kiểm tra điểm và Top-1 từng ca. 234 test và 9 subtest qua; 9 cảnh báo đã có về bundle tham chiếu legacy trong test và API torch deprecated. Benchmark cũ vẫn qua kiểm chứng nguồn/hash.

## 5. Môi trường và cách dùng

Python 3.12; môi trường phân lớp/NLP giữ nguyên. Phần ảnh đã kiểm thử với torch 2.13.0, torchvision 0.28.0, Pillow 12.3.0. Chạy được CPU, Apple Silicon MPS, CUDA khi runtime tương ứng hỗ trợ. Không sao chép thư mục `.venv` sang máy khác.

```bash
cd /Users/thien/Documents/Gliner
.venv/bin/python -m pip install -r requirements-vision.txt
```

Trên máy mới, cài requirements hiện tại của dự án trước rồi bổ sung requirements-vision. Không nâng cấp tùy ý scikit-learn/LightGBM khi dùng bundle joblib đã đóng băng. PyTorch/torchvision phải dùng cặp phiên bản tương thích. Khi không có GPU, dùng `--device cpu`; tốc độ sẽ khác. File ảnh qua PIL như JPEG/PNG; chưa bổ sung đọc DICOM nguyên bản.

### CLI: bệnh án TXT và ảnh cùng ca

Thay `/duong-dan/benh_an.txt` và `/duong-dan/xray.jpg` bằng hai file của **cùng ca bệnh**:

```bash
cd /Users/thien/Documents/Gliner
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python -m clinical_ie.cli analyze-file \
  --input /duong-dan/benh_an.txt \
  --image /duong-dan/xray.jpg \
  --ie-bundle dist/clinical-ie-models-v1.3 \
  --classifier-bundle dist/classifier-fusion-v1 \
  --index-bundle dist/reference-index-v1.1 \
  --device mps \
  --output artifacts/demo_fusion_result.json
```

Không có ảnh: bỏ `--image`, vẫn có thể dùng bundle fusion; kết quả phân lớp quay về v2 nguyên trạng. Có thể tiếp tục dùng bundle v2 và các lệnh cũ như trước. CLI `ask-symptoms` cũng nhận `--image`, nhưng chưa có đánh giá chất lượng riêng cho đầu vào câu hỏi ngắn.

Hệ thống không tự xác minh danh tính ảnh/TXT. Không lấy ảnh của một bệnh nhân ghép với văn bản bệnh nhân khác, kể cả cùng nhãn bệnh.

### Python API toàn tuyến

```python
from clinical_ie.api import ResearchAssistant

assistant = ResearchAssistant.from_bundles(
    ie_bundle="dist/clinical-ie-models-v1.3",
    classifier_bundle="dist/classifier-fusion-v1",
    index_bundle="dist/reference-index-v1.1",
    device="auto",
)
result = assistant.analyze_file("benh_an.txt", image_path="xray.jpg")
print(result.status)  # late_fusion nếu đủ hai nhánh
print(result.top5)

# Không có ảnh: giữ nguyên quyết định v2.
text_only = assistant.analyze_file("benh_an.txt")
```

### Python API nếu đã có đồ thị

```python
from clinical_ie.classification.late_fusion import LateFusionClassifier

classifier = LateFusionClassifier.from_bundle("dist/classifier-fusion-v1", device="auto")
prediction = classifier.predict(text=prediagnosis_text, graph=case_graph, image_path="xray.jpg")
print(prediction.top5)
print(prediction.branch_probabilities["image"])
```

`image_probabilities=` là giao diện thấp tầng dành cho cache benchmark: vector 12 giá trị theo **đúng thứ tự LABELS**, tổng bằng 1. Người gọi chịu trách nhiệm về đúng model/ca/thứ tự nhãn. Không truyền đồng thời với `image_path`. Mức API này không tự chứng minh vector thuộc ca bệnh đang xét.

## 6. Chạy lại benchmark

Đầu ra hiện tại được giữ tại `reports/late_fusion_benchmark_2026-10-11`. Khi chạy lại, chọn **thư mục output/cache/bundle mới**, không ghi đè kết quả hiện có.

```bash
# 1. Chỉ suy luận validation trước.
.venv/bin/python scripts/cache_xray_predictions.py \
  --output-dir reports/fusion_new/image_cache --device mps --splits validation

# 2. Khóa lựa chọn bằng validation.
.venv/bin/python scripts/benchmark_late_fusion.py --phase select \
  --cache-dir reports/fusion_new/image_cache --output-dir reports/fusion_new

# 3. Sau khi selection.json đã được lưu mới chạy test.
.venv/bin/python scripts/cache_xray_predictions.py \
  --output-dir reports/fusion_new/image_cache --device mps --splits test

# 4. Đánh giá và xuất bundle độc lập, không ghi đè bản cũ.
.venv/bin/python scripts/benchmark_late_fusion.py --phase evaluate \
  --cache-dir reports/fusion_new/image_cache --output-dir reports/fusion_new \
  --fusion-bundle dist/classifier-fusion-new

# 5. Kiểm thử hệ thống.
.venv/bin/python -m pytest -q tests
```

Các script benchmark ghi JSON/NPZ đầy đủ, không làm tròn trước tính metric. CSV hiện tại được xuất từ các bảng typed qua artifact-tool và kiểm tra lại với JSON/NPZ. `scripts/export_late_fusion_csv.mjs` cần Node và `@oai/artifact-tool` nếu muốn dùng lại bước xuất CSV; đây là công cụ báo cáo, **không là phụ thuộc của inference**.

Kiểm tra lại báo cáo đã xuất:

```bash
.venv/bin/python scripts/verify_late_fusion_benchmark.py \
  reports/late_fusion_benchmark_2026-10-11 --bundle dist/classifier-fusion-v1
```

## 7. Tệp kết quả

Trong `reports/late_fusion_benchmark_2026-10-11`:

| Tệp | Nội dung |
| --- | --- |
| `fusion_summary.csv` | 5 phương pháp × 2 split, các metric tổng hợp |
| `fusion_per_class.csv` | Precision, recall, F1, TP/FP/FN, support của từng lớp |
| `fusion_confusion_matrices.csv` | Ma trận nhầm lẫn dạng dài; hàng là nhãn thật, cột là nhãn dự đoán |
| `fusion_validation_grid.csv` | 42 cấu hình đã thử chỉ trên validation |
| `fusion_paired_coverage.csv` | Số ca Text + Graph, số ca ghép được, ca thiếu ảnh theo lớp |
| `fusion_bootstrap_delta.csv` | Chênh lệch macro-F1 fusion − v2, khoảng bootstrap |
| `selection.json` | Cấu hình khóa, tiêu chí chọn, hash nguồn |
| `benchmark_results.json` | Số chính xác, support, thời gian, giới hạn |
| `predictions.npz` | doc_id, y, score, dự đoán và vector ảnh chưa làm tròn |
| `image_cache/` | Logit CNN validation/test và hash/runtime tương ứng |
| `cpu_validation_audit/` | Đối chứng CPU cho validation |
| `verification.json` | Kiểm chứng các bảng, metric, hash, runtime audit |
| `neural_api_smoke.json` | Tóm tắt chạy thử toàn tuyến một ca validation |

Metric trong CSV là tỷ lệ 0–1; các cột hậu tố `_pp` là **điểm phần trăm**. `is_selected=true` chỉ lựa chọn validation đã cố định, không phải lựa chọn lại bằng test.

Suy luận ảnh theo batch 16 trên M4/MPS: validation 22,09 giây, test 22,22 giây, khoảng 0,0132 giây/ảnh, không tính tải model và kiểm tra toàn bộ checksum. CPU validation khoảng 73 giây. Đây không phải thời gian toàn tuyến IE cho một bệnh án.

Smoke toàn tuyến MPS: tải ba bundle khoảng 12,67 giây; phân tích một ca TXT + ảnh khoảng 5,43 giây, có tính lazy-load CNN. Chỉ là một lần đo, không phải cam kết độ trễ trung bình.

Các gói bàn giao/archivo cũ trong `release/` **chưa được dựng lại** và chưa tự động chứa module/bundle ảnh mới. Khi bàn giao bản có ảnh, phải bổ sung code mới, requirements-vision và `dist/classifier-fusion-v1` cùng bundle IE/index đang dùng.
