import { API_BASE_URL, apiRequest, CHAT_TIMEOUT_MS, httpError, ApiError } from "./client";
import type { Assessment, ChatMessage, Conversation } from "../types";
export interface VoiceReply {
  conversation: Conversation;
  message: ChatMessage | null;
  assessment?: Assessment | null;
  display_text: string;
  spoken_text: string;
  conversation_action: string;
  expects_reply: boolean;
  has_more: boolean;
  speech_chunks?: string[] | null;
  speech_style?: string;
}
export interface VoiceConfig {
  stt_installed: boolean; tts_installed: boolean; external_tts: boolean; max_seconds: number;
  greeting?: string; streaming?: boolean; sample_rate?: number; tts_voice?: string; detail?: string;
}

export async function readVoiceEvents(body: ReadableStream<Uint8Array>, onSentence: (text: string) => void): Promise<VoiceReply> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  let index = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      pending += decoder.decode(value, { stream: !done });
      if (pending.length > 250000) throw new ApiError("Phản hồi giọng nói vượt giới hạn.");
      let boundary: number;
      while ((boundary = pending.indexOf("\n")) >= 0 || (done && pending.trim())) {
        if (boundary < 0) boundary = pending.length;
        const line = pending.slice(0, boundary).trim();
        pending = pending.slice(boundary + 1);
        if (!line) continue;
        const event = JSON.parse(line);
        if (event.type === "sentence") {
          if (event.index !== index || typeof event.text !== "string" || !event.text.trim()) throw new ApiError("Luồng lời thoại không hợp lệ.");
          index += 1; onSentence(event.text);
        } else if (event.type === "error") {
          const detail = event.detail;
          throw new ApiError(typeof detail === "string" ? detail : detail?.message || "Chưa hoàn tất câu trả lời.", event.status || 502);
        } else if (event.type === "complete") {
          if (!event.reply || event.streamed_sentences !== index) throw new ApiError("Luồng lời thoại chưa hoàn chỉnh.");
          return event.reply as VoiceReply;
        } else throw new ApiError("Sự kiện giọng nói không hợp lệ.");
      }
      if (done) throw new ApiError("Kết nối giọng nói bị ngắt trước khi hoàn tất.");
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

async function turnStream(conversationId: string, transcript: string, messageId: string, assessmentVersion: number | undefined,
  signal: AbortSignal, onSentence: (text: string) => void): Promise<VoiceReply> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal.addEventListener("abort", abort, { once: true });
  if (signal.aborted) abort();
  const timer = window.setTimeout(abort, CHAT_TIMEOUT_MS);
  try {
    const response = await fetch(API_BASE_URL + "/api/v1/voice/turn/stream", {
      method: "POST", credentials: "include", signal: controller.signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversationId, transcript, messageId, assessmentVersion }),
    });
    if (!response.ok) throw httpError(response.status);
    if (!response.body) throw new ApiError("Trình duyệt chưa hỗ trợ phản hồi streaming.");
    return await readVoiceEvents(response.body, onSentence);
  } finally { clearTimeout(timer); signal.removeEventListener("abort", abort); }
}

async function speakStream(text: string, signal: AbortSignal, onChunk: (chunk: Uint8Array) => Promise<void>) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal.addEventListener("abort", abort, { once: true });
  if (signal.aborted) abort();
  const timer = window.setTimeout(abort, 180000);
  try {
  const response = await fetch(API_BASE_URL + "/api/v1/voice/speech/stream", {
    method: "POST", credentials: "include", signal: controller.signal,
    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new ApiError(typeof detail.detail === "string" ? detail.detail : "Chưa phát được giọng VieNeu.", response.status);
  }
  if (!response.body || response.headers.get("X-Audio-Sample-Rate") !== "48000" ||
      response.headers.get("X-Audio-Format") !== "s16le") throw new ApiError("Định dạng âm thanh VieNeu không hợp lệ.");
  const reader = response.body.getReader();
  let bytes = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (value) { bytes += value.length; await onChunk(value); }
    }
    if (!bytes || bytes % 2) throw new ApiError("Âm thanh VieNeu bị thiếu dữ liệu. Bạn có thể phát lại.");
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
  } finally { clearTimeout(timer); signal.removeEventListener("abort", abort); }
}
async function binaryRequest(path: string, body: BodyInit, signal: AbortSignal, json = false) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal.addEventListener("abort", abort, { once: true });
  if (signal.aborted) abort();
  const timer = window.setTimeout(abort, CHAT_TIMEOUT_MS);
  try {
    const response = await fetch(API_BASE_URL + path, { method: "POST", body,
      credentials: "include", signal: controller.signal,
      headers: json ? { "Content-Type": "application/json" } : undefined });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw typeof data.detail === "string" ? new ApiError(data.detail, response.status) : httpError(response.status);
    }
    return response;
  } finally { clearTimeout(timer); signal.removeEventListener("abort", abort); }
}
export const voiceApi = {
  config: (signal: AbortSignal) => apiRequest<VoiceConfig>("/api/v1/voice/config", { signal }),
  turnStream, speakStream,
  async transcribe(blob: Blob, signal: AbortSignal, mode: "fast" | "careful" = "fast") {
    const form = new FormData();
    form.append("file", blob, "voice.webm");
    form.append("mode", mode);
    return (await binaryRequest("/api/v1/voice/transcribe", form, signal)).json() as Promise<{ transcript: string; warnings?: string[]; metrics?: Record<string, unknown>; suggested_transcript?: string | null; uncertain?: boolean }>;
  },
  turn: (conversationId: string, transcript: string, messageId: string, assessmentVersion: number | undefined, signal: AbortSignal) =>
    apiRequest<VoiceReply>("/api/v1/voice/turn", { method: "POST", signal,
      body: JSON.stringify({ conversationId, transcript, messageId, assessmentVersion }) }, CHAT_TIMEOUT_MS),
  reply: (id: string, signal: AbortSignal) => apiRequest<VoiceReply>(`/api/v1/voice/reply/${encodeURIComponent(id)}`, { signal }, CHAT_TIMEOUT_MS),
  async speak(text: string, signal: AbortSignal) {
    return (await binaryRequest("/api/v1/voice/speech", JSON.stringify({ text }), signal, true)).blob();
  },
};
