import { apiRequest, CHAT_TIMEOUT_MS, USE_MOCK_API } from "./client";
import { mockService } from "../mocks/mockService";
import type { ChatRequest, ChatResponse } from "../types";
export const chatApi = {
  sendMessage: (request: ChatRequest): Promise<ChatResponse> =>
    USE_MOCK_API
      ? mockService.sendMessage(request)
      : apiRequest("/api/v1/chat/message", {
          method: "POST",
          body: JSON.stringify({
            ...request,
            message: {
              ...request.message,
              attachments: request.message.attachments?.map(
                ({ url: _url, ...attachment }) => attachment,
              ),
            },
          }),
        }, CHAT_TIMEOUT_MS),
};
