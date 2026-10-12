import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  ArrowUpRight,
  BookOpen,
  ChevronRight,
  Database,
  Info,
  Plus,
  Settings,
  ShieldCheck,
} from "lucide-react";
import { BrandMark } from "../common/BrandMark";
import { ConversationList } from "../conversations/ConversationList";
import { useApp } from "../../context/AppContext";
import { vi } from "../../i18n/vi";
import { API_BASE_URL } from "../../api/client";
export function Sidebar({ onNavigate }: { onNavigate: () => void }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { status, checking } = useApp();
  return (
    <div className="sidebar-inner">
      <Link to="/chat" className="brand" onClick={onNavigate}>
        <BrandMark />
        <strong>{vi.brand}</strong>
      </Link>
      <button
        className="new-chat-button"
        onClick={() => {
          navigate("/chat", { state: { reset: Date.now() } });
          onNavigate();
        }}
      >
        <Plus size={19} />
        {vi.newChat}
      </button>
      <div className="sidebar-section-label">
        CUỘC TRÒ CHUYỆN <span>{status.mode === "mock" ? "DEMO" : ""}</span>
      </div>
      <ConversationList onNavigate={onNavigate} />
      <div className="sidebar-bottom">
        <a href={`${API_BASE_URL}/data?return_to=${encodeURIComponent(window.location.origin)}`} className="settings-link" onClick={onNavigate}>
          <Database size={18} /> Quản lý dữ liệu <ChevronRight size={16} />
        </a>
        <div className="system-card">
          <div className="system-card-title">
            <span
              className={`status-dot ${status.online ? "online" : "offline"}`}
            />
            <strong>
              {checking
                ? "Đang kết nối…"
                : status.mode === "mock"
                  ? "AI System · Demo"
                  : status.online
                    ? "AI System Online"
                    : "Mất kết nối"}
            </strong>
          </div>
          <p>
            <BookOpen size={13} /> Knowledge Base{" "}
            {(status.mode === "mock" || (status.online && status.knowledgeBase)) && (
              <span>{status.mode === "mock" ? "Demo" : status.knowledgeBase}</span>
            )}
          </p>
          <Link to="/settings" onClick={onNavigate}>
            {vi.systemInfo}
            <ArrowUpRight size={14} />
          </Link>
        </div>
        <Link
          to="/settings"
          onClick={onNavigate}
          className={`settings-link ${location.pathname === "/settings" ? "active" : ""}`}
        >
          <Settings size={18} />
          {vi.settings}
          <ChevronRight size={16} />
        </Link>
        <div className="workspace-label">
          <span className="workspace-avatar">
            <ShieldCheck size={18} />
          </span>
          <div>
            Không gian làm việc<small>{vi.brandSubtitle}</small>
          </div>
          <Info size={15} />
        </div>
      </div>
    </div>
  );
}
