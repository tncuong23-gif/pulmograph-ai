# Context Resolver v2

## Mục tiêu

Cải thiện phục hồi ngữ cảnh cho hội thoại y khoa, đặc biệt các câu có đồng tham chiếu như `nó`, `bệnh đó`, `thuốc đó`, `triệu chứng đó`.

## Thay đổi chính

- Tách **Discourse Entity** khỏi **Clinical Fact**.
- Một entity trong câu hỏi/hypothesis có thể vào History Graph nhưng không tự động vào Patient Graph.
- Context retrieval = `recent window + relevant history`.
- Thêm antecedent candidate ranking theo entity type, recency, mention confidence và provenance.
- Generic pronoun dùng semantic hint của câu hỏi để ưu tiên đúng loại entity.
- Không resolve khi hai candidate cùng loại gần ngang nhau.
- Qwen nhận `candidate_entities` có cấu trúc và bị validator kiểm tra lại.
- Nếu Qwen bỏ sót một reference nhưng rule có candidate duy nhất đủ mạnh, default `LLM_FALLBACK_TO_RULES=true` cho phép deterministic repair.
- `/v1/history/turns` cũng trích discourse mention cho assistant/system turn.
- API response thêm `resolution_status`, `resolution_method`, `candidate_entities`.
- UI hiển thị candidate ranking và mention cụ thể trong History.

## Regression case quan trọng

```text
Turn 1: Viêm phổi là gì?
Turn 2: Nó có triệu chứng gì?
```

Expected:

```text
normalized_question = Viêm phổi có triệu chứng gì?
resolution_status = resolved
```

Đồng thời `Viêm phổi` không được ghi thành bệnh của patient chỉ vì xuất hiện trong câu hỏi.

## Case mơ hồ

```text
Turn 1: Viêm phổi khác COPD như thế nào?
Turn 2: Nó nguy hiểm không?
```

Expected:

```text
resolution_status = unresolved
```

Hệ thống không chọn ngẫu nhiên `Viêm phổi` hoặc `COPD`.

## Kiểm thử

```bash
python -m pytest -q
```

Kết quả tại thời điểm đóng gói: `15 passed`.
