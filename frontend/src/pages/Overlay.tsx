import { useState } from "react";
import { useNavigate } from "react-router-dom";
import OrchestratrLogo from "../components/OrchestratrLogo";
import TaskComposer from "../components/TaskComposer";
import { AlertIcon, CheckCircleIcon } from "../lib/icons";
import { badgeFor, isRunning, taskSubtitle, useStore } from "../store";

export default function Overlay() {
  const { tasks, approvals, connected, titleFor } = useStore();
  const [pinned, setPinned] = useState(false);
  const navigate = useNavigate();
  const needsApproval = tasks.filter(
    (task) => task.state === "AWAITING_APPROVAL" || Boolean(approvals[task.task_id]),
  );
  const running = tasks.filter((task) => isRunning(task.state));
  const recent = tasks.filter((task) => !needsApproval.includes(task) && !running.includes(task)).slice(0, 5);

  function openTask(taskId: string) {
    window.orchestratrDesktop?.openFullApp();
    navigate(`/task/${taskId}`);
  }

  return (
    <div className="overlay-app">
      <header className="overlay-header">
        <OrchestratrLogo size={30} wordmark />
        <div className="overlay-controls">
          <span className={`connection-chip${connected ? " online" : ""}`}>{connected ? "Connected" : "Offline"}</span>
          <button
            className={`pin-button${pinned ? " active" : ""}`}
            onClick={() => {
              const next = !pinned;
              setPinned(next);
              window.orchestratrDesktop?.setOverlayPinned(next);
            }}
          >
            {pinned ? "Pinned" : "Pin"}
          </button>
        </div>
      </header>

      <div className="overlay-scroll">
        <section className="overlay-new">
          <h1>New task</h1>
          <TaskComposer variant="inline" onCreated={openTask} />
        </section>

        {needsApproval.length > 0 && (
          <OverlaySection title="Needs approval" count={needsApproval.length}>
            {needsApproval.map((task) => (
              <button className="overlay-task attention" key={task.task_id} onClick={() => openTask(task.task_id)}>
                <span><AlertIcon size={18} /></span>
                <div><strong>{titleFor(task)}</strong><small>Waiting for your decision</small></div>
              </button>
            ))}
          </OverlaySection>
        )}

        {running.length > 0 && (
          <OverlaySection title="Running" count={running.length}>
            {running.map((task) => (
              <button className="overlay-task" key={task.task_id} onClick={() => openTask(task.task_id)}>
                <span className="overlay-live" />
                <div><strong>{titleFor(task)}</strong><small>{taskSubtitle(task)}</small></div>
              </button>
            ))}
          </OverlaySection>
        )}

        {recent.length > 0 && (
          <OverlaySection title="Recent" count={recent.length}>
            {recent.map((task) => {
              const badge = badgeFor(task.state);
              return (
                <button className="overlay-task" key={task.task_id} onClick={() => openTask(task.task_id)}>
                  <span className={`overlay-state ${badge.tone}`}>{task.state === "COMPLETED" && <CheckCircleIcon size={16} />}</span>
                  <div><strong>{titleFor(task)}</strong><small>{badge.label}</small></div>
                </button>
              );
            })}
          </OverlaySection>
        )}
      </div>

      <footer className="overlay-footer">
        <button onClick={() => window.orchestratrDesktop?.openFullApp()}>Open full app <span>↗</span></button>
      </footer>
    </div>
  );
}

function OverlaySection({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  return (
    <section className="overlay-section">
      <div><h2>{title}</h2><span>{count}</span></div>
      {children}
    </section>
  );
}
