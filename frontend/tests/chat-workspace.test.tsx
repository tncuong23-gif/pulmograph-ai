import { StrictMode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../src/App";
import { conversationApi } from "../src/api/conversationApi";
import { chatApi } from "../src/api/chatApi";
import { systemApi } from "../src/api/systemApi";
import { voiceApi } from "../src/api/voiceApi";

vi.mock("../src/api/client", async importOriginal => ({
  ...await importOriginal<object>(), USE_MOCK_API: false,
}));
const composerCount = () => document.querySelectorAll(".chat-composer").length;
beforeEach(() => {
  vi.spyOn(conversationApi, "getConversations").mockResolvedValue([]);
  vi.spyOn(systemApi, "getStatus").mockResolvedValue({ online: true, model: "test", knowledgeBase: "test", mode: "live" });
  vi.spyOn(voiceApi, "config").mockResolvedValue({ stt_installed: true, tts_installed: true, external_tts: false, max_seconds: 90 });
  vi.spyOn(chatApi, "sendMessage").mockImplementation(async request => ({ message: {
    id: "answer-" + request.message.id, role: "assistant", content: "Kết quả kiểm thử", createdAt: new Date().toISOString(),
  } }));
});

it("keeps one composer through landing, submission and new conversation in StrictMode", async () => {
  window.history.replaceState({}, "", "/");
  const user = userEvent.setup(); render(<StrictMode><App /></StrictMode>);
  expect(composerCount()).toBe(0);
  await user.click(screen.getByRole("link", { name: "Bắt đầu chat" }));
  await screen.findByRole("textbox", { name: "Câu hỏi y tế" });
  expect(composerCount()).toBe(1);
  const originalComposer = document.querySelector(".chat-composer");
  await user.type(screen.getByRole("textbox", { name: "Câu hỏi y tế" }), "Ho kéo dài là gì?");
  await user.click(screen.getByRole("button", { name: "Gửi tin nhắn" }));
  await screen.findByText("Kết quả kiểm thử");
  expect(composerCount()).toBe(1);
  expect(document.querySelector(".chat-composer")).toBe(originalComposer);
  expect(document.querySelectorAll("#chat-question")).toHaveLength(1);
  await user.click(screen.getByRole("button", { name: "Cuộc trò chuyện mới", exact: true }));
  await waitFor(() => expect(screen.getByRole("textbox", { name: "Câu hỏi y tế" })).toHaveValue(""));
  expect(composerCount()).toBe(1);
});

it("hides the text composer during voice mode and restores one clean composer after closing", async () => {
  window.history.replaceState({}, "", "/chat");
  const user = userEvent.setup(); render(<StrictMode><App /></StrictMode>);
  await screen.findByRole("textbox", { name: "Câu hỏi y tế" });
  // Starting another session clears staged attachments without mounting a second composer.
  fireEvent.change(screen.getByTestId("medical-record-input"), { target: { files: [new File(["record"], "pending.txt", { type: "text/plain" })] } });
  expect(screen.getByText("pending.txt")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Cuộc trò chuyện mới", exact: true }));
  await waitFor(() => expect(screen.queryByText("pending.txt")).not.toBeInTheDocument());
  for (let index = 0; index < 3; index++) {
    await user.click(screen.getByRole("button", { name: "Trò chuyện bằng giọng nói" }));
    await screen.findByRole("dialog");
    expect(composerCount()).toBe(0);
    expect(document.querySelectorAll(".voice-dialog")).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "Kết thúc trò chuyện giọng nói" }));
    await screen.findByRole("textbox", { name: "Câu hỏi y tế" });
    expect(composerCount()).toBe(1);
    expect(document.querySelectorAll("#chat-question")).toHaveLength(1);
  }
  await user.click(screen.getByRole("button", { name: "Trò chuyện bằng giọng nói" }));
  await screen.findByRole("dialog");
  act(() => {
    window.history.replaceState({}, "", "/chat");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await screen.findByRole("textbox", { name: "Câu hỏi y tế" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(composerCount()).toBe(1);
});
