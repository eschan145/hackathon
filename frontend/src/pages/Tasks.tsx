import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import { MessageIcon } from "../lib/icons";
import { TaskRecord } from "../api/client";
import {
  badgeFor,
  Column,
  columnFor,
  formatDate,
  taskProgress,
  taskSubtitle,
  useStore,
} from "../store";

const COLUMNS: Array<{ key: Column; label: string; dot: string }> = [
  { key: "ongoing", label: "Ongoing", dot: "blue" },
  { key: "next", label: "Up Next", dot: "amber" },
  { key: "done", label: "Completed", dot: "green" },
];

export default function Tasks() {
  const { tasks, tasksLoaded, error, setQuickAddOpen } = useStore();
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return tasks;
    return tasks.filter((t) => t.objective.toLowerCase().includes(q));
  }, [tasks, query]);

  const grouped = useMemo(() => {
    const map: Record<Column, TaskRecord[]> = { ongoing: [], next: [], done: [] };
    for (const t of filtered) map[columnFor(t.state)].push(t);
    return map;
  }, [filtered]);

  return (
    <>
      <PageHeader
        title="Tasks"
        subtitle="Organize and monitor ongoing deliverables"
        search={{ value: query, onChange: setQuery, placeholder: "Filter objectives" }}
        help={[
          "Every card is a live objective running through the local orchestrator.",
          "Ongoing covers planning, executing and verifying. Up Next holds queued work and steps waiting on your approval.",
          "Open a card to watch the agent's reasoning and approve high-risk steps.",
        ]}
      />

      <div className="page-body">
        {error && <div className="banner">Backend unavailable — {error}</div>}

        {tasksLoaded && tasks.length === 0 ? (
          <div className="empty-state">
            <h3>No tasks yet</h3>
            <p>Give the assistant an objective and it will plan and execute it locally.</p>
            <button className="btn-primary" onClick={() => setQuickAddOpen(true)}>
              Quick Add Task
            </button>
          </div>
        ) : (
          <div className="board">
            {COLUMNS.map((col) => (
              <section className="board-col" key={col.key}>
                <div className="col-head">
                  <span className={`dot ${col.dot}`} />
                  <span className="col-title">{col.label}</span>
                  <span className="col-count">{grouped[col.key].length}</span>
                </div>
                <div className="col-cards">
                  {grouped[col.key].map((task) => (
                    <TaskCard key={task.task_id} task={task} done={col.key === "done"} />
                  ))}
                </div>
              </section>
            ))}
          </div>
        )}
      </div>
    </>
  );
}

function TaskCard({ task, done }: { task: TaskRecord; done: boolean }) {
  const navigate = useNavigate();
  const badge = badgeFor(task.state);
  const { done: completed, total } = taskProgress(task);
  const open = () => navigate(`/chat/${task.task_id}`);

  return (
    <article
      className={`card${done ? " is-done" : ""}`}
      onClick={open}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter") open();
      }}
    >
      <div className="card-top">
        <span className={`badge ${badge.tone}`}>{badge.label}</span>
        <span className="card-date">{done ? "Done" : formatDate(task.created_at)}</span>
      </div>
      <h3 className="card-title">{task.objective}</h3>
      <p className="card-desc">{taskSubtitle(task)}</p>
      <div className="card-foot">
        <span className="card-meta">
          {total ? `${completed}/${total} steps` : "Planning…"}
          <span className="meta-sep">·</span>
          {task.source}
        </span>
        <span className="card-action" aria-hidden>
          <MessageIcon size={16} />
        </span>
      </div>
    </article>
  );
}
