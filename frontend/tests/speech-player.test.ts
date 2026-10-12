import { afterEach, expect, it, vi } from "vitest";
import { voiceApi } from "../src/api/voiceApi";
import { SpeechPlayer } from "../src/components/voice/SpeechPlayer";
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });
function audioMock() {
  vi.useFakeTimers(); const epoch = Date.now();
  const starts: { at: number; duration: number; first: number }[] = [];
  const stopped = vi.fn();
  vi.stubGlobal("AudioContext", class {
    state = "running"; destination = {};
    get currentTime() { return (Date.now() - epoch)/1000; }
    resume = vi.fn().mockResolvedValue(undefined); close = vi.fn().mockResolvedValue(undefined);
    createBuffer(_channels: number, length: number, rate: number) {
      return { duration: length/rate, first: 0, copyToChannel(samples: Float32Array) { this.first = samples[0]; } };
    }
    createBufferSource() {
      return { buffer: null as { duration: number; first: number } | null, connect: vi.fn(), disconnect: vi.fn(),
        stop: stopped, onended: null, start(at: number) { starts.push({ at, duration: this.buffer!.duration, first: this.buffer!.first }); } };
    }
  }); return { starts, stopped };
}
function pcm(seconds: number, sample = 1000) {
  const audio = new Int16Array(Math.round(seconds*48000)); audio.fill(sample); return new Uint8Array(audio.buffer);
}
function pending(signal: AbortSignal) {
  return new Promise<void>(resolve => { if (signal.aborted) resolve(); else signal.addEventListener("abort", () => resolve(), { once: true }); });
}
it("prefetches two sentences, plays before synthesis ends and cancels the third", async () => {
  const { starts, stopped } = audioMock(); const started = vi.fn();
  let firstChunk!: (data: Uint8Array) => Promise<void>;
  const synthesis = vi.spyOn(voiceApi, "speakStream").mockImplementation(async (text, signal, onChunk) => {
    if (text === "Câu đầu.") firstChunk = onChunk; else await onChunk(pcm(1.2, 2000));
    await pending(signal);
  });
  const player = new SpeechPlayer(started, vi.fn(), { mode: "stream" });
  player.enqueue("Câu đầu."); player.enqueue("Câu hai."); player.enqueue("Câu ba.");
  await vi.advanceTimersByTimeAsync(100);
  expect(synthesis).toHaveBeenCalledTimes(2); expect(starts).toHaveLength(0);
  await firstChunk(pcm(1.2, 1000)); await vi.advanceTimersByTimeAsync(40);
  expect(started).toHaveBeenCalledOnce(); expect(starts.every(source => source.first === 1000/32768)).toBe(true);
  player.stop(); await vi.advanceTimersByTimeAsync(40); await player.finish();
  expect(synthesis).toHaveBeenCalledTimes(2); expect(stopped).toHaveBeenCalled();
});
it("buffers jitter and schedules adjacent PCM blocks without adding gaps", async () => {
  const { starts } = audioMock(); let push!: (data: Uint8Array) => Promise<void>;
  vi.spyOn(voiceApi, "speakStream").mockImplementation(async (_text, signal, onChunk) => { push = onChunk; await pending(signal); });
  const player = new SpeechPlayer(vi.fn(), vi.fn(), { mode: "stream" }); player.enqueue("Một câu.");
  await push(pcm(0.3)); await vi.advanceTimersByTimeAsync(200); expect(starts).toHaveLength(0);
  await push(pcm(0.8)); await vi.advanceTimersByTimeAsync(40); expect(starts.length).toBeGreaterThan(1);
  for (let i=1; i<starts.length; i++) expect(starts[i].at).toBeCloseTo(starts[i-1].at + starts[i-1].duration, 8);
  expect(player.diagnostics().underruns).toBe(0); player.stop(); await vi.advanceTimersByTimeAsync(40); await player.finish();
});
it("flushes short final sentences in order even when the second arrives first", async () => {
  const { starts } = audioMock(); let release!: () => void;
  vi.spyOn(voiceApi, "speakStream").mockImplementation(async (text, _signal, onChunk) => {
    if (text === "Đầu.") { await new Promise<void>(resolve => { release = resolve; }); await onChunk(pcm(0.06, 1000)); }
    else await onChunk(pcm(0.04, 2000));
  });
  const player = new SpeechPlayer(vi.fn(), vi.fn(), { mode: "stream" }); player.enqueue("Đầu."); player.enqueue("Sau.");
  const finished = player.finish(); await vi.advanceTimersByTimeAsync(100); expect(starts).toHaveLength(0);
  release(); await vi.advanceTimersByTimeAsync(400); await finished;
  expect(starts.map(item => item.first)).toEqual([1000/32768, 2000/32768]);
  expect(starts[1].at).toBeCloseTo(starts[0].at + 0.06, 8);
});
it("rebuffers a starved stream and reports the interruption", async () => {
  const { starts } = audioMock(); let push!: (data: Uint8Array) => Promise<void>;
  vi.spyOn(voiceApi, "speakStream").mockImplementation(async (_text, signal, onChunk) => { push=onChunk; await pending(signal); });
  const player = new SpeechPlayer(vi.fn(), vi.fn(), { startBufferMs: 100, rebufferMs: 300, mode: "stream" }); player.enqueue("Một câu.");
  await push(pcm(0.2)); await vi.advanceTimersByTimeAsync(500);
  const before = starts.length; await push(pcm(0.1)); await vi.advanceTimersByTimeAsync(100); expect(starts.length).toBe(before);
  await push(pcm(0.3)); await vi.advanceTimersByTimeAsync(40);
  expect(starts.length).toBeGreaterThan(before); expect(player.diagnostics().underruns).toBe(1);
  expect(player.diagnostics().gapMs).toBeGreaterThan(0); player.stop(); await vi.advanceTimersByTimeAsync(40); await player.finish();
});
it("bounds queued audio while producers outrun playback", async () => {
  audioMock();
  vi.spyOn(voiceApi, "speakStream").mockImplementation(async (_text, signal, onChunk) => { await onChunk(pcm(20)); await pending(signal); });
  const player = new SpeechPlayer(vi.fn(), vi.fn(), { mode: "stream" }); player.enqueue("Đầu."); player.enqueue("Sau.");
  await vi.advanceTimersByTimeAsync(100);
  expect(player.diagnostics().peakQueuedSeconds).toBeLessThanOrEqual(12.001); player.stop(); await vi.advanceTimersByTimeAsync(40); await player.finish();
});
it("rejects truncated PCM and aborts the other prefetch", async () => {
  audioMock(); const error = vi.fn(); let secondSignal!: AbortSignal;
  vi.spyOn(voiceApi, "speakStream").mockImplementation(async (text, signal, onChunk) => {
    if (text === "Lỗi.") await onChunk(new Uint8Array([1])); else { secondSignal = signal; await pending(signal); }
  });
  const player = new SpeechPlayer(vi.fn(), error); player.enqueue("Lỗi."); player.enqueue("Sau.");
  const assertion = expect(player.finish()).rejects.toThrow("inside a sample");
  await vi.advanceTimersByTimeAsync(50); await assertion;
  expect(error).toHaveBeenCalledOnce(); expect(secondSignal.aborted).toBe(true);
});

it("smooth mode waits for a complete sentence and plays it as one uninterrupted source", async () => {
  const { starts } = audioMock(); let push!: (data: Uint8Array) => Promise<void>; let complete!: () => void;
  vi.spyOn(voiceApi, "speakStream").mockImplementation(async (_text, _signal, onChunk) => {
    push = onChunk; await new Promise<void>(resolve => { complete = resolve; });
  });
  const player = new SpeechPlayer(vi.fn(), vi.fn()); player.enqueue("Mình giải thích ý chính trước nhé.");
  const finished = player.finish();
  await push(pcm(1)); await vi.advanceTimersByTimeAsync(1500); expect(starts).toHaveLength(0);
  await push(pcm(1)); complete(); await vi.advanceTimersByTimeAsync(40);
  expect(starts).toHaveLength(1); expect(starts[0].duration).toBe(2);
  await vi.advanceTimersByTimeAsync(2200); await finished;
  expect(player.diagnostics().underruns).toBe(0);
});

it("smooth mode joins complete sentences in order even when synthesis finishes out of order", async () => {
  const { starts } = audioMock(); let complete!: () => void;
  vi.spyOn(voiceApi, "speakStream").mockImplementation(async (text, _signal, onChunk) => {
    if (text === "Đầu.") await new Promise<void>(resolve => { complete = resolve; });
    await onChunk(pcm(0.5, text === "Đầu." ? 1000 : 2000));
  });
  const player = new SpeechPlayer(vi.fn(), vi.fn()); player.enqueue("Đầu."); player.enqueue("Sau.");
  const finished = player.finish(); await vi.advanceTimersByTimeAsync(100); expect(starts).toHaveLength(0);
  complete(); await vi.advanceTimersByTimeAsync(1200); await finished;
  expect(starts.map(s => s.first)).toEqual([1000/32768, 2000/32768]);
  expect(starts[1].at).toBeCloseTo(starts[0].at + 0.5, 8);
});

it("smooth mode rejects a corrupt tail before playing any of the sentence", async () => {
  const { starts } = audioMock();
  vi.spyOn(voiceApi, "speakStream").mockImplementation(async (_text, _signal, onChunk) => {
    await onChunk(pcm(1)); await onChunk(new Uint8Array([1]));
  });
  const player = new SpeechPlayer(vi.fn(), vi.fn()); player.enqueue("Câu lỗi.");
  const assertion = expect(player.finish()).rejects.toThrow("inside a sample");
  await vi.advanceTimersByTimeAsync(50); await assertion; expect(starts).toHaveLength(0);
});
