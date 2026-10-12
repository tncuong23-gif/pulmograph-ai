import { useState } from "react";
import { Link, useNavigate, useMatch } from "react-router-dom";
import * as Menu from "@radix-ui/react-dropdown-menu";
import { MessageSquare, MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import { useChat } from "../../context/ChatContext";
import { useApp } from "../../context/AppContext";
import { vi } from "../../i18n/vi";
import type { ConversationSummary } from "../../types";
import { Modal } from "../common/Modal";
import { ErrorState } from "../common/ErrorState";
import { errorMessage } from "../../api/client";
function groupLabel(date: string) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const day = new Date(date);
  day.setHours(0, 0, 0, 0);
  const days = Math.round((today.getTime() - day.getTime()) / 86400000);
  return days <= 0
    ? vi.today
    : days === 1
      ? vi.yesterday
      : days <= 7
        ? vi.week
        : vi.older;
}
export function ConversationList({ onNavigate }: { onNavigate: () => void }) {
  const {
    summaries,
    historyLoading,
    historyError,
    refreshHistory,
    rename,
    remove,
    busyIds,
  } = useChat();
  const conversationId = useMatch("/chat/:conversationId")?.params
    .conversationId;
  const navigate = useNavigate();
  const { toast } = useApp();
  const [editing, setEditing] = useState<{
    item: ConversationSummary;
    action: "rename" | "delete";
  } | null>(null);
  const [title, setTitle] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const groups = [vi.today, vi.yesterday, vi.week, vi.older]
    .map((label) => ({
      label,
      items: summaries.filter((i) => groupLabel(i.updatedAt) === label),
    }))
    .filter((g) => g.items.length);
  const close = () => {
    if (!saving) {
      setEditing(null);
      setError("");
    }
  };
  const submit = async () => {
    if (!editing) return;
    setSaving(true);
    setError("");
    try {
      if (editing.action === "rename") {
        await rename(editing.item.id, title.trim());
        toast("Đã đổi tên cuộc trò chuyện");
      } else {
        await remove(editing.item.id);
        if (conversationId === editing.item.id) navigate("/chat");
        toast("Đã xóa cuộc trò chuyện");
      }
      setEditing(null);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };
  return (
    <>
      <div className="history-list" aria-label="Lịch sử trò chuyện">
        {historyLoading && (
          <div className="history-skeleton" aria-label="Đang tải lịch sử">
            <i />
            <i />
            <i />
          </div>
        )}
        {historyError && (
          <ErrorState
            message={historyError}
            onRetry={() => void refreshHistory()}
          />
        )}
        {!historyLoading && !historyError && !summaries.length && (
          <p className="history-empty">
            Các cuộc trò chuyện của bạn sẽ xuất hiện ở đây.
          </p>
        )}
        {groups.map((group) => (
          <section key={group.label} className="history-group">
            <h3>{group.label}</h3>
            {group.items.map((item) => (
              <div
                key={item.id}
                className={`conversation-item ${conversationId === item.id ? "selected" : ""}`}
              >
                <Link
                  to={`/chat/${item.id}`}
                  onClick={onNavigate}
                  title={item.title}
                >
                  <MessageSquare size={16} />
                  <span>
                    {item.title}
                    <small>
                      {new Date(item.updatedAt).toLocaleTimeString("vi-VN", {
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                      {busyIds.has(item.id) ? " · Đang trả lời" : ""}
                    </small>
                  </span>
                </Link>
                <Menu.Root>
                  <Menu.Trigger asChild>
                    <button
                      className="icon-button conversation-menu"
                      aria-label={`Tùy chọn: ${item.title}`}
                      title="Tùy chọn"
                    >
                      <MoreHorizontal size={17} />
                    </button>
                  </Menu.Trigger>
                  <Menu.Portal>
                    <Menu.Content
                      className="dropdown-menu"
                      sideOffset={5}
                      align="end"
                    >
                      <Menu.Item
                        disabled={busyIds.has(item.id)}
                        onSelect={() => {
                          setEditing({ item, action: "rename" });
                          setTitle(item.title);
                          setError("");
                        }}
                      >
                        <Pencil size={15} />
                        {vi.rename}
                      </Menu.Item>
                      <Menu.Item
                        className="danger"
                        disabled={busyIds.has(item.id)}
                        onSelect={() => {
                          setEditing({ item, action: "delete" });
                          setError("");
                        }}
                      >
                        <Trash2 size={15} />
                        {vi.delete}
                      </Menu.Item>
                    </Menu.Content>
                  </Menu.Portal>
                </Menu.Root>
              </div>
            ))}
          </section>
        ))}
      </div>
      <Modal
        open={!!editing}
        onOpenChange={(open) => {
          if (!open) close();
        }}
        title={
          editing?.action === "rename"
            ? "Đổi tên cuộc trò chuyện"
            : "Xóa cuộc trò chuyện?"
        }
        description={
          editing?.action === "delete"
            ? `Cuộc trò chuyện “${editing.item.title}” sẽ bị xóa khỏi lịch sử. Bạn không thể hoàn tác thao tác này.`
            : undefined
        }
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          {editing?.action === "rename" && (
            <label className="field-label">
              Tên cuộc trò chuyện
              <input
                autoFocus
                className="text-input"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                maxLength={100}
                required
              />
            </label>
          )}
          {error && <ErrorState message={error} />}
          <div className="modal-actions">
            <button
              type="button"
              className="secondary-button"
              onClick={close}
              disabled={saving}
            >
              {vi.cancel}
            </button>
            <button
              className={
                editing?.action === "delete"
                  ? "danger-button"
                  : "primary-button"
              }
              disabled={
                saving || (editing?.action === "rename" && !title.trim())
              }
            >
              {saving
                ? "Đang lưu…"
                : editing?.action === "delete"
                  ? vi.delete
                  : vi.save}
            </button>
          </div>
        </form>
      </Modal>
    </>
  );
}
