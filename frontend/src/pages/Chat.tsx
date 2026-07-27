import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import {
  AlertIcon,
  BanIcon,
  CheckCircleIcon,
  CloseIcon,
  LinkIcon,
  MoreIcon,
  PaperclipIcon,
  SendIcon,
} from "../lib/icons";
import {
  badgeFor,
  cleanStepText,
  formatElapsed,
  isRunning,
  taskProgress,
  useNow,
  useStore,
} from "../store";

const STEP_STATUS_LABEL: Record<string, string> = {
  pending: "Not started",
  ready: "Ready",
  running: "In progress",
  verified: "Completed",
  failed: "Failed",
  skipped: "Skipped",
};

export default function Chat() {
  const { taskId = "" } = useParams();
  const navigate = useNavigate();
  const {
    getTask,
    reasoning,
    chat,
    appendChat,
    approvals,
    resolveApproval,
    createTask,
    cancelTask,
    deleteTask,
    refresh,
    titleFor,
  } = useStore();
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [planOpen, setPlanOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [procedureBusy, setProcedureBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const hasMounted = useRef(false);
  const now = useNow(500);

  const task = getTask(taskId);
  const messages = chat[taskId] ?? [];
  const entries = reasoning[taskId] ?? [];
  const approval = approvals[taskId];
  const live = task ? isRunning(task.state) : false;

  useEffect(() => {
    if (!taskId) return;
    let cancelled = false;
    api
      .getTask(taskId)
      .then(() => {
        if (!cancelled) void refresh();
      })
      .catch(() => {
        if (!cancelled) setNotFound(true);
      });
    return () => {
      cancelled = true;
    };
  }, [taskId, refresh]);

  useEffect(() => {
    if (!hasMounted.current) {
      hasMounted.current = true;
      return;
    }
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages.length, approval?.stepId]);

  const activity = useMemo(() => {
    if (entries.length) {
      return entries.map((entry) => ({
        id: entry.id,
        lead: friendlyLead(entry.lead),
        detail: cleanStepText(entry.detail),
        ts: entry.ts,
        tone: toneForLead(entry.lead),
      }));
    }
    return (task?.steps ?? []).map((step, index) => ({
      id: step.id,
      lead: friendlyStep(step.status, step.description),
      detail: cleanStepText(step.description),
      ts: (task?.created_at ?? 0) * 1000 + index,
      tone: toneForLead(step.status),
    }));
  }, [entries, task]);

  async function addContext() {
    const text = draft.trim();
    if (!text || sending) return;
    setDraft("");
    appendChat(taskId, { role: "user", text });
    appendChat(taskId, {
      role: "assistant",
      text: approval
        ? "Context added. I’m still waiting for your approval decision."
        : live
          ? "Context added to this task."
          : "Context saved with this task.",
    });
  }

  async function createFollowUp() {
    const text = draft.trim();
    if (!text || sending) return;
    setSending(true);
    try {
      const followUpId = await createTask(text, `follow-up:${taskId}`);
      appendChat(taskId, { role: "user", text });
      appendChat(taskId, { role: "assistant", text: "Follow-up task created." });
      setDraft("");
      navigate(`/task/${followUpId}`);
    } catch (caught) {
      appendChat(taskId, {
        role: "assistant",
        text: `The follow-up could not be created: ${
          caught instanceof Error ? caught.message : "backend unavailable"
        }`,
      });
    } finally {
      setSending(false);
    }
  }

  async function decideProcedure(save: boolean) {
    if (procedureBusy) return;
    setProcedureBusy(true);
    try {
      await api.decideProcedure(taskId, save);
      await refresh();
    } finally {
      setProcedureBusy(false);
    }
  }

  if (!task && notFound) {
    return (
      <div className="view missing-view">
        <button className="back-link" onClick={() => navigate("/now")}>← Task Overview</button>
        <div className="quiet-empty">
          <h1>Task not found</h1>
          <p>It may have been removed or cleared after a backend restart.</p>
        </div>
      </div>
    );
  }

  if (!task) {
    return <div className="view task-loading"><span className="mini-spinner dark" /> Loading task</div>;
  }

  const badge = badgeFor(task.state);
  const { done, total } = taskProgress(task);
  const resources = taskResources(task.objective);
  const finished = ["COMPLETED", "FAILED", "CANCELLED"].includes(task.state.toUpperCase());
  const progress = total ? Math.round((done / total) * 100) : live ? 8 : 0;

  return (
    <div className="view conversation-view">
      <header className="conversation-header">
        <button className="back-link" onClick={() => navigate("/now")}>← Task Overview</button>
        <div className="conversation-title">
          <div>
            <h1>{titleFor(task)}</h1>
            <div className="conversation-meta">
              <span className={`status-pill ${badge.tone}`}>{badge.label}</span>
              <span>{progress}%</span>
              {task.created_at && <span>{formatElapsed(task.created_at * 1000, now)}</span>}
            </div>
          </div>
          <div className="conversation-actions">
            <button className={`plan-toggle${planOpen ? " active" : ""}`} onClick={() => setPlanOpen((open) => !open)}>
              Plan <span>{done}/{total || "—"}</span>
            </button>
            {!finished && <button className="stop-button" onClick={() => cancelTask(task.task_id)}><BanIcon size={16} /> Stop</button>}
            <div className="header-menu-wrap">
              <button className="icon-button" aria-label="More actions" onClick={() => setMenuOpen((open) => !open)}><MoreIcon /></button>
              {menuOpen && (
                <div className="header-menu">
                  <button className="danger" onClick={async () => {
                    if (!window.confirm(`Delete “${titleFor(task)}”?`)) return;
                    await deleteTask(task.task_id);
                    navigate("/now");
                  }}><CloseIcon size={14} /> Delete task</button>
                </div>
              )}
            </div>
          </div>
        </div>
        <div className="conversation-progress"><span style={{ width: `${progress}%` }} /></div>
      </header>

      <div className="conversation-shell">
        <main className="conversation-scroll" ref={scrollRef}>
          <div className="conversation-column">
            <article className="message user original-request">
              <span className="message-author">You</span>
              <p>{task.objective.split("\n\n")[0]}</p>
              {resources.length > 0 && (
                <div className="message-resources">
                  {resources.map((resource) => (
                    <span key={resource.value}>
                      {resource.kind === "file" ? <PaperclipIcon size={14} /> : <LinkIcon size={14} />}
                      {resource.value.split("/").pop()}
                    </span>
                  ))}
                </div>
              )}
            </article>

            {activity.length === 0 ? (
              <div className="working-message"><span className="mini-spinner dark" /> Preparing the task</div>
            ) : (
              <section className="activity-timeline" aria-label="Task activity">
                {activity.map((item, index) => (
                  <article className={`activity-update ${item.tone}${index === activity.length - 1 && live ? " current" : ""}`} key={item.id}>
                    <span className="activity-icon">{item.tone === "success" ? <CheckCircleIcon size={16} /> : <span />}</span>
                    <div>
                      <div><strong>{item.lead}</strong><time>{item.ts ? new Date(item.ts).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : ""}</time></div>
                      {item.detail && item.detail.toLowerCase() !== item.lead.toLowerCase() && <p>{item.detail}</p>}
                    </div>
                  </article>
                ))}
              </section>
            )}

            {approval && (
              <section className="approval-card">
                <div className="approval-heading">
                  <span><AlertIcon size={20} /></span>
                  <div><small>Approval required</small><h2>{approvalAction(approval.description)}</h2></div>
                </div>
                <dl>
                  <div><dt>Action</dt><dd>{approval.description}</dd></div>
                  <div><dt>Reason</dt><dd>This action can change an external account, file, or person.</dd></div>
                  <div><dt>Impact</dt><dd>Orchestratr will continue this task after your decision.</dd></div>
                </dl>
                <div className="approval-actions">
                  <button className="secondary-button" onClick={() => resolveApproval(taskId, false)}>Deny</button>
                  <button className="primary-button" onClick={() => resolveApproval(taskId, true)}>Allow once</button>
                </div>
              </section>
            )}

            {messages.map((message) => (
              <article className={`message ${message.role}`} key={message.id}>
                <span className="message-author">{message.role === "user" ? "You" : "Orchestratr"}</span>
                <p>{message.text}</p>
              </article>
            ))}

            {task.state === "COMPLETED" && (
              <section className="completion-card">
                <span><CheckCircleIcon size={20} /></span>
                <div>
                  <small>Completed</small>
                  <h2>Your task is ready</h2>
                  <p>{activity[activity.length - 1]?.detail || `${done} steps completed and checked.`}</p>
                </div>
              </section>
            )}

            {task.procedure_candidate?.status === "offered" && (
              <section className="procedure-card">
                <div>
                  <small>Reusable procedure</small>
                  <h2>Save “{task.procedure_candidate.name}”?</h2>
                  <p>{task.procedure_candidate.description}</p>
                </div>
                <div className="approval-actions">
                  <button className="secondary-button" disabled={procedureBusy} onClick={() => void decideProcedure(false)}>Not now</button>
                  <button className="primary-button" disabled={procedureBusy} onClick={() => void decideProcedure(true)}>Save procedure</button>
                </div>
              </section>
            )}

            {task.procedure_candidate?.status === "saved" && (
              <section className="procedure-card saved">
                <div><small>Procedure saved</small><h2>{task.procedure_candidate.name}</h2><p>This verified path is now in the local procedure library.</p></div>
              </section>
            )}
          </div>
        </main>

        <footer className="conversation-composer">
          <div className="conversation-input">
            <button className="attach-button" aria-label="Attach files"><PaperclipIcon size={18} /></button>
            <textarea
              value={draft}
              rows={1}
              aria-label="Add context"
              placeholder={finished ? "What should Orchestratr do next?" : "Add context"}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void addContext();
                }
              }}
            />
            <button className="send-button" onClick={() => void addContext()} disabled={!draft.trim()} aria-label="Send">
              <SendIcon size={17} />
            </button>
          </div>
          <button className="followup-button" onClick={() => void createFollowUp()} disabled={!draft.trim() || sending}>
            Create follow-up task
          </button>
        </footer>
      </div>

      <aside className={`plan-drawer${planOpen ? " open" : ""}`} aria-hidden={!planOpen}>
        <div className="drawer-header">
          <div><h2>Plan</h2><p>{done} of {total || 0} steps completed</p></div>
          <button className="icon-button" onClick={() => setPlanOpen(false)} aria-label="Close plan"><CloseIcon /></button>
        </div>
        {task.steps.length === 0 ? (
          <p className="drawer-empty">The plan will appear when preparation finishes.</p>
        ) : (
          <ol className="drawer-plan">
            {task.steps.map((step, index) => (
              <li className={step.status} key={step.id}>
                <span className="drawer-index">{index + 1}</span>
                <div>
                  <p>{cleanStepText(step.description)}</p>
                  <small>{STEP_STATUS_LABEL[step.status] ?? step.status}{step.risk_level === "high" ? " · Approval gate" : ""}</small>
                  {step.success_criteria && <details><summary>Verification details</summary><p>{step.success_criteria}</p></details>}
                </div>
              </li>
            ))}
          </ol>
        )}
      </aside>
    </div>
  );
}

function friendlyLead(lead: string): string {
  const value = lead.toLowerCase();
  if (value.includes("objective")) return "Reviewing your request";
  if (value.includes("plan generated")) return "Plan ready";
  if (value.includes("execut")) return "Working on the next step";
  if (value.includes("verif")) return "Checking the result";
  if (value.includes("replan")) return "Adjusting the approach";
  if (value.includes("plann")) return "Deciding the next action";
  if (value.includes("approv")) return "Waiting for your approval";
  if (value.includes("complete")) return "Your task is ready";
  if (value.includes("fail")) return "Something needs attention";
  if (value.includes("cancel")) return "Task stopped";
  return lead;
}

function friendlyStep(status: string, description: string): string {
  if (status === "verified") return "Completed a step";
  if (status === "running") return cleanStepText(description);
  if (status === "failed") return "A step could not be completed";
  return STEP_STATUS_LABEL[status] ?? "Preparing";
}

function toneForLead(lead: string): "neutral" | "active" | "success" | "danger" | "attention" {
  const value = lead.toLowerCase();
  if (value.includes("fail") || value.includes("cancel")) return "danger";
  if (value.includes("approv") || value.includes("wait")) return "attention";
  if (value.includes("verif") || value.includes("complete")) return "success";
  if (value.includes("execut") || value.includes("plan") || value.includes("replan") || value.includes("running")) return "active";
  return "neutral";
}

function approvalAction(description: string): string {
  const short = cleanStepText(description);
  return short.length > 72 ? "Allow this action?" : short;
}

function taskResources(objective: string): Array<{ kind: "file" | "link"; value: string }> {
  const resources: Array<{ kind: "file" | "link"; value: string }> = [];
  let kind: "file" | "link" | null = null;
  for (const line of objective.split("\n").slice(1)) {
    if (line.trim() === "Files to work with:") {
      kind = "file";
      continue;
    }
    if (line.trim() === "Links to use:") {
      kind = "link";
      continue;
    }
    if (kind && line.trim().startsWith("- ")) resources.push({ kind, value: line.trim().slice(2) });
  }
  return resources;
}
