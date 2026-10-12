import { useEffect, useRef } from "react";
import type { Attachment, ChatMessage } from "../../types";
import { MessageBubble } from "./MessageBubble";
import { TypingIndicator } from "./TypingIndicator";
import { ErrorState } from "../common/ErrorState";
export function MessageList({
  messages,
  busy,
  error,
  onRetry,
  onRegenerate,
  onFeedback,
  onView,
  onConfirmKG,
}: {
  messages: ChatMessage[];
  busy: boolean;
  error?: string;
  onRetry: () => void;
  onRegenerate: (id: string) => void;
  onFeedback: (id: string, value: "up" | "down") => void;
  onView: (attachment: Attachment) => void;
  onConfirmKG?: (messageId: string, ids: string[]) => void;
}) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, busy, error]);
  return (
    <div
      className="message-list"
      role="log"
      aria-label="Nội dung cuộc trò chuyện"
      aria-live="polite"
    >
      {messages.map((message) => (
        <MessageBubble
          key={message.id}
          message={message}
          onView={onView}
          onRegenerate={() => onRegenerate(message.id)}
          onFeedback={(value) => onFeedback(message.id, value)}
          busy={busy}
          onConfirmKG={onConfirmKG && message.id === messages.at(-1)?.id
            ? ids => onConfirmKG(message.id, ids) : undefined}
        />
      ))}
      {busy && <TypingIndicator />}
      {error && <ErrorState message={error} onRetry={onRetry} />}
      <div ref={end} />
    </div>
  );
}
