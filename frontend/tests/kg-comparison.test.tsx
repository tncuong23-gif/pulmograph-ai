import { afterEach, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { KGQueryDetails } from "../src/components/chat/KGQueryDetails";
import type { ChatMessage, Conversation, KGComparison } from "../src/types";
import App from "../src/App";
import { conversationApi } from "../src/api/conversationApi";

afterEach(() => vi.restoreAllMocks());

function fixture(): KGComparison {
  const left = { id: "D1", name: "Bệnh A thử", type: "Disease" };
  const right = { id: "D2", name: "Bệnh B thử", type: "Disease" };
  const feature = { id: "S1", name: "Dấu hiệu chung thử", type: "Symptom" };
  const extra = { id: "S2", name: "Dấu hiệu khác thử", type: "Symptom" };
  return {
    mode: "compare", entities: [left, right], complete: false, truncated: false,
    notice: "Chưa tìm thấy ở một bên không có nghĩa bên đó không có đặc điểm này.",
    criteria: [{ id: "symptom", label: "Triệu chứng" }],
    rows: [
      { criterion: "symptom", criterion_label: "Triệu chứng", feature, predicate: "HAS_SYMPTOM", direction: "out",
        classification: "common", label: "Ghi nhận tương ứng ở cả hai", cells: [
          { entity_id: "D1", status: "recorded", fact_indices: [0] },
          { entity_id: "D2", status: "recorded", fact_indices: [1] }] },
      { criterion: "symptom", criterion_label: "Triệu chứng", feature: extra, predicate: "HAS_SYMPTOM", direction: "out",
        classification: "left_only", label: "Mới tìm thấy ở bên trái", cells: [
          { entity_id: "D1", status: "recorded", fact_indices: [2] },
          { entity_id: "D2", status: "not_found_in_retrieved_data", fact_indices: [] }] },
    ],
    facts: [left, right, left].map((subject, index) => ({ subject, predicate: "HAS_SYMPTOM", object: index === 2 ? extra : feature,
      doc_ids: ["DOC_" + index], evidence: [{ doc_id: "DOC_" + index, evidence_id: "E" + index, text: "Bằng chứng thử " + index }],
      assertions: [{ document_id: "DOC_" + index, evidence_ids: ["E" + index], properties: {}, properties_valid: true }],
    })),
  };
}
function message(comparison = fixture()): ChatMessage {
  return { id: "comparison-test", role: "assistant", createdAt: "2026-10-11T00:00:00Z", content: "Kết quả đối chiếu thử.",
    metadata: { kg_query: { mode: comparison.mode }, kg_comparison: comparison } };
}

it("renders the two named sides and unknown cells without claiming absence", () => {
  render(<KGQueryDetails message={message()} busy={false} />);
  expect(screen.getByRole("columnheader", { name: "Bệnh A thử" })).toBeVisible();
  expect(screen.getByRole("columnheader", { name: "Bệnh B thử" })).toBeVisible();
  expect(screen.getByText("Chưa tìm thấy trong dữ liệu truy xuất")).toBeVisible();
  expect(screen.getByText(/không có nghĩa bên đó/)).toBeVisible();
  expect(screen.getByRole("region", { name: /có thể cuộn ngang/ })).toHaveAttribute("tabindex", "0");
});

it("filters common and differing rows while keeping the missing-data notice", async () => {
  const user = userEvent.setup();
  render(<KGQueryDetails message={message()} busy={false} />);
  await user.click(screen.getByRole("button", { name: "Điểm chung", exact: true }));
  expect(screen.getByText("Dấu hiệu chung thử")).toBeVisible();
  expect(screen.queryByText("Dấu hiệu khác thử")).toBeNull();
  await user.click(screen.getByRole("button", { name: "Điểm khác / cần kiểm tra" }));
  expect(screen.getByText("Dấu hiệu khác thử")).toBeVisible();
  expect(screen.queryByText("Dấu hiệu chung thử")).toBeNull();
  expect(screen.getByText(/không có nghĩa bên đó/)).toBeVisible();
});

it("shows each side's own evidence and negation before source details are opened", async () => {
  const user = userEvent.setup(), comparison = fixture();
  comparison.facts[0].assertions[0].properties = { negated: true, population: "Nhóm thử" };
  comparison.rows[0].classification = "assertion_difference";
  comparison.rows[0].label = "Thuộc tính nguồn khác nhau";
  render(<KGQueryDetails message={message(comparison)} busy={false} />);
  expect(screen.getByText("Có phủ định trong nguồn")).toBeVisible();
  const row = screen.getByRole("rowheader", { name: /Dấu hiệu chung thử/ }).closest("tr")!;
  const cells = within(row).getAllByRole("cell");
  await user.click(within(cells[0]).getByText("Điều kiện và nguồn"));
  expect(within(cells[0]).queryByText("DOC_0")).not.toBeInTheDocument();
  expect(within(cells[0]).getByText("Bằng chứng thử 0")).toBeVisible();
  expect(within(cells[0]).getByText("Phủ định")).toBeVisible();
  expect(within(cells[0]).getByText("Nhóm thử")).toBeVisible();
  expect(within(cells[0]).getByText("Bằng chứng thử 0")).toBeVisible();
  expect(within(cells[0]).queryByText("Bằng chứng thử 1")).toBeNull();
});

it("keeps source strings as escaped text", async () => {
  const comparison = fixture(), user = userEvent.setup();
  comparison.facts[0].evidence[0].text = "<img src=x onerror=alert(1)>";
  comparison.facts[0].assertions[0].properties = { condition: "<script>bad()</script>" };
  const { container } = render(<KGQueryDetails message={message(comparison)} busy={false} />);
  await user.click(screen.getAllByText("Điều kiện và nguồn")[0]);
  expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeVisible();
  expect(screen.getByText("<script>bad()</script>")).toBeVisible();
  expect(container.querySelector("img,script")).toBeNull();
});

it("reports an empty or limited comparison without asserting equivalence", () => {
  const comparison = fixture();
  comparison.mode = "common"; comparison.rows = []; comparison.truncated = true;
  render(<KGQueryDetails message={message(comparison)} busy={false} />);
  expect(screen.getByText(/bảng có thể chưa đầy đủ/)).toBeVisible();
  expect(screen.getByText(/không khẳng định có hay không có điểm chung/)).toBeVisible();
  expect(screen.queryByRole("table")).toBeNull();
});

it("restores the comparison table from conversation history", async () => {
  window.history.replaceState({}, "", "/chat/comparison-history");
  const conversation: Conversation = { id: "comparison-history", title: "Đối chiếu", createdAt: "2026-10-11T00:00:00Z",
    updatedAt: "2026-10-11T00:00:00Z", messages: [message()] };
  vi.spyOn(conversationApi, "getConversations").mockResolvedValue([conversation]);
  vi.spyOn(conversationApi, "getConversation").mockResolvedValue(conversation);
  render(<App />);
  expect(await screen.findByRole("table")).toBeVisible();
  expect(screen.getByText("KG · So sánh")).toBeVisible();
});
