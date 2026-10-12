import { afterEach, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SourcesProvider, SourcesList } from "../src/components/chat/EvidenceSources";
import { KGQueryDetails } from "../src/components/chat/KGQueryDetails";
import type { ChatMessage, Conversation } from "../src/types";
import App from "../src/App";
import { conversationApi } from "../src/api/conversationApi";
import { chatApi } from "../src/api/chatApi";

afterEach(() => vi.restoreAllMocks());
function pending(): ChatMessage {
  return { id: "pending-kg", role: "assistant", content: "Vui lòng xác nhận tên.", createdAt: new Date().toISOString(),
    metadata: { route: "NEEDS_CLARIFICATION", kg_query: { mode: "one_hop" }, kg_clarification: {
      message: "Vui lòng xác nhận tên.", can_confirm: true,
      groups: [{ mention: "ABC", candidates: [
        { id: "D1", name: "Bệnh A", type: "Disease", matched_by: "alias" },
        { id: "D2", name: "Bệnh B", type: "Disease", matched_by: "alias" },
      ] }],
    } } };
}

it("requires an explicit choice and disables repeat submission while busy", async () => {
  const user = userEvent.setup(), confirm = vi.fn(), message = pending();
  const view = render(<KGQueryDetails message={message} busy={false} onConfirm={confirm} />);
  const submit = screen.getByRole("button", { name: "Xác nhận và truy vấn" });
  expect(submit).toBeDisabled();
  await user.selectOptions(screen.getByRole("combobox"), "D2");
  await user.click(submit);
  expect(confirm).toHaveBeenCalledWith(["D2"]);
  view.rerender(<KGQueryDetails message={message} busy onConfirm={confirm} />);
  expect(submit).toBeDisabled();
  expect(screen.getByRole("combobox")).toBeDisabled();
});

it("does not allow choices on a stale clarification", () => {
  render(<KGQueryDetails message={pending()} busy={false} />);
  expect(screen.getByRole("combobox")).toBeDisabled();
  expect(screen.getByRole("button")).toBeDisabled();
  expect(screen.getByText(/Lượt xác nhận này đã kết thúc/)).toBeInTheDocument();
});

it("shows numbered sources, plain evidence text and graph limits without executing source markup", async () => {
  const user = userEvent.setup();
  const message: ChatMessage = { ...pending(), metadata: { kg_query: { mode: "path", warnings: ["Đường liên kết không chứng minh nhân quả."] },
    sources: [{ doc_id: "DOC_TEST", evidence_id: "E1", text: "<img src=x onerror=alert(1)>" }] } };
  const { container } = render(<SourcesProvider sources={message.metadata?.sources}><KGQueryDetails message={message} busy={false} /><SourcesList/></SourcesProvider>);
  expect(screen.getByText("KG · Đường liên kết")).toBeInTheDocument();
  await user.click(screen.getByText("Nguồn tham khảo (1)"));
  expect(screen.queryByText("DOC_TEST")).not.toBeInTheDocument();
  expect(screen.queryByText("E1")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", {name:"Nguồn 1"}));
  expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeVisible();
  await user.click(screen.getByRole("button", {name:"Đóng nguồn"}));
  expect(container.querySelector("img")).toBeNull();
  await user.click(screen.getByText("Giới hạn dữ liệu"));
  expect(screen.getByText("Đường liên kết không chứng minh nhân quả.")).toBeVisible();
});

it("leaves legacy messages unchanged", () => {
  const { container } = render(<KGQueryDetails message={{ ...pending(), metadata: undefined }} busy={false} />);
  expect(container).toBeEmptyDOMElement();
});

it("restores pending KG choices from history and sends only the selected IDs tied to that message", async () => {
  const user = userEvent.setup();
  window.history.replaceState({}, "", "/chat/kg-conversation");
  const conversation: Conversation = { id: "kg-conversation", title: "Câu hỏi KG", createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(), messages: [pending()] };
  vi.spyOn(conversationApi, "getConversations").mockResolvedValue([conversation]);
  vi.spyOn(conversationApi, "getConversation").mockResolvedValue(conversation);
  const send = vi.spyOn(chatApi, "sendMessage").mockResolvedValue({ message: {
    id: "result-kg", role: "assistant", content: "Câu trả lời từ KG.", createdAt: new Date().toISOString(),
    metadata: { kg_confirmation_used: true, kg_query: { mode: "one_hop" }, sources: [{ doc_id: "D", evidence_id: "E", text: "Nguồn thử nghiệm" }] },
  } });
  render(<App />);
  const select = await screen.findByRole("combobox");
  await user.selectOptions(select, "D1");
  await user.click(screen.getByRole("button", { name: "Xác nhận và truy vấn" }));
  await screen.findByText("Câu trả lời từ KG.");
  expect(send).toHaveBeenCalledTimes(1);
  expect(send.mock.calls[0][0]).toMatchObject({ conversationId: "kg-conversation",
    kg_confirmation: { message_id: "pending-kg", entity_ids: ["D1"] }, message: { content: "Tôi xác nhận: Bệnh A." } });
  await waitFor(() => expect(select).toBeDisabled());
  expect(screen.getByText("Nguồn tham khảo (1)")).toBeInTheDocument();
});
