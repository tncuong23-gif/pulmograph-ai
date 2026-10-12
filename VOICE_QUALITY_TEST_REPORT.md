# Kiểm thử bản cập nhật chất lượng giọng nói

## Phạm vi

Nâng cấp từ bản đã có giao diện teal, VieNeu v3 Turbo cục bộ, semantic RAG và nạp dữ liệu theo lô. STT chuyển mặc định từ `small` sang `large-v3-turbo`, CPU/int8; có gợi ý từ vựng ngắn, beam/VAD cấu hình được, cảnh báo chất lượng và thời gian từng giai đoạn. Bỏ bộ lọc phụ chỉ xét `no_speech_prob` trên các đoạn đã được Whisper trả về. Transcript vẫn phải được kiểm tra trước khi gửi.

Bộ phát giữ tối đa hai câu đang được nhận, thứ tự phát tách khỏi thứ tự hoàn tất HTTP. Bộ đệm PCM chờ tối đa sáu giây mỗi câu; lịch phát đi trước tối đa khoảng 1.5 giây cộng một block 120 ms. Khởi động mặc định gom một giây âm thanh, sau hụt bộ đệm gom 800 ms; các block nối theo `AudioContext.currentTime` mà không thêm 40 ms vào từng block. Gói không đổi dependency hoặc runtime VieNeu.

## Kết quả

| Kiểm tra | Kết quả |
| --- | --- |
| `python -m pytest -q` trong backend | **277 passed, 6 skipped, 18 warnings** |
| `npm test` trong frontend | **42 passed, 11 test files** |
| `npm run build` | TypeScript và Vite thành công; 1954 modules |

Kiểm tra chạy trong môi trường Linux, Python 3.12. Bộ STT dùng PyAV 16.1.0 để giải mã WAV thật từ 8 kHz lên mono 16 kHz, và Whisper giả lập để kiểm tra tích hợp mà không tải trọng số. Những phép kiểm tra giải mã bỏ qua nếu không có thư viện voice tùy chọn; trong lần kiểm tra này đã cài PyAV và các phép kiểm tra đó đều chạy. Sáu kiểm tra bỏ qua thuộc tích hợp KG cần MongoDB/Neo4j thật. Cảnh báo gồm deprecation của FastAPI/Starlette đã có và một cảnh báo socket chưa đóng từ môi trường test; không báo lỗi chức năng.

Các tình huống đã kiểm tra:

- Cấu hình STT hợp lệ/không hợp lệ, có/tắt prompt và VAD, beam tuỳ chọn, model được tái sử dụng và phân biệt lượt nạp đầu/lượt sau.
- Giải mã và resample thật, giới hạn thời lượng trước tải model, file hỏng và bản ghi im lặng bị từ chối. Âm lượng nhỏ/quá lớn sinh cảnh báo nhưng giữ nguyên kết quả STT trả về.
- Câu `Không sốt, SpO2 92.5%.` vẫn giữ phủ định, dấu thập phân và đơn vị khi một đoạn được Whisper chấp nhận có `no_speech_prob` cao. Không áp dụng sửa ý tự động.
- Prefetch hai câu trước khi câu đầu tổng hợp xong; câu hai có dữ liệu trước vẫn không phát trước câu một. Câu thứ ba chưa được gọi khi cửa sổ chờ còn đầy; hủy lượt dừng cả hai request và các source đã lên lịch.
- Gom bộ đệm khi dữ liệu đến gián đoạn, lịch bắt đầu các block khớp điểm kết thúc block trước, phát được câu cuối ngắn, hụt dữ liệu thì chờ gom lại và ghi thông số gián đoạn.
- Producer nhanh hơn playback vẫn bị giới hạn bộ đệm; PCM thiếu một byte bị phát hiện và báo lỗi, request còn lại bị hủy.
- Cảnh báo STT xuất hiện khi xem lại transcript; giữ hành vi không gửi trước xác nhận, trả micro trước phát, giữ text khi TTS lỗi và dọn tài nguyên khi đóng hộp thoại.
- Công cụ benchmark chuẩn hóa Unicode/chữ hoa/khoảng trắng; khác phủ định hoặc số đo tạo lỗi so sánh. Chỉ số khoảng trắng được gọi đúng là token/âm tiết, không khẳng định WER theo từ tiếng Việt.
- Các kiểm tra hồi quy sẵn có tiếp tục chạy cho chat, xác nhận Patient Graph, assessment, semantic chunking và nạp RAG theo lô.

## Giới hạn và kiểm tra trên máy sử dụng

Chưa có bản ghi của người dùng, chưa chạy trọng số Whisper thật hay VieNeu trên RTX 4060 Laptop của người dùng trong lần kiểm tra này. Các số trên kiểm chứng hành vi chương trình, không chứng minh tỷ lệ lỗi nhận dạng, chất lượng giọng hoặc mức giảm khoảng ngắt với âm thanh thật. CPU/int8 giữ tương thích môi trường cũ; model lớn hơn có thể làm tăng thời gian nhận dạng. GPU là tùy chọn cần kiểm tra CTranslate2, thư viện CUDA/cuDNN và VRAM đồng thời với Ollama/E5.

Bộ đệm giảm gián đoạn do dữ liệu đến không đều và khoảng chờ giữa request, nhưng không bảo đảm liên tục nếu dịch vụ tổng hợp lâu hơn thời lượng âm thanh. Không sửa khoảng ngừng tự nhiên đã có trong PCM do model sinh ra. Hãy dùng `scripts.benchmark_stt`, `scripts.benchmark_voice`, log backend và `voice.playback` trên máy thật theo `VOICE_QUALITY_UPDATE_VI.md`.

Khi đóng gói, đối chiếu từng byte với ZIP trước cập nhật: chỉ những file được liệt kê trong bản vá được sửa/thêm; assets teal, dependency locks, model phân lớp, mã RAG/KG/Context và các dịch vụ phụ giữ nguyên. Cả ZIP đầy đủ và ZIP bản vá được kiểm tra CRC; mô phỏng áp bản vá vào bản trước cho kết quả trùng gói đầy đủ và giữ file cấu hình/dữ liệu thêm tại đích.
