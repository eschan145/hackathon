import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import { BanIcon, MessageIcon } from "../lib/icons";
import { badgeFor, columnFor, formatDate, taskProgress, taskSubtitle, useStore } from "../store";

export default function Overview() {
  const { tasks, tasksLoaded, error, cancelTask } = useStore();
  const [query, setQuery] = useState("");
  const navigate = useNavigate();

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return tasks;
    return tasks.filter((t) => t.objective.toLowerCase().includes(q));
  }, [tasks, query]);

  return (
    <>
      <PageHeader
        title="Overview"
        subtitle="Comprehensive status and document tracker"
        search={{ value: query, onChange: setQuery, placeholder: "Filter objectives" }}
        help={[
          "One row per objective the assistant has received, newest first.",
          "Progress counts steps the verifier has confirmed against the plan's total.",
          "Stop cancels the in-flight run on the backend.",
        ]}
      />

      <div className="page-body">
        {error && <div className="banner">Backend unavailable — {error}</div>}

        {tasksLoaded && rows.length === 0 ? (
          <div className="empty-state">
            <h3>{tasks.length === 0 ? "Nothing tracked yet" : "No matching tasks"}</h3>
            <p>
              {tasks.length === 0
                ? "Objectives you submit will appear here with their live status."
                : "Try a different search term."}
            </p>
          </div>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Task Name</th>
                  <th>Status</th>
                  <th>Created</th>
                  <th>Progress</th>
                  <th className="right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((task) => {
                  const badge = badgeFor(task.state);
                  const { done, total } = taskProgress(task);
                  const finished = columnFor(task.state) === "done";
                  return (
                    <tr key={task.task_id}>
                      <td>
                        <div className="cell-title">{task.objective}</div>
                        <div className="cell-sub">{taskSubtitle(task)}</div>
                      </td>
                      <td>
                        <span className={`badge ${badge.tone}`}>{badge.label}</span>
                      </td>
                      <td className="cell-muted">
                        {finished ? "Completed" : formatDate(task.created_at)}
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
                          "—"
                        )}
                      </td>
                      <td>
                        <div className="row-actions">
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
          </div>
        )}
      </div>
    </>
  );
}
