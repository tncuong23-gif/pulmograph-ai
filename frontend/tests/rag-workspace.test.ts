import { readFileSync } from "node:fs";
import { resolve, join } from "node:path";
import { afterEach, expect, it, vi } from "vitest";

afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals(); document.body.innerHTML = ""; });

it("shows old chunks awaiting migration and refreshes their status after reindex", async () => {
  vi.useFakeTimers();
  const root = resolve(process.cwd(), "../backend/app/modules/rag/static");
  const html = readFileSync(join(root, "index.html"), "utf8");
  const source = readFileSync(join(root, "app.js"), "utf8");
  document.body.innerHTML = new DOMParser().parseFromString(html, "text/html").body.innerHTML;
  let needsReindex = true;
  const fetch = vi.fn(async (url: string, options?: RequestInit) => {
    let result: unknown;
    if (url.endsWith("/health")) result = { mode: "live", chunking: { method: "semantic" } };
    else if (url.endsWith("/batch/jobs")) result = { active_job_id: null, items: [] };
    else if (url.endsWith("/stats")) result = { documents: 1, chunks: 2, propositions: 0, vectors: 2 };
    else if (url.includes("/documents?")) result = { total: 1, items: [{ document_id: "DOC_1", title: "Nguồn mẫu", chunks: 2, propositions: 0,
      chunking: { method: needsReindex ? "token" : "semantic" }, needs_reindex: needsReindex }] };
    else if (url.endsWith("/documents/DOC_1/reindex")) {
      expect(options?.method).toBe("POST"); needsReindex = false;
      result = { status: "completed", chunking: { method: "semantic" }, chunking_summary: { semantic: 1 }, actions: { update: 2 } };
    } else throw Error("Unexpected RAG request: " + url);
    return { ok: true, json: async () => result } as Response;
  });
  vi.stubGlobal("fetch", fetch);
  new Function(source)();
  await vi.waitFor(() => expect(document.querySelector("#documents")?.textContent).toContain("Cần reindex"));
  expect(document.querySelector("#chunking-title")?.textContent).toBe("Chia đoạn theo ngữ nghĩa");
  document.querySelector<HTMLButtonElement>('[data-action="reindex"]')!.click();
  await vi.waitFor(() => expect(document.querySelector("#documents")?.textContent).not.toContain("Cần reindex"));
  expect(document.querySelector("#documents")?.textContent).toContain("Chia theo ngữ nghĩa");
  expect(document.querySelector("#report")?.textContent).toContain("Điểm chuyển chủ đề: 1");
});

it("uploads multiple files, reports upload failures, and renders batch progress and report links", async () => {
  vi.useFakeTimers();
  const root = resolve(process.cwd(), "../backend/app/modules/rag/static");
  document.body.innerHTML = new DOMParser().parseFromString(readFileSync(join(root, "index.html"), "utf8"), "text/html").body.innerHTML;
  const base = { job_id: "BATCH", source: "files", mode: "commit", started_at: "2026-10-09T00:00:00Z",
    total: 2, processed: 0, completed: 0, skipped: 0, failed: 0, current_file: "good.json", status: "running",
    items: [{ filename: "good.json", status: "pending" }, { filename: "bad.json", status: "pending" }] };
  let posted = false;
  const fetch = vi.fn(async (url: string, options?: RequestInit) => {
    let result: unknown;
    if (url.endsWith("/health")) result = { mode: "live", chunking: { method: "semantic" } };
    else if (url.endsWith("/stats")) result = { documents: posted ? 1 : 0, chunks: 1, propositions: 0, vectors: 1 };
    else if (url.includes("/documents?")) result = { total: 0, items: [] };
    else if (url.includes("/batch/uploads/")) {
      expect(options?.method).toBe("PUT");
      expect(options?.body).toBeInstanceOf(File);
      if (url.endsWith("bad.json")) return { ok: false, json: async () => ({ detail: "Không thể lưu file" }) } as Response;
      result = { saved: true, filename: "good.json" };
    } else if (url.endsWith("/batch/jobs") && options?.method === "POST") {
      expect(JSON.parse(options.body as string)).toEqual({ source: "files", mode: "commit", files: [
        { filename: "good.json" }, { filename: "bad.json", upload_error: "Không thể lưu file" }] });
      posted = true; result = base;
    } else if (url.endsWith("/batch/jobs")) result = { active_job_id: null, items: posted ? [{ ...base, status: "completed", processed: 2, failed: 1 }] : [] };
    else if (url.endsWith("/batch/jobs/BATCH")) result = { ...base, processed: 2, completed: 1, failed: 1, current_file: null, status: "completed",
      items: [{ filename: "good.json", document_id: "D", status: "completed", chunks: 1 },
        { filename: "bad.json", status: "failed", error: "Không thể lưu file" }] };
    else throw Error("Unexpected request: " + url);
    return { ok: true, json: async () => result } as Response;
  });
  vi.stubGlobal("fetch", fetch);
  new Function(readFileSync(join(root, "app.js"), "utf8"))();
  await vi.waitFor(() => expect(document.querySelector("#connection")?.textContent).toContain("sẵn sàng"));
  const input = document.querySelector<HTMLInputElement>("#file")!;
  expect(input.multiple).toBe(true);
  Object.defineProperty(input, "files", { value: [new File(["{}"], "good.json"), new File(["{"], "bad.json")] });
  input.dispatchEvent(new Event("change"));
  expect(document.querySelector("#selected-files")?.textContent).toContain("bad.json");
  document.querySelector<HTMLButtonElement>("#import")!.click();
  await vi.waitFor(() => expect(posted).toBe(true));
  expect(document.querySelector<HTMLButtonElement>("#import-folder")!.disabled).toBe(true);
  await vi.advanceTimersByTimeAsync(1100);
  await vi.waitFor(() => expect(document.querySelector("#report-status")?.textContent).toContain("2/2"));
  expect(document.querySelector("#report")?.textContent).toContain("Lỗi: 1");
  expect(document.querySelector("#report")?.textContent).toContain("Không thể lưu file");
  expect(document.querySelector<HTMLAnchorElement>('a[href$="kind=errors"]')!.getAttribute("href")).toBe("/modules/rag/api/v1/rag/batch/jobs/BATCH/report?kind=errors");
  await vi.waitFor(() => expect(document.querySelector<HTMLButtonElement>("#import-folder")!.disabled).toBe(false));
});

it("imports the backend folder only after a click and supports single-file preview", async () => {
  vi.useFakeTimers();
  const root = resolve(process.cwd(), "../backend/app/modules/rag/static");
  document.body.innerHTML = new DOMParser().parseFromString(readFileSync(join(root, "index.html"), "utf8"), "text/html").body.innerHTML;
  const payloads: unknown[] = [];
  const fetch = vi.fn(async (url: string, options?: RequestInit) => {
    let result: unknown;
    if (url.endsWith("/health")) result = { mode: "live", chunking: { method: "semantic" } };
    else if (url.endsWith("/stats")) result = { documents: 0, chunks: 0, propositions: 0, vectors: 0 };
    else if (url.includes("/documents?")) result = { total: 0, items: [] };
    else if (url.includes("/batch/uploads/")) result = { saved: true };
    else if (url.endsWith("/batch/jobs") && options?.method === "POST") {
      const payload = JSON.parse(options.body as string); payloads.push(payload);
      result = { job_id: "DONE", mode: payload.mode, status: "completed", processed: 1, total: 1, completed: 1, skipped: 0, failed: 0,
        items: [{ filename: "single.json", status: "completed", chunks: 1 }] };
    } else if (url.endsWith("/batch/jobs")) result = { active_job_id: null, items: [] };
    else throw Error(url);
    return { ok: true, json: async () => result } as Response;
  });
  vi.stubGlobal("fetch", fetch);
  new Function(readFileSync(join(root, "app.js"), "utf8"))();
  await vi.waitFor(() => expect(document.querySelector("#connection")?.textContent).toContain("sẵn sàng"));
  expect(payloads).toEqual([]);
  document.querySelector<HTMLButtonElement>("#import-folder")!.click();
  await vi.waitFor(() => expect(payloads).toHaveLength(1));
  expect(payloads[0]).toEqual({ source: "directory", files: [], mode: "commit" });
  await vi.waitFor(() => expect(document.querySelector<HTMLButtonElement>("#import-folder")!.disabled).toBe(false));
  const input = document.querySelector<HTMLInputElement>("#file")!;
  Object.defineProperty(input, "files", { value: [new File(["{}"], "single.json")] });
  input.dispatchEvent(new Event("change"));
  document.querySelector<HTMLButtonElement>("#dryrun")!.click();
  await vi.waitFor(() => expect(payloads).toHaveLength(2));
  expect(payloads[1]).toEqual({ source: "files", files: [{ filename: "single.json" }], mode: "dry_run" });
  expect(document.querySelector("#report")?.textContent).toContain("chưa ghi CSDL");
});

it("resumes progress after reload even while the health request is waiting", async () => {
  vi.useFakeTimers();
  const root = resolve(process.cwd(), "../backend/app/modules/rag/static");
  document.body.innerHTML = new DOMParser().parseFromString(readFileSync(join(root, "index.html"), "utf8"), "text/html").body.innerHTML;
  let pollCount = 0;
  const job = { job_id: "ACTIVE", started_at: "2026-10-09T00:00:00Z", mode: "commit", status: "running",
    processed: 0, total: 1, completed: 0, skipped: 0, failed: 0, current_file: "source.json",
    items: [{ filename: "source.json", status: "pending" }] };
  let releaseHealth!: (response: Response) => void;
  const fetch = vi.fn(async (url: string, options?: RequestInit) => {
    expect(options?.method).not.toBe("POST");
    if (url.endsWith("/health")) return new Promise<Response>(resolve => { releaseHealth = resolve; });
    let result: unknown;
    if (url.endsWith("/batch/jobs")) result = { active_job_id: pollCount < 2 ? "ACTIVE" : null, items: [job] };
    else if (url.endsWith("/batch/jobs/ACTIVE")) {
      pollCount++; result = pollCount === 1 ? job : { ...job, status: "completed", processed: 1, completed: 1,
        current_file: null, items: [{ filename: "source.json", status: "completed", chunks: 1 }] };
    } else if (url.endsWith("/stats")) result = { documents: 1, chunks: 1, propositions: 0, vectors: 1 };
    else if (url.includes("/documents?")) result = { total: 0, items: [] };
    else throw Error(url);
    return { ok: true, json: async () => result } as Response;
  });
  vi.stubGlobal("fetch", fetch);
  new Function(readFileSync(join(root, "app.js"), "utf8"))();
  await vi.waitFor(() => expect(document.querySelector("#report")?.textContent).toContain("source.json"));
  expect(document.querySelector<HTMLButtonElement>("#import-folder")!.disabled).toBe(true);
  await vi.advanceTimersByTimeAsync(1100);
  await vi.waitFor(() => expect(document.querySelector("#report-status")?.textContent).toContain("1/1"));
  releaseHealth({ ok: true, json: async () => ({ mode: "live", chunking: { method: "semantic" } }) } as Response);
  await vi.waitFor(() => expect(document.querySelector<HTMLButtonElement>("#import-folder")!.disabled).toBe(false));
});
