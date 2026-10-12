import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiRequest, CHAT_TIMEOUT_MS } from '../src/api/client';

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
function pendingFetch() {
  vi.stubGlobal('fetch', vi.fn((_url, init: RequestInit) => new Promise((_resolve, reject) => {
    init.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
  })));
}
describe('request time budgets', () => {
  it('chat is not aborted at the old 45 second cutoff', async () => {
    vi.useFakeTimers(); pendingFetch();
    const request = apiRequest('/api/v1/chat/message', {}, CHAT_TIMEOUT_MS);
    const failure = expect(request).rejects.toThrow('thời gian chờ');
    await vi.advanceTimersByTimeAsync(45000);
    expect((fetch as ReturnType<typeof vi.fn>).mock.calls[0][1].signal.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(CHAT_TIMEOUT_MS - 45000);
    await failure;
  });
  it('timeout still works with an external AbortSignal', async () => {
    vi.useFakeTimers(); pendingFetch();
    const external = new AbortController();
    const failure = expect(apiRequest('/status', {signal: external.signal}, 100)).rejects.toThrow('thời gian chờ');
    await vi.advanceTimersByTimeAsync(100); await failure;
    expect(external.signal.aborted).toBe(false);
  });
  it('user cancellation still aborts the request', async () => {
    pendingFetch(); const external = new AbortController();
    const failure = expect(apiRequest('/status', {signal: external.signal})).rejects.toThrow('đã được hủy');
    external.abort(); await failure;
  });
});
