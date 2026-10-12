import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";
export class ErrorBoundary extends Component<
  { children: ReactNode },
  { hasError: boolean }
> {
  state = { hasError: false };
  static getDerivedStateFromError() {
    return { hasError: true };
  }
  componentDidCatch(_error: Error, _info: ErrorInfo) {
    /* Integrate a redacted error reporter here; never log patient data. */
  }
  render() {
    return this.state.hasError ? (
      <main className="fatal-error">
        <h1>Không thể hiển thị giao diện</h1>
        <p>
          Vui lòng tải lại trang để tiếp tục. Dữ liệu của phiên demo sẽ được đặt
          lại.
        </p>
        <button
          className="primary-button"
          onClick={() => window.location.reload()}
        >
          Tải lại trang
        </button>
      </main>
    ) : (
      this.props.children
    );
  }
}
