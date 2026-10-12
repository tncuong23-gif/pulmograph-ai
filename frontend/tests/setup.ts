import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";
afterEach(() => {
  cleanup();
  localStorage.clear();
});
HTMLElement.prototype.scrollIntoView = vi.fn();
URL.createObjectURL = vi.fn(() => `blob:test-${crypto.randomUUID()}`);
URL.revokeObjectURL = vi.fn();
window.matchMedia = vi
  .fn()
  .mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
Object.defineProperty(navigator, "clipboard", {
  configurable: true,
  value: { writeText: vi.fn().mockResolvedValue(undefined) },
});
if (!window.PointerEvent)
  window.PointerEvent = MouseEvent as typeof PointerEvent;
HTMLElement.prototype.hasPointerCapture = () => false;
HTMLElement.prototype.setPointerCapture = () => {};
HTMLElement.prototype.releasePointerCapture = () => {};
