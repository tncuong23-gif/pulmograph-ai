import { expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../src/App";
import { conversationApi } from "../src/api/conversationApi";
import { chatApi } from "../src/api/chatApi";
import * as client from "../src/api/client";
import type { Conversation } from "../src/types";

it("restores a pending assessment and polls the answer after submission without classifying again", async () => {
  const user = userEvent.setup();
  window.history.replaceState({}, "", "/chat/assessment-conv");
  const c: Conversation = { id: "assessment-conv", title: "Kiểm thử khôi phục", createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(), messages: [], assessment: {
    id: "assessment-1", version: 1, status: "confirming", drafts: [{ id: "f1", display: "ho", fact_type: "symptom", presence: "present", timeframe: "current", experiencer: "patient", details: "", origin: "current_message" }], facts: [], warnings: [], graph_sync: "pending",
  } };
  let current = c;
  vi.spyOn(conversationApi, "getConversations").mockResolvedValue([c]);
  vi.spyOn(conversationApi, "getConversation").mockImplementation(async () => current);
  const send = vi.spyOn(chatApi, "sendMessage");
  const api = vi.spyOn(client, "apiRequest").mockImplementation(async (_path, init) => {
    const body = JSON.parse(init?.body as string);
    current = { ...current, assessment: { ...current.assessment!, version: current.assessment!.version + 1, status: body.action === "confirm" ? "ready" : "running", facts: body.facts || current.assessment!.facts } };
    return { conversation: current };
  });
  render(<App />);
  await screen.findByText("1. Xác nhận dữ kiện vừa khai");
  expect(screen.getByRole("textbox", { name: "Câu hỏi y tế" })).toBeDisabled();
  await user.click(screen.getByRole("checkbox", { name: /Tôi đã kiểm tra/ }));
  await user.click(screen.getByRole("button", { name: "Xác nhận dữ kiện vừa khai" }));
  await screen.findByText("4. Xác nhận gửi đánh giá");
  await user.click(screen.getByRole("checkbox", { name: /Tôi đã kiểm tra/ }));
  await user.click(screen.getByRole("button", { name: "Gửi đánh giá" }));
  await screen.findByText(/Đang xử lý dữ kiện đã xác nhận/);
  current = { ...current, assessment: { ...current.assessment!, status: "completed", graph_sync: "synced", version: 4 }, messages: [{ id: "answer", role: "assistant", content: "Kết quả sau khi khôi phục", createdAt: new Date().toISOString(), metadata: { route: "DIAGNOSTIC_ASSESSMENT" } }] };
  await screen.findByText("Kết quả sau khi khôi phục", {}, { timeout: 4000 });
  await waitFor(() => expect(screen.getByRole("textbox", { name: "Câu hỏi y tế" })).toBeEnabled());
  expect(send).not.toHaveBeenCalled();
  expect(api.mock.calls[0][0]).toBe("/api/v1/assessments/assessment-1/actions");
  expect(JSON.parse(api.mock.calls[0][1]!.body as string)).toMatchObject({ action: "confirm", version: 1, same_patient: true });
  expect(screen.queryByRole("button", { name: "Tạo lại câu trả lời" })).not.toBeInTheDocument();
});

it("restores history review and excludes old data before moving to the KG question", async () => {
  const user=userEvent.setup();window.history.replaceState({},"","/chat/review-history");
  const fact={id:"old",display:"chóng mặt",fact_type:"symptom" as const,presence:"present" as const,timeframe:"history" as const,experiencer:"patient" as const,details:"",origin:"patient_graph"};
  let current:Conversation={id:"review-history",title:"Review",createdAt:new Date().toISOString(),updatedAt:new Date().toISOString(),messages:[],assessment:{
    id:"a-history",version:2,status:"confirming_history",drafts:[],history_drafts:[fact],facts:[],warnings:[],graph_sync:"pending",workflow_version:2}};
  vi.spyOn(conversationApi,"getConversations").mockResolvedValue([current]);
  vi.spyOn(conversationApi,"getConversation").mockImplementation(async()=>current);
  const send=vi.spyOn(chatApi,"sendMessage");
  const api=vi.spyOn(client,"apiRequest").mockImplementation(async(_path,init)=>{
    const body=JSON.parse(init!.body as string);
    expect(body).toMatchObject({action:"confirm_history",reviewed:true,facts:[],version:2});
    current={...current,assessment:{...current.assessment!,version:3,status:"questioning",question_proposal:{question_id:"q",question_text:"Bạn có sốt không?",basis:[]}}};
    return {conversation:current};
  });
  render(<App/>);
  await screen.findByText("2. Kiểm tra dữ kiện Patient Graph");
  expect(screen.getByLabelText("Trạng thái 1")).toHaveValue("exclude");
  await user.click(screen.getByRole("button",{name:"Không dùng dữ kiện cũ, tiếp tục"}));
  await screen.findByText("3. Khai thác thông tin từ KG");
  expect(screen.getByRole("textbox",{name:"Câu hỏi y tế"})).toBeDisabled();
  expect(api).toHaveBeenCalledTimes(1);expect(send).not.toHaveBeenCalled();
});
