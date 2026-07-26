import { HashRouter, NavLink, Route, Routes } from "react-router-dom";
import { useEffect, useState } from "react";
import Home from "./pages/Home";
import Task from "./pages/Task";
import History from "./pages/History";
import Settings from "./pages/Settings";
import { TaskProvider } from "./TaskContext";
import { eventSocket } from "./hooks/useEventSocket";

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
      <div className="conn-status">
        <span className={`conn-dot ${connected ? "connected" : ""}`} />
        {connected ? "Connected" : "Disconnected"}
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
