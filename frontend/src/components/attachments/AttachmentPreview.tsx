import { Check, FileText, ImageIcon, RotateCcw, X } from "lucide-react";
import type { Attachment } from "../../types";
import { fileExtension, formatFileSize } from "../../config/uploads";
import { vi } from "../../i18n/vi";
export function AttachmentPreview({
  attachment: a,
  onRemove,
  onRetry,
  onView,
}: {
  attachment: Attachment;
  onRemove?: () => void;
  onRetry?: () => void;
  onView?: (attachment: Attachment) => void;
}) {
  const isImage = a.type === "xray";
  const busy = !["pending", "processed", "error"].includes(a.status);
  return (
    <article
      className={`attachment-card ${isImage ? "xray-card" : "record-card"} ${a.status === "error" ? "attachment-error" : ""}`}
    >
      {isImage ? (
        <button
          type="button"
          className="xray-thumbnail"
          aria-label={`Xem ảnh ${a.fileName}`}
          onClick={() => onView?.(a)}
          disabled={!a.url || a.isDicom}
        >
          {a.url && !a.isDicom ? (
            <img src={a.url} alt={`Ảnh X-quang: ${a.fileName}`} />
          ) : (
            <ImageIcon size={25} />
          )}
        </button>
      ) : (
        <div className="file-icon">
          <FileText size={23} />
          <small>{fileExtension(a.fileName).toUpperCase()}</small>
        </div>
      )}
      <div className="attachment-details">
        <strong title={a.fileName}>{a.fileName}</strong>
        <span>
          {formatFileSize(a.fileSize)}
          {a.width && a.height
            ? ` · ${a.width} × ${a.height}`
            : a.isDicom
              ? " · DICOM"
              : ""}
        </span>
        <span className={`attachment-status ${a.status}`} title={a.error}>
          {a.status === "processed" && <Check size={12} />}{" "}
          {a.isDicom && a.status === "processed"
            ? "Đã nhận · Không xem trước"
            : vi.statuses[a.status]}
          {a.status === "uploading" ? ` ${a.progress}%` : ""}
        </span>
        {a.status === "error" && (
          <small className="attachment-error-text">{a.error}</small>
        )}
        {a.analysisAnswer && (
          <div className="attachment-analysis-answer" role="status">
            <strong>Tóm tắt phân tích</strong>
            <p>{a.analysisAnswer}</p>
          </div>
        )}
        {busy && (
          <div
            className={`upload-progress ${a.status === "processing" ? "processing" : ""}`}
            role="progressbar"
            aria-label={`Tiến trình ${a.fileName}`}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={a.progress}
          >
            <span style={{ width: `${a.progress}%` }} />
          </div>
        )}
      </div>
      {onRemove && (
        <button
          type="button"
          className="icon-button remove-attachment"
          onClick={onRemove}
          aria-label={`Xóa tệp ${a.fileName}`}
          title="Bỏ tệp đính kèm"
        >
          <X size={15} />
        </button>
      )}
      {a.status === "error" && onRetry && (
        <button
          type="button"
          className="icon-button retry-attachment"
          onClick={onRetry}
          aria-label={`Thử lại ${a.fileName}`}
          title="Tải lại"
        >
          <RotateCcw size={16} />
        </button>
      )}
    </article>
  );
}
export function AttachmentList({
  attachments,
  onRemove,
  onRetry,
  onView,
}: {
  attachments: Attachment[];
  onRemove?: (id: string) => void;
  onRetry?: (id: string) => void;
  onView?: (a: Attachment) => void;
}) {
  return (
    <div className="attachment-list">
      {attachments.map((a) => (
        <AttachmentPreview
          key={a.id}
          attachment={a}
          onRemove={onRemove ? () => onRemove(a.id) : undefined}
          onRetry={onRetry ? () => onRetry(a.id) : undefined}
          onView={onView}
        />
      ))}
    </div>
  );
}
