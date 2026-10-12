import { useState } from "react";
import { Outlet } from "react-router-dom";
import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { Sidebar } from "./Sidebar";
import { Header } from "./Header";
export function AppLayout() {
  const [open, setOpen] = useState(false);
  return (
    <div className="app-layout">
      <aside className="desktop-sidebar">
        <Sidebar onNavigate={() => {}} />
      </aside>
      <Dialog.Root open={open} onOpenChange={setOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="modal-overlay drawer-overlay" />
          <Dialog.Content className="mobile-sidebar">
            <Dialog.Title className="sr-only">
              Điều hướng và lịch sử
            </Dialog.Title>
            <Dialog.Description className="sr-only">
              Lịch sử cuộc trò chuyện và cài đặt
            </Dialog.Description>
            <Dialog.Close
              className="icon-button drawer-close"
              aria-label="Đóng menu"
            >
              <X size={19} />
            </Dialog.Close>
            <Sidebar onNavigate={() => setOpen(false)} />
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
      <div className="main-panel">
        <Header onMenu={() => setOpen(true)} />
        <Outlet />
      </div>
    </div>
  );
}
