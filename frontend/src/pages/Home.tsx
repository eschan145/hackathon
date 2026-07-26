import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useTaskContext } from "../TaskContext";

const QUICK_SOURCE_EXAMPLES: Record<string, string> = {
  todoist: "Complete my top 3 overdue Todoist tasks",
  gmail: "Reply to unread emails from my manager with a short status update",
  calendar: "Find a free 30-minute slot tomorrow and schedule a call with Alex",
  files: "Organize my Downloads folder into dated subfolders",
};

const QUICK_SOURCES: Array<{ key: string; label: string }> = [
  { key: "todoist", label: "Todoist" },
  { key: "gmail", label: "Gmail" },
  { key: "calendar", label: "Calendar" },
  { key: "files", label: "Files" },
];

export default function Home() {
  const [objective, setObjective] = useState("");
  const [source, setSource] = useState("manual");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();
  const { setActiveTaskId } = useTaskContext();

  function setQuickSource(key: string) {
    setObjective(QUICK_SOURCE_EXAMPLES[key] ?? "");
    setSource(key);
  }

  async function runObjective() {
    const text = objective.trim();
    if (!text || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await api.createObjective({ objective: text, source });
      setActiveTaskId(res.task_id);
      setObjective("");
      navigate("/task");
    } catch (e) {
      setError(
        e instanceof Error
          ? `Failed to submit objective: ${e.message}`
          : "Failed to submit objective.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="page">
      <div className="panel" style={{ maxWidth: 640, margin: "0 auto" }}>
        <h1 className="page-title">What do you want to get done?</h1>

        <div className="field-row">
          <input
            type="text"
            className="objective-input"
            placeholder="e.g. Book a table for 2 at 7pm tonight"
            value={objective}
            onChange={(e) => setObjective(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") runObjective();
            }}
          />
        </div>

        <span className="field-label">Quick sources (demo stubs):</span>
        <div className="quick-sources">
          {QUICK_SOURCES.map((s) => (
            <button key={s.key} onClick={() => setQuickSource(s.key)}>
              {s.label}
            </button>
          ))}
        </div>

        {error && <div style={{ color: "var(--danger-bright)", marginBottom: 12 }}>{error}</div>}

        <button
          className="primary run-button"
          onClick={runObjective}
          disabled={!objective.trim() || submitting}
        >
          {submitting ? "Submitting..." : "Run"}
        </button>
      </div>
    </div>
  );
}
