import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppProvider } from "./context/AppContext";
import { ChatProvider } from "./context/ChatContext";
import { AppLayout } from "./components/layout/AppLayout";
import { ChatContainer } from "./components/chat/ChatContainer";
import { ErrorBoundary } from "./components/common/ErrorBoundary";
import { Landing } from "./pages/Landing";
import { Settings } from "./pages/Settings";
export default function App() {
  return (
    <ErrorBoundary>
      <AppProvider>
        <ChatProvider>
          <BrowserRouter>
            <a className="skip-link" href="#main-content">
              Đến nội dung chính
            </a>
            <Routes>
              <Route path="/" element={<Landing />} />
              <Route element={<AppLayout />}>
                <Route path="/chat/:conversationId?" element={<ChatContainer />} />
                <Route path="/settings" element={<Settings />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Route>
            </Routes>
          </BrowserRouter>
        </ChatProvider>
      </AppProvider>
    </ErrorBoundary>
  );
}
