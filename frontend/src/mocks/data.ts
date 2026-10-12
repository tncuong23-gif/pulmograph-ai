import type { Conversation } from "../types";
export const DEMO_RESPONSE = `### Phiên trả lời minh họa

Tôi đã nhận được câu hỏi của bạn. Đây là **chế độ demo giao diện**, chưa kết nối nguồn tri thức y khoa hoặc mô hình AI.

Khi kết nối hệ thống, câu trả lời có thể được trình bày theo cấu trúc:

1. **Tóm tắt thông tin** liên quan đến câu hỏi.
2. **Giải thích chi tiết** từ nguồn dữ liệu y khoa được cung cấp.
3. **Nguồn tham khảo** để kiểm chứng thông tin.

| Dữ liệu đầu vào | Cách sử dụng dự kiến |
| --- | --- |
| Câu hỏi | Xác định nội dung cần tra cứu |
| Bệnh án | Cung cấp bối cảnh bệnh nhân |
| Ảnh X-quang | Đính kèm để hệ thống xử lý |

*Phiên demo không phân tích file, diễn giải ảnh X-quang hoặc đưa ra chẩn đoán.*`;
export function seedConversations(): Conversation[] {
  const now = new Date();
  return [
    { title: "Tìm hiểu về bệnh phổi tắc nghẽn", days: 0, hours: 1 },
    { title: "Phân biệt COPD và hen phế quản", days: 0, hours: 3 },
    { title: "Các yếu tố nguy cơ hô hấp", days: 1, hours: 0 },
    { title: "Xét nghiệm chẩn đoán viêm phổi", days: 4, hours: 0 },
  ].map((item, i) => {
    const date = new Date(now);
    date.setDate(date.getDate() - item.days);
    date.setHours(date.getHours() - item.hours);
    const createdAt = date.toISOString();
    return {
      id: `demo-${i + 1}`,
      title: item.title,
      createdAt,
      updatedAt: createdAt,
      messages: [
        { id: `demo-user-${i}`, role: "user", content: item.title, createdAt },
        {
          id: `demo-assistant-${i}`,
          role: "assistant",
          content: DEMO_RESPONSE,
          createdAt,
        },
      ],
    };
  });
}
