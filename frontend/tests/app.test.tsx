import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../src/App";
import { chatApi } from "../src/api/chatApi";
import { uploadApi } from "../src/api/uploadApi";
import { conversationApi } from "../src/api/conversationApi";
import { ApiError } from "../src/api/client";
import type { Attachment } from "../src/types";
const clinicalResult: Attachment = {id:"job", type:"medical_record", fileName:"record.txt", fileSize:4, mimeType:"text/plain",
  status:"processed", progress:100, analysisAnswer:"Đây là kết quả mô phỏng Clinical IE trong kiểm thử."};
beforeEach(() => {
  window.history.replaceState({}, "", "/chat");
  vi.spyOn(uploadApi, "analyzeClinical").mockImplementation(async () => {
    await new Promise(resolve => setTimeout(resolve, 80));
    return clinicalResult;
  });
});
const sent = () => screen.getByRole("button", { name: "Gửi tin nhắn" });
const question = () => screen.getByRole("textbox", { name: "Câu hỏi y tế" });
const ready = async () => {
  await waitFor(() =>
    expect(
      screen.getByText("Tìm hiểu về bệnh phổi tắc nghẽn"),
    ).toBeInTheDocument(),
  );
};
describe("Central medical chat workflow", () => {
  it("starts empty, selects a suggestion, sends, shows loading and a markdown response, accepts feedback and starts a fresh conversation", async () => {
    const user = userEvent.setup();
    render(<App />);
    await ready();
    expect(sent()).toBeDisabled();
    await user.click(
      screen.getByRole("button", {
        name: /TRIỆU CHỨNG.*Triệu chứng thường gặp/,
      }),
    );
    expect(question()).toHaveValue("Triệu chứng thường gặp của COPD là gì?");
    await user.click(sent());
    expect(screen.getByText("PulmoGraph AI đang trả lời")).toBeInTheDocument();
    expect(sent()).toBeDisabled();
    await screen.findByRole(
      "heading",
      { name: "Phiên trả lời minh họa" },
      { timeout: 4000 },
    );
    expect(screen.getByRole("table")).toBeInTheDocument();
    const feedback = screen.getByRole("button", {
      name: "Câu trả lời hữu ích",
    });
    await user.click(feedback);
    expect(feedback).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "Sao chép" }));
    expect(screen.getByRole("status")).toHaveTextContent("Đã sao chép");
    await user.click(
      screen.getByRole("button", { name: "Tạo lại câu trả lời" }),
    );
    expect(screen.getByText("PulmoGraph AI đang trả lời")).toBeInTheDocument();
    await waitFor(
      () =>
        expect(
          screen.queryByText("PulmoGraph AI đang trả lời"),
        ).not.toBeInTheDocument(),
      { timeout: 4000 },
    );
    expect(
      screen.getAllByRole("heading", { name: "Phiên trả lời minh họa" }),
    ).toHaveLength(1);
    await user.click(
      screen.getByRole("button", { name: "Cuộc trò chuyện mới", exact: true }),
    );
    expect(question()).toHaveValue("");
    expect(screen.getByText("Bắt đầu với một câu hỏi")).toBeInTheDocument();
  });
  it("waits for Send, clears the composer, shows typing and displays the record answer without chat classification", async () => {
    const send = vi.spyOn(chatApi, "sendMessage");
    let complete!: () => void;
    const upload = vi.spyOn(uploadApi, "analyzeClinical").mockImplementationOnce(() =>
      new Promise<Attachment>(resolve => { complete = () => resolve(clinicalResult); }));
    const user = userEvent.setup();
    render(<App />);
    await ready();
    fireEvent.change(screen.getByTestId("medical-record-input"), {
      target: { files: [new File(["test"], "demo-record.txt", { type: "text/plain" })] },
    });
    expect(question()).toBeDisabled();
    expect(sent()).toBeEnabled();
    expect(screen.getByText("Chờ gửi")).toBeInTheDocument();
    expect(upload).not.toHaveBeenCalled();
    await user.click(sent());
    expect(upload).toHaveBeenCalledTimes(1);
    expect(document.querySelector(".composer-area .attachment-card")).toBeNull();
    expect(screen.getByText("PulmoGraph AI đang trả lời")).toBeInTheDocument();
    expect(sent()).toBeDisabled();
    await act(async () => complete());
    await screen.findByText(/Đây là kết quả mô phỏng/, {}, { timeout: 5000 });
    expect(screen.queryByText("PulmoGraph AI đang trả lời")).not.toBeInTheDocument();
    expect(document.querySelector(".assistant-message .markdown-content")).toHaveTextContent("Clinical IE");
    expect(document.querySelector(".message-list .attachment-card")).toBeNull();
    expect(send).not.toHaveBeenCalled();
    expect(question()).toBeEnabled();
    await user.type(question(), "Triệu chứng thường gặp của COPD là gì?");
    await user.click(sent());
    expect(send).toHaveBeenCalledTimes(1);
  });
  it("rejects invalid files before upload, respects the attachment limit and removes pending files", async () => {
    const upload = vi.spyOn(uploadApi, "analyzeClinical");
    const user = userEvent.setup();
    render(<App />);
    await ready();
    fireEvent.change(screen.getByTestId("medical-record-input"), {
      target: {
        files: [
          new File(["x"], "bad.exe", { type: "application/octet-stream" }),
        ],
      },
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Định dạng file không được hỗ trợ",
    );
    expect(upload).not.toHaveBeenCalled();
    const records = Array.from(
      { length: 6 },
      (_, i) => new File(["demo"], `record-${i}.txt`, { type: "text/plain" }),
    );
    fireEvent.change(screen.getByTestId("medical-record-input"), {
      target: { files: records },
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Mỗi lượt chỉ nhận một TXT");
    expect(screen.getAllByRole("article")).toHaveLength(1);
    await user.click(
      screen.getByRole("button", { name: "Xóa tệp record-0.txt" }),
    );
    expect(screen.queryByText("record-0.txt")).not.toBeInTheDocument();
    expect(screen.queryAllByRole("article")).toHaveLength(0);
  });
  it("retries a failed record upload without duplicating the user message or calling chat", async () => {
    const user = userEvent.setup();
    const send = vi.spyOn(chatApi, "sendMessage");
    const upload = vi.spyOn(uploadApi, "analyzeClinical").mockRejectedValueOnce(
      new Error("Không thể tải file lên máy chủ."),
    );
    render(<App />);
    await ready();
    fireEvent.change(screen.getByTestId("medical-record-input"), {
      target: { files: [new File(["test"], "retry.txt", { type: "text/plain" })] },
    });
    expect(upload).not.toHaveBeenCalled();
    await user.click(sent());
    await screen.findByText("Không thể tải file lên máy chủ.");
    expect(screen.queryByText("PulmoGraph AI đang trả lời")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Thử lại", exact: true }));
    await screen.findByText(/Đây là kết quả mô phỏng/, {}, { timeout: 5000 });
    expect(upload).toHaveBeenCalledTimes(2);
    expect(document.querySelectorAll(".user-message")).toHaveLength(1);
    expect(send).not.toHaveBeenCalled();
  });
  it.each(["text", "xray", "text_xray", "typed_text_xray"])("auto-detects clinical %s from attachments without chat classification", async kind => {
    const user=userEvent.setup();
    const send=vi.spyOn(chatApi,"sendMessage");
    const upload=vi.spyOn(uploadApi,"analyzeClinical");
    render(<App />);await ready();
    expect(screen.queryByRole("checkbox",{name:"Phân tích văn bản bệnh án"})).not.toBeInTheDocument();
    if(kind==="typed_text_xray")await user.type(question(),"Ho, không sốt.");
    if(kind==="text" || kind==="text_xray")fireEvent.change(screen.getByTestId("medical-record-input"),{target:{files:[new File(["Ho, không sốt."],"record.txt",{type:"text/plain"})]}});
    if(kind!=="text")fireEvent.change(screen.getByTestId("xray-input"),{target:{files:[new File(["image"],"x.png",{type:"image/png"})]}});
    expect(upload).not.toHaveBeenCalled();
    expect(screen.queryByRole("checkbox",{name:/văn bản và ảnh thuộc cùng một ca/})).not.toBeInTheDocument();
    expect(sent()).toBeEnabled();
    await user.click(sent());
    await screen.findByText(/Đây là kết quả mô phỏng/);
    expect(upload).toHaveBeenCalledTimes(1);
    expect(upload.mock.calls[0][0]).toHaveLength(kind.includes("xray") ? kind==="text_xray"?2:1 : 1);
    expect(upload.mock.calls[0][1]).toBe(kind==="typed_text_xray"?"Ho, không sốt.":"");
    expect(send).not.toHaveBeenCalled();
    expect(document.querySelectorAll(".user-message")).toHaveLength(1);
  });
  it("shows a network/session error and successfully retries without duplicating the user message", async () => {
    vi.spyOn(chatApi, "sendMessage").mockRejectedValueOnce(
      new ApiError("Phiên làm việc đã hết hạn.", 401),
    );
    const user = userEvent.setup();
    render(<App />);
    await ready();
    await user.type(question(), "Kiểm thử lỗi phiên");
    await user.click(sent());
    await screen.findByRole("alert");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Phiên làm việc đã hết hạn",
    );
    await user.click(
      screen.getByRole("button", { name: "Thử lại", exact: true }),
    );
    await screen.findByRole(
      "heading",
      { name: "Phiên trả lời minh họa" },
      { timeout: 4000 },
    );
    expect(document.querySelectorAll(".user-message")).toHaveLength(1);
  });
  it("loads history, renames a conversation, cancels deletion and confirms deletion", async () => {
    const user = userEvent.setup();
    render(<App />);
    await ready();
    await user.click(
      screen.getByRole("link", { name: /Tìm hiểu về bệnh phổi tắc nghẽn/ }),
    );
    await screen.findByRole(
      "heading",
      { name: "Phiên trả lời minh họa" },
      { timeout: 4000 },
    );
    await user.click(
      screen.getByRole("button", {
        name: "Tùy chọn: Tìm hiểu về bệnh phổi tắc nghẽn",
      }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Đổi tên" }));
    await user.clear(
      screen.getByRole("textbox", { name: "Tên cuộc trò chuyện" }),
    );
    await user.type(
      screen.getByRole("textbox", { name: "Tên cuộc trò chuyện" }),
      "Hội thoại kiểm thử",
    );
    await user.click(screen.getByRole("button", { name: "Lưu thay đổi" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(
      screen.getByRole("link", { name: /Hội thoại kiểm thử/ }),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Tùy chọn: Hội thoại kiểm thử" }),
    );
    await user.click(
      screen.getByRole("menuitem", { name: "Xóa", exact: true }),
    );
    await user.click(screen.getByRole("button", { name: "Hủy" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Tùy chọn: Hội thoại kiểm thử" }),
    );
    await user.click(
      screen.getByRole("menuitem", { name: "Xóa", exact: true }),
    );
    await user.click(screen.getByRole("button", { name: "Xóa", exact: true }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("link", { name: /Hội thoại kiểm thử/ }),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getByText("Bắt đầu với một câu hỏi")).toBeInTheDocument();
  });
});
describe("Settings and recoverable route errors", () => {
  it("toggles dark/light, saves only the preference and opens/closes the mobile drawer", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getAllByRole("link", { name: "Cài đặt" })[0]);
    await user.click(screen.getByRole("button", { name: "Tối", exact: true }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem("medical-ai-theme")).toBe("dark");
    expect(localStorage.length).toBe(1);
    await user.click(screen.getByRole("button", { name: "Sáng", exact: true }));
    expect(document.documentElement.dataset.theme).toBe("light");
    await user.click(screen.getByRole("button", { name: "Mở menu" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Đóng menu" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
  it("recovers from a conversation API failure without crashing", async () => {
    window.history.replaceState({}, "", "/chat/unavailable");
    vi.spyOn(conversationApi, "getConversation").mockRejectedValue(
      new Error("Không thể kết nối tới máy chủ."),
    );
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("alert");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Không thể kết nối tới máy chủ",
    );
    await user.click(
      screen.getByRole("button", { name: "Tạo cuộc trò chuyện mới" }),
    );
    expect(question()).toBeInTheDocument();
  });
  it("keeps Shift+Enter as a newline and uses Enter to send", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.type(question(), "Dòng một");
    await user.keyboard("{Shift>}{Enter}{/Shift}");
    await user.type(question(), "Dòng hai");
    expect(question()).toHaveValue("Dòng một\nDòng hai");
    await user.keyboard("{Enter}");
    expect(screen.getByText("PulmoGraph AI đang trả lời")).toBeInTheDocument();
    await screen.findByRole(
      "heading",
      { name: "Phiên trả lời minh họa" },
      { timeout: 4000 },
    );
  });
});
describe("Optional WebMCP draft tool", () => {
  it("stages a valid draft, rejects invalid data and unregisters on unmount", async () => {
    type Tool = { name: string; execute: (input: unknown) => Promise<unknown> };
    let registered: Tool | undefined;
    let signal: AbortSignal | undefined;
    Object.defineProperty(document, "modelContext", {
      configurable: true,
      value: {
        registerTool: (tool: Tool, options: { signal: AbortSignal }) => {
          registered = tool;
          signal = options.signal;
        },
      },
    });
    const view = render(<App />);
    expect(registered?.name).toBe("stage_medical_question");
    await act(async () => {
      expect(
        await registered!.execute({ question: "Câu hỏi đã soạn" }),
      ).toEqual({ status: "draft_ready", sent: false });
    });
    expect(question()).toHaveValue("Câu hỏi đã soạn");
    expect(
      screen.queryByText("PulmoGraph AI đang trả lời"),
    ).not.toBeInTheDocument();
    await expect(registered!.execute({ question: "" })).rejects.toThrow();
    expect(question()).toHaveValue("Câu hỏi đã soạn");
    view.unmount();
    expect(signal?.aborted).toBe(true);
    Object.defineProperty(document, "modelContext", {
      configurable: true,
      value: undefined,
    });
  });
});

describe("PulmoGraph branding and voice composer", () => {
  it("uses the user-provided logo, the pulmonary-data title, and keeps the voice action inside the input bar", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "Trợ lý ảo truy vấn thông tin từ dữ liệu bệnh phổi" });
    expect(screen.getByRole("heading", { name: "Trợ lý ảo truy vấn thông tin từ dữ liệu bệnh phổi" })).toBeInTheDocument();
    expect(screen.getByText("PulmoGraph AI")).toBeInTheDocument();
    expect(document.querySelector(".brand-mark img")).toHaveAttribute("src", "/favicon.svg");
    expect(document.querySelector(".voice-launch")).toBeNull();
    const voice = screen.getByRole("button", { name: "Trò chuyện bằng giọng nói" });
    expect(voice.closest(".chat-composer")).not.toBeNull();
    expect(screen.queryByText("Chưa kết nối")).not.toBeInTheDocument();
  });
});
