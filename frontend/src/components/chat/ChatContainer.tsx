import { useEffect, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { FlaskConical } from "lucide-react";
import { useChat } from "../../context/ChatContext";
import { USE_MOCK_API, errorMessage } from "../../api/client";
import type { Attachment, SelectedRecord } from "../../types";
import { vi } from "../../i18n/vi";
import { WelcomeScreen } from "./WelcomeScreen";
import { AssessmentPanel } from "./AssessmentPanel";
import { ChatInput } from "./ChatInput";
import { MessageList } from "./MessageList";
import { XrayViewer } from "../attachments/XrayViewer";
import { ErrorState } from "../common/ErrorState";
import { LoadingState } from "../common/LoadingState";
import { useWebMcp } from "../../hooks/useWebMcp";
import { VoiceAssistant } from "../voice/VoiceAssistant";
export function ChatContainer() {
  const { conversationId } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const {
    conversations,
    loadConversation,
    send,
    sendRecords,
    confirmKG,
    assessmentAction,
    busyIds,
    errors,
    retry,
    feedback,
  } = useChat();
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [viewer, setViewer] = useState<Attachment | null>(null);
  useWebMcp(setDraft);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    setVoiceOpen(Boolean(location.state?.voiceSession));
  }, [conversationId, location.key]);
  useEffect(() => {
    setDraft("");
    setLoadError("");
    setViewer(null);
    if (!conversationId || (location.state?.voiceSession && !conversations[conversationId])) {
      setLoading(false);
      return;
    }
    let live = true;
    setLoading(true);
    loadConversation(conversationId)
      .catch((e) => {
        if (live) setLoadError(errorMessage(e));
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [conversationId, loadConversation, attempt, location.key]);
  const conversation = conversationId
    ? conversations[conversationId]
    : undefined;
  const busy = (!!conversationId && busyIds.has(conversationId)) || conversation?.assessment?.status === "running";
  const assessmentOpen = !!conversation?.assessment && !["completed", "cancelled"].includes(conversation.assessment.status);
  const onSend = (content: string, attachments: Attachment[]) => {
    const id = send(content, attachments, conversationId);
    if (id !== conversationId) navigate(`/chat/${id}`);
  };
  const onSendRecords = (records: SelectedRecord[], text = "") => {
    const id = sendRecords(records, conversationId, text);
    if (id !== conversationId) navigate(`/chat/${id}`);
  };
  return (
    <main className="chat-page" id="main-content">
      {USE_MOCK_API && (
        <div className="demo-notice">
          <FlaskConical size={14} />
          <span>
            <strong>{vi.mockNotice}</strong>
            <span className="demo-detail"> · {vi.demoHint}</span>
          </span>
        </div>
      )}
      <div className={`chat-scroll ${!conversationId ? "welcome-scroll" : ""}`}>
        {loading && !conversation ? (
          <LoadingState />
        ) : loadError ? (
          <div className="load-error">
            <ErrorState
              message={loadError}
              onRetry={() => setAttempt((v) => v + 1)}
            />
            <button
              className="secondary-button"
              onClick={() => navigate("/chat")}
            >
              Tạo cuộc trò chuyện mới
            </button>
          </div>
        ) : conversation ? (
          <>
          <MessageList
            messages={conversation.messages}
            busy={busy}
            error={errors[conversation.id]}
            onRetry={() => retry(conversation.id)}
            onRegenerate={(id) => retry(conversation.id, id)}
            onFeedback={(id, value) => feedback(conversation.id, id, value)}
            onView={setViewer}
            onConfirmKG={(messageId, ids) => confirmKG(conversation.id, messageId, ids)}
          />
          {!voiceOpen && conversation.assessment && <AssessmentPanel key={`${conversation.assessment.id}:${conversation.assessment.version}`} assessment={conversation.assessment} busy={busy} onAction={body => void assessmentAction(conversation.id, body)} />}
          </>
        ) : (
          <WelcomeScreen onSelect={setDraft} />
        )}
      </div>
      {!loadError && !voiceOpen && (
        <ChatInput
          sessionKey={conversationId ?? location.key}
          draft={draft}
          setDraft={setDraft}
          onSend={onSend}
          onSendRecords={onSendRecords}
          busy={busy || loading || assessmentOpen || voiceOpen}
          onView={setViewer}
          onVoiceStart={() => {
            if (!conversationId) navigate(`/chat/${crypto.randomUUID()}`, { state: { voiceSession: true } });
            setVoiceOpen(true);
          }}
        />
      )}
      {voiceOpen && conversationId && <VoiceAssistant key={conversationId} conversationId={conversationId} onClose={() => setVoiceOpen(false)} />}
      <XrayViewer attachment={viewer} onClose={() => setViewer(null)} />
    </main>
  );
}
