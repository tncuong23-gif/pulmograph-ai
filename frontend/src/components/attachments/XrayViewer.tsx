import { useEffect, useRef, useState } from "react";
import {
  Expand,
  Maximize,
  Minimize,
  RotateCw,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import type { Attachment } from "../../types";
import { Modal } from "../common/Modal";
import { formatFileSize } from "../../config/uploads";
export function XrayViewer({
  attachment,
  onClose,
}: {
  attachment: Attachment | null;
  onClose: () => void;
}) {
  const [zoom, setZoom] = useState(1);
  const [rotation, setRotation] = useState(0);
  const [full, setFull] = useState(false);
  const [error, setError] = useState("");
  const viewport = useRef<HTMLDivElement>(null);
  useEffect(() => {
    setZoom(1);
    setRotation(0);
    setError("");
  }, [attachment?.id]);
  useEffect(() => {
    const change = () => setFull(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", change);
    return () => document.removeEventListener("fullscreenchange", change);
  }, []);
  const fullscreen = async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await viewport.current?.parentElement?.requestFullscreen();
    } catch {
      setError("Trình duyệt này không hỗ trợ chế độ toàn màn hình.");
    }
  };
  const close = () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    onClose();
  };
  return (
    <Modal
      open={!!attachment}
      onOpenChange={(open) => {
        if (!open) close();
      }}
      title="Trình xem ảnh X-quang"
      description={
        attachment
          ? `${attachment.fileName} · ${formatFileSize(attachment.fileSize)}${attachment.width ? ` · ${attachment.width} × ${attachment.height} px` : ""}`
          : undefined
      }
      className="xray-viewer"
    >
      <div className="viewer-stage" ref={viewport}>
        {attachment?.url ? (
          <img
            src={attachment.url}
            alt={attachment.fileName}
            onError={() => setError("Không thể hiển thị ảnh này.")}
            style={{ transform: `scale(${zoom}) rotate(${rotation}deg)` }}
          />
        ) : (
          <p>Không có ảnh xem trước.</p>
        )}
        <span className="viewer-label">X-RAY VIEWER</span>
      </div>
      <div className="viewer-toolbar">
        <button
          className="icon-button"
          aria-label="Thu nhỏ"
          title="Thu nhỏ"
          disabled={zoom <= 0.25}
          onClick={() => setZoom((z) => Math.max(0.25, z - 0.25))}
        >
          <ZoomOut size={19} />
        </button>
        <span>{Math.round(zoom * 100)}%</span>
        <button
          className="icon-button"
          aria-label="Phóng to"
          title="Phóng to"
          disabled={zoom >= 4}
          onClick={() => setZoom((z) => Math.min(4, z + 0.25))}
        >
          <ZoomIn size={19} />
        </button>
        <i />
        <button
          className="icon-button"
          aria-label="Đặt lại ảnh"
          title="Đặt lại"
          onClick={() => {
            setZoom(1);
            setRotation(0);
          }}
        >
          <Expand size={19} />
        </button>
        <button
          className="icon-button"
          aria-label="Xoay ảnh"
          title="Xoay 90°"
          onClick={() => setRotation((r) => (r + 90) % 360)}
        >
          <RotateCw size={19} />
        </button>
        <button
          className="icon-button"
          aria-label="Toàn màn hình"
          title="Toàn màn hình"
          onClick={() => void fullscreen()}
        >
          {full ? <Minimize size={19} /> : <Maximize size={19} />}
        </button>
      </div>
      {error && (
        <p role="alert" className="viewer-error">
          {error}
        </p>
      )}
      <p className="viewer-note">
        Chỉ hỗ trợ xem ảnh. Không thực hiện phân tích hoặc chẩn đoán.
      </p>
    </Modal>
  );
}
