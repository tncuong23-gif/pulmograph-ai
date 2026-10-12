# Cập nhật nhận dạng và phát giọng nói — ghi đè, không cài lại

Áp dụng cho bản Medical AI đã có giao diện teal, VieNeu-TTS v3 Turbo cục bộ, semantic chunking và nạp RAG nhiều file/thư mục. Bản vá này nâng cấp từ gói đầy đủ ngay trước lần sửa chất lượng giọng nói. Nếu dự án đã có các sửa riêng, đối chiếu các file trong `VOICE_PATCH_FILES.txt` trước khi chép. Nếu dùng bản rất cũ chưa có VieNeu/voice streaming, cần nâng cấp các phần đó theo `VOICE_VIENEU_GUIDE_VI.md` trước.

## 1. Chuẩn bị

1. Dừng cửa sổ backend và frontend bằng `Ctrl+C`.
2. Sao lưu các file sắp ghi đè cùng `backend\.env` và `frontend\.env`. Có thể sao chép toàn bộ thư mục dự án để tiện khôi phục.
3. Giải nén **medical-ai-voice-quality-patch.zip** vào thư mục riêng, ví dụ `D:\medical_wed\updates\voice-quality-patch`. Bên trong có thư mục `medical-ai-integrated`.

Dùng ZIP bản vá khi cập nhật tại chỗ. Gói đầy đủ chứa cả cấu hình mẫu và những phần mã khác để cài mới/đối chiếu; không chép đè cả gói đầy đủ lên dự án có sửa riêng.

## 2. Ghi đè đúng đường dẫn

Các file trực tiếp thay đổi hoạt động:

| Đường dẫn trong dự án | Thay đổi |
| --- | --- |
| `backend/app/services/voice.py` | STT, VAD, cảnh báo chất lượng và log thời gian |
| `backend/app/main.py` | Thông tin cấu hình STT qua API voice |
| `frontend/src/components/voice/SpeechPlayer.ts` | Chuẩn bị trước tối đa hai câu, bộ đệm và lịch phát liên tục |
| `frontend/src/components/voice/VoiceAssistant.tsx` | Hiển thị cảnh báo khi kiểm tra lời nhận dạng |
| `frontend/src/api/voiceApi.ts` | Nhận cảnh báo và thông số đo STT |
| `backend/.env.example` | Mẫu cấu hình STT mới |
| `frontend/.env.example` | Mẫu cấu hình bộ đệm mới |

ZIP còn có công cụ `backend/scripts/benchmark_stt.py`, kiểm thử và tài liệu. Danh sách đầy đủ nằm trong `VOICE_PATCH_FILES.txt`. Chép toàn bộ nội dung thư mục `medical-ai-integrated` của **bản vá** vào thư mục dự án cũ; chọn **Replace the files in the destination** khi Windows hỏi. Hai thư mục `backend` và `frontend` được gộp vào thư mục cùng tên, không tạo `backend\backend`.

Hoặc dùng CMD, thay đường dẫn nguồn nếu bạn giải nén ở nơi khác:

```bat
robocopy "D:\medical_wed\updates\voice-quality-patch\medical-ai-integrated" "D:\medical_wed\banzip\medical-ai-integrated" /E
```

Không thêm `/MIR` hoặc `/PURGE`. Lệnh trên chỉ chép file bản vá, không xóa file đích. Robocopy trả mã 0–7 vẫn có thể là thành công; mã từ 8 trở lên cần kiểm tra lỗi sao chép.

Bản vá không chứa `.env` thật, `venv`, `.venv-vieneu`, `node_modules`, `dist`, dữ liệu nhập, cơ sở dữ liệu hay trọng số model. Những file này ở dự án cũ được giữ lại. Không chạy lại index RAG hoặc tạo lại CSDL cho lần nâng cấp giọng nói này.

## 3. Sửa `.env` hiện có

Mở `backend\.env`, **thay giá trị của dòng đã có**, thêm dòng nếu chưa có; mỗi tên biến chỉ để một dòng:

```dotenv
VOICE_STT_MODEL=large-v3-turbo
VOICE_STT_DEVICE=cpu
VOICE_STT_COMPUTE=int8
VOICE_STT_BEAM_SIZE=5
VOICE_STT_VAD=true
VOICE_STT_VAD_THRESHOLD=0.35
VOICE_STT_VAD_SILENCE_MS=650
VOICE_STT_VAD_PAD_MS=300
```

Không chép `.env.example` đè lên `.env`: bạn cần giữ mật khẩu Neo4j, MongoDB, Ollama và đường dẫn dữ liệu hiện có. Nếu `.env` cũ vẫn đặt `VOICE_STT_MODEL=small`, backend tiếp tục dùng `small` dù đã ghi đè mã nguồn.

Khi không đặt `VOICE_STT_INITIAL_PROMPT`, backend dùng gợi ý ngắn về từ vựng hô hấp. Muốn tự chọn gợi ý, thêm biến này với danh sách thuật ngữ ngắn, tối đa 1000 ký tự; không đưa thông tin bệnh nhân hoặc kết luận vào prompt. Đặt giá trị trống để tắt gợi ý. Nếu VAD vẫn bỏ mất từ ở đầu/cuối trên bản ghi của bạn, có thể thử `VOICE_STT_VAD=false` rồi đo lại; không bật/tắt theo phỏng đoán cho tất cả người dùng.

Frontend đã có mặc định nên không bắt buộc sửa `frontend\.env`. Nếu muốn chỉ rõ:

```dotenv
VITE_VOICE_START_BUFFER_MS=1000
VITE_VOICE_REBUFFER_MS=800
```

Đơn vị là mili giây; giới hạn 0–3000. Bộ đệm tăng độ chờ ban đầu để bù dao động tốc độ. Khi có ít âm thanh và câu đã hoàn tất, bộ phát vẫn phát câu ngắn; khi đang nhận một câu chậm, chờ gom bộ đệm tối đa khoảng hai giây tính từ lúc có dữ liệu có thể phát.

## 4. Khởi động lại, dùng môi trường cũ

Trong CMD backend:

```bat
cd /d D:\medical_wed\banzip\medical-ai-integrated\backend
venv\Scripts\activate
python -c "import av, faster_whisper; print('STT dependencies OK')"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8100 --workers 1
```

Nếu bạn dùng `.venv` thay `venv`, sửa đường dẫn kích hoạt. Bản này không thay `requirements.txt`, `requirements-voice.txt`, `package.json` hoặc `package-lock.json`; môi trường đã chạy STT và frontend ở bản trước không cần `pip install`/`npm install` lại. **Chỉ khi phép kiểm tra import báo thiếu STT**, trong venv hiện có chạy `python -m pip install -r requirements-voice.txt`; đây là bổ sung thư viện, không tạo lại môi trường. Backend vẫn cần Python 3.11 trở lên.

Nếu chạy frontend bằng Vite:

```bat
cd /d D:\medical_wed\banzip\medical-ai-integrated\frontend
npm run dev
```

Nếu đang phục vụ bản production, chạy `npm run build` và cập nhật nội dung `frontend\dist` lên nơi đang phục vụ. Sau đó tải lại trang bằng `Ctrl+F5`. Thay file nguồn không tự đổi bản `dist` đã được triển khai.

Giữ các dịch vụ DB/Ollama/Clinical IE như trước. VieNeu phải đang chạy tại cổng 8880; nếu đã dừng thì chạy `start_vieneu_windows.bat`. Bản vá không đổi cài đặt dịch vụ VieNeu hoặc số luồng tổng hợp của nó.

**Lần nhận dạng đầu tiên:** model mới được nạp lười; cần mạng để tải trọng số `large-v3-turbo` nếu chưa có trong cache. Model không nằm trong ZIP. Thời gian tải và nạp lần đầu khác thời gian nhận dạng các lần tiếp theo. Giữ đủ dung lượng đĩa cho cache; không xóa cache khi cập nhật.

## 5. Kiểm tra với âm thanh thật

1. Mở trợ lý giọng nói, thu vài câu có tên bệnh, phủ định, số thập phân và đơn vị. Lặp lại trong môi trường yên tĩnh và có tiếng nền.
2. Đối chiếu ô lời nhận dạng với lời thực sự đã nói. Sửa trước khi bấm xác nhận gửi; cảnh báo nhận dạng không chắc chắn sẽ xuất hiện ở bước này. Hệ thống không tự dùng LLM sửa ý của bạn.
3. Nghe một câu trả lời nhiều câu; thử tắt tiếng, phát lại và đóng hộp thoại. Xem Console trình duyệt, tìm `voice.playback`: `underruns` đếm lần lịch phát hết âm thanh rồi phải nối lại, `gapMs` là thời gian hết lịch phát trước khi nối lại, `peakQueuedSeconds` là bộ đệm của các câu đang chờ. Các số này không đo khoảng im lặng đã có sẵn trong âm thanh hoặc độ trễ thiết bị.

Đo STT với cùng file âm thanh và bản lời gốc đã kiểm tra:

```bat
python -m scripts.benchmark_stt --audio "D:\test-audio\mau.wav" --reference "Tôi không sốt, SpO2 92.5%." --runs 2 --output "D:\test-audio\stt-turbo.json"
```

Dùng lời gốc của bản ghi của bạn, không sao chép câu ví dụ nếu bạn nói khác. Báo cáo có transcript, cảnh báo, thời gian tải model/giải mã/nhận dạng và tỷ lệ lỗi ký tự, lỗi đơn vị cách nhau bằng khoảng trắng. Với tiếng Việt, chỉ số khoảng trắng thường tính theo âm tiết, không phải WER theo từ ngôn ngữ học; dấu câu được tính. Để so sánh, đổi model về `small`, khởi động lại backend, chạy cùng file rồi đổi lại `large-v3-turbo` và khởi động lại. So sánh lượt đã nạp model, không lấy thời gian tải lần đầu làm tốc độ suy luận.

Đo riêng dịch vụ VieNeu:

```bat
python -m scripts.benchmark_voice --output "D:\test-audio\vieneu.wav"
```

`rtf` là thời gian tạo âm thanh chia độ dài âm thanh. RTF trên 1 cho thấy tổng hợp chậm hơn thời lượng âm thanh trên lần đo đó; bộ đệm hữu hạn không bảo đảm phát liên tục mọi câu trả lời dài. Log backend `tts_complete` bao gồm chờ hàng đợi và chờ bên nhận, nên dùng công cụ đo trực tiếp VieNeu để tách tốc độ tổng hợp khỏi bộ phát.

## 6. Tùy chọn GPU và khôi phục

Mặc định CPU/int8 dùng được với môi trường STT hiện có và tránh chiếm thêm VRAM khi Ollama/E5 đang chạy. `large-v3-turbo` trên CPU có thể chậm hơn `small`; bản vá hướng tới chất lượng nhận dạng và giảm khoảng ngắt do bộ phát, không cam kết tăng tốc suy luận trên mọi máy.

Muốn thử CUDA, trong venv kiểm tra `python -c "import ctranslate2; print(ctranslate2.get_supported_compute_types('cuda'))"`. CTranslate2/faster-whisper cần thư viện NVIDIA tương thích; tài liệu hiện tại nêu CUDA 12/cuBLAS và cuDNN 9. PyTorch nhận GPU không đủ để xác nhận STT chạy được. Sau khi kiểm tra thư viện và VRAM còn trống, mới thử `VOICE_STT_DEVICE=cuda`, `VOICE_STT_COMPUTE=int8_float16`, khởi động lại và thu một bản ghi. Nếu lỗi CUDA/thiếu VRAM, trở về `cpu`/`int8`; không cần cài lại dự án. Bản vá không tự cài CUDA hoặc đổi GPU của các dịch vụ khác.

Để quay lại hoàn toàn, dừng backend/frontend, chép lại các file đã sao lưu và `.env` cũ, khởi động lại; nếu dùng production thì build lại frontend. Chỉ muốn giảm tải STT thì đổi `VOICE_STT_MODEL=small` rồi khởi động lại backend, vẫn giữ các sửa bộ phát.

Tài liệu nền tảng: [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [model card Whisper Turbo](https://huggingface.co/openai/whisper-large-v3-turbo), [Web Audio scheduling](https://developer.mozilla.org/en-US/docs/Web/API/AudioBufferSourceNode/start). Kết quả kiểm thử của gói nằm trong `VOICE_QUALITY_TEST_REPORT.md`; cần bản ghi thực và máy của bạn để đánh giá độ chính xác, độ trễ và khoảng ngắt thực tế.
