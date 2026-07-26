import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import TaskComposer from "../components/TaskComposer";
import { BanIcon, MessageIcon } from "../lib/icons";
import {
  badgeFor,
  columnFor,
  formatDate,
  firstLine,
  formatElapsed,
  isRunning,
  taskProgress,
  taskSubtitle,
  useNow,
  useStore,
} from "../store";

/** Past this, a "running" task is stale enough that a date reads better. */
const SIX_HOURS_MS = 6 * 60 * 60 * 1000;

export default function Tasks() {
  const { tasks, tasksLoaded, error, cancelTask } = useStore();
  const [query, setQuery] = useState("");
  const navigate = useNavigate();
  const now = useNow(1000);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return tasks;
    return tasks.filter((t) => t.objective.toLowerCase().includes(q));
  }, [tasks, query]);

  return (
    <>
      <PageHeader
        title="Tasks"
        subtitle="Everything the assistant is working on, locally"
        search={{ value: query, onChange: setQuery, placeholder: "Filter objectives" }}
        help={[
          "One row per objective, newest first. Rows update live from the orchestrator.",
          "Progress counts steps the verifier confirmed against the plan's total.",
          "Add context, files, and links directly from the task composer. Press ⌘K to open it anywhere.",
        ]}
      />

      <div className="page-body">
        {error && <div className="banner">Backend unavailable — {error}</div>}

        <TaskComposer variant="inline" />

        {!tasksLoaded ? (
          <SkeletonTable />
        ) : rows.length === 0 ? (
          <div className="empty-state">
            <h3>{tasks.length === 0 ? "Nothing running yet" : "No matching tasks"}</h3>
            <p>
              {tasks.length === 0
                ? "Type an objective above — the planner decomposes it and starts executing locally."
                : "Try a different search term."}
            </p>
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Task</th>
                <th>Status</th>
                <th>Progress</th>
                <th>Started</th>
                <th className="right" />
              </tr>
            </thead>
            <tbody>
              {rows.map((task) => {
                const badge = badgeFor(task.state);
                const { done, total } = taskProgress(task);
                const finished = columnFor(task.state) === "done";
                const live = isRunning(task.state);
                return (
                  <tr
                    key={task.task_id}
                    className={live ? "is-live" : undefined}
                    onClick={() => navigate(`/chat/${task.task_id}`)}
                  >
                    <td>
                      <div className="cell-title">
                        {live && <span className="pulse" aria-hidden />}
                        {firstLine(task.objective)}
                      </div>
                      <div className={`cell-sub${live ? " shimmer" : ""}`}>{taskSubtitle(task)}</div>
                    </td>
                    <td>
                      <span className={`badge ${badge.tone}`}>{badge.label}</span>
                    </td>
                    <td className="cell-muted">
                      {total ? (
                        <span className="progress">
                          <span className="progress-bar">
                            <span style={{ width: `${(done / total) * 100}%` }} />
                          </span>
                          {done}/{total}
                        </span>
                      ) : (
                        <span className="cell-faint">planning…</span>
                      )}
                    </td>
                    <td className="cell-muted">
                      {live && task.created_at && now - task.created_at * 1000 < SIX_HOURS_MS ? (
                        <span className="elapsed">{formatElapsed(task.created_at * 1000, now)}</span>
                      ) : finished ? (
                        "—"
                      ) : (
                        formatDate(task.created_at)
                      )}
                    </td>
                    <td>
                      <div className="row-actions" onClick={(e) => e.stopPropagation()}>
                        <button
                          className="icon-btn sm"
                          title="Open task chat"
                          onClick={() => navigate(`/chat/${task.task_id}`)}
                        >
                          <MessageIcon size={15} />
                        </button>
                        <button
                          className="icon-btn sm"
                          title={finished ? "Run already finished" : "Cancel run"}
                          disabled={finished}
                          onClick={() => cancelTask(task.task_id)}
                        >
                          <BanIcon size={15} />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

function SkeletonTable() {
  return (
    <div className="skeleton-table" aria-hidden>
      {[0, 1, 2].map((i) => (
        <div className="skeleton-row" key={i}>
          <div className="sk sk-title" />
          <div className="sk sk-sub" />
        </div>
      ))}
    </div>
  );
}
