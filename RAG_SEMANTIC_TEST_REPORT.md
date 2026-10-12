# Kiểm thử semantic chunking — bản tích hợp

Đây là kết quả tại thời điểm thêm semantic chunking. Bản nạp hàng loạt mới hơn có
kết quả kiểm thử toàn dự án tại [RAG_BATCH_TEST_REPORT.md](RAG_BATCH_TEST_REPORT.md).

## Kết quả

- Backend: **243 passed, 6 skipped**, 18 cảnh báo; Python 3.12, pytest 8.3.4, pytest-asyncio 1.3.0. Bộ semantic mới có **25 kiểm thử**.
- Frontend: **34 passed / 10 files**, Vitest 4.1.11. Có kiểm thử JSDOM cho trang quản lý RAG và thao tác reindex.
- `npm run build`: TypeScript/Vite thành công. `node --check backend/app/modules/rag/static/app.js` thành công.
- Không thay `requirements.txt`, `package.json` hoặc `package-lock.json`; không thêm thư viện/model cho semantic chunking.

Lệnh kiểm tra:

```bat
cd backend
python -m pytest -q -rs --disable-warnings
```

```bat
cd frontend
npm test
npm run build
```

## Các trường hợp kiểm chứng

- Cùng JSON và cùng giới hạn token, thay vector từ đồng nhất sang hai chủ đề làm ranh giới chunk thay đổi; điểm tách xuất hiện trước khi chạm trần. Đây là kiểm tra semantic logic bằng vector có kiểm soát, không phải đánh giá nội dung y khoa.
- Window làm mượt, percentile/sàn khoảng cách và mức tối thiểu mềm hạn chế tách các nhóm quá ngắn. Tắt semantic không gọi embedding ranh giới.
- Văn bản ghép lại đúng nguyên văn từng section, gồm dấu tiếng Việt, khoảng trắng, xuống dòng, phủ định, số thập phân và đơn vị. `source_spans` bao phủ toàn bộ ký tự nguồn; ID paragraph/sentence không đổi, không ghép xuyên section.
- Một câu quá dài được chia an toàn thành mảnh, giữ đủ ký tự và vị trí evidence; tất cả input embedding và chunk cuối nằm trong giới hạn.
- Quan hệ chunk → sentence → proposition/evidence/entity/relation vẫn có thể truy lại theo ID gốc.
- Embedding ranh giới theo batch tối đa 32. Adapter E5 được kiểm tra với model/tokenizer giả lập: `query:` cho so sánh đối xứng, `passage:` cho lập chỉ mục, từ chối input quá dài.
- Vector rỗng, không hữu hạn, độ dài bằng không hoặc số vector sai làm import lỗi; không âm thầm thay bằng size chunking. Config không hợp lệ bị từ chối trước khi nạp model/mở DB.
- Startup đọc đúng cấu hình mặc định semantic và override token. Demo encoder được báo là phương thức token với lý do fallback, không mang nhãn semantic.
- Dry-run không ghi DB; commit lưu cấu hình/ranh giới; import cùng nội dung/cấu hình/model được skip. Thay cấu hình đánh dấu tài liệu cần reindex.
- Tài liệu phiên bản cũ thiếu metadata chunking được phát hiện và reindex từ JSON đã lưu; nguồn không đổi.
- Lỗi embedding trước kích hoạt giữ snapshot đang hoạt động. Các kiểm thử upstream cũng kiểm tra lỗi stage không làm mất snapshot cũ.
- Kiểm thử SQLite, MongoDB bằng mongomock và **Qdrant local in-memory thật**: metadata roundtrip, search, kích hoạt snapshot mới và dọn vector cũ. Qdrant local không hỗ trợ payload indexes; kiểm thử adapter upstream riêng kiểm tra các lời gọi index.
- UI RAG nhận cấu hình từ health, hiện kiểu chia thực tế và cảnh báo reindex, gửi POST reindex rồi làm mới nhãn/báo cáo thành công.
- Các kiểm thử chat chữ, giọng nói VieNeu, xác nhận dữ kiện, đánh giá và upstream hiện có vẫn qua. Sáu kiểm thử bị skip vì chưa cấu hình MongoDB/Neo4j thật.

## Giới hạn và cách đọc kết quả

**Chưa tải/chạy trọng số E5 thật trong vòng kiểm thử này.** Vector semantic được điều khiển để kiểm chứng logic; model/tokenizer của adapter được giả lập. Không có benchmark CPU/GPU, VRAM, thời gian import hoặc đánh giá retrieval trên kho tài liệu của bạn. Không suy ra tăng độ chính xác chỉ từ việc các kiểm thử này qua.

MongoDB server, Neo4j và Qdrant server thật của bạn chưa được truy cập. Qdrant local và mongomock kiểm chứng adapter nhưng không thay thế kiểm tra vận hành server. Cần dùng dry-run, xem chunk/evidence và so sánh truy xuất trên cùng tài liệu sau khi cài.

Frontend được kiểm tra bằng JSDOM/build, chưa có ảnh chụp trình duyệt thật hoặc vòng micro vật lý. Các giới hạn kiểm chứng VieNeu ở `VOICE_TEST_REPORT.md` tiếp tục áp dụng; trọng số/model runtime vẫn không nằm trong ZIP.

Hướng dẫn: [RAG_SEMANTIC_CHUNKING_VI.md](RAG_SEMANTIC_CHUNKING_VI.md). Giao diện teal và VieNeu được giữ; không sửa dữ liệu KG/Patient Graph.
