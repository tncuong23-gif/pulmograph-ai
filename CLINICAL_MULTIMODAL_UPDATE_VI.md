# Clinical IE đa phương thức — bản v14

Cập nhật trên Medical AI Integrated v13: tích hợp module `clinical-ie-handover-0.2.0-research` vào cây backend và nối giao diện hội thoại với ba luồng nhập. Frontend vẫn gọi backend cổng 8100; dịch vụ suy luận Clinical IE chạy cục bộ ở cổng 8002 trong môi trường Python riêng.

## 1. Trạng thái bàn giao cần biết

**Mã tích hợp và giao diện đã hoàn thành, nhưng ZIP module được cung cấp thiếu hai file trọng số. Vì thế bản này chưa thể chạy suy luận neural hoàn chỉnh cho văn bản/TXT và văn bản + X-quang.** Không có chế độ giả lập thành công hoặc tự chuyển sang luật khi thiếu model.

Các đường dẫn dưới đây tính từ `backend/clinical_service/vendor/clinical-ie/`:

| File cần bổ sung | SHA-256 theo manifest gốc |
| --- | --- |
| `models/clinical-ie-models-v1.3/joint/final_model/model.safetensors` | `55f3b1ccbef9221967e3d646864359b8845a01ab4ff2e5c0a1616426a5738df2` |
| `models/clinical-ie-models-v1.3/simplifier/final_model/model.safetensors` | `4a317d28515316b74aa8bf533a34c99f85bb4be573797c8673a511aa8c28ffae` |

Lấy đúng hai file từ bản huấn luyện/bàn giao của module này, đặt vào đúng thư mục. Không thay bằng trọng số của một model nền cùng tên: chúng không phải checkpoint đã huấn luyện và sẽ không khớp checksum.

Checkpoint X-quang ConvNeXt Tiny đã có trong gói. Luồng chỉ ảnh không nạp pipeline NLP nên không cần hai file trên; vẫn cần cài đầy đủ thư viện dịch vụ. Chưa chạy kiểm chứng suy luận CNN hoặc GPU thực tế trong môi trường bàn giao này. Hai luồng văn bản đã được kiểm tra hợp đồng tích hợp bằng bộ suy luận giả lập, không phải kiểm định độ chính xác y khoa.

## 2. Ba luồng sử dụng

**Cập nhật tự động (12/10/2026):** Đã bỏ cả checkbox chế độ và checkbox cùng ca. Chỉ cần chọn tệp rồi nhấn Gửi; frontend không gửi trường `same_case`, backend chọn luồng `text`/`xray`/`text_xray` dựa trên dữ liệu. Ảnh X-quang trên frontend đã được mở lại (bỏ thuộc tính `disabled`). Để tránh gán nhầm dữ liệu y tế, người dùng cần đảm bảo TXT và ảnh tải trong cùng một lượt thực sự thuộc cùng một ca.


| Luồng | Thao tác trong hội thoại | Xử lý |
| --- | --- | --- |
| Văn bản/TXT | Chọn một TXT UTF-8 (không cần bật checkbox) | Clinical IE trích xuất, dựng graph nội bộ, phân lớp và tìm ca tham chiếu |
| Chỉ X-quang | Chọn một ảnh JPEG/PNG; để trống ô văn bản | Nhánh ảnh phân lớp; không tạo thực thể hay báo cáo tổn thương từ ảnh |
| Văn bản + X-quang | Chọn TXT và ảnh, hoặc nhập văn bản rồi thêm ảnh; tự xử lý là **cùng một ca** | Pipeline văn bản và late fusion với ảnh theo cấu hình gốc |

Mỗi lượt tối đa một nguồn văn bản và một ảnh. Chọn tệp chỉ đưa vào hàng chờ ở trình duyệt; bấm **Gửi** mới tải lên. Có thể bỏ tệp trước khi gửi. Không trộn TXT của người này với ảnh của người khác.

Giới hạn: mỗi file 20 MB, văn bản 100.000 ký tự, ảnh một khung tối đa 25 triệu pixel. PDF, DOCX, DICOM và WebP chưa được nhận ở luồng này. TXT phải là UTF-8. Đầu vào trống, ảnh hỏng và tệp giả phần mở rộng bị từ chối.

Ô nhập khi không có tệp vẫn dùng bộ điều phối chat trước đây; nhập văn bản kết hợp ảnh sẽ chạy Clinical IE. Các luồng Clinical tường minh không đi qua bộ phân lớp câu hỏi hoặc gọi thêm Qwen để viết lại thứ hạng. Kết quả được trình bày trực tiếp từ JSON module.

Điểm hiển thị là điểm xếp hạng chưa hiệu chuẩn; không phải xác suất mắc bệnh. Luồng này không tự ghi thực thể vào Patient Graph. Quy trình chẩn đoán cần xác nhận dữ kiện hiện có vẫn giữ nguyên.

## 3. Ghi đè vào dự án đang chạy

1. Dừng frontend, backend và dịch vụ Clinical IE cũ. Sao lưu mã nguồn, `.env`, SQLite và thư mục uploads đang dùng. Các CSDL Docker không cần xóa hay khởi tạo lại vì bản vá này.
2. Giải nén `medical-ai-clinical-multimodal-patch.zip`. Chép **nội dung bên trong** thư mục `medical-ai-integrated` vào thư mục dự án hiện tại, đồng ý ghi đè. Không tạo thêm tầng `medical-ai-integrated/medical-ai-integrated`.
3. Giữ `.env`, venv hiện có và dữ liệu của bạn. Bản vá không chứa các tệp này. Danh sách thay đổi nằm trong `CLINICAL_MULTIMODAL_PATCH_FILES.txt`.
4. Trong CMD tại backend, bổ sung Pillow cho việc kiểm tra ảnh ở API chính:

```bat
cd /d D:\medical_wed\banzip\medical-ai-integrated\backend
venv\Scripts\python.exe -m pip install "Pillow>=10.4,<13"
```

Nếu môi trường backend của bạn có tên khác `venv`, sửa đường dẫn tương ứng. Không cài requirements của module Clinical IE vào venv backend hiện có: phiên bản Torch và các thư viện của module bàn giao khác với RAG/KG.

SQLite tự bổ sung cột lưu loại đầu vào, nội dung ca và liên kết hội thoại khi backend khởi động. Không cần nạp lại RAG hoặc tạo lại index KG chỉ vì bản vá v14.

Gói `medical-ai-integrated.zip` là mã nguồn dự án cộng dồn, bao gồm giao diện teal, các cập nhật v13 và tích hợp v14. Gói không chứa venv, node_modules, dữ liệu CSDL cá nhân hoặc hai trọng số đang thiếu. Nếu cài từ đầu, làm phần cài đặt cơ sở trong `README_VI.md`, rồi phần Clinical IE dưới đây.

## 4. Cài dịch vụ Clinical IE riêng trên Windows

Module bàn giao yêu cầu Python **3.12**. Mở CMD tại backend:

```bat
cd /d D:\medical_wed\banzip\medical-ai-integrated\backend
py -3.12 --version
install_clinical_windows.bat
```

Script tạo `.venv-clinical`, cài API và các requirements nguyên bản của module, kiểm tra xung đột dependency, sau đó kiểm tra checksum model. Nó không sửa venv backend.

**Với gói hiện tại, bước kiểm tra cuối sẽ báo thiếu hai trọng số và trả mã 2.** Đây là thiếu tài sản model, không phải yêu cầu cài lại từ đầu. Bổ sung hai file ở mục 1 rồi chạy:

```bat
.venv-clinical\Scripts\python.exe -m scripts.check_clinical_assets
```

Khi đủ dữ liệu, `missing_files` và `invalid_files` phải đều là danh sách rỗng. Checkpoint ảnh và 21 tệp liên quan hiện có đã khớp checksum lúc đóng gói.

Nếu pip báo không tìm được một phiên bản, giữ nguyên thông báo và kiểm tra nguồn package/Python trước; không tự bỏ ghim phiên bản. Module sử dụng cả checkpoint Torch và model joblib nên nâng/hạ sklearn, LightGBM hoặc Torch tùy tiện có thể gây lỗi nạp.

Máy từng hết ổ C có thể đặt cache và thư mục tạm trên ổ D trước khi chạy script:

```bat
mkdir D:\medical_cache\pip
mkdir D:\medical_cache\tmp
set "PIP_CACHE_DIR=D:\medical_cache\pip"
set "TEMP=D:\medical_cache\tmp"
set "TMP=D:\medical_cache\tmp"
```

## 5. Cấu hình và khởi động

Thêm hoặc cập nhật đúng một lần các dòng trong `backend/.env`:

```dotenv
CLINICAL_IE_BASE_URL=http://127.0.0.1:8002
CLINICAL_DEVICE=auto
```

`auto` chọn thiết bị theo runtime của module. Việc venv backend nhận GPU không đồng nghĩa `.venv-clinical` cũng có Torch CUDA. Kiểm tra đúng môi trường:

```bat
.venv-clinical\Scripts\python.exe -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"
```

Chỉ đặt `CLINICAL_DEVICE=cuda` sau khi lệnh trên trả `True`. Nếu yêu cầu CUDA mà môi trường không nhận, dịch vụ trả lỗi thay vì âm thầm chuyển CPU. Không sao chép thư mục Torch từ venv khác. Bản bàn giao ghim Torch 2.13.0 và torchvision 0.28.0; cấu hình GPU phải tương thích với chính bộ thư viện này. Chưa xác nhận nhu cầu VRAM trên RTX 4060 8 GB của bạn; Ollama, STT, TTS và embeddings có thể cùng chiếm VRAM. Có thể đặt `CLINICAL_DEVICE=cpu` để chẩn đoán lỗi nạp trước.

Mở ba cửa sổ CMD:

**Cửa sổ 1 — Clinical IE:**

```bat
cd /d D:\medical_wed\banzip\medical-ai-integrated\backend
start_clinical_windows.bat
```

Script chạy `clinical_service.app:app` tại `127.0.0.1:8002`, một worker. Dừng dịch vụ Clinical IE cũ đang chiếm cổng này. Không dùng lại đường dẫn `clinical_ie_api.app:app` của bản trước cho module mới.

Kiểm tra:

```bat
curl.exe http://127.0.0.1:8002/health
```

`/health` kiểm tra danh mục tệp, chưa nạp mạng neural. Khi thiếu hai trọng số, nó trả HTTP 503, `text=false`, `text_xray=false`, `xray=true`. `xray=true` chỉ xác nhận tệp nhánh ảnh có mặt; phép suy luận đầu tiên mới kiểm tra dependency và nạp checkpoint. Khởi động Uvicorn thành công chưa có nghĩa suy luận đã sẵn sàng.

**Cửa sổ 2 — backend chính:**

```bat
cd /d D:\medical_wed\banzip\medical-ai-integrated\backend
call venv\Scripts\activate.bat
python -m uvicorn app.main:app --host 127.0.0.1 --port 8100 --workers 1
```

Neo4j, MongoDB, Qdrant và Ollama vẫn phải sẵn sàng theo cấu hình cũ. Lỗi `Neo.ClientError.Security.Unauthorized` thuộc kết nối Neo4j của Context; cần sửa thông tin đăng nhập đang dùng, không phải thay cổng Clinical IE.

**Cửa sổ 3 — frontend:**

Đảm bảo `frontend/.env` dùng:

```dotenv
VITE_USE_MOCK_API=false
VITE_API_BASE_URL=http://127.0.0.1:8100
```

```bat
cd /d D:\medical_wed\banzip\medical-ai-integrated\frontend
npm run dev
```

Nếu chưa có node_modules thì chạy `npm ci` trước. Với triển khai bản build, chạy `npm run build` rồi dùng thư mục `dist` vừa tạo. Không dùng lại dist cũ. Mở địa chỉ do Vite in ra; vào hội thoại và thử lần lượt ba luồng trong mục 2.

## 6. API và lưu kết quả

- `POST /api/v1/clinical/analyze` trên backend 8100: form `conversationId`, `clientId`, tùy chọn `text`, `file` TXT, `image` JPEG/PNG. Backend tự xác định cùng ca khi có cả văn bản và ảnh, không cần `same_case`. Trả 202 cùng `id/serverId` của lượt xử lý.
- `GET /api/v1/files/{id}`: trạng thái và nội dung trả lời cho frontend.
- `GET /api/v1/clinical/jobs/{id}`: trạng thái cùng JSON kết quả đầy đủ, bao gồm modality và điểm gốc.
- Dịch vụ 8002 nhận `POST /api/v1/analyze`; giữ `/api/v1/analyze-text`, `/api/v1/analyze-file`, `/api/v1/ask-symptoms` cho luồng tương thích.
- Endpoint cũ `/api/v1/files/xray` vẫn không phải luồng phân tích mới. Giao diện v14 sử dụng `/api/v1/clinical/analyze` cho cả ba loại đầu vào.

Kết quả thành công được lưu vào SQLite và lịch sử hội thoại. Ảnh được lưu trong upload directory; văn bản ca và JSON kết quả nằm trong dữ liệu job ở SQLite. Hai lượt gửi cùng `conversationId/clientId` và nội dung chỉ dùng một job; nếu cùng mã nhưng đổi dữ liệu, API trả 409. Khi thất bại, nút thử lại có thể chạy lại job đó; khi chỉ hết thời gian chờ frontend, nút thử lại tiếp tục theo dõi ID đang xử lý.

Đây là background task trong một tiến trình, chưa phải hàng đợi bền vững nhiều worker. Nếu backend khởi động lại lúc xử lý, lượt đó chuyển lỗi; nếu đã tải lại trang và mất dữ liệu chờ trong trình duyệt, chọn lại dữ liệu để gửi. Không đóng trang khi đang tải tệp. Các kết quả đã xử lý thành công vẫn xem lại được trong lịch sử.

Dịch vụ Clinical IE xử lý lần lượt một ca để tránh nạp model đồng thời. Nếu đang bận, yêu cầu khác nhận lỗi 409 và có thể thử lại sau. Model được giữ trong bộ nhớ tiến trình sau lần nạp đầu; lần đầu có thể chậm hơn các lần tiếp theo.

## 7. Phạm vi kiểm chứng

Xem `CLINICAL_MULTIMODAL_TEST_REPORT.md`: 452 kiểm thử backend đạt, 6 bỏ qua theo điều kiện hiện có; 79 kiểm thử frontend đạt; TypeScript và build production thành công. Phần tích hợp kiểm tra đầu vào, gửi kết hợp một lượt, polling, thử lại, idempotency và lưu lịch sử bằng bộ suy luận giả lập.

Chưa đo độ chính xác, thời gian suy luận, độ phù hợp lâm sàng, mức dùng VRAM hoặc kết nối các CSDL thật trên máy bạn. Không coi việc build/API test thành công là bằng chứng model đã hoạt động đúng trên ca bệnh thực tế.
