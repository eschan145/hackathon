import { HashRouter, NavLink, Route, Routes } from "react-router-dom";
import { useEffect, useState } from "react";
import Home from "./pages/Home";
import Task from "./pages/Task";
import History from "./pages/History";
import Settings from "./pages/Settings";
import { TaskProvider } from "./TaskContext";
import { eventSocket } from "./hooks/useEventSocket";
import { api, ModelStatus } from "./api/client";

// Re-poll occasionally rather than fetch once: the backend caches this for
// 30s on its side anyway (see planning/openclaw_client.py), so this is just
// keeping a long-lived Electron window's badge honest if config/models.yaml
// changes and the backend restarts, without hammering the openclaw CLI.
const MODEL_STATUS_POLL_MS = 60_000;

function ModelStatusBadge() {
  const [status, setStatus] = useState<ModelStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    function load() {
      api
        .getModelStatus()
        .then((s) => {
          if (!cancelled) setStatus(s);
        })
        .catch(() => {
          if (!cancelled) setStatus(null);
        });
    }
    load();
    const id = setInterval(load, MODEL_STATUS_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  if (!status) {
    return <div className="model-status unknown">Model: unknown</div>;
  }

  const modeLabel = status.mode === "local" ? "Local" : status.mode === "cloud" ? "Cloud" : "Unknown";

  return (
    <div
      className={`model-status ${status.mode}`}
      title={status.error ? `${status.display_name} — ${status.error}` : status.display_name}
    >
      <span className={`model-dot ${status.mode}`} />
      {status.display_name} · {modeLabel}
    </div>
  );
}

function NavBar() {
  const [connected, setConnected] = useState(eventSocket.isConnected);

  useEffect(() => {
    eventSocket.connect();
    return eventSocket.onConnectionChange(setConnected);
  }, []);

  return (
    <div className="navbar">
      <span className="brand">Assistant</span>
      <NavLink to="/" end className={({ isActive }) => (isActive ? "active" : "")}>
        Home
      </NavLink>
      <NavLink to="/task" className={({ isActive }) => (isActive ? "active" : "")}>
        Task
      </NavLink>
      <NavLink to="/history" className={({ isActive }) => (isActive ? "active" : "")}>
        History
      </NavLink>
      <NavLink to="/settings" className={({ isActive }) => (isActive ? "active" : "")}>
        Settings
      </NavLink>
      <div className="navbar-right">
        <ModelStatusBadge />
        <div className="conn-status">
          <span className={`conn-dot ${connected ? "connected" : ""}`} />
          {connected ? "Connected" : "Disconnected"}
        </div>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <TaskProvider>
      <HashRouter>
        <div className="app-shell">
          <NavBar />
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/task" element={<Task />} />
            <Route path="/history" element={<History />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </div>
      </HashRouter>
    </TaskProvider>
  );
}
