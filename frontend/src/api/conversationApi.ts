import { apiRequest, USE_MOCK_API } from "./client";
import { mockService } from "../mocks/mockService";
import type { Conversation, ConversationSummary } from "../types";
export const conversationApi = {
  getConversations: (): Promise<ConversationSummary[]> =>
    USE_MOCK_API
      ? mockService.getConversations()
      : apiRequest("/api/v1/conversations"),
  getConversation: (id: string): Promise<Conversation> =>
    USE_MOCK_API
      ? mockService.getConversation(id)
      : apiRequest(`/api/v1/conversations/${encodeURIComponent(id)}`),
  renameConversation: (id: string, title: string): Promise<void> =>
    USE_MOCK_API
      ? mockService.rename(id, title)
      : apiRequest(`/api/v1/conversations/${encodeURIComponent(id)}`, {
          method: "PATCH",
          body: JSON.stringify({ title }),
        }),
  deleteConversation: (id: string): Promise<void> =>
    USE_MOCK_API
      ? mockService.delete(id)
      : apiRequest(`/api/v1/conversations/${encodeURIComponent(id)}`, {
          method: "DELETE",
        }),
};
