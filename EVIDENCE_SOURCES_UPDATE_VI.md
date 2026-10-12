> **Bản rà soát tiếp theo:** xem [VERIFIED_UPDATE_VI.md](VERIFIED_UPDATE_VI.md). Kết quả hiện tại: 463 backend đạt, 87 frontend đạt, 0 lỗi; 25 bài backend bỏ qua. Mục kiểm chứng ở cuối tài liệu này ghi lại thời điểm bàn giao trước đó.

# Lọc bằng chứng và nguồn đánh số cho PulmoGraph AI

Áp dụng trên `medical-ai-integrated-patient-review-full.zip` đã bàn giao ở tác vụ xác nhận bệnh nhân. Bản đầy đủ cộng dồn từ dự án bạn gửi, bao gồm quy trình xác nhận vừa khai → Patient Graph → KG.

## Những gì thay đổi

Backend chuẩn bị một gói bằng chứng chung trước khi gọi Ollama. Các luồng RAG, KG, RAG + KG, chẩn đoán đã xác nhận, bệnh án cũ và ba luồng Clinical IE mới đều sử dụng bộ lọc này.

- **RAG:** giữ đoạn nguồn, tiêu đề/mục và số tham chiếu; bỏ vector, embedding text, revision, cấu hình chunking/reindex và metadata lưu trữ khỏi prompt. Các đoạn giống nhau trong cùng tài liệu được dùng chung một nguồn.
- **KG:** giữ tên/loại thực thể, quan hệ có hướng, thuộc tính assertion, phủ định, điều kiện và tham chiếu nguồn. Không gửi ID node/cạnh/tài liệu/mệnh đề, anchors, timings hay toàn bộ response envelope. Mỗi assertion giữ tham chiếu nguồn riêng để không đổi nguồn của một điều kiện sang điều kiện khác.
- **Chuỗi/path/so sánh KG:** giữ chỉ số tham chiếu facts, các bước và hàng đối chiếu. Kiểm tra chỉ số có hợp lệ; không tự cắt một cạnh hoặc đổi chiều quan hệ. Nhóm KG vượt ngân sách bị bỏ nguyên nhóm, có thông báo giới hạn; bảng so sánh không hiển thị như bằng chứng được dùng nếu nhóm đó bị bỏ.
- **Clinical IE:** giữ thực thể/quan hệ trích xuất, thuộc tính lâm sàng, xếp hạng cần thiết, câu hỏi còn thiếu và cảnh báo; bỏ graph nội bộ đầy đủ, danh sách điểm lặp, IDs, phiên bản model và provenance kỹ thuật không cần cho câu trả lời. Điểm giữ nguyên ý nghĩa xếp hạng chưa hiệu chuẩn, không phải xác suất bệnh.
- **Patient Graph:** gửi đúng dữ kiện đã chọn/xác nhận: tên, loại, Có/Không/Chưa biết, thời điểm, chủ thể và chi tiết. Không gửi original_fact lồng nhiều tầng, IDs hoặc sự kiện xác nhận.

Module trả kết quả gốc vẫn được giữ để lưu trữ/truy vết; bộ lọc không sửa kết quả gốc hoặc tạo lại chỉ mục.

## Nguồn `[1]`, `[2]` hoạt động thế nào?

Mỗi câu trả lời có registry nguồn riêng. Backend cấp số **trước khi gọi LLM**, dựa trên bằng chứng được chọn. Cùng đoạn văn/cùng tài liệu được dùng chung số giữa RAG và KG; khác tài liệu vẫn giữ nguồn riêng.

LLM nhận nguồn có số, tên, mục và văn bản; mã nội bộ nằm trong `origins` của metadata phục vụ truy vết, không được in trong giao diện nguồn thông thường. Câu trả lời dùng `[n]` sát nhận định cần kiểm tra. Backend loại số trích dẫn không có trong registry và hiện thông báo giới hạn, không tự gán một số nguồn khác để che lỗi.

Các mã nguồn nội bộ có trong kết quả hoặc mang dạng DOC_/PROP_/SENT_/ENT_/REL_/CHUNK_ được loại khỏi phần trả lời mới. Văn bản nguồn được trình bày nguyên văn bằng text an toàn; không chạy HTML hoặc chỉ dẫn nằm trong đó.

**Nguồn `kind=model` được phân biệt:** đó là đầu ra Clinical IE, không phải tài liệu y khoa chứng minh bệnh nhân mắc bệnh. Dữ kiện người dùng xác nhận cũng không được biến thành kết luận đã được bác sĩ xác minh.

## Giao diện

- Trả lời chính trước; LLM được hướng dẫn dùng các mục Markdown ngắn khi phù hợp: giải thích, giới hạn dữ liệu, thông tin cần bổ sung. Không bắt buộc tạo các mục trống hoặc chép lại JSON đầu vào.
- `[n]` là nút nhỏ màu teal. Rê chuột hoặc focus bằng bàn phím để thấy tên/mục và trích đoạn. Bấm hoặc Enter để mở bảng nguồn bên cạnh, đọc toàn văn **trích đoạn được cung cấp**, không phải toàn bộ tài liệu gốc.
- Bảng nguồn có nút đóng, Escape, chuyển nguồn và focus trở lại nút mở. Điện thoại chạm để mở bảng rộng theo màn hình.
- Cuối câu trả lời có mục **Nguồn tham khảo** thu gọn, sử dụng tên đọc được thay cho mã. Khi module chưa trả tên tài liệu, dùng nhãn “Tài liệu truy xuất”, không tự bịa tên tác giả/tài liệu.
- Bảng so sánh và phần gợi ý câu hỏi KG cũng sử dụng nguồn đánh số, không in mã tài liệu/evidence trong các nhãn nguồn. Các câu hỏi KG có registry riêng trong khung hỏi.
- Giọng nói không đọc số trích dẫn; nguồn vẫn xem được ở phần chat.

Nguồn được lưu cùng metadata tin nhắn/job. Tải lại trang vẫn giữ số và nội dung tương ứng. Quy tắc hiển thị và sinh trả lời mới không viết lại nội dung lịch sử cũ; câu trả lời cũ từng in mã có thể vẫn chứa chúng.

## Ba luồng TXT/X-quang/kết hợp

Sau khi Clinical IE xử lý, backend gửi bằng chứng đã lọc cho Ollama diễn đạt. Không còn mặc định dựng câu trả lời bằng khối JSON thực thể của `format_analysis()` ở luồng mới.

Nếu Ollama lỗi, job chuyển lỗi và **giữ kết quả Clinical IE**. Nút thử lại dùng kết quả phân tích đã lưu, không chạy lại model. Nguồn cũng được lưu vào SQLite và trả qua API file/job, nên giao diện vừa gửi và lịch sử dùng cùng dữ liệu nguồn.

Chỉ ảnh vẫn là phân lớp ảnh; LLM không được tự tạo báo cáo tổn thương, xét nghiệm hoặc triệu chứng người dùng chưa khai. Việc thêm bước diễn đạt không bổ sung hai trọng số NLP từng thiếu hoặc khắc phục một dịch vụ ML/CSDL chưa sẵn sàng.

## Ngân sách và các giới hạn thực tế

Bộ lọc dùng trần **18.000 byte UTF-8** cho JSON bằng chứng, có phần dự phòng thông báo. Đây là giới hạn dung lượng/ước lượng đầu vào, **không phải đếm token chính xác theo tokenizer Ollama**; chưa bao gồm system prompt và câu hỏi. Không tự cắt giữa một trích đoạn để tránh bỏ mất phủ định/điều kiện. Snapshot người dùng đã xác nhận vượt trần bị từ chối thay vì âm thầm bỏ dữ kiện.

Nếu sau lọc không còn bằng chứng hoặc dữ kiện phù hợp để dùng, OllamaClient trả thông báo chưa đủ bằng chứng và không gọi model sinh câu trả lời.

Bản này lọc cấu trúc, gộp trùng và hạn chế dung lượng. Độ liên quan về nội dung vẫn phụ thuộc bước truy xuất của module và việc LLM đọc ngữ cảnh; **chưa thêm semantic reranker**. Kiểm tra trích dẫn xác minh **số nguồn tồn tại**, không tự chứng minh mỗi nhận định được đoạn nguồn hỗ trợ về mặt y khoa. Người dùng có thể mở nguồn để kiểm tra; chưa có mô hình kiểm định entailment hoặc thẩm định y khoa tự động.

Không có thêm lượt LLM để chạy bộ lọc. Luồng Clinical mới thêm một lượt diễn đạt vốn chưa có ở phiên bản trước, nên thời gian trả lời còn phụ thuộc Ollama.

## Cập nhật trên Windows

1. Dừng backend và frontend. Sao lưu SQLite đang dùng và `.env`.
2. Giải nén `medical-ai-integrated-evidence-ui-patch.zip`. Chép **nội dung bên trong** thư mục `medical-ai-integrated` vào dự án hiện có, đồng ý ghi đè. Áp dụng cả backend và frontend.
3. Giữ `.env`, dữ liệu CSDL, venv và node_modules. Không cần cài lại thư viện, đổi embedding, nạp lại RAG hoặc index lại KG.
4. Khởi động lại:

```bat
cd /d D:\medical_wed\banzip\medical-ai-integrated\backend
call venv\Scripts\activate.bat
python -m uvicorn app.main:app --host 127.0.0.1 --port 8100 --workers 1
```

```bat
cd /d D:\medical_wed\banzip\medical-ai-integrated\frontend
npm run dev
```

Nếu chạy bản build, chạy `npm run build` và sử dụng dist mới. API chính vẫn ở 8100; frontend không gọi trực tiếp các module hay Ollama. Clinical IE và Ollama cần chạy theo cấu hình hiện có.

SQLite tự bổ sung cột `analysis_sources` cho attachment để lưu nguồn. Không xóa hoặc tạo lại CSDL.

Gói `medical-ai-integrated-evidence-ui-full.zip` là mã nguồn cộng dồn; không chứa `.env` riêng, CSDL cá nhân, venv, node_modules hoặc dist. Ưu tiên bản vá nhỏ khi cập nhật dự án đang chạy. Danh sách: `EVIDENCE_SOURCES_PATCH_FILES.txt`.

## Kiểm chứng

- **401 bài backend đạt, 25 bỏ qua; 59 lỗi KG có sẵn** giống bản nền: thiếu tệp mẫu import và khác biệt ontology. Không có tên bài lỗi mới sau đối chiếu.
- **87 bài frontend đạt**, TypeScript và production build thành công.
- Kiểm tra dữ liệu thực tế gửi qua HTTPX tới Ollama bằng mock transport: không có IDs/vector/revision trong prompt; dùng JSON bằng chứng đã lọc.
- Kiểm tra số nguồn chung RAG/KG, gộp trùng, bảo toàn điều kiện/phủ định/chủ thể/thời điểm/giá trị, đường đi và ô so sánh tham chiếu đúng facts.
- Kiểm tra nguồn của từng assertion, loại số trích dẫn không tồn tại, không gọi Ollama khi không có bằng chứng, cache kết quả Clinical IE khi diễn đạt lỗi và lưu nguồn vào lịch sử/job.
- Kiểm thử DOM cho hover/focus/Enter/Escape, nguồn câu hỏi KG, nguồn mô hình, Markdown code/link và văn bản HTML không được thực thi.
- Chưa chạy suy luận thực tế với Ollama/Clinical IE/Neo4j trên máy Windows của bạn; chưa kiểm định chất lượng diễn đạt y khoa. Chưa kiểm tra trực quan bằng trình duyệt thật trong môi trường bàn giao này.

Các bài kiểm thử cũ được cập nhật theo hợp đồng mới: nguồn có `number/title/text/origins`; ID truy vết không còn là nhãn hiển thị hoặc nội dung prompt.
