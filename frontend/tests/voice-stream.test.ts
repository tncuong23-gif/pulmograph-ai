import { describe, expect, it, vi, afterEach } from "vitest";
import { ReadableStream as NodeStream } from "node:stream/web";
import { readVoiceEvents, voiceApi } from "../src/api/voiceApi";
import { PCMDecoder, speechSentences } from "../src/components/voice/SpeechPlayer";

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
function body(text: string, stride = 3) {
  const data = new TextEncoder().encode(text);
  return new NodeStream<Uint8Array>({ start(controller) {
    for (let i = 0; i < data.length; i += stride) controller.enqueue(data.slice(i, i + stride));
    controller.close();
  } }) as unknown as ReadableStream<Uint8Array>;
}

describe("voice stream", () => {
  it("decodes split UTF-8 and delivers sentences before the final reply", async () => {
    const spoken: string[] = [];
    const reply = { spoken_text: "Không sốt.", conversation: { id: "v" } };
    const text = JSON.stringify({ type: "sentence", index: 0, text: "Không sốt; SpO2 92.5%." }) + "\n" +
      JSON.stringify({ type: "complete", streamed_sentences: 1, reply }) + "\n";
    expect(await readVoiceEvents(body(text), sentence => spoken.push(sentence))).toEqual(reply);
    expect(spoken).toEqual(["Không sốt; SpO2 92.5%."]);
  });
  it("rejects a disconnect and preserves the error status for stale facts", async () => {
    await expect(readVoiceEvents(body('{"type":"sentence","index":0,"text":"Có."}\n'), () => {})).rejects.toThrow("bị ngắt");
    await expect(readVoiceEvents(body('{"type":"error","status":409,"detail":"Dữ kiện thay đổi"}\n'), () => {})).rejects.toMatchObject({ status: 409 });
  });
  it("rejects reordered or duplicate sentence indices", async () => {
    await expect(readVoiceEvents(body('{"type":"sentence","index":1,"text":"Có."}\n'), () => {})).rejects.toThrow("không hợp lệ");
  });
});

it("PCM decoder preserves sample boundaries across odd-sized chunks", () => {
  const decoder = new PCMDecoder();
  expect([...decoder.decode(new Uint8Array([0]))]).toEqual([]);
  expect([...decoder.decode(new Uint8Array([128, 255, 127, 0]))]).toEqual([-1, 32767/32768]);
  expect([...decoder.decode(new Uint8Array([0]))]).toEqual([0]);
  decoder.finish();
  decoder.decode(new Uint8Array([1]));
  expect(() => decoder.finish()).toThrow("inside a sample");
});

it("sentence boundaries retain negation, decimals and units", () => {
  expect(speechSentences("Không sốt, SpO2 92.5%; 0.5 mg. Chưa đủ bằng chứng."))
    .toEqual(["Không sốt, SpO2 92.5%; 0.5 mg.", "Chưa đủ bằng chứng."]);
});

