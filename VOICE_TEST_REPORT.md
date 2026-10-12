# Kiểm tra bản giọng nói VieNeu-TTS

> Báo cáo của bản VieNeu trước khi bổ sung semantic chunking. Kết quả toàn dự án mới nhất nằm trong `RAG_SEMANTIC_TEST_REPORT.md`; cấu hình và giới hạn kiểm chứng giọng nói dưới đây vẫn áp dụng.

## Kết quả bản VieNeu

- Backend toàn bộ, gồm upstream: **217 passed, 7 skipped**, 17 cảnh báo; `python -m pytest -q --disable-warnings` (Python 3.12).
- Frontend: **33 passed / 9 test files**; `npm test` (Vitest 4.1.11).
- `npm run build`: TypeScript và Vite thành công.
- `npm audit --json`: **0 vulnerabilities**; giữ bản sửa dependency của bản teal.
- Cài thật `vieneu==3.8.3` + `uvicorn==0.54.0` thành công trong môi trường Python 3.12 riêng; CPU/ONNX không cần PyTorch. Server vào bước tải model nhưng việc tải trọng số chưa hoàn tất trong môi trường kiểm thử. **Chưa tổng hợp thật, chưa nghe giọng hoặc đo tốc độ VieNeu thực tế.**
- `python -m scripts.benchmark_voice --help` chạy thành công; kèm công cụ đo PCM đầu tiên/RTF và ghi WAV để kiểm tra tại máy Windows.

## Phạm vi đã kiểm thử

- Một lượt LLM streaming tạo lời thoại và chi tiết; callback nhận câu hoàn chỉnh trước khi phần chi tiết hoàn tất, không có lượt LLM chọn đoạn thứ hai.
- Parser không phát câu chưa đủ JSON; giữ dấu tiếng Việt, dấu ngoặc kép, phủ định, số thập phân và đơn vị. Từ chối cấu trúc không hợp lệ; câu phát khớp nguyên văn nội dung cuối trong chat.
- NDJSON giữ thứ tự câu, phát hiện thiếu phản hồi cuối/lỗi phiên bản dữ kiện. Câu hỏi dùng cùng lịch sử; gửi lại cùng message ID không tạo lại câu trả lời.
- Adapter gọi đúng API VieNeu: pcm, stream_format=audio, mono 48 kHz. Nhận gói đầu trước khi stream kết thúc, kiểm tra header/rate, từ chối dữ liệu rỗng/truncated/sai định dạng. VieNeu chỉ cho phép địa chỉ loopback.
- API audio cũ trả WAV hợp lệ. TTS lỗi trước gói đầu trả JSON 502 thay vì HTTP 200 với âm thanh rỗng.
- Frontend ghép mẫu PCM qua chunk lẻ byte, phát trước khi tổng hợp hoàn tất, dừng nguồn âm thanh/hủy các câu xếp hàng khi ngừng phát.
- Thành phần trợ lý gọi TTS khi nhận câu đầu trước phản hồi cuối; TTS lỗi vẫn giữ lời thoại và nút phát lại.
- STT cần kiểm tra trước khi gửi; nhả micro trước khi phát, đóng bảng lúc thu không gửi audio, thu hồi tài nguyên khi đóng.
- Xác nhận vẫn giữ chủ thể, phủ định, thời điểm, số đo; Patient Graph cũ không tự được chọn. “Đúng rồi” không gửi đánh giá, “không biết” không chuyển thành phủ định; phiên bản dữ kiện cũ bị từ chối cả ở API streaming.
- Chat chữ, Clinical IE, đánh giá tương tác và bộ upstream vẫn qua. Các kiểm thử cần dịch vụ tùy chọn được skip như báo cáo pytest.

## Giới hạn

API dùng HTTPX MockTransport/dịch vụ giả lập; kiểm thử kiểm chứng giao thức và luồng xử lý, không kiểm chứng phát âm hay độ đúng của câu LLM tạo từ kho tài liệu thật. Chưa gọi Ollama, Clinical IE, Neo4j/Qdrant thực của bạn trong vòng hỏi–đáp này; chưa có micro vật lý hoặc máy Windows RTX 4060 để đo STT, TTFA, RTF, VRAM và nghe thuật ngữ.

VieNeu là TTS tạo âm thanh từ kịch bản; độ tự nhiên cần nghe thử, không được bảo đảm như người thật chỉ nhờ tích hợp API. Model/weights không nằm trong ZIP. Lần đầu tải/nạp model có thể chậm; mặc định CPU để tránh tranh VRAM với Qwen.

Frontend được kiểm tra bằng JSDOM và build, chưa có ảnh chụp trình duyệt thực trong môi trường này. Chưa có tự phát hiện kết thúc lượt nói, ngắt lời bằng micro hoặc avatar. Hướng dẫn hiện hành: `VOICE_VIENEU_GUIDE_VI.md`.
