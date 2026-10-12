import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { VoiceAssistant } from "../src/components/voice/VoiceAssistant";
import { ChatProvider } from "../src/context/ChatContext";
import { voiceApi } from "../src/api/voiceApi";

let stopTrack: ReturnType<typeof vi.fn>;
let audioPlayer: { play: ReturnType<typeof vi.fn>; pause: ReturnType<typeof vi.fn>; onended: (() => void) | null; onerror: (() => void) | null };
class Recorder {
  static isTypeSupported() { return true; }
  state = "inactive";
  mimeType = "audio/webm";
  onstop: (() => void) | null = null;
  onerror: (() => void) | null = null;
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  start() { this.state = "recording"; }
  stop() { this.state = "inactive"; this.ondataavailable?.({ data: new Blob(["audio"]) }); this.onstop?.(); }
}
function Harness() {
  const [open, setOpen] = useState(true);
  return <ChatProvider>{open && <VoiceAssistant conversationId="voice-test" onClose={() => setOpen(false)} />}</ChatProvider>;
}
beforeEach(() => {
  stopTrack = vi.fn();
  vi.stubGlobal("isSecureContext", true);
  vi.stubGlobal("MediaRecorder", Recorder);
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: stopTrack }] }) } });
  audioPlayer = { play: vi.fn().mockResolvedValue(undefined), pause: vi.fn(), onended: null, onerror: null };
  vi.stubGlobal("Audio", function () { return audioPlayer; });
  URL.createObjectURL = vi.fn().mockReturnValue("blob:voice");
  URL.revokeObjectURL = vi.fn();
  vi.spyOn(voiceApi, "config").mockResolvedValue({ stt_installed: true, tts_installed: true, external_tts: true, max_seconds: 90 });
  vi.spyOn(voiceApi, "transcribe").mockResolvedValue({ transcript: "Tôi không sốt, SpO2 92%", warnings: ["Có đoạn chưa chắc chắn, hãy kiểm tra lời nói."] });
  vi.spyOn(voiceApi, "speak").mockResolvedValue(new Blob(["mp3"]));
  vi.spyOn(voiceApi, "turn").mockResolvedValue({ conversation: { id: "voice-test", title: "Giọng nói", createdAt: "now", updatedAt: "now", messages: [] }, message: null, display_text: "Đã nhận dữ kiện.", spoken_text: "Hãy kiểm tra dữ kiện đã nhận.", conversation_action: "answer", expects_reply: true, has_more: false });
});
describe("Voice assistant", () => {
  it("keeps regional speech until the user accepts the spelling suggestion", async () => {
    vi.mocked(voiceApi.transcribe).mockResolvedValue({ transcript: "Tui hổng sốt, SpO2 92.5%", suggested_transcript: "Tôi không sốt, SpO2 92.5%" });
    const user = userEvent.setup(); render(<Harness />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Bắt đầu nghe" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Bắt đầu nghe" }));
    await user.click(screen.getByRole("button", { name: "Kết thúc lượt nói" }));
    await screen.findByDisplayValue("Tui hổng sốt, SpO2 92.5%");
    expect(voiceApi.turn).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Dùng cách viết này" }));
    expect(screen.getByDisplayValue("Tôi không sốt, SpO2 92.5%")).toBeInTheDocument();
    expect(voiceApi.turn).not.toHaveBeenCalled();
  });
  it("retries recognition using the same recording and preserves text when retry fails", async () => {
    const user = userEvent.setup(); render(<Harness />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Bắt đầu nghe" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Bắt đầu nghe" }));
    await user.click(screen.getByRole("button", { name: "Kết thúc lượt nói" }));
    await screen.findByDisplayValue("Tôi không sốt, SpO2 92%");
    const recording = vi.mocked(voiceApi.transcribe).mock.calls[0][0];
    vi.mocked(voiceApi.transcribe).mockRejectedValueOnce(new Error("Nhận dạng lại thất bại"));
    await user.click(screen.getByRole("button", { name: "Nhận dạng lại kỹ hơn" }));
    await screen.findByText("Nhận dạng lại thất bại");
    expect(voiceApi.transcribe).toHaveBeenLastCalledWith(recording, expect.any(AbortSignal), "careful");
    expect(screen.getByDisplayValue("Tôi không sốt, SpO2 92%")).toBeInTheDocument();
    expect(voiceApi.turn).not.toHaveBeenCalled();
  });
  it("only submits reviewed speech, releases the microphone before playback, and cleans audio on close", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Bắt đầu nghe" })).toBeEnabled());
    expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Bắt đầu nghe" }));
    await waitFor(() => expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledOnce());
    await user.click(screen.getByRole("button", { name: "Kết thúc lượt nói" }));
    await screen.findByDisplayValue("Tôi không sốt, SpO2 92%");
    expect(voiceApi.turn).not.toHaveBeenCalled();
    expect(screen.getByText("Có đoạn chưa chắc chắn, hãy kiểm tra lời nói.")).toBeInTheDocument();
    expect(stopTrack).toHaveBeenCalledOnce();
    await user.click(screen.getByRole("button", { name: "Xác nhận lời nói và gửi" }));
    await waitFor(() => expect(audioPlayer.play).toHaveBeenCalledOnce());
    expect(voiceApi.turn).toHaveBeenCalledWith("voice-test", "Tôi không sốt, SpO2 92%", expect.any(String), undefined, expect.any(AbortSignal));
    await user.click(screen.getByRole("button", { name: "Kết thúc trò chuyện giọng nói" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(audioPlayer.pause).toHaveBeenCalled();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:voice");
  });
  it("keeps spoken text visible if TTS fails", async () => {
    vi.mocked(voiceApi.speak).mockRejectedValue(new Error("TTS đang ngoại tuyến"));
    const user = userEvent.setup(); render(<Harness />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Bắt đầu nghe" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Bắt đầu nghe" }));
    await act(async () => {});
    await user.click(screen.getByRole("button", { name: "Kết thúc lượt nói" }));
    await screen.findByDisplayValue("Tôi không sốt, SpO2 92%");
    await user.click(screen.getByRole("button", { name: "Xác nhận lời nói và gửi" }));
    await screen.findByText("TTS đang ngoại tuyến");
    expect(screen.getByText("Hãy kiểm tra dữ kiện đã nhận.")).toBeInTheDocument();
  });
  it("stops recording without sending audio when the dialog closes", async () => {
    const user = userEvent.setup(); render(<Harness />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Bắt đầu nghe" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Bắt đầu nghe" }));
    await act(async () => {});
    await user.click(screen.getByRole("button", { name: "Kết thúc trò chuyện giọng nói" }));
    expect(stopTrack).toHaveBeenCalledOnce();
    expect(voiceApi.transcribe).not.toHaveBeenCalled();
  });
  it("starts sentence synthesis before the streamed reply finishes and keeps text after audio failure", async () => {
    vi.mocked(voiceApi.config).mockResolvedValue({ stt_installed: true, tts_installed: true, external_tts: false, max_seconds: 90, streaming: true });
    const close = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("AudioContext", class {
      state = "running";
      resume = vi.fn().mockResolvedValue(undefined);
      close = close;
    });
    vi.spyOn(voiceApi, "speakStream").mockRejectedValue(new Error("VieNeu chưa sẵn sàng"));
    let finish!: () => void;
    const final = vi.mocked(voiceApi.turn).getMockImplementation()!;
    vi.spyOn(voiceApi, "turnStream").mockImplementation(async (...args) => {
      args[5]("Lời nói đầu tiên.");
      await new Promise<void>(resolve => { finish = resolve; });
      const reply = await final(...args.slice(0, 5) as Parameters<typeof voiceApi.turn>);
      return { ...reply, spoken_text: "Lời nói đầu tiên.", speech_chunks: ["Lời nói đầu tiên."] };
    });
    const user = userEvent.setup(); render(<Harness />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Bắt đầu nghe" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Bắt đầu nghe" }));
    await user.click(screen.getByRole("button", { name: "Kết thúc lượt nói" }));
    await screen.findByDisplayValue("Tôi không sốt, SpO2 92%");
    await user.click(screen.getByRole("button", { name: "Xác nhận lời nói và gửi" }));
    await waitFor(() => expect(voiceApi.speakStream).toHaveBeenCalledOnce());
    expect(screen.getByText("Lời nói đầu tiên.")).toBeInTheDocument();
    await act(async () => { finish(); });
    await screen.findByText("VieNeu chưa sẵn sàng");
    await waitFor(() => expect(screen.getByRole("button", { name: "Phát lại" })).toBeEnabled());
    expect(voiceApi.turn).not.toHaveBeenCalled();
    expect(close).toHaveBeenCalled();
  });
});
