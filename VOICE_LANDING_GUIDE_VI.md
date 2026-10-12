# Trang giới thiệu và trợ lý hội thoại giọng nói

> Tài liệu bản giọng nói đầu tiên. Bản hiện tại dùng VieNeu-TTS cục bộ và streaming; xem **[VOICE_VIENEU_GUIDE_VI.md](VOICE_VIENEU_GUIDE_VI.md)** để cài đặt. Các đoạn Edge TTS, chọn chỉ số đoạn và cổng frontend 5174 dưới đây thuộc bản cũ.

## Bản cập nhật này có gì?

- Trang `/`: giới thiệu hệ thống, nút **Bắt đầu chat**, tiếp tục hội thoại gần nhất khi có lịch sử.
- Dùng logo phổi, minh họa phân tích bệnh án và hai ảnh mới cho trang giới thiệu, màn hình chào chat. Ảnh nằm trong `frontend/public/assets`; xem `UI_TEAL_UPDATE_VI.md` cho bản cập nhật giao diện mới nhất.
- `/chat` và `/chat/:conversationId`: giữ giao diện chat, thêm nút **Trò chuyện bằng giọng nói**. Không thêm micro cạnh ô nhập.
- Bảng trợ lý: bắt đầu nghe, kết thúc lượt nói, xem/sửa lời nhận dạng, xác nhận gửi, phát lại, tắt tiếng, dừng âm thanh và kết thúc.
- Có thể bật tự nghe lượt tiếp theo sau câu trả lời thông thường. Lượt hiện tại kết thúc bằng nút **Kết thúc lượt nói**; chưa có tự xác định lúc người dùng nói xong hoặc ngắt lời trực tiếp.
- Câu hỏi giọng nói dùng chung session, lịch sử và orchestrator với chat chữ. Frontend chỉ gọi backend tích hợp.

## 1. Cập nhật mã nguồn

Giải nén và ghi đè vào thư mục `medical-ai-integrated` hiện tại. Dừng backend và frontend trước khi ghi đè. Giữ bản sao thư mục đang chạy để có thể quay lại.

Các thư mục môi trường Python, `node_modules`, cache, tệp build, dữ liệu SQLite và file `.env` thực tế không có trong gói. Giữ các file `.env` và dữ liệu hiện tại của bạn; gói chỉ kèm `.env.example`. Nếu chạy từ thư mục mới, tạo `.env` từ `.env.example` rồi điền lại cấu hình. Backend và frontend hiện có vẫn dùng các model, cơ sở dữ liệu và cấu hình của bạn. Không yêu cầu huấn luyện lại classifier hoặc các module.

Thư mục `frontend-patch` cũ không kèm gói cập nhật; chỉ dùng `frontend` để chạy bản này. Không chép bản vá cũ lên mã nguồn mới.

## 2. Cài phần giọng nói trong backend

Mở CMD trong `medical-ai-integrated\backend`, kích hoạt môi trường Python hiện có rồi cài:

```bat
venv\Scripts\activate
python -m pip install -r requirements-voice.txt
```

Nếu môi trường của bạn tên `.venv`, dùng `.venv\Scripts\activate`.

Phần mới dùng `faster-whisper` để nhận dạng tiếng Việt và `edge-tts` để tạo giọng đọc. Hai thư viện được cài riêng, không yêu cầu thay bản PyTorch hiện tại. Lần đầu STT sẽ tải model nếu chưa có trong cache; cần Internet cho lần tải này. Có thể đặt `VOICE_STT_MODEL` bằng đường dẫn tới thư mục model CTranslate2 đã tải để chạy STT ngoại tuyến.

Thêm cấu hình sau vào `backend\.env` nếu muốn chỉ định rõ:

```dotenv
VOICE_STT_MODEL=small
VOICE_STT_DEVICE=cpu
VOICE_STT_COMPUTE=int8
VOICE_TTS_PROVIDER=edge
VOICE_TTS_VOICE=vi-VN-HoaiMyNeural
```

Mặc định STT dùng CPU để dành bộ nhớ GPU cho Qwen và các module khác. Trên máy RTX 4060 8 GB của bạn, có thể thử:

```dotenv
VOICE_STT_DEVICE=cuda
VOICE_STT_COMPUTE=int8_float16
```

Việc dùng CUDA cần cuBLAS/cuDNN phù hợp với CTranslate2 và đủ VRAM còn trống. Nếu STT lỗi GPU, quay về `cpu` + `int8`. Có thể thử `base` khi ưu tiên tốc độ; cần kiểm tra lại tên bệnh, phủ định và số đo vì chất lượng nhận dạng phụ thuộc âm thanh.

**TTS mặc định cần Internet** và gửi nội dung lời đọc tới dịch vụ Microsoft Edge. Giao diện thông báo điều này trước khi người dùng bắt đầu thu âm. Backend không lưu file âm thanh gốc; lưu văn bản và nội dung hội thoại như chat chữ. Cấu hình dịch vụ qua adapter thay thế nếu muốn tự triển khai TTS.

## 3. Chạy backend

Khởi động các cơ sở dữ liệu, Ollama và Clinical IE theo cấu hình dự án hiện tại. Sau đó:

```bat
python -m uvicorn app.main:app --host 127.0.0.1 --port 8100 --workers 1
```

STT được nạp khi có lượt nói đầu tiên. Không chặn startup các module hiện có nếu chưa cài phần giọng nói; nút nghe sẽ báo thành phần còn thiếu.

## 4. Chạy frontend

Mở CMD khác trong `medical-ai-integrated\frontend`:

```bat
npm install
npm run dev -- --port 5174
```

`frontend\.env`:

```dotenv
VITE_USE_MOCK_API=false
VITE_API_BASE_URL=http://127.0.0.1:8100
VITE_CHAT_TIMEOUT_MS=600000
```

Mở `http://localhost:5174/` để xem trang giới thiệu và nhấn **Bắt đầu chat**. Mở `http://localhost:5174/chat` để vào chat trực tiếp. Nếu bạn chạy cổng khác, bổ sung origin tương ứng trong `CORS_ORIGINS` tại backend.

Micro cần HTTPS hoặc `localhost`/`127.0.0.1` và quyền micro trong trình duyệt. Địa chỉ HTTP bằng IP mạng LAN thường không đủ điều kiện dùng micro. Chế độ demo không bật trợ lý giọng nói.

## 5. Một lượt hội thoại

1. Nhấn **Trò chuyện bằng giọng nói**.
2. Nhấn **Bắt đầu nghe**, cho phép micro.
3. Nói câu hỏi, nhấn **Kết thúc lượt nói**. Mỗi lượt tối đa 90 giây, 12 MB.
4. Kiểm tra bản nhận dạng; sửa tên bệnh, phủ định, con số và đơn vị nếu cần.
5. Nhấn **Xác nhận lời nói và gửi**.
6. Backend gọi luồng Context → classifier → module phù hợp → LLM như chat hiện có.
7. Câu trả lời đầy đủ nằm trong lịch sử; trợ lý phát lời thoại được biên soạn từ cùng nội dung.
8. Nhấn **Nói tiếp** hoặc bật tự nghe lượt tiếp theo. Khi phát âm thanh, không thu micro.

**Kết thúc trò chuyện giọng nói** dừng thu/phát và đóng bảng. Câu hỏi đã gửi vẫn có thể được backend xử lý và lưu; đóng bảng không hủy một đánh giá đã được xác nhận gửi.

## 6. Lời thoại và xác nhận y khoa

Câu trả lời để hiển thị giữ nội dung đầy đủ và nguồn. Lời đọc được xử lý riêng:

- Chọn đoạn chính từ câu trả lời gốc; LLM chỉ chọn chỉ số đoạn, không được tự viết thêm kết luận y khoa.
- Giữ các đoạn chứa phủ định, giới hạn, điều kiện và lưu ý quan trọng.
- Loại bỏ cú pháp trình bày/đường dẫn; giữ số đo, đơn vị và phủ định. Bảng được chuyển sang lời mô tả theo từng dòng, không đọc các ký hiệu Markdown.
- Nếu rút gọn, báo còn nội dung và cho người dùng nói **nghe tiếp**.
- Nếu bước chọn đoạn lỗi, đọc nội dung đã làm sạch thay vì tự tạo một bản diễn giải thiếu căn cứ.
- Lời dài được phát thành nhiều phần liên tiếp. Có thể dừng phát bất cứ lúc nào.

Các bước kiểm tra dữ kiện, hỏi bổ sung và xác nhận gửi đánh giá dùng mẫu thống nhất. Câu lệnh được kiểm tra bởi backend theo trạng thái và phiên bản hiện tại:

| Bước | Câu nói được hỗ trợ |
|---|---|
| Xác nhận các dữ kiện vừa đọc | “Tôi xác nhận các dữ kiện vừa đọc thuộc cùng một bệnh nhân” |
| Trả lời câu hỏi KG | “Có”, “Không”, “Không biết”, “Bỏ qua” |
| Kết thúc phần hỏi bổ sung | “Kết thúc hỏi bổ sung” |
| Gửi bản cuối để đánh giá | “Tôi đồng ý gửi bản dữ kiện đã kiểm tra để đánh giá” |
| Hủy lượt chưa gửi | “Hủy lượt đánh giá” |

Những câu chung như “đúng rồi” không tự kích hoạt lưu dữ kiện hoặc gửi đánh giá. Mỗi lời nói đều phải qua bước xem lại văn bản trước khi gửi.

**Dữ kiện Patient Graph cũ mặc định không được chọn khi xác nhận bằng giọng nói.** Muốn dùng lại hoặc sửa dữ kiện, dùng bảng kiểm tra được tích hợp ngay trong bảng trợ lý, chọn/sửa và xác nhận bằng nút. Lệnh xác nhận giọng nói dùng các dữ kiện hiện tại vừa được backend đọc; không dùng các chỉnh sửa chưa được gửi từ biểu mẫu.

Nếu phiên bản dữ kiện đã đổi, backend từ chối câu xác nhận cũ và giao diện tải lại lời đọc để người dùng kiểm tra lại. Chỉ `AssessmentService` hiện có mới được phép chuyển trạng thái, lưu bản xác nhận và gọi Clinical IE.

## 7. Thay TTS qua adapter

Nếu có dịch vụ TTS tiếng Việt tự triển khai, hỗ trợ API tương thích `POST /audio/speech` với các trường `model`, `voice`, `input`, `response_format`, trả âm thanh MP3:

```dotenv
VOICE_TTS_PROVIDER=compatible
VOICE_TTS_BASE_URL=http://127.0.0.1:8880/v1
VOICE_TTS_MODEL=ten-model-cua-ban
VOICE_TTS_VOICE=ten-giong-cua-ban
VOICE_TTS_API_KEY=
```

Đây là adapter kết nối; gói cập nhật không kèm server hoặc model TTS riêng. `VOICE_TTS_VOICE` phải đúng với dịch vụ được chọn. Không đưa API key vào frontend.

## 8. API mới

| API | Chức năng |
|---|---|
| `GET /api/v1/voice/config` | Kiểm tra thư viện đã cài, loại TTS và giới hạn lượt nói |
| `POST /api/v1/voice/transcribe` | Nhận multipart `file`, trả `transcript` |
| `POST /api/v1/voice/turn` | Nhận bản nhận dạng đã kiểm tra, xử lý bằng luồng chat/đánh giá hiện có |
| `GET /api/v1/voice/reply/{conversation_id}` | Lấy lời đọc theo trạng thái hiện tại; `?full=true` đọc đầy đủ |
| `POST /api/v1/voice/speech` | Nhận `text`, trả âm thanh MP3 |

Mẫu phản hồi `/voice/turn`:

```json
{
  "conversation": {"id": "session-id", "messages": []},
  "message": {"id": "assistant-id", "role": "assistant", "content": "Nội dung đầy đủ"},
  "assessment": null,
  "display_text": "Nội dung đầy đủ",
  "spoken_text": "Lời đọc đã biên soạn",
  "conversation_action": "answer",
  "expects_reply": true,
  "has_more": false
}
```

Các giá trị action khác: `clarify`, `confirm_patient_facts`, `ask_follow_up`, `confirm_diagnosis`, `processing`. Chúng được backend quyết định; không cho LLM tự kích hoạt chẩn đoán.

## 9. Kiểm tra sau khi cài

- Hỏi câu thông tin chung, kiểm tra câu hỏi xuất hiện trong đúng session và lịch sử sau xử lý.
- Thử câu hỏi KG và RAG+KG, đối chiếu nội dung chữ với âm thanh.
- Thử nhận dạng “không sốt”, SpO2 và con số; sửa bản nhận dạng trước khi gửi.
- Thử câu chẩn đoán, xem bước xác nhận và dữ kiện cũ mặc định bị loại.
- Thử “đúng rồi”: không tự gửi chẩn đoán.
- Thử tắt tiếng, dừng phát, đóng bảng trong lúc thu âm.
- Ngắt kết nối TTS: nội dung chữ vẫn hiển thị và có nút phát lại.

Kiểm thử tự động và các giới hạn kiểm chứng được ghi trong `VOICE_TEST_REPORT.md`.

## Tài liệu thư viện

- faster-whisper: https://github.com/SYSTRAN/faster-whisper
- edge-tts: https://github.com/rany2/edge-tts
