import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Check,
  Copy,
  RotateCcw,
  ThumbsDown,
  ThumbsUp,
  UserRound,
} from "lucide-react";
import type { Attachment, ChatMessage } from "../../types";
import { BrandMark } from "../common/BrandMark";
import { AttachmentList } from "../attachments/AttachmentPreview";
import { vi } from "../../i18n/vi";
import { useApp } from "../../context/AppContext";
import { SourcesProvider, SourcesList, SourceCitation, numberedCitations } from "./EvidenceSources";
import { KGQueryDetails } from "./KGQueryDetails";
export function MessageBubble({
  message,
  onView,
  onRegenerate,
  onFeedback,
  busy,
  onConfirmKG,
}: {
  message: ChatMessage;
  onView: (attachment: Attachment) => void;
  onRegenerate: () => void;
  onFeedback: (value: "up" | "down") => void;
  busy: boolean;
  onConfirmKG?: (ids: string[]) => void;
}) {
  const [copied, setCopied] = useState(false);
  const { toast } = useApp();
  const user = message.role === "user";
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      toast(vi.copied);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast("Không thể sao chép. Vui lòng chọn nội dung để sao chép thủ công.");
    }
  };
  return (
    <SourcesProvider sources={message.metadata?.sources}><article
      className={`message ${user ? "user-message" : "assistant-message"}`}
    >
      <div className="message-avatar">
        {user ? <UserRound size={18} /> : <BrandMark />}
      </div>
      <div className="message-main">
        <div className="message-meta">
          <strong>{user ? "Bạn" : vi.brand}</strong>
          <time dateTime={message.createdAt}>
            {new Date(message.createdAt).toLocaleTimeString("vi-VN", {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </time>
        </div>
        {message.attachments?.length ? (
          <AttachmentList attachments={message.attachments} onView={onView} />
        ) : null}
        {message.content && (
          <div className={user ? "user-content" : "markdown-content"}>
            {user ? (
              message.content
            ) : (
              <ReactMarkdown
                remarkPlugins={[remarkGfm, numberedCitations(message.metadata?.sources ?? [])]}
                components={{
                  a: ({ children, href }) => href?.match(/^#source-(\d+)$/)
                    ? <SourceCitation number={Number(href.slice(8))}/>
                    : <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
                }}
              >
                {message.content}
              </ReactMarkdown>
            )}
          </div>
        )}
        {!user && <KGQueryDetails message={message} busy={busy} onConfirm={onConfirmKG} />}
        {!user && <SourcesList/>}
        {!user && (
          <div className="message-toolbar">
            <button
              className="icon-button"
              onClick={() => void copy()}
              title={copied ? vi.copied : vi.copy}
              aria-label={vi.copy}
            >
              {copied ? <Check size={16} /> : <Copy size={16} />}
            </button>
            {message.kind !== "medical_record" && message.metadata?.route !== "DIAGNOSTIC_ASSESSMENT" && !message.metadata?.kg_clarification && !message.metadata?.kg_confirmation_used && <button
              className="icon-button"
              onClick={onRegenerate}
              disabled={busy}
              title={vi.regenerate}
              aria-label={vi.regenerate}
            >
              <RotateCcw size={16} />
            </button>}
            <span />
            <button
              className={`icon-button ${message.feedback === "up" ? "chosen" : ""}`}
              onClick={() => onFeedback("up")}
              title={vi.positive}
              aria-label={vi.positive}
              aria-pressed={message.feedback === "up"}
            >
              <ThumbsUp size={16} />
            </button>
            <button
              className={`icon-button ${message.feedback === "down" ? "chosen" : ""}`}
              onClick={() => onFeedback("down")}
              title={vi.negative}
              aria-label={vi.negative}
              aria-pressed={message.feedback === "down"}
            >
              <ThumbsDown size={16} />
            </button>
          </div>
        )}
      </div>
    </article></SourcesProvider>
  );
}
