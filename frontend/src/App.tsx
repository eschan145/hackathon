import { useEffect } from "react";
import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import Sidebar from "./components/Sidebar";
import QuickAddModal from "./components/QuickAddModal";
import Tasks from "./pages/Tasks";
import Overview from "./pages/Overview";
import Chat from "./pages/Chat";
import Notifications from "./pages/Notifications";
import Settings from "./pages/Settings";
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

export default function App() {
  return (
    <StoreProvider>
      <HashRouter>
        <Shortcuts />
        <div className="app-shell">
          <Sidebar />
          <main className="main">
            <div className="surface">
              <Routes>
                <Route path="/" element={<Navigate to="/tasks" replace />} />
                <Route path="/tasks" element={<Tasks />} />
                <Route path="/overview" element={<Overview />} />
                <Route path="/notifications" element={<Notifications />} />
                <Route path="/chat/:taskId" element={<Chat />} />
                <Route path="/settings" element={<Settings />} />
                <Route path="*" element={<Navigate to="/tasks" replace />} />
              </Routes>
            </div>
          </main>
        </div>
        <QuickAddModal />
      </HashRouter>
    </StoreProvider>
  );
}
