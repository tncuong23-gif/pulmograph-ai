import { useEffect, useRef } from "react";
import * as Menu from "@radix-ui/react-dropdown-menu";
import { ArrowUp, AudioLines, FileText, ImageIcon, Plus, ShieldCheck } from "lucide-react";
import type { Attachment, SelectedRecord } from "../../types";
import { useAttachments } from "../../hooks/useAttachments";
import { acceptedFiles, MAX_ATTACHMENTS } from "../../config/uploads";
import { AttachmentList } from "../attachments/AttachmentPreview";
import { ErrorState } from "../common/ErrorState";
import { vi } from "../../i18n/vi";
import { USE_MOCK_API } from "../../api/client";
export function ChatInput({
  draft,
  sessionKey,
  setDraft,
  onSend,
  onSendRecords,
  busy,
  onView,
  onVoiceStart,
}: {
  draft: string;
  sessionKey?: string;
  setDraft: (value: string) => void;
  onSend: (content: string, attachments: Attachment[]) => void;
  onSendRecords: (records: SelectedRecord[], text?: string) => void;
  busy: boolean;
  onView: (attachment: Attachment) => void;
  onVoiceStart: () => void;
}) {
  const files = useAttachments();
  useEffect(() => { files.reset(); }, [sessionKey, files.reset]);
  const input = useRef<HTMLTextAreaElement>(null);
  const recordPicker = useRef<HTMLInputElement>(null);
  const xrayPicker = useRef<HTMLInputElement>(null);
  const recordMode = files.attachments.some((a) => a.type === "medical_record");
  const imageMode = files.attachments.some(a=>a.type==="xray");
  // Tệp đính kèm tự kích hoạt phân tích Clinical IE; văn bản không có tệp là chat thông thường.
  const clinical = files.attachments.length > 0;
  const disabled =
    busy ||
    files.busy ||
    files.hasErrors ||
    (!draft.trim() && !files.attachments.length);
  useEffect(() => {
    if (input.current) {
      input.current.style.height = "auto";
      input.current.style.height = `${Math.min(160, input.current.scrollHeight)}px`;
    }
  }, [draft]);
  useEffect(() => {
    if (draft) input.current?.focus();
  }, [draft]);
  const submit = () => {
    if (disabled) return;
    if (clinical) onSendRecords(files.commitRecords(), recordMode ? "" : draft.trim());
    else onSend(draft.trim(), files.commit());
    setDraft("");
    if (input.current) input.current.style.height = "auto";
  };
  const limit = busy || files.attachments.length >= MAX_ATTACHMENTS;
  return (
    <footer className="composer-area">
      <form
        className="chat-composer"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        {files.attachments.length > 0 && (
          <AttachmentList
            attachments={files.attachments}
            onRemove={files.remove}
            onRetry={files.retry}
            onView={onView}
          />
        )}
        {files.error && <ErrorState message={files.error} />}
        <label htmlFor="chat-question" className="sr-only">
          Câu hỏi y tế
        </label>
        <textarea
          ref={input}
          id="chat-question"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          disabled={recordMode || busy || files.busy || files.hasErrors}
          placeholder={recordMode ? "Bấm Gửi để phân tích bệnh án..." : imageMode ? "Có thể thêm văn bản bệnh án để phân tích kết hợp..." : vi.placeholder}
          rows={2}
          maxLength={10000}
          onKeyDown={(e) => {
            if (
              e.key === "Enter" &&
              !e.shiftKey &&
              !e.nativeEvent.isComposing
            ) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <div className="composer-actions">
          <div className="attachment-actions">
            <Menu.Root>
              <Menu.Trigger asChild>
                <button
                  type="button"
                  className="icon-button add-attachment"
                  aria-label="Thêm tệp đính kèm"
                  title="Thêm tệp đính kèm"
                  disabled={limit}
                >
                  <Plus size={20} />
                </button>
              </Menu.Trigger>
              <Menu.Portal>
                <Menu.Content
                  className="dropdown-menu"
                  side="top"
                  sideOffset={8}
                >
                  <Menu.Item onSelect={() => recordPicker.current?.click()}>
                    <FileText size={16} />
                    {vi.medicalRecord}
                  </Menu.Item>
                  <Menu.Item onSelect={() => xrayPicker.current?.click()}>
                    <ImageIcon size={16} />
                    {vi.xray}
                  </Menu.Item>
                </Menu.Content>
              </Menu.Portal>
            </Menu.Root>
            <span className="composer-divider" />
            <button
              type="button"
              className="attachment-button"
              aria-label={vi.medicalRecord}
              title={vi.medicalRecord}
              disabled={limit}
              onClick={() => recordPicker.current?.click()}
            >
              <FileText size={17} />
              <span>{vi.medicalRecord}</span>
            </button>
            <button
              type="button"
              className="attachment-button"
              aria-label={vi.xray}
              title="Ảnh X-quang JPEG/PNG"
              disabled={limit || imageMode}
              onClick={() => xrayPicker.current?.click()}
            >
              <ImageIcon size={17} />
              <span>{vi.xray}</span>
            </button>
            <button
              type="button"
              className="attachment-button composer-voice-button"
              aria-label="Trò chuyện bằng giọng nói"
              title="Trò chuyện bằng giọng nói"
              disabled={busy || files.busy || files.attachments.length > 0 || USE_MOCK_API}
              onClick={onVoiceStart}
            >
              <AudioLines size={17} />
              <span className="composer-voice-label">Giọng nói</span>
            </button>
          </div>
          <div className="send-actions">
            <span className="enter-hint">
              {clinical
                ? "Bấm Gửi để phân tích tệp"
                : files.busy
                ? "Đang xử lý tệp…"
                : busy
                  ? "AI đang trả lời…"
                  : "Enter để gửi"}
            </span>
            <button
              type="submit"
              className="send-button"
              aria-label={vi.send}
              title={clinical
                ? "Gửi tệp để phân tích"
                : files.hasErrors ? "Vui lòng tải lại hoặc bỏ tệp lỗi" : vi.send}
              disabled={disabled}
            >
              <ArrowUp size={21} />
            </button>
          </div>
        </div>
        <input
          ref={recordPicker}
          data-testid="medical-record-input"
          className="sr-only"
          type="file"
          tabIndex={-1}
          accept={acceptedFiles("medical_record")}
          onChange={(e) => {
            if (e.target.files) files.add(e.target.files, "medical_record");
            e.target.value = "";
          }}
        />
        <input
          ref={xrayPicker}
          data-testid="xray-input"
          className="sr-only"
          type="file"
          tabIndex={-1}
          accept={acceptedFiles("xray")}
          onChange={(e) => {
            if (e.target.files) files.add(e.target.files, "xray");
            e.target.value = "";
          }}
        />
      </form>
      <div className="composer-caption">
        <span>
          <ShieldCheck size={13} />
          {USE_MOCK_API ? vi.privacy : "Bệnh án chỉ được tải lên khi bạn bấm Gửi"}
        </span>
        <span>
          {files.attachments.length
            ? `${files.attachments.length}/${MAX_ATTACHMENTS} tệp`
            : "Tối đa 2 tệp · 20 MB/tệp"}
        </span>
      </div>
      <p className="medical-disclaimer">{vi.disclaimer}</p>
    </footer>
  );
}
