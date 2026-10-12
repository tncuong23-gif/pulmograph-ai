export const USE_MOCK_API = import.meta.env.VITE_USE_MOCK_API === "true";
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "").replace(
  /\/$/,
  "",
);
function timeoutSetting(value: string | undefined, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}
export const CHAT_TIMEOUT_MS = timeoutSetting(import.meta.env.VITE_CHAT_TIMEOUT_MS, 600000);
export const FILE_PROCESSING_TIMEOUT_MS = timeoutSetting(import.meta.env.VITE_FILE_PROCESSING_TIMEOUT_MS, 600000);
export class ApiError extends Error {
  constructor(
    message: string,
    public status = 0,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
export const errorMessage = (error: unknown) =>
  error instanceof Error ? error.message : "Đã xảy ra lỗi. Vui lòng thử lại.";
export function httpError(status: number): ApiError {
  return new ApiError(
    status === 401 || status === 403
      ? "Phiên làm việc đã hết hạn hoặc bạn không có quyền truy cập. Vui lòng đăng nhập lại qua hệ thống của bạn."
      : status === 404
        ? "Không tìm thấy cuộc trò chuyện hoặc tệp được yêu cầu."
        : status === 413
          ? "File vượt quá kích thước máy chủ cho phép."
          : status === 429
            ? "Có quá nhiều yêu cầu. Vui lòng thử lại sau."
            : "Máy chủ chưa xử lý được yêu cầu. Vui lòng thử lại.",
    status,
  );
}
export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
  timeoutMs = 45000,
): Promise<T> {
  const controller = new AbortController();
  let timedOut = false;
  const abort = () => controller.abort();
  init.signal?.addEventListener("abort", abort, { once: true });
  if (init.signal?.aborted) controller.abort();
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs);
  try {
    const headers = new Headers(init.headers);
    if (!(init.body instanceof FormData) && !headers.has("Content-Type"))
      headers.set("Content-Type", "application/json");
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      credentials: "include",
      headers,
      signal: controller.signal,
    });
    if (!response.ok) {
      let detail: unknown;
      try { detail = (await response.json()).detail; } catch { /* default HTTP message */ }
      const message = typeof detail === "string" ? detail :
        detail && typeof detail === "object" && "message" in detail && typeof detail.message === "string" ? detail.message : null;
      throw message ? new ApiError(message, response.status) : httpError(response.status);
    }
    return response.status === 204
      ? (undefined as T)
      : ((await response.json()) as T);
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(
      timedOut
        ? "Yêu cầu đã hết thời gian chờ xử lý. Kiểm tra dịch vụ đang chạy trước khi gửi lại."
        : controller.signal.aborted
          ? "Yêu cầu đã được hủy."
        : "Không thể kết nối tới máy chủ. Vui lòng thử lại.",
    );
  } finally {
    clearTimeout(timer);
    init.signal?.removeEventListener("abort", abort);
  }
}
