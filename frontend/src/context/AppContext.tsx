import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import type { ReactNode } from "react";
import type { SystemStatus, Theme } from "../types";
import { systemApi } from "../api/systemApi";
import { USE_MOCK_API } from "../api/client";
interface AppState {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  status: SystemStatus;
  checking: boolean;
  refreshStatus: () => Promise<void>;
  toast: (message: string) => void;
  notice: string;
}
const AppContext = createContext<AppState | null>(null);
export function AppProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => {
    try {
      return localStorage.getItem("medical-ai-theme") === "dark"
        ? "dark"
        : "light";
    } catch {
      return "light";
    }
  });
  const [status, setStatus] = useState<SystemStatus>({
    online: false,
    model: "",
    knowledgeBase: "",
    mode: USE_MOCK_API ? "mock" : "live",
  });
  const [checking, setChecking] = useState(true);
  const [notice, setNotice] = useState("");
  const setTheme = (value: Theme) => {
    setThemeState(value);
    try {
      localStorage.setItem("medical-ai-theme", value);
    } catch {
      /* preferences are optional */
    }
  };
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
  }, [theme]);
  const refreshStatus = useCallback(async () => {
    setChecking(true);
    try {
      setStatus(await systemApi.getStatus());
    } catch {
      setStatus((s) => ({ ...s, online: false }));
    } finally {
      setChecking(false);
    }
  }, []);
  useEffect(() => {
    void refreshStatus();
  }, [refreshStatus]);
  useEffect(() => {
    if (notice) {
      const timer = setTimeout(() => setNotice(""), 3500);
      return () => clearTimeout(timer);
    }
  }, [notice]);
  return (
    <AppContext.Provider
      value={{
        theme,
        setTheme,
        status,
        checking,
        refreshStatus,
        toast: setNotice,
        notice,
      }}
    >
      {children}
      <div className={`toast ${notice ? "visible" : ""}`} role="status">
        {notice}
      </div>
    </AppContext.Provider>
  );
}
export function useApp() {
  const context = useContext(AppContext);
  if (!context) throw new Error("AppProvider missing");
  return context;
}
