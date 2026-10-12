import { voiceApi } from "../../api/voiceApi";

export function speechSentences(text: string): string[] {
  const parts = text.split(/(?<=[.!?])\s+(?=[A-ZÀ-ỸĐ“"])/u).map(p => p.trim()).filter(Boolean);
  const result: string[] = [];
  for (let part of parts) {
    while (part.length > 600) {
      // Whitespace boundaries preserve decimals, units and names inside each phrase.
      const space = part.lastIndexOf(" ", 600);
      const cut = space > 0 ? space : 600;
      result.push(part.slice(0, cut)); part = part.slice(cut).trim();
    }
    if (part) result.push(part);
  }
  return result;
}

export class PCMDecoder {
  private tail: number | null = null;
  decode(chunk: Uint8Array): Float32Array {
    const bytes = new Uint8Array(chunk.length + (this.tail === null ? 0 : 1));
    if (this.tail !== null) { bytes[0] = this.tail; bytes.set(chunk, 1); }
    else bytes.set(chunk);
    const length = bytes.length - bytes.length % 2;
    this.tail = bytes.length % 2 ? bytes[bytes.length - 1] : null;
    const view = new DataView(bytes.buffer);
    const samples = new Float32Array(length / 2);
    for (let i = 0; i < samples.length; i++) samples[i] = view.getInt16(i*2, true)/32768;
    return samples;
  }
  finish() { if (this.tail !== null) throw new Error("PCM stream ended inside a sample"); }
}

interface SpeechJob { text: string; buffers: Float32Array[]; seconds: number; done: boolean }
export interface PlaybackMetrics { audioSeconds: number; underruns: number; gapMs: number; peakQueuedSeconds: number }
function bufferMs(value: string | undefined, fallback: number) {
  const parsed = value?.trim() ? Number(value) : fallback;
  return Number.isFinite(parsed) ? Math.min(3000, Math.max(0, parsed)) : fallback;
}

/** Fetch at most two sentences ahead of the playback head; schedule on the audio clock. */
export class SpeechPlayer {
  private context: AudioContext;
  private controller = new AbortController();
  private nextTime = 0;
  private sources = new Set<AudioBufferSourceNode>();
  private jobs: SpeechJob[] = [];
  private head = 0;
  private fetchCursor = 0;
  private inputDone = false;
  private failure: unknown = null;
  private started = false;
  private bufferingSince: number | null = null;
  private consumer: Promise<void>;
  private startBuffer: number;
  private rebuffer: number;
  private mode: "smooth" | "stream";
  private metrics: PlaybackMetrics = { audioSeconds: 0, underruns: 0, gapMs: 0, peakQueuedSeconds: 0 };
  constructor(private onStart: () => void, private onError: (error: unknown) => void,
    options: { startBufferMs?: number; rebufferMs?: number; mode?: "smooth" | "stream" } = {}) {
    this.context = new AudioContext();
    this.mode = options.mode ?? (import.meta.env.VITE_VOICE_PLAYBACK_MODE === "stream" ? "stream" : "smooth");
    this.startBuffer = bufferMs(String(options.startBufferMs ?? import.meta.env.VITE_VOICE_START_BUFFER_MS ?? 1000), 1000)/1000;
    this.rebuffer = bufferMs(String(options.rebufferMs ?? import.meta.env.VITE_VOICE_REBUFFER_MS ?? 800), 800)/1000;
    // Resume during the click gesture, not after the first network response.
    this.consumer = this.consume(this.context.resume()).catch(error => this.fail(error));
  }
  enqueue(text: string) {
    if (this.controller.signal.aborted || this.inputDone) return;
    for (const part of speechSentences(text)) this.jobs.push({ text: part, buffers: [], seconds: 0, done: false });
    this.dispatch();
  }
  private dispatch() {
    while (!this.controller.signal.aborted && this.fetchCursor < this.jobs.length && this.fetchCursor < this.head + 2) {
      const job = this.jobs[this.fetchCursor++];
      void this.fetch(job).catch(error => this.fail(error));
    }
  }
  private async fetch(job: SpeechJob) {
    const decoder = new PCMDecoder();
    let received = 0;
    await voiceApi.speakStream(job.text, this.controller.signal, async chunk => {
      const samples = decoder.decode(chunk);
      received += samples.length;
      if (received > 48000 * 90) throw new Error("Âm thanh một câu vượt giới hạn. Hãy thử lại với câu trả lời ngắn hơn.");
      // Bounded six-second queue per sentence, separate from scheduled playback.
      for (let i = 0; i < samples.length; i += 5760) {
        const piece = samples.slice(i, i + 5760);
        while (this.mode === "stream" && !this.controller.signal.aborted && job.seconds + piece.length/48000 > 6) await this.pause();
        if (this.controller.signal.aborted) return;
        job.buffers.push(piece); job.seconds += piece.length/48000;
        this.metrics.peakQueuedSeconds = Math.max(this.metrics.peakQueuedSeconds,
          this.jobs.slice(this.head, this.head + 2).reduce((sum, item) => sum + item.seconds, 0));
      }
    });
    if (this.controller.signal.aborted) return;
    decoder.finish(); job.done = true;
  }
  private available() {
    let total = 0;
    for (let i = this.head; i < this.jobs.length; i++) {
      total += this.jobs[i].seconds;
      if (!this.jobs[i].done) break;
    }
    return total;
  }
  private async consume(ready: Promise<void>) {
    await ready;
    while (!this.controller.signal.aborted) {
      const job = this.jobs[this.head];
      if (!job) {
        if (this.inputDone) break;
        await this.pause(); continue;
      }
      if (job.done && !job.buffers.length) { this.head++; this.dispatch(); continue; }
      if (this.mode === "smooth") {
        // A complete sentence is a single Web Audio source: a slow producer or
        // delayed JavaScript callback cannot interrupt it halfway through.
        if (!job.done || this.nextTime - this.context.currentTime > 12) { await this.pause(); continue; }
        const length = job.buffers.reduce((sum, part) => sum + part.length, 0);
        const samples = new Float32Array(length);
        let offset = 0;
        for (const part of job.buffers) { samples.set(part, offset); offset += part.length; }
        job.buffers = [samples];
      }
      if (!job.buffers.length || (this.mode === "stream" && this.nextTime - this.context.currentTime > 1.5)) { await this.pause(); continue; }
      const now = this.context.currentTime;
      if (!this.started || this.nextTime <= now) {
        this.bufferingSince ??= now;
        const completeTail = this.jobs.slice(this.head).every(item => item.done);
        const target = this.mode === "smooth" ? 0 : this.started ? this.rebuffer : this.startBuffer;
        if (this.available() < target && !completeTail && now - this.bufferingSince < 2) { await this.pause(); continue; }
        if (this.started) {
          this.metrics.underruns++;
          this.metrics.gapMs += Math.max(0, now - this.nextTime)*1000;
        }
        this.nextTime = now + 0.04;
        this.bufferingSince = null;
      }
      const samples = job.buffers.shift()!;
      job.seconds = Math.max(0, job.seconds - samples.length/48000);
      const buffer = this.context.createBuffer(1, samples.length, 48000);
      buffer.copyToChannel(new Float32Array(samples), 0);
      const source = this.context.createBufferSource();
      source.buffer = buffer; source.connect(this.context.destination);
      this.sources.add(source);
      source.onended = () => { this.sources.delete(source); source.disconnect(); };
      source.start(this.nextTime); this.nextTime += buffer.duration;
      this.metrics.audioSeconds += buffer.duration;
      if (!this.started) { this.started = true; this.onStart(); }
    }
    while (!this.controller.signal.aborted && this.context.currentTime < this.nextTime) await this.pause();
  }
  private async pause() { await new Promise<void>(resolve => setTimeout(resolve, 20)); }
  private fail(error: unknown) {
    if (this.controller.signal.aborted) return;
    this.failure = error;
    this.stop(); this.onError(error);
  }
  diagnostics(): PlaybackMetrics { return { ...this.metrics }; }
  async finish() {
    this.inputDone = true;
    await this.consumer;
    if (this.failure) throw this.failure;
    console.info("voice.playback", this.diagnostics());
    this.stop();
  }
  stop() {
    this.controller.abort();
    for (const job of this.jobs) { job.buffers = []; job.seconds = 0; }
    for (const source of this.sources) { source.onended = null; try { source.stop(); } catch { /* already ended */ } source.disconnect(); }
    this.sources.clear();
    if (this.context.state !== "closed") void this.context.close().catch(() => {});
  }
}
