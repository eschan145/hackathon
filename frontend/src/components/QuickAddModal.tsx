import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CloseIcon } from "../lib/icons";
import { useStore } from "../store";

const PRIORITIES = ["High", "Medium", "Low"];

/**
 * The objective is the only field the backend takes (POST /api/objectives),
 * so the extra fields are folded into it as natural-language context the
 * planner can actually act on rather than being dropped.
 */
function composeObjective(title: string, description: string, due: string, priority: string): string {
  const parts = [title.trim()];
  if (description.trim()) parts.push(description.trim());
  const context: string[] = [];
  if (due) {
    const d = new Date(`${due}T00:00:00`);
    if (!Number.isNaN(d.getTime())) {
      context.push(
        `Due ${d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}`,
      );
    }
  }
  if (priority) context.push(`Priority: ${priority}`);
  if (context.length) parts.push(context.join(" · "));
  return parts.join("\n\n");
}

export default function QuickAddModal() {
  const { quickAddOpen, setQuickAddOpen, createTask } = useStore();
  const navigate = useNavigate();

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [due, setDue] = useState("");
  const [priority, setPriority] = useState("High");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (quickAddOpen) {
      setTitle("");
      setDescription("");
      setDue("");
      setPriority("High");
      setError(null);
    }
  }, [quickAddOpen]);

  useEffect(() => {
    if (!quickAddOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setQuickAddOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [quickAddOpen, setQuickAddOpen]);

  if (!quickAddOpen) return null;

  async function submit() {
    if (!title.trim() || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const taskId = await createTask(composeObjective(title, description, due, priority), "gui");
      setQuickAddOpen(false);
      navigate(`/chat/${taskId}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not reach the backend.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="modal-overlay" onMouseDown={() => setQuickAddOpen(false)}>
      <div className="modal" role="dialog" aria-modal onMouseDown={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>Create New Task</h2>
          <button className="icon-btn ghost" onClick={() => setQuickAddOpen(false)} aria-label="Close">
            <CloseIcon />
          </button>
        </div>

        <label className="field">
          <span className="field-label">Task Title</span>
          <input
            autoFocus
            value={title}
            placeholder="e.g. Draft a reply to the unread email from Alex"
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
            }}
          />
        </label>

        <label className="field">
          <span className="field-label">Description</span>
          <textarea
            rows={3}
            value={description}
            placeholder="Describe details of the deliverable..."
            onChange={(e) => setDescription(e.target.value)}
          />
        </label>

        <div className="field-grid">
          <label className="field">
            <span className="field-label">Due Date</span>
            <input type="date" value={due} onChange={(e) => setDue(e.target.value)} />
          </label>
          <label className="field">
            <span className="field-label">Priority</span>
            <select value={priority} onChange={(e) => setPriority(e.target.value)}>
              {PRIORITIES.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </label>
        </div>

        {error && <div className="form-error">{error}</div>}

        <div className="modal-actions">
          <button className="btn-ghost" onClick={() => setQuickAddOpen(false)}>
            Cancel
          </button>
          <button className="btn-primary" onClick={submit} disabled={!title.trim() || submitting}>
            {submitting ? "Adding..." : "Add Task"}
          </button>
        </div>
      </div>
    </div>
  );
}
