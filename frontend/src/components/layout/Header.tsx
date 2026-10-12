import { Link, useNavigate } from "react-router-dom";
import { House, Menu, Plus, Settings } from "lucide-react";
import { vi } from "../../i18n/vi";
export function Header({ onMenu }: { onMenu: () => void }) {
  const navigate = useNavigate();
  return (
    <header className="app-header">
      <button
        className="icon-button mobile-menu"
        onClick={onMenu}
        aria-label="Mở menu"
      >
        <Menu size={22} />
      </button>
      <div className="header-title">
        <h1>{vi.title}</h1>
        <p>{vi.subtitle}</p>
      </div>
      <div className="header-actions">
        <button
          className="header-new"
          onClick={() => navigate("/chat", { state: { reset: Date.now() } })}
          title="Cuộc trò chuyện mới"
        >
          <Plus size={18} />
          <span>Trò chuyện mới</span>
        </button>
        <Link to="/" className="icon-button" title="Trang giới thiệu" aria-label="Trang giới thiệu"><House size={19} /></Link>
        <span className="header-divider" />
        <Link
          className="icon-button"
          to="/settings"
          aria-label="Cài đặt"
          title="Cài đặt"
        >
          <Settings size={19} />
        </Link>
      </div>
    </header>
  );
}
