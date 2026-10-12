# Patient Assertion Gate v2.1

Patient Graph chỉ chứa dữ liệu lâm sàng được người dùng thực sự khẳng định về bệnh nhân, hoặc family history có experiencer rõ ràng.

## Tách History khỏi Patient Graph

- `Viêm phổi là gì?` -> History có `Viêm phổi [condition]`; Patient Graph không ghi bệnh.
- `Viêm phổi có triệu chứng gì?` -> History có chủ đề; Patient Graph không ghi triệu chứng hay bệnh.
- `Tôi có bị viêm phổi không?` -> không được biến câu hỏi chẩn đoán thành `condition=viêm phổi`.
- `Tôi đang sốt, liệu tôi có bị viêm phổi không?` -> chỉ `symptom=sốt` được phép đi vào Patient Graph.

## Điều kiện ghi Patient Graph

Candidate phải đồng thời:

1. là `statement_type=fact` sau clinical extraction;
2. có bằng chứng trực tiếp trong utterance hiện tại;
3. không nằm trong clause dạng question/hypothesis/plan;
4. có experiencer phù hợp;
5. có `display` là concept nguyên tử, không phải câu/mệnh đề dài;
6. qua `ClinicalAssertionValidator` và ngưỡng confidence.

LLM không có quyền ghi thẳng vào Patient Graph. `PatientAssertionGate` là lớp deterministic độc lập chặn lỗi phân loại của LLM.
