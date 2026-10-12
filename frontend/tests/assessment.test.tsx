import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AssessmentPanel } from "../src/components/chat/AssessmentPanel";
import type { Assessment } from "../src/types";

const base: Assessment = { id: "a", version: 1, status: "confirming", drafts: [], facts: [], warnings: [], graph_sync: "pending" };
const fact = { display: "Ho", fact_type: "symptom" as const, presence: "present" as const, timeframe: "history" as const, experiencer: "patient" as const, details: "3 ngày", origin: "patient_graph", id: "old-fact" };

describe("Diagnostic confirmation interface", () => {
  it("excludes old graph data until selected and requires explicit confirmation", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    render(<AssessmentPanel assessment={{ ...base, status:"confirming_history", history_drafts: [fact] }} busy={false} onAction={onAction} />);
    const submit = screen.getByRole("button", { name: "Xác nhận dữ kiện cũ đã chọn" });
    expect(submit).toBeDisabled();
    expect(screen.getByLabelText("Trạng thái 1")).toHaveValue("exclude");
    await user.selectOptions(screen.getByLabelText("Trạng thái 1"), "absent");
    expect(submit).toBeDisabled();
    await user.click(screen.getByRole("checkbox"));
    await user.click(submit);
    expect(onAction).toHaveBeenCalledWith({ action: "confirm_history", same_patient: true, reviewed:true, facts: [expect.objectContaining({ id: "old-fact", presence: "absent", timeframe: "history" })] });
    await user.type(screen.getByLabelText("Dữ kiện 1"), " mới");
    expect(screen.getByRole("checkbox")).not.toBeChecked();
  });
  it("keeps unknown distinct from no and allows skipping without asserting a fact", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    render(<AssessmentPanel assessment={{ ...base, status: "questioning", question_proposal: { question_id: "q1", question_text: "Câu hỏi thử", basis: [] } }} busy={false} onAction={onAction} />);
    expect(screen.getByRole("button", { name: "Không biết" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Bỏ qua" })).toBeEnabled();
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "Không biết" }));
    expect(onAction).toHaveBeenCalledWith({ action: "answer", question_id: "q1", answer: "unknown", reviewed: true });
  });
  it("requires final review and prevents edits while processing", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    const { rerender } = render(<AssessmentPanel assessment={{ ...base, status: "ready", facts: [fact] }} busy={false} onAction={onAction} />);
    expect(screen.getByRole("button", { name: "Gửi đánh giá" })).toBeDisabled();
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "Gửi đánh giá" }));
    expect(onAction).toHaveBeenCalledWith({ action: "diagnose", reviewed: true });
    rerender(<AssessmentPanel assessment={{ ...base, status: "running", facts: [fact] }} busy={false} onAction={onAction} />);
    expect(screen.getByRole("status")).toHaveTextContent("Đang xử lý");
    expect(screen.queryByRole("button", { name: "Hủy lượt đánh giá" })).not.toBeInTheDocument();
  });
});

it("shows only current declarations first and resets history selection on the next step", async () => {
  const user=userEvent.setup();const onAction=vi.fn();
  const current={...fact,id:"current",display:"ho khan",origin:"current_message",timeframe:"current" as const,details:""};
  const old={...fact,id:"old",display:"sốt",details:"",timeframe:"current" as const};
  const {rerender}=render(<AssessmentPanel assessment={{...base,workflow_version:2,drafts:[current],history_drafts:[old]}} busy={false} onAction={onAction}/>);
  expect(screen.getAllByLabelText(/Dữ kiện \d/)).toHaveLength(1);
  expect(screen.getByLabelText("Dữ kiện 1")).toHaveValue("ho khan");
  expect(screen.queryByDisplayValue("sốt")).not.toBeInTheDocument();
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button",{name:"Xác nhận dữ kiện vừa khai"}));
  expect(onAction).toHaveBeenLastCalledWith(expect.objectContaining({action:"confirm",facts:[expect.objectContaining({display:"ho khan"})]}));
  rerender(<AssessmentPanel assessment={{...base,version:2,status:"confirming_history",drafts:[current],history_drafts:[old],facts:[current]}} busy={false} onAction={onAction}/>);
  expect(screen.getByText("2. Kiểm tra dữ kiện Patient Graph")).toBeInTheDocument();
  expect(screen.getByLabelText("Dữ kiện 1")).toHaveValue("sốt");
  expect(screen.getByLabelText("Trạng thái 1")).toHaveValue("exclude");
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  expect(screen.queryByDisplayValue("ho khan")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button",{name:"Không dùng dữ kiện cũ, tiếp tục"}));
  expect(onAction).toHaveBeenLastCalledWith({action:"confirm_history",same_patient:true,reviewed:true,facts:[]});
});

it("uses numbered source cards for KG followups without showing document/evidence codes", async()=>{
 const user=userEvent.setup();
 render(<AssessmentPanel assessment={{...base,status:"questioning",question_proposal:{question_id:"q",question_text:"Câu hỏi từ KG",basis:[{evidence:[{doc_id:"DOC_PRIVATE",evidence_id:"EVID_PRIVATE",text:"Văn bản chứng minh cho câu hỏi thử nghiệm."}]}]}}} busy={false} onAction={()=>{}}/>);
 await user.click(screen.getByText("Nguồn tham khảo (1)"));
 expect(screen.queryByText("DOC_PRIVATE")).not.toBeInTheDocument();
 expect(screen.queryByText("EVID_PRIVATE")).not.toBeInTheDocument();
 await user.click(screen.getByRole("button",{name:"Nguồn 1"}));
 expect(screen.getByRole("dialog")).toHaveTextContent("Văn bản chứng minh");
});
