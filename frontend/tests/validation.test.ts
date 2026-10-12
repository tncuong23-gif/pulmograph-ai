import { describe, expect, it } from "vitest";
import {
  MAX_FILE_SIZE,
  acceptedFiles,
  validateFile,
} from "../src/config/uploads";
import { httpError } from "../src/api/client";
describe("File validation and API errors", () => {
  it("rejects files above the size limit and empty files", () => {
    expect(
      validateFile(
        { name: "large.txt", size: MAX_FILE_SIZE + 1, type: "text/plain" },
        "medical_record",
      ),
    ).toContain("20 MB");
    expect(
      validateFile(
        { name: "empty.txt", size: 0, type: "text/plain" },
        "medical_record",
      ),
    ).toContain("File trống");
  });
  it("rejects mismatched MIME and extensions while accepting known extensions with missing MIME", () => {
    expect(
      validateFile(
        { name: "fake.png", size: 10, type: "application/pdf" },
        "xray",
      ),
    ).toContain("không khớp");
    expect(
      validateFile({ name: "scan.PNG", size: 10, type: "" }, "xray"),
    ).toBeUndefined();
    expect(
      validateFile(
        { name: "notes.txt", size: 10, type: "" },
        "medical_record",
      ),
    ).toBeUndefined();
    expect(acceptedFiles("medical_record")).toBe(".txt");
    expect(acceptedFiles("xray")).toContain(".png");
  });
  it("returns clear session and throttling errors", () => {
    expect(httpError(401).message).toContain("Phiên làm việc");
    expect(httpError(429).message).toContain("quá nhiều yêu cầu");
  });
});
