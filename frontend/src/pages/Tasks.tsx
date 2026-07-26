import { MouseEvent, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { TaskRecord } from "../api/client";
import TaskComposer from "../components/TaskComposer";
import { BanIcon, CheckCircleIcon, MoreIcon } from "../lib/icons";
import {
  badgeFor,
  formatElapsed,
  formatRelative,
  isRunning,
  taskProgress,
  taskSubtitle,
  useNow,
  useStore,
} from "../store";

type Filter = "all" | "running" | "attention" | "completed" | "failed";

export default function Tasks() {
  const { tasks, tasksLoaded, error, approvals } = useStore();
  const [filter, setFilter] = useState<Filter>("all");
  const navigate = useNavigate();
  const now = useNow(1000);

  const counts = useMemo(
    () => ({
      all: tasks.length,
      running: tasks.filter((task) => isRunning(task.state)).length,
      attention: tasks.filter(
        (task) => task.state === "AWAITING_APPROVAL" || Boolean(approvals[task.task_id]),
      ).length,
      completed: tasks.filter((task) => task.state === "COMPLETED").length,
      failed: tasks.filter((task) => ["FAILED", "CANCELLED"].includes(task.state)).length,
    }),
    [approvals, tasks],
  );

  const visible = useMemo(() => {
    const filtered = tasks.filter((task) => {
      if (filter === "running") return isRunning(task.state);
      if (filter === "attention") {
        return task.state === "AWAITING_APPROVAL" || Boolean(approvals[task.task_id]);
      }
      if (filter === "completed") return task.state === "COMPLETED";
      if (filter === "failed") return ["FAILED", "CANCELLED"].includes(task.state);
      return true;
    });
    return filtered.sort((a, b) => {
      const aAttention = a.state === "AWAITING_APPROVAL" || Boolean(approvals[a.task_id]);
      const bAttention = b.state === "AWAITING_APPROVAL" || Boolean(approvals[b.task_id]);
      if (aAttention !== bAttention) return aAttention ? -1 : 1;
      return (b.created_at ?? 0) - (a.created_at ?? 0);
    });
  }, [approvals, filter, tasks]);

  return (
    <div className="view overview-view">
      <header className="overview-header">
        <div>
          <h1>Task Overview</h1>
          <p>{counts.running} running · {counts.attention} {counts.attention === 1 ? "needs" : "need"} approval</p>
        </div>
      </header>

      <div className="overview-content">
        {error && (
          <div className="offline-banner" role="status">
            <span className="system-dot" />
            Backend offline
            <span>Tasks already loaded remain available.</span>
          </div>
        )}

        <section className="new-task-section" aria-labelledby="new-task-title">
          <div className="section-heading">
            <div>
              <h2 id="new-task-title">New task</h2>
              <p>Describe the result you want.</p>
            </div>
          </div>
          <TaskComposer variant="inline" onCreated={(taskId) => navigate(`/task/${taskId}`)} />
        </section>

        <section className="today-section" aria-labelledby="today-title">
          <div className="section-heading table-heading">
            <div>
              <h2 id="today-title">Today’s tasks</h2>
              <p>Active and recently created tasks.</p>
            </div>
            <div className="task-filters" role="tablist" aria-label="Filter tasks">
              {([
                ["all", "All"],
                ["running", "Running"],
                ["attention", "Needs attention"],
                ["completed", "Completed"],
                ["failed", "Failed"],
              ] as Array<[Filter, string]>).map(([value, label]) => (
                <button
                  role="tab"
                  aria-selected={filter === value}
                  className={filter === value ? "active" : ""}
                  key={value}
                  onClick={() => setFilter(value)}
                >
                  {label} <span>{counts[value]}</span>
                </button>
              ))}
            </div>
          </div>

          {!tasksLoaded ? (
            <div className="task-table-loading" aria-label="Loading tasks">
              <span /><span /><span />
            </div>
          ) : visible.length === 0 ? (
            <div className="table-empty">
              <h3>{tasks.length ? "No tasks in this view" : "No tasks yet"}</h3>
              <p>{tasks.length ? "Choose another filter." : "Start with the composer above."}</p>
            </div>
          ) : (
            <div className="task-table" role="table" aria-label="Today’s tasks">
              <div className="task-table-head" role="row">
                <span role="columnheader">Task</span>
                <span role="columnheader">Status</span>
                <span role="columnheader">Current action</span>
                <span role="columnheader">Progress</span>
                <span role="columnheader">Started</span>
                <span role="columnheader">Actions</span>
              </div>
              {visible.map((task) => <TaskRow task={task} now={now} key={task.task_id} />)}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function TaskRow({ task, now }: { task: TaskRecord; now: number }) {
  const { approvals, cancelTask, completeTask, deleteTask, titleFor } = useStore();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  const badge = badgeFor(task.state);
  const { done, total } = taskProgress(task);
  const live = isRunning(task.state);
  const finished = ["COMPLETED", "FAILED", "CANCELLED"].includes(task.state.toUpperCase());
  const needsApproval = Boolean(approvals[task.task_id]) || task.state === "AWAITING_APPROVAL";
  const progress = total ? Math.round((done / total) * 100) : live ? 8 : 0;

  function stop(event: MouseEvent) {
    event.stopPropagation();
  }

  return (
    <div
      className={`task-table-row${needsApproval ? " attention" : ""}`}
      role="row"
      tabIndex={0}
      onClick={() => navigate(`/task/${task.task_id}`)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") navigate(`/task/${task.task_id}`);
      }}
    >
      <div className="table-task" role="cell">
        <span className={`table-status-dot ${badge.tone}${live ? " live" : ""}`} />
        <strong>{titleFor(task)}</strong>
      </div>
      <div role="cell"><span className={`status-pill ${badge.tone}`}>{badge.label}</span></div>
      <div className="current-action" role="cell">{needsApproval ? "Waiting for your decision" : taskSubtitle(task)}</div>
      <div className="table-progress" role="cell">
        <span className="progress-track"><span style={{ width: `${progress}%` }} /></span>
        <span>{total ? `${done} of ${total}` : live ? "Planning" : "—"}</span>
      </div>
      <div className="started-time" role="cell">
        {live && task.created_at
          ? formatElapsed(task.created_at * 1000, now)
          : task.created_at
            ? formatRelative(task.created_at * 1000)
            : "—"}
      </div>
      <div className="table-actions" role="cell" onClick={stop}>
        {!finished && (
          <>
            <button aria-label="Stop task" title="Stop task" onClick={() => cancelTask(task.task_id)}><BanIcon size={16} /></button>
            <button aria-label="Mark complete" title="Mark complete" onClick={() => completeTask(task.task_id)}><CheckCircleIcon size={16} /></button>
          </>
        )}
        <button aria-label="More task actions" onClick={() => setMenuOpen((open) => !open)}><MoreIcon size={18} /></button>
        {menuOpen && (
          <div className="row-menu">
            <button className="danger" onClick={() => {
              if (window.confirm(`Delete “${titleFor(task)}”?`)) void deleteTask(task.task_id);
            }}>Delete task</button>
          </div>
        )}
      </div>
    </div>
  );
}
