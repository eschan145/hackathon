import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import { ChipIcon, GearIcon, SendIcon } from "../lib/icons";
import { api } from "../api/client";
import { badgeFor, formatElapsed, isRunning, useNow, useStore } from "../store";

const STEP_STATUS_LABEL: Record<string, string> = {
  pending: "Queued",
  ready: "Ready",
  running: "Running",
  verified: "Verified",
  failed: "Failed",
  skipped: "Skipped",
};

export default function Chat() {
  const { taskId = "" } = useParams();
  const {
    getTask,
    reasoning,
    chat,
    appendChat,
    approvals,
    resolveApproval,
    holdApproval,
    createTask,
    refresh,
  } = useStore();
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const now = useNow(500);

  const task = getTask(taskId);
  const messages = chat[taskId] ?? [];
  const entries = reasoning[taskId] ?? [];
  const approval = approvals[taskId];
  const live = task ? isRunning(task.state) : false;

  // Pull the authoritative snapshot when landing directly on this view.
  useEffect(() => {
    if (!taskId) return;
    let cancelled = false;
    api
      .getTask(taskId)
      .then(() => {
        if (!cancelled) refresh();
      })
      .catch(() => {
        if (!cancelled) setNotFound(true);
      });
    return () => {
      cancelled = true;
    };
  }, [taskId, refresh]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages.length, entries.length, approval?.stepId]);

  const steps = task?.steps ?? [];

  const reasoningLines = useMemo(() => {
    if (entries.length) {
      return entries.map((e) => ({ id: e.id, lead: e.lead, detail: e.detail }));
    }
    return steps.map((s) => ({
      id: s.id,
      lead: STEP_STATUS_LABEL[s.status] ?? s.status,
      detail: s.description,
    }));
  }, [entries, steps]);

  async function send() {
    const text = draft.trim();
    if (!text || sending) return;
    setDraft("");
    appendChat(taskId, { role: "user", text });

    // There is no chat endpoint on the backend, so a message either adds
    // context to a pending approval decision or is submitted as a
    // follow-up objective the orchestrator can actually run.
    if (approval) {
      appendChat(taskId, {
        role: "assistant",
        text: "Noted. I'm still holding on your approval for the step above — approve or deny to continue.",
      });
      return;
    }

    setSending(true);
    try {
      await createTask(text, "chat");
      appendChat(taskId, {
        role: "assistant",
        text: "Queued that as a follow-up objective. I'll plan it and start executing — track it on the Tasks page.",
      });
    } catch (e) {
      appendChat(taskId, {
        role: "assistant",
        text: `I couldn't reach the backend to queue that: ${
          e instanceof Error ? e.message : "unknown error"
        }`,
      });
    } finally {
      setSending(false);
    }
  }

  if (!task && notFound) {
    return (
      <>
        <PageHeader title="Task" subtitle="Task not found" />
        <div className="page-body">
          <div className="empty-state">
            <h3>Unknown task</h3>
            <p>This task isn't in the backend's memory. It may have been cleared on restart.</p>
          </div>
        </div>
      </>
    );
  }

  const badge = task ? badgeFor(task.state) : null;
  const countdown = approval?.autoApproveAt
    ? Math.max(0, Math.ceil((approval.autoApproveAt - now) / 1000))
    : null;

  return (
    <>
      <PageHeader
        title={task ? task.objective.split("\n")[0] : "Task"}
        subtitle={
          task
            ? `${badge?.label ?? task.state} · ${steps.length} step${steps.length === 1 ? "" : "s"}${
                live && task.created_at ? ` · running ${formatElapsed(task.created_at * 1000, now)}` : ""
              }`
            : "Loading…"
        }
        help={[
          "The reasoning panel mirrors the orchestrator's live event stream for this task.",
          "High-risk steps pause here until you approve or deny them, unless Settings says otherwise.",
          "Anything you send is queued as a follow-up objective for the agent.",
        ]}
      />

      <div className="page-body chat-body" ref={scrollRef}>
        <div className="thread">
          <section className="reasoning">
            <div className="reasoning-head">
              <GearIcon size={13} className={live ? "spin" : undefined} />
              Chain of thought
              {live && <span className="live-tag">live</span>}
            </div>
            {reasoningLines.length === 0 ? (
              <p className="reasoning-empty">
                Waiting on the planner — reasoning streams in here as the agent works.
              </p>
            ) : (
              <ol className="reasoning-list">
                {reasoningLines.map((line, i) => (
                  <li key={line.id} className={i === reasoningLines.length - 1 && live ? "current" : undefined}>
                    <strong>{line.lead}:</strong> {line.detail}
                  </li>
                ))}
              </ol>
            )}
          </section>

          {messages.map((m) => (
            <div className={`msg ${m.role}`} key={m.id}>
              {m.role === "assistant" && (
                <span className="msg-avatar">
                  <ChipIcon size={14} />
                </span>
              )}
              <div className="msg-body">
                <p>{m.text}</p>
              </div>
            </div>
          ))}

          {live && (
            <div className="msg assistant">
              <span className="msg-avatar">
                <ChipIcon size={14} />
              </span>
              <div className="msg-body">
                <span className="typing" aria-label="Agent is working">
                  <i />
                  <i />
                  <i />
                </span>
              </div>
            </div>
          )}

          {approval && (
            <div className="approval-card">
              <div className="approval-copy">
                <span className="approval-title">
                  Approval required
                  {countdown !== null && <span className="countdown">auto-approving in {countdown}s</span>}
                </span>
                <p>{approval.description}</p>
              </div>
              <div className="approval-actions">
                {countdown !== null && (
                  <button className="btn-ghost" onClick={() => holdApproval(taskId)}>
                    Hold
                  </button>
                )}
                <button className="btn-ghost" onClick={() => resolveApproval(taskId, false)}>
                  Deny
                </button>
                <button className="btn-primary" onClick={() => resolveApproval(taskId, true)}>
                  Approve
                </button>
              </div>
              {countdown !== null && approval.autoApproveAt && (
                <span
                  className="approval-progress"
                  style={{
                    width: `${Math.max(0, Math.min(100, ((approval.autoApproveAt - now) / 10000) * 100))}%`,
                  }}
                />
              )}
            </div>
          )}
        </div>
      </div>

      <div className="composer">
        <div className="composer-pill">
          <input
            value={draft}
            placeholder="Ask the agent or add a follow-up objective…"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") send();
            }}
          />
          <button
            className="btn-primary send"
            onClick={send}
            disabled={!draft.trim() || sending}
            aria-label="Send"
          >
            <SendIcon size={15} />
          </button>
        </div>
      </div>
    </>
  );
}
