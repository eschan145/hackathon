import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import { ChipIcon, GearIcon, SendIcon } from "../lib/icons";
import { api } from "../api/client";
import { badgeFor, useStore } from "../store";

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
  const { getTask, reasoning, chat, appendChat, approvals, resolveApproval, createTask, refresh } =
    useStore();
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const task = getTask(taskId);
  const messages = chat[taskId] ?? [];
  const entries = reasoning[taskId] ?? [];
  const approval = approvals[taskId];

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
  }, [messages.length, entries.length]);

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
        text: "Queued that as a follow-up objective. I'll plan it and start executing — track it on the Tasks board.",
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
        <PageHeader title="Task AI Chat" subtitle="Task not found" />
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

  return (
    <>
      <PageHeader
        title="Task AI Chat"
        subtitle={task ? `Collaborate with AI on '${task.objective.split("\n")[0]}'` : "Loading task…"}
        help={[
          "The reasoning panel mirrors the orchestrator's live event stream for this task.",
          "High-risk steps pause here until you approve or deny them.",
          "Anything you send is queued as a follow-up objective for the agent.",
        ]}
      />

      <div className="page-body chat-body" ref={scrollRef}>
        <section className="reasoning">
          <div className="reasoning-head">
            <GearIcon size={14} />
            AI Chain of Thought / Internal Reasoning
          </div>
          {reasoningLines.length === 0 ? (
            <p className="reasoning-empty">
              Waiting on the planner — reasoning steps will stream in here as the agent works.
            </p>
          ) : (
            <ol className="reasoning-list">
              {reasoningLines.map((line) => (
                <li key={line.id}>
                  <strong>{line.lead}:</strong> {line.detail}
                </li>
              ))}
            </ol>
          )}
          {badge && (
            <div className="reasoning-foot">
              <span className={`badge ${badge.tone}`}>{badge.label}</span>
              <span className="cell-muted">{steps.length} steps in plan</span>
            </div>
          )}
        </section>

        <div className="messages">
          {messages.map((m) => (
            <div className={`msg ${m.role}`} key={m.id}>
              <span className="msg-avatar">
                {m.role === "assistant" ? <ChipIcon size={15} /> : "You"}
              </span>
              <div className="msg-bubble">
                <span className="msg-label">{m.role === "assistant" ? "AI Copilot" : "You"}</span>
                <p>{m.text}</p>
              </div>
            </div>
          ))}

          {approval && (
            <div className="approval-card">
              <div>
                <span className="approval-title">Approval required</span>
                <p>{approval.description}</p>
              </div>
              <div className="approval-actions">
                <button className="btn-ghost" onClick={() => resolveApproval(taskId, false)}>
                  Deny
                </button>
                <button className="btn-primary" onClick={() => resolveApproval(taskId, true)}>
                  Approve
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="composer">
        <input
          value={draft}
          placeholder="Ask AI or type a response to redirect reasoning..."
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") send();
          }}
        />
        <button className="btn-primary send" onClick={send} disabled={!draft.trim() || sending} aria-label="Send">
          <SendIcon size={16} />
        </button>
      </div>
    </>
  );
}
