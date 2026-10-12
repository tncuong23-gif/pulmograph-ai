import {
  ArrowLeft,
  Check,
  ChevronRight,
  CircleHelp,
  Globe2,
  Moon,
  RefreshCw,
  Server,
  ShieldCheck,
  Sun,
} from "lucide-react";
import { Link } from "react-router-dom";
import { useApp } from "../context/AppContext";
import { vi } from "../i18n/vi";
export function Settings() {
  const { theme, setTheme, status, checking, refreshStatus } = useApp();
  return (
    <main className="settings-page" id="main-content">
      <div className="settings-content">
        <Link to="/chat" className="back-link">
          <ArrowLeft size={16} />
          Trở về trò chuyện
        </Link>
        <div className="settings-heading">
          <h2>Cài đặt</h2>
          <p>Tùy chỉnh không gian làm việc của bạn.</p>
        </div>
        <section className="settings-section">
          <div className="settings-section-heading">
            <Server size={20} />
            <h3>Kết nối hệ thống</h3>
          </div>
          <div className="setting-row">
            <div>
              <strong>Trạng thái kết nối API</strong>
              <p>
                {status.mode === "mock"
                  ? "Đang sử dụng dữ liệu và câu trả lời mô phỏng."
                  : "Kết nối đến hệ thống y khoa của bạn."}
              </p>
            </div>
            <span
              className={`connection-badge ${!status.online ? "disconnected" : ""}`}
            >
              <span className="status-dot" />
              {checking
                ? "Đang kiểm tra"
                : status.mode === "mock"
                  ? "Demo"
                  : status.online
                    ? "Đã kết nối"
                    : "Mất kết nối"}
            </span>
          </div>
          <div className="system-details">
            <span>
              AI Assistant<strong>{status.model || "—"}</strong>
            </span>
            <span>
              Knowledge Base<strong>{status.online ? (status.knowledgeBase || "—") : "—"}</strong>
            </span>
          </div>
          <button
            className="secondary-button check-connection"
            disabled={checking}
            onClick={() => void refreshStatus()}
          >
            <RefreshCw size={15} />
            {checking ? "Đang kiểm tra…" : "Kiểm tra kết nối"}
          </button>
        </section>
        <section className="settings-section">
          <div className="settings-section-heading">
            <Sun size={20} />
            <h3>Giao diện</h3>
          </div>
          <p className="setting-description">
            Chọn chế độ hiển thị phù hợp với bạn.
          </p>
          <div
            className="theme-options"
            role="group"
            aria-label="Chế độ giao diện"
          >
            {(["light", "dark"] as const).map((value) => (
              <button
                key={value}
                className={`theme-option ${theme === value ? "selected" : ""}`}
                aria-pressed={theme === value}
                onClick={() => setTheme(value)}
              >
                <span className={`theme-miniature ${value}`}>
                  <i />
                  <span>
                    <i />
                    <i />
                    <i />
                  </span>
                </span>
                <span className="theme-option-label">
                  {value === "light" ? <Sun size={17} /> : <Moon size={17} />}{" "}
                  {value === "light" ? "Sáng" : "Tối"}
                  {theme === value && <Check size={17} />}
                </span>
              </button>
            ))}
          </div>
        </section>
        <section className="settings-section">
          <div className="setting-row">
            <div className="settings-section-heading">
              <Globe2 size={20} />
              <div>
                <h3>Ngôn ngữ</h3>
                <p>Ngôn ngữ hiển thị của ứng dụng.</p>
              </div>
            </div>
            <select aria-label="Ngôn ngữ" value="vi" onChange={() => {}}>
              <option value="vi">Tiếng Việt</option>
            </select>
          </div>
        </section>
        <section className="settings-section disclaimer-setting">
          <div className="settings-section-heading">
            <ShieldCheck size={20} />
            <h3>Lưu ý y khoa & dữ liệu</h3>
          </div>
          <p>{vi.disclaimer}</p>
          <p>
            {status.mode === "mock"
              ? "Trong phiên demo, bệnh án, ảnh và hội thoại chỉ nằm trong bộ nhớ của trình duyệt; không được gửi lên máy chủ và sẽ mất khi tải lại trang."
              : "Tệp được tải lên API đã cấu hình khi bạn chọn đính kèm. Hội thoại được gửi khi bạn nhấn Gửi. Ứng dụng không lưu bệnh án hoặc ảnh vào bộ nhớ lâu dài của trình duyệt."}
          </p>
          <div className="settings-note">
            <CircleHelp size={16} />
            <span>
              Ảnh DICOM có thể đính kèm; bản này chưa hỗ trợ hiển thị ảnh DICOM.
            </span>
          </div>
        </section>
        <Link className="settings-footer-link" to="/chat">
          Bắt đầu trò chuyện
          <ChevronRight size={16} />
        </Link>
      </div>
    </main>
  );
}
