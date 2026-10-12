import type { Attachment, SelectedRecord } from "../types";
import {
  API_BASE_URL,
  FILE_PROCESSING_TIMEOUT_MS,
  apiRequest,
  ApiError,
  httpError,
  USE_MOCK_API,
} from "./client";
import { delay, mockService } from "../mocks/mockService";
type Change = (patch: Partial<Attachment>) => void;
async function upload(
  file: File,
  attachment: Attachment,
  onChange: Change,
  signal: AbortSignal,
): Promise<Attachment> {
  if (USE_MOCK_API) return mockService.upload(attachment, onChange, signal);
  const path =
    attachment.type === "medical_record"
      ? "/api/v1/files/medical-record"
      : "/api/v1/files/xray";
  let uploaded = attachment.serverId && attachment.status !== "error"
    ? await apiRequest<Attachment>(`/api/v1/files/${encodeURIComponent(attachment.serverId)}`, { signal })
    : await new Promise<Attachment>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const abort = () => xhr.abort();
    xhr.open("POST", `${API_BASE_URL}${path}`);
    xhr.withCredentials = true;
    xhr.timeout = 120000;
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable)
        onChange({
          status: "uploading",
          progress: Math.round((event.loaded / event.total) * 100),
        });
    };
    xhr.onload = () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(httpError(xhr.status));
        return;
      }
      try {
        resolve(JSON.parse(xhr.responseText) as Attachment);
      } catch {
        reject(new ApiError("Máy chủ trả về dữ liệu file không hợp lệ."));
      }
    };
    xhr.onerror = () =>
      reject(new ApiError("Không thể tải file lên máy chủ. Vui lòng thử lại."));
    xhr.ontimeout = () =>
      reject(new ApiError("Tải file quá thời gian chờ. Vui lòng thử lại."));
    xhr.onabort = () => reject(new DOMException("Aborted", "AbortError"));
    xhr.onloadend = () => signal.removeEventListener("abort", abort);
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const form = new FormData();
    form.append("file", file);
    form.append("clientId", attachment.id);
    xhr.send(form);
  });
  onChange({
    status: uploaded.status,
    progress: 100,
    serverId: uploaded.serverId ?? uploaded.id,
    analysisAnswer: uploaded.analysisAnswer,
    error: uploaded.error,
  });
  // Optional asynchronous processing contract: GET /api/v1/files/{id}.
  const deadline = Date.now() + FILE_PROCESSING_TIMEOUT_MS;
  while (uploaded.status !== "processed" && uploaded.status !== "error" && Date.now() < deadline) {
    await delay(2000, signal);
    uploaded = await apiRequest<Attachment>(
      `/api/v1/files/${encodeURIComponent(uploaded.serverId ?? uploaded.id)}`,
      { signal },
    );
    onChange({
      status: uploaded.status,
      progress: 100,
      error: uploaded.error,
      analysisAnswer: uploaded.analysisAnswer,
    });
  }
  if (uploaded.status !== "processed")
    throw new ApiError(
      uploaded.error ?? "Chưa xử lý được file. Vui lòng thử lại.",
    );
  return {
    ...attachment,
    serverId: uploaded.serverId ?? uploaded.id,
    url: attachment.url ?? uploaded.url,
    status: "processed",
    progress: 100,
    analysisAnswer: uploaded.analysisAnswer,
  };
}
async function analyzeClinical(records: SelectedRecord[], text: string,
  conversationId: string, clientId: string, signal: AbortSignal, onChange: Change, previous?: Attachment): Promise<Attachment> {
  if (USE_MOCK_API) throw new ApiError("Phân tích Clinical IE cần chế độ live.");
  let result = previous?.serverId && previous.status!=="error"
    ? await apiRequest<Attachment>(`/api/v1/files/${encodeURIComponent(previous.serverId)}`, {signal})
    : undefined;
  if (!result || result.status==='error') {
    const form = new FormData();
    form.append('conversationId',conversationId);form.append('clientId',clientId);
    if(text) form.append('text',text);
    for(const item of records)form.append(item.attachment.type==='xray'?'image':'file',item.file);
    result = await apiRequest<Attachment>('/api/v1/clinical/analyze',{method:'POST',body:form,signal},120000);
  }
  onChange({...result,serverId:result.serverId??result.id});
  const deadline=Date.now()+FILE_PROCESSING_TIMEOUT_MS;
  while(!['processed','error'].includes(result.status) && Date.now()<deadline){
    await delay(2000,signal);
    result=await apiRequest<Attachment>(`/api/v1/files/${encodeURIComponent(result.serverId??result.id)}`,{signal});
    onChange({...result,serverId:result.serverId??result.id});
  }
  if(result.status!=='processed')throw new ApiError(result.error??'Ca vẫn đang xử lý. Bấm thử lại để tiếp tục theo dõi.');
  return result;
}
export const uploadApi = { uploadMedicalRecord: upload, uploadXray: upload, analyzeClinical };
