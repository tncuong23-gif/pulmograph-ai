import type {
  Attachment,
  ChatRequest,
  ChatResponse,
  Conversation,
  ConversationSummary,
  SystemStatus,
} from "../types";
import { DEMO_RESPONSE, seedConversations } from "./data";
import { ApiError } from "../api/client";
const conversations = new Map(
  seedConversations().map((item) => [item.id, item]),
);
export const delay = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const onAbort = () => {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    signal?.addEventListener("abort", onAbort, { once: true });
  });
export const mockService = {
  async getConversations(): Promise<ConversationSummary[]> {
    await delay(250);
    return Array.from(conversations.values()).map(
      ({ messages: _messages, ...rest }) => ({ ...rest }),
    );
  },
  async getConversation(id: string): Promise<Conversation> {
    await delay(200);
    const found = conversations.get(id);
    if (!found) throw new ApiError("Không tìm thấy cuộc trò chuyện.", 404);
    return structuredClone(found);
  },
  async rename(id: string, title: string) {
    await delay(150);
    const item = conversations.get(id);
    if (item) conversations.set(id, { ...item, title });
  },
  async delete(id: string) {
    await delay(150);
    conversations.delete(id);
  },
  async sendMessage(request: ChatRequest): Promise<ChatResponse> {
    await delay(1400);
    const now = new Date().toISOString();
    const current = conversations.get(request.conversationId) ?? {
      id: request.conversationId,
      title: request.message.content.slice(0, 70) || "Tra cứu từ tài liệu",
      createdAt: now,
      updatedAt: now,
      messages: [],
    };
    const attachmentText = request.message.attachments?.length
      ? `\n\n**Tệp đính kèm:** ${request.message.attachments.length} tệp đã được tiếp nhận trong phiên demo. Nội dung các tệp chưa được đọc hoặc phân tích.`
      : "";
    const message = {
      id: crypto.randomUUID(),
      role: "assistant" as const,
      content: DEMO_RESPONSE + attachmentText,
      createdAt: now,
    };
    const messages = request.regenerateMessageId
      ? current.messages.map((m) =>
          m.id === request.regenerateMessageId ? message : m,
        )
      : [
          ...current.messages.filter((m) => m.id !== request.message.id),
          request.message,
          message,
        ];
    conversations.set(current.id, { ...current, updatedAt: now, messages });
    return { message };
  },
  async upload(
    attachment: Attachment,
    onChange: (patch: Partial<Attachment>) => void,
    signal: AbortSignal,
  ): Promise<Attachment> {
    for (const progress of [12, 35, 62, 85, 100]) {
      await delay(170, signal);
      onChange({ status: "uploading", progress });
    }
    onChange({ status: "uploaded", progress: 100 });
    await delay(220, signal);
    onChange({ status: "processing" });
    await delay(750, signal);
    return {
      ...attachment,
      serverId: attachment.id,
      status: "processed",
      progress: 100,
      analysisAnswer: attachment.type === "medical_record"
        ? "Đây là kết quả mô phỏng. Khi kết nối backend, Qwen sẽ tóm tắt kết quả Clinical IE tại đây."
        : undefined,
    };
  },
  async status(): Promise<SystemStatus> {
    await delay(100);
    return {
      online: true,
      model: "AI Assistant · Demo",
      knowledgeBase: "Demo",
      mode: "mock",
    };
  },
};
