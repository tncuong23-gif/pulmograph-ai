import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import type {
  AssessmentAction,
  Attachment,
  ChatMessage,
  Conversation,
  ConversationSummary,
  SelectedRecord,
} from "../types";
import { conversationApi } from "../api/conversationApi";
import { chatApi } from "../api/chatApi";
import { uploadApi } from "../api/uploadApi";
import { apiRequest, CHAT_TIMEOUT_MS, errorMessage } from "../api/client";
import { releaseAllFileUrls, releaseFileUrl } from "../lib/files";
interface ChatState {
  ingestConversation: (conversation: Conversation) => void;
  assessmentAction: (id: string, body: AssessmentAction) => Promise<void>;
  summaries: ConversationSummary[];
  conversations: Record<string, Conversation>;
  busyIds: Set<string>;
  errors: Record<string, string>;
  historyError: string;
  historyLoading: boolean;
  refreshHistory: () => Promise<void>;
  loadConversation: (id: string) => Promise<void>;
  send: (content: string, attachments: Attachment[], id?: string) => string;
  sendRecords: (records: SelectedRecord[], id?: string, text?: string) => string;
  confirmKG: (id: string, messageId: string, entityIds: string[]) => void;
  retry: (id: string, assistantId?: string) => void;
  rename: (id: string, title: string) => Promise<void>;
  remove: (id: string) => Promise<void>;
  feedback: (id: string, messageId: string, value: "up" | "down") => void;
}
const ChatContext = createContext<ChatState | null>(null);
export function ChatProvider({ children }: { children: ReactNode }) {
  const [summaries, setSummaries] = useState<ConversationSummary[]>([]);
  const [conversations, setConversations] = useState<
    Record<string, Conversation>
  >({});
  const current = useRef(conversations);
  current.current = conversations;
  const busyRef = useRef(new Set<string>());
  const [busyIds, setBusyIds] = useState<Set<string>>(new Set());
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [historyError, setHistoryError] = useState("");
  const [historyLoading, setHistoryLoading] = useState(true);
  const loadRequests = useRef(new Map<string, Promise<void>>());
  const deleted = useRef(new Set<string>());
  const failedRegeneration = useRef(new Map<string, string>());
  const recordJobs = useRef(new Map<string, {records: SelectedRecord[]; text: string; job?: Attachment}>());
  const recordControllers = useRef(new Map<string, AbortController>());
  const localRecordConversations = useRef(new Set<string>());
  const update = (conversation: Conversation) => {
    if (deleted.current.has(conversation.id)) return;
    current.current = { ...current.current, [conversation.id]: conversation };
    setConversations(current.current);
    const { messages: _messages, ...summary } = conversation;
    setSummaries((items) =>
      [summary, ...items.filter((i) => i.id !== summary.id)].sort((a, b) =>
        b.updatedAt.localeCompare(a.updatedAt),
      ),
    );
  };
  const refreshHistory = useCallback(async () => {
    setHistoryLoading(true);
    setHistoryError("");
    try {
      const remote = await conversationApi.getConversations();
      setSummaries((local) => {
        const merged = new Map(remote.map((item) => [item.id, item]));
        for (const item of local) {
          const existing = merged.get(item.id);
          if (!existing || item.updatedAt >= existing.updatedAt)
            merged.set(item.id, item);
        }
        return Array.from(merged.values())
          .filter((item) => !deleted.current.has(item.id))
          .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
      });
    } catch (e) {
      setHistoryError(errorMessage(e));
    } finally {
      setHistoryLoading(false);
    }
  }, []);
  useEffect(() => {
    void refreshHistory();
    return () => {
      recordControllers.current.forEach((controller) => controller.abort());
      releaseAllFileUrls();
    };
  }, [refreshHistory]);
  const loadConversation = useCallback(async (id: string) => {
    if (current.current[id]) return;
    if (loadRequests.current.has(id)) return loadRequests.current.get(id);
    const task = (async () => {
      try {
        update(await conversationApi.getConversation(id));
      } finally {
        loadRequests.current.delete(id);
      }
    })();
    loadRequests.current.set(id, task);
    return task;
  }, []);
  const assessmentAction = async (id: string, body: AssessmentAction) => {
    const assessment = current.current[id]?.assessment;
    if (!assessment || busyRef.current.has(id)) return;
    busyRef.current.add(id);
    setBusyIds(new Set(busyRef.current));
    setErrors(items => ({ ...items, [id]: "" }));
    try {
      const result = await apiRequest<{ conversation: Conversation }>(`/api/v1/assessments/${encodeURIComponent(assessment.id)}/actions`, {
        method: "POST", body: JSON.stringify({ ...body, version: assessment.version, action_id: crypto.randomUUID() }),
      }, CHAT_TIMEOUT_MS);
      update(result.conversation);
    } catch (error) {
      setErrors(items => ({ ...items, [id]: errorMessage(error) }));
      // A timeout may occur after the action was committed. Reconcile before retry.
      try { update(await conversationApi.getConversation(id)); } catch { /* error stays visible */ }
    } finally {
      busyRef.current.delete(id);
      setBusyIds(new Set(busyRef.current));
    }
  };
  useEffect(() => {
    let active = true;
    let fetching = false;
    const timer = window.setInterval(async () => {
      if (fetching) return;
      fetching = true;
      try {
        for (const c of Object.values(current.current)) {
          if (c.assessment?.status !== "running" || deleted.current.has(c.id)) continue;
          try {
            const fresh = await conversationApi.getConversation(c.id);
            if (active) { update(fresh); setErrors(items => ({ ...items, [c.id]: "" })); }
          } catch {
            if (active) setErrors(items => ({ ...items, [c.id]: "Chưa cập nhật được tiến trình. Hệ thống sẽ tự thử kết nối lại." }));
          }
        }
      } finally { fetching = false; }
    }, 2000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);
  const request = async (
    id: string,
    user: ChatMessage,
    assistantId?: string,
  ) => {
    if (busyRef.current.has(id)) return;
    busyRef.current.add(id);
    setBusyIds(new Set(busyRef.current));
    setErrors((e) => ({ ...e, [id]: "" }));
    failedRegeneration.current.delete(id);
    try {
      const response = await chatApi.sendMessage({
        conversationId: id,
        message: user,
        regenerateMessageId: assistantId,
        kg_confirmation: user.metadata?.kg_confirmation,
      });
      localRecordConversations.current.delete(id);
      const conversation = current.current[id];
      if (!conversation || deleted.current.has(id)) return;
      if (
        !response.message ||
        response.message.role !== "assistant" ||
        typeof response.message.content !== "string"
      )
        throw new Error(
          "Câu trả lời từ hệ thống không hợp lệ. Vui lòng thử lại.",
        );
      const messages = assistantId
        ? conversation.messages.map((m) =>
            m.id === assistantId ? response.message : m,
          )
        : [...conversation.messages, response.message];
      update(response.conversation ?? {
        ...conversation,
        assessment: response.assessment,
        messages,
        updatedAt: new Date().toISOString(),
      });
    } catch (e) {
      if (!deleted.current.has(id)) {
        if (assistantId) failedRegeneration.current.set(id, assistantId);
        setErrors((errors) => ({ ...errors, [id]: errorMessage(e) }));
        if (user.metadata?.kg_confirmation) {
          try {
            const fresh = await conversationApi.getConversation(id);
            if (fresh.messages.at(-1)?.id !== user.metadata.kg_confirmation.message_id) update(fresh);
          } catch { /* Keep the retryable request and visible error. */ }
        }
      }
    } finally {
      busyRef.current.delete(id);
      setBusyIds(new Set(busyRef.current));
    }
  };
  const send = (
    content: string,
    attachments: Attachment[],
    existingId?: string,
  ) => {
    const id = existingId ?? crypto.randomUUID();
    if (busyRef.current.has(id)) return id;
    const now = new Date().toISOString();
    const message: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content,
      attachments,
      createdAt: now,
    };
    const conversation = current.current[id] ?? {
      id,
      title: content.slice(0, 70) || "Tra cứu từ tài liệu",
      createdAt: now,
      updatedAt: now,
      messages: [],
    };
    update({
      ...conversation,
      messages: [...conversation.messages, message],
      updatedAt: now,
    });
    void request(id, message);
    return id;
  };
  const requestRecords = async (id: string, user: ChatMessage) => {
    const input = recordJobs.current.get(user.id);
    if (!input || busyRef.current.has(id)) return;
    busyRef.current.add(id);
    setBusyIds(new Set(busyRef.current));
    setErrors((e) => ({ ...e, [id]: "" }));
    const controller = new AbortController();
    recordControllers.current.set(id, controller);
    try {
      const result = await uploadApi.analyzeClinical(input.records, input.text, id, user.id,
        controller.signal, patch => { input.job = { ...input.job, ...patch } as Attachment; }, input.job);
      const answer = result.analysisAnswer || "Backend chưa trả nội dung kết quả.";
      const conversation = current.current[id];
      if (!conversation || deleted.current.has(id)) return;
      update({
        ...conversation,
        messages: [...conversation.messages, {
          id: crypto.randomUUID(), role: "assistant", kind: "medical_record",
          content: answer, createdAt: new Date().toISOString(),
          metadata: {route:"CLINICAL_ANALYSIS", sources:result.sources},
        }],
        updatedAt: new Date().toISOString(),
      });
      input.records.forEach(item=>releaseFileUrl(item.attachment.url));
      recordJobs.current.delete(user.id);
      localRecordConversations.current.delete(id);
    } catch (e) {
      if (!deleted.current.has(id) && !controller.signal.aborted)
        setErrors((errors) => ({ ...errors, [id]: errorMessage(e) }));
    } finally {
      recordControllers.current.delete(id);
      busyRef.current.delete(id);
      setBusyIds(new Set(busyRef.current));
    }
  };
  const confirmKG = (id: string, messageId: string, entityIds: string[]) => {
    const conversation = current.current[id];
    if (!conversation || busyRef.current.has(id) || conversation.messages.at(-1)?.id !== messageId) return;
    const pending = conversation.messages.at(-1)?.metadata?.kg_clarification;
    if (!pending?.can_confirm || entityIds.length !== pending.groups.length) return;
    const names = entityIds.map((eid, index) => pending.groups[index].candidates.find(c => c.id === eid)?.name);
    if (names.some(name => !name)) return;
    const now = new Date().toISOString();
    const message: ChatMessage = {
      id: crypto.randomUUID(), role: "user", content: `Tôi xác nhận: ${names.join("; ")}.`, createdAt: now,
      metadata: { kg_confirmation: { message_id: messageId, entity_ids: entityIds } },
    };
    update({ ...conversation, messages: [...conversation.messages, message], updatedAt: now });
    void request(id, message);
  };
  const sendRecords = (records: SelectedRecord[], existingId?: string, text = "") => {
    const id = existingId ?? crypto.randomUUID();
    if ((!records.length && !text.trim()) || busyRef.current.has(id)) return id;
    if (!current.current[id]) localRecordConversations.current.add(id);
    const now = new Date().toISOString();
    const message: ChatMessage = {
      id: crypto.randomUUID(), role: "user", kind: "medical_record",
      content: `Phân tích ${records.map((r) => r.attachment.fileName).join(", ") || "văn bản bệnh án"}`,
      createdAt: now,
    };
    const conversation = current.current[id] ?? {
      id, title: `Bệnh án: ${records[0]?.attachment.fileName || "Văn bản"}`.slice(0, 70),
      createdAt: now, updatedAt: now, messages: [],
    };
    recordJobs.current.set(message.id, {records,text});
    update({ ...conversation, messages: [...conversation.messages, message], updatedAt: now });
    void requestRecords(id, message);
    return id;
  };
  const retry = (id: string, assistantId?: string) => {
    assistantId = assistantId ?? failedRegeneration.current.get(id);
    const conversation = current.current[id];
    if (!conversation) return;
    if (conversation.assessment && !["completed", "cancelled"].includes(conversation.assessment.status)) {
      void conversationApi.getConversation(id).then(update).catch(e => setErrors(items => ({ ...items, [id]: errorMessage(e) })));
      return;
    }
    const targetIndex = assistantId
      ? conversation.messages.findIndex((m) => m.id === assistantId)
      : conversation.messages.length;
    const user = conversation.messages
      .slice(0, targetIndex)
      .findLast((m) => m.role === "user");
    if (user?.kind === "medical_record") void requestRecords(id, user);
    else if (user) void request(id, user, assistantId);
  };
  const rename = async (id: string, title: string) => {
    if (!localRecordConversations.current.has(id))
      await conversationApi.renameConversation(id, title);
    const conversation = current.current[id];
    if (conversation) update({ ...conversation, title });
    else
      setSummaries((items) =>
        items.map((i) => (i.id === id ? { ...i, title } : i)),
      );
  };
  const remove = async (id: string) => {
    if (!localRecordConversations.current.has(id))
      await conversationApi.deleteConversation(id);
    deleted.current.add(id);
    recordControllers.current.get(id)?.abort();
    current.current[id]?.messages.forEach((m) => {
      recordJobs.current.get(m.id)?.records.forEach(item => releaseFileUrl(item.attachment.url));
      recordJobs.current.delete(m.id);
    });
    localRecordConversations.current.delete(id);
    current.current[id]?.messages.forEach((m) =>
      m.attachments?.forEach((a) => releaseFileUrl(a.url)),
    );
    const next = { ...current.current };
    delete next[id];
    current.current = next;
    setConversations(next);
    setSummaries((items) => items.filter((i) => i.id !== id));
  };
  const feedback = (id: string, messageId: string, value: "up" | "down") => {
    const c = current.current[id];
    if (c)
      update({
        ...c,
        messages: c.messages.map((m) =>
          m.id === messageId
            ? { ...m, feedback: m.feedback === value ? undefined : value }
            : m,
        ),
      });
  };
  return (
    <ChatContext.Provider
      value={{
        ingestConversation: update,
        summaries,
        conversations,
        busyIds,
        errors,
        historyError,
        historyLoading,
        refreshHistory,
        loadConversation,
        send,
        sendRecords,
        confirmKG,
        assessmentAction,
        retry,
        rename,
        remove,
        feedback,
      }}
    >
      {children}
    </ChatContext.Provider>
  );
}
export function useChat() {
  const context = useContext(ChatContext);
  if (!context) throw new Error("ChatProvider missing");
  return context;
}
