import { useEffect, useState } from "react";
import { api, TaskSummary } from "../api/client";

export default function History() {
  const [tasks, setTasks] = useState<TaskSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      const data = await api.listTasks();
      setTasks(data);
      setError(null);
    } catch (e) {
      setTasks([]);
      setError(
        e instanceof Error
          ? `Could not load history: ${e.message}`
          : "Could not load history (backend unavailable?).",
      );
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  return (
    <div className="page">
      <h1 className="page-title">Task History</h1>
      {error && <div style={{ color: "var(--danger-bright)", marginBottom: 16 }}>{error}</div>}
      {tasks === null ? (
        <div className="empty-state">Loading...</div>
      ) : tasks.length === 0 ? (
        <div className="empty-state">No task history available yet.</div>
      ) : (
        <div className="history-list">
          {tasks.map((t) => (
            <div className="history-row" key={t.task_id}>
              <div>
                <div className="objective">{t.objective}</div>
                <div className="meta">
                  {t.source ? `${t.source} · ` : ""}
                  {t.created_at ?? t.updated_at ?? ""}
                </div>
              </div>
              <span className={`badge ${t.state.toLowerCase()}`}>{t.state}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
