import type { AttachmentType } from "../types";
export const MAX_FILE_SIZE = 20 * 1024 * 1024;
export const MAX_ATTACHMENTS = 2;
export const ALLOWED_MEDICAL_RECORD_TYPES: Record<string, readonly string[]> = {
  txt: ["text/plain"],
};
export const ALLOWED_XRAY_TYPES: Record<string, readonly string[]> = {
  jpg: ["image/jpeg"], jpeg: ["image/jpeg"], png: ["image/png"],
};
export const fileExtension = (name: string) =>
  name.split(".").pop()?.toLowerCase() ?? "";
export function validateFile(
  file: Pick<File, "name" | "size" | "type">,
  type: AttachmentType,
): string | undefined {
  const types =
    type === "medical_record"
      ? ALLOWED_MEDICAL_RECORD_TYPES
      : ALLOWED_XRAY_TYPES;
  const extension = fileExtension(file.name);
  if (!types[extension]) return "Định dạng file không được hỗ trợ.";
  // Empty MIME values are common for DOC/DICOM on Windows; extension validation still applies.
  if (file.type && !types[extension].includes(file.type.toLowerCase()))
    return "Loại nội dung của file không khớp với định dạng được hỗ trợ.";
  if (!file.size) return "File trống. Vui lòng chọn file có nội dung.";
  if (file.size > MAX_FILE_SIZE)
    return "File vượt quá kích thước cho phép (20 MB).";
}
export const acceptedFiles = (type: AttachmentType) =>
  Object.keys(
    type === "medical_record"
      ? ALLOWED_MEDICAL_RECORD_TYPES
      : ALLOWED_XRAY_TYPES,
  )
    .map((x) => `.${x}`)
    .join(",");
export const formatFileSize = (size: number) =>
  size < 1024 * 1024
    ? `${Math.max(1, Math.round(size / 1024))} KB`
    : `${(size / 1024 / 1024).toFixed(1)} MB`;
