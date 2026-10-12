# Context Resolver v2.3 — Context Need Gate

## Nguyên tắc

Context Resolver chỉ được phục hồi câu hỏi khi câu hiện tại phụ thuộc ngữ cảnh.

### 1. Câu tự đủ nghĩa

Giữ nguyên câu sau bước chuẩn hóa khoảng trắng:

```text
Viêm phổi có triệu chứng gì?
COPD có nguy hiểm không?
Tôi bị ho ba ngày nay.
```

Kết quả:

```json
{
  "resolution_status": "not_needed",
  "resolution_method": "context_not_needed"
}
```

Qwen/OpenAI resolver không được gọi cho nhóm này.

### 2. Câu có tham chiếu

Ví dụ:

```text
COPD là gì?
Nó có triệu chứng gì?
```

Kết quả:

```text
COPD có triệu chứng gì?
```

### 3. Câu tỉnh lược thiếu chủ thể

Ví dụ:

```text
Viêm phổi là gì?
Có nguy hiểm không?
```

Kết quả:

```text
Viêm phổi có nguy hiểm không?
```

Các mẫu v2.3 hỗ trợ gồm các nhóm như:

- `Có nguy hiểm không?`
- `Điều trị thế nào?`
- `Có chữa được không?`
- `Còn triệu chứng?`
- `Nguyên nhân?`
- `Biến chứng?`
- `Phòng ngừa thế nào?`
- `Có cần ngưng không?`
- `Tác dụng phụ?`

### 4. Không đủ căn cứ

Nếu không có antecedent hoặc có nhiều antecedent cùng mức ưu tiên:

```text
Viêm phổi khác COPD như thế nào?
Có nguy hiểm không?
```

Kết quả:

```json
{
  "normalized_question": "Có nguy hiểm không?",
  "resolution_status": "unresolved"
}
```

Hệ thống không đoán.

## Bảo vệ chống paraphrase

`ContextResolutionValidator` có hard gate: nếu câu ban đầu được xác định là `not_needed`, mọi rewrite do LLM đề xuất đều bị loại và `normalized_question` được đưa về câu gốc.

Đối với câu cần resolve, validator chỉ chấp nhận antecedent tồn tại trong candidate list và đúng priority tier. Với các mẫu tỉnh lược đã biết, câu cuối được dựng lại bằng template deterministic, không lấy paraphrase tự do của LLM.
