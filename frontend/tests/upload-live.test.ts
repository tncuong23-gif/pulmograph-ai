import { afterEach, expect, it, vi } from "vitest";
import type { Attachment } from "../src/types";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.resetModules();
});

it("uploads to the backend, polls its file ID and preserves the analysis summary", async () => {
  vi.stubEnv("VITE_USE_MOCK_API", "false");
  vi.resetModules();
  const open = vi.fn();
  const send = vi.fn();
  class UploadRequest {
    upload = {};
    status = 202;
    responseText = JSON.stringify({ id: "server-file", status: "processing" });
    onload?: () => void;
    onloadend?: () => void;
    open = open;
    send(body: FormData) {
      send(body);
      queueMicrotask(() => { this.onload?.(); this.onloadend?.(); });
    }
    abort() {}
  }
  vi.stubGlobal("XMLHttpRequest", UploadRequest);
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ id: "server-file", status: "processed", analysisAnswer: "Kết quả kiểm thử." }),
  });
  vi.stubGlobal("fetch", fetchMock);
  const { uploadApi } = await import("../src/api/uploadApi");
  vi.useFakeTimers();
  const attachment: Attachment = {
    id: "client-file", type: "medical_record", fileName: "record.txt",
    fileSize: 4, mimeType: "text/plain", status: "pending", progress: 0,
  };
  const onChange = vi.fn();
  const result = uploadApi.uploadMedicalRecord(
    new File(["test"], "record.txt"), attachment, onChange, new AbortController().signal,
  );
  await vi.advanceTimersByTimeAsync(2100);
  expect(await result).toMatchObject({ serverId: "server-file", status: "processed", analysisAnswer: "Kết quả kiểm thử." });
  expect(open).toHaveBeenCalledWith("POST", expect.stringContaining("/api/v1/files/medical-record"));
  expect(send.mock.calls[0][0].get("file")).toBeInstanceOf(File);
  expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/api/v1/files/server-file"), expect.anything());
  expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ analysisAnswer: "Kết quả kiểm thử." }));
});

it("sends TXT and image together as multipart and resumes one job without reupload", async () => {
  vi.stubEnv("VITE_USE_MOCK_API", "false");vi.resetModules();
  const done={id:"combined",serverId:"combined",status:"processed",analysisAnswer:"Result"};
  const fetchMock=vi.fn().mockResolvedValue({ok:true,status:202,json:async()=>done});
  vi.stubGlobal("fetch",fetchMock);
  const {uploadApi}=await import("../src/api/uploadApi");
  const record:Attachment={id:"r",type:"medical_record",fileName:"r.txt",fileSize:2,mimeType:"text/plain",status:"pending",progress:0};
  const image:Attachment={...record,id:"i",type:"xray",fileName:"x.png",mimeType:"image/png"};
  const records=[{attachment:record,file:new File(["Ho"],"r.txt")},{attachment:image,file:new File(["image"],"x.png")}];
  const args=[records,"","conversation","message",new AbortController().signal,vi.fn()] as const;
  const result=await uploadApi.analyzeClinical(...args);
  const request=fetchMock.mock.calls[0][1];
  expect(request.body).toBeInstanceOf(FormData);
  expect(request.headers.has("Content-Type")).toBe(false);
  expect(request.body.has("same_case")).toBe(false);
  expect(request.body.get("file").name).toBe("r.txt");
  expect(request.body.get("image").name).toBe("x.png");
  expect(request.body.get("conversationId")).toBe("conversation");
  expect(request.body.get("clientId")).toBe("message");
  await uploadApi.analyzeClinical(...args,result);
  expect(fetchMock.mock.calls[1][0]).toContain("/api/v1/files/combined");
  expect(fetchMock.mock.calls[1][1].body).toBeUndefined();
});
