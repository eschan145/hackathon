import { useEffect } from "react";
import { HashRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import Sidebar from "./components/Sidebar";
import QuickAddModal from "./components/QuickAddModal";
import Tasks from "./pages/Tasks";
import Chat from "./pages/Chat";
import Settings from "./pages/Settings";
import Overlay from "./pages/Overlay";
import Onboarding from "./components/Onboarding";
import { StoreProvider, useStore } from "./store";

/** Cmd/Ctrl+K toggles Quick Add from anywhere. */
function Shortcuts() {
  const { setQuickAddOpen } = useStore();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setQuickAddOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setQuickAddOpen]);

  return null;
}

function AppContent() {
  const location = useLocation();
  const overlay = location.pathname === "/overlay";
  if (overlay) return <Routes><Route path="/overlay" element={<Overlay />} /></Routes>;

  return (
    <>
      <Shortcuts />
      <div className="app-shell">
        <Sidebar />
        <main className="main">
          <Routes>
            <Route path="/" element={<Navigate to="/now" replace />} />
            <Route path="/now" element={<Tasks />} />
            <Route path="/tasks" element={<Navigate to="/now" replace />} />
            <Route path="/overview" element={<Navigate to="/now" replace />} />
            <Route path="/notifications" element={<Navigate to="/now" replace />} />
            <Route path="/task/:taskId" element={<Chat />} />
            <Route path="/chat/:taskId" element={<Chat />} />
            <Route path="/archive" element={<Navigate to="/now" replace />} />
            <Route path="/completed-chats" element={<Navigate to="/now" replace />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/now" replace />} />
          </Routes>
        </main>
      </div>
      <QuickAddModal />
      <Onboarding />
    </>
  );
}

export default function App() {
  return (
    <StoreProvider>
      <HashRouter>
        <AppContent />
      </HashRouter>
    </StoreProvider>
  );
}
