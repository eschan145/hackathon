import { useNavigate } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import { MessageIcon } from "../lib/icons";
import { firstLine, formatDate, useStore } from "../store";

/** A dedicated, in-app archive of chats for tasks marked complete. */
export default function CompletedChats() {
  const { tasks, tasksLoaded } = useStore();
  const navigate = useNavigate();
  const completedTasks = tasks.filter((task) => task.state === "COMPLETED");

  return (
    <>
      <PageHeader
        title="Completed chats"
        subtitle="Conversations for tasks you’ve finished"
        help={["Select a task to reopen its chat in the main window."]}
      />

      <div className="page-body">
        {!tasksLoaded ? (
          <div className="banner subtle">Loading completed chats…</div>
        ) : completedTasks.length === 0 ? (
          <div className="empty-state">
            <h3>No completed chats yet</h3>
            <p>Completed tasks will appear here so you can revisit their conversations.</p>
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Task</th>
                <th>Started</th>
                <th className="right" />
              </tr>
            </thead>
            <tbody>
              {completedTasks.map((task) => (
                <tr key={task.task_id} onClick={() => navigate(`/chat/${task.task_id}`)}>
                  <td>
                    <div className="cell-title">{firstLine(task.objective)}</div>
                    <div className="cell-sub">Completed</div>
                  </td>
                  <td className="cell-muted">{formatDate(task.created_at)}</td>
                  <td>
                    <div className="row-actions visible" onClick={(event) => event.stopPropagation()}>
                      <button
                        className="icon-btn sm"
                        title="Open completed chat"
                        onClick={() => navigate(`/chat/${task.task_id}`)}
                      >
                        <MessageIcon size={15} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
