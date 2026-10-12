# Trợ lý giọng nói — VieNeu-TTS cục bộ

## 1. Cập nhật mã nguồn

Dừng backend/frontend, sao lưu thư mục đang chạy rồi giải nén và ghi đè mã nguồn từ ZIP. Dùng `frontend`, không chép `frontend-patch` cũ lên bản này. Giữ nguyên `.env`, dữ liệu và các môi trường hiện có; chúng không nằm trong ZIP. Giao diện teal và ảnh của bản trước được giữ lại.

Gói chứa mã nguồn backend/frontend, classifier hiện có, adapter VieNeu, bộ cài Windows và kiểm thử. Không chứa model VieNeu, Whisper, Qwen/E5 hoặc dữ liệu Docker. Các model cần tải về hoặc có sẵn trong cache; không yêu cầu huấn luyện lại.

## 2. Cài STT trong môi trường backend hiện tại

Mở CMD:

```bat
cd /d D:\medical_wed\banzip\medical-ai-integrated\backend
venv\Scripts\activate
python -m pip install -r requirements-voice.txt
```

Nếu môi trường tên `.venv`, dùng `.venv\Scripts\activate`. STT dùng faster-whisper `small`, CPU/int8; lần đầu nhận dạng sẽ tải/nạp model nếu chưa có cache. File requirements giữ Edge TTS để tương thích cấu hình cũ; khi chọn `vieneu`, Edge TTS không được gọi.

## 3. Cài và chạy VieNeu riêng

Mở CMD mới trong thư mục backend:

```bat
setup_vieneu_windows.bat
start_vieneu_windows.bat
```

Bộ cài dùng Python 3.12, tạo `.venv-vieneu` riêng, cài `vieneu==3.8.3` và server API chính thức `apps.openai_speech`. Nó không thay PyTorch/thư viện trong môi trường backend hiện có.

Lần khởi động đầu cần Internet để tải trọng số Hugging Face; thời gian tùy mạng. Chờ **Application startup complete**, rồi giữ cửa sổ này mở. Sau khi tải đủ và có cache, VieNeu tổng hợp trên máy; backend gửi lời thoại tới loopback. Mặc định CPU/ONNX, một luồng tổng hợp để dành GPU cho Qwen. Tốc độ thực tế phụ thuộc CPU, độ dài câu và các module khác.

Kiểm tra ở CMD khác:

```bat
curl http://127.0.0.1:8880/health
curl http://127.0.0.1:8880/v1/voices
```

Nếu tải model lỗi, kiểm tra mạng, dung lượng ổ đĩa/cache Hugging Face và log VieNeu. Nếu thiếu DLL ONNX trên Windows, kiểm tra Microsoft Visual C++ Redistributable x64 theo tài liệu ONNX Runtime. Nếu cổng 8880 đang bận, dừng tiến trình dùng cổng hoặc đổi đồng thời cổng server và URL backend.

## 4. Sửa backend\.env, khởi động lại backend

Giữ nguyên mật khẩu/URI Neo4j, MongoDB, Qdrant, Clinical IE và Ollama. Thay các dòng `VOICE_TTS_*` cũ, không để hai dòng trùng tên:

```dotenv
VOICE_TTS_PROVIDER=vieneu
VOICE_TTS_BASE_URL=http://127.0.0.1:8880/v1
VOICE_TTS_MODEL=vieneu-v3-turbo
VOICE_TTS_VOICE=Mai Anh
VOICE_TTS_API_KEY=
VOICE_STT_MODEL=small
VOICE_STT_DEVICE=cpu
VOICE_STT_COMPUTE=int8
```

`Mai Anh` là giọng có sẵn. Có thể đổi bằng tên đúng từ `/v1/voices`, rồi khởi động lại backend. API VieNeu hiện không áp dụng `speed` hay `instructions`; bản này dùng đặc tính giọng gốc, chưa có nhân bản giọng cá nhân.

Khởi động CSDL, Ollama và Clinical IE như trước. Trong môi trường backend:

```bat
python -m uvicorn app.main:app --host 127.0.0.1 --port 8100 --workers 1
```

Kiểm tra:

```bat
curl http://127.0.0.1:8100/api/v1/voice/config
```

`tts_installed: true` cho VieNeu nghĩa là backend gọi được `/health` của TTS. `stt_installed` kiểm tra thư viện; lần đầu STT vẫn có thể chờ tải/nạp model. Nếu TTS chưa sẵn sàng, giao diện hiện lỗi; khởi động VieNeu rồi mở lại bảng trợ lý.

## 5. Chạy frontend

CMD khác:

```bat
cd /d D:\medical_wed\banzip\medical-ai-integrated\frontend
npm ci
npm run dev
```

`frontend\.env`:

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8100
VITE_USE_MOCK_API=false
VITE_CHAT_TIMEOUT_MS=600000
```

Mở `http://localhost:5173`. Nếu Vite đổi cổng do 5173 đang bận, bổ sung origin đó vào `CORS_ORIGINS` backend và khởi động lại. Micro cần localhost/HTTPS và quyền trình duyệt. Frontend chỉ gọi backend 8100, không gọi trực tiếp VieNeu.

## 6. Luồng trả lời

1. Nói câu hỏi, kết thúc lượt nói, kiểm tra/sửa bản nhận dạng và xác nhận gửi.
2. Context, classifier và truy xuất dùng luồng hiện tại.
3. Một lượt LLM tạo các câu nói hoàn chỉnh và phần chi tiết/nguồn. Lời thoại có ràng buộc giữ phủ định, số đo, chủ thể và giới hạn bằng chứng. Các câu được nói cũng nằm nguyên văn trong nội dung lưu ở chat.
4. Câu đầu hoàn chỉnh được chuyển ngay tới frontend. VieNeu tổng hợp PCM mono 48 kHz; frontend phát từng gói âm thanh khi nhận được trong khi phần trả lời còn lại tiếp tục được tạo.
5. Chi tiết/nguồn được lưu trong chat. Nói “nghe tiếp” để nghe đầy đủ; phát lại dùng lời thoại đã lưu, không gọi thêm LLM chọn đoạn.

Xác nhận dữ kiện/gửi đánh giá vẫn dùng mẫu cố định và kiểm tra phiên bản/trạng thái; LLM không tự gửi chẩn đoán. Dữ kiện Patient Graph cũ không tự được chọn. Bản nhận dạng vẫn cần kiểm tra trước khi gửi.

**Dừng âm thanh** trong lúc tạo câu trả lời dừng phát và tắt tiếng; văn bản vẫn hoàn tất. Đóng bảng ngắt lượt phản hồi streaming đang truyền, nên có thể chưa có câu trả lời hoàn chỉnh trong lịch sử. Đóng bảng không hủy một đánh giá đã xác nhận gửi. Khi VieNeu lỗi, chat giữ câu trả lời chữ để phát lại sau.

Bản này chưa có tự phát hiện kết thúc lượt nói, ngắt lời bằng micro khi trợ lý đang nói, hoặc avatar. Cần nghe thử độ tự nhiên và phát âm thuật ngữ trên máy bạn; prompt ràng buộc không thay thế kiểm tra nội dung y khoa.

## 7. Đo tốc độ, nghe thử

Trong môi trường backend đã có httpx, khi VieNeu sẵn sàng:

```bat
python -m scripts.benchmark_voice --output vieneu-sample.wav
```

Công cụ tạo WAV và đo thời gian tới PCM đầu tiên, tổng thời gian tổng hợp, thời lượng âm thanh, RTF (thời gian tổng hợp / thời lượng). RTF < 1 nghĩa là tổng hợp nhanh hơn thời lượng phát câu mẫu; đây không phải độ trễ toàn bộ hỏi đáp. Đo lại sau khi model nóng. Console backend có `voice.stage` cho STT, câu đầu, kịch bản hoàn tất, PCM đầu tiên và tổng hợp xong; `chat.stage` chỉ ra thời gian Context/classifier/truy xuất.

Nếu CPU chưa đủ nhanh, có thể thử PyTorch/CUDA theo tài liệu VieNeu trong môi trường TTS riêng, rồi đặt `VIENEU_BACKEND=pytorch`, `VIENEU_DEVICE=cuda` trước khi chạy batch. Không chỉ đổi biến khi chưa cài dependency GPU. RTX 4060 8 GB phải chia VRAM với Qwen/E5; cần đo lại bộ nhớ và độ trễ. Chưa kiểm thử CUDA trên máy bạn.

## 8. API, kiểm thử và nguồn

| API | Kết quả |
|---|---|
| `POST /api/v1/voice/turn/stream` | NDJSON: câu hoàn chỉnh, phản hồi cuối hoặc lỗi |
| `POST /api/v1/voice/speech/stream` | PCM s16le mono 48 kHz, hủy được khi dừng |
| `POST /api/v1/voice/speech` | WAV với VieNeu, giữ tương thích client cũ |
| `GET /api/v1/voice/config` | Trạng thái STT/VieNeu và streaming |
| `GET /api/v1/voice/reply/{id}` | Lời thoại đã lưu/mẫu xác nhận hiện tại |

Xem `VOICE_TEST_REPORT.md` cho kết quả và giới hạn kiểm chứng. Nguồn: [VieNeu-TTS](https://github.com/pnnbao97/VieNeu-TTS), [Streaming](https://github.com/pnnbao97/VieNeu-TTS/blob/main/docs/streaming.md), [ONNX Runtime](https://onnxruntime.ai/docs/install/).
