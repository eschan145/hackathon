import { useEffect, useMemo, useRef, useState } from "react";
import { api, AssistantEvent, TaskStep } from "../api/client";
import { useEventSocket } from "../hooks/useEventSocket";
import { useTaskContext } from "../TaskContext";

const STATUS_ICON: Record<string, string> = {
  pending: "○",
  ready: "○",
  running: "◐",
  verified: "✅",
  failed: "❌",
  skipped: "➖",
};

interface StepState extends TaskStep {}

interface PendingApproval {
  stepId: string;
  description: string;
}

export default function Task() {
  const { activeTaskId } = useTaskContext();
  const { subscribe } = useEventSocket();
  const [statusText, setStatusText] = useState("No active task.");
  const [steps, setSteps] = useState<Record<string, StepState>>({});
  const [stepOrder, setStepOrder] = useState<string[]>([]);
  const [previewSrc, setPreviewSrc] = useState<string | null>(null);
  const [paused, setPaused] = useState(false);
  const [approval, setApproval] = useState<PendingApproval | null>(null);
  const stepsRef = useRef(steps);
  stepsRef.current = steps;

  // Load current task snapshot (covers the case where Task page is
  // opened/refreshed after the objective was already submitted).
  useEffect(() => {
    if (!activeTaskId) return;
    let cancelled = false;
    api
      .getTask(activeTaskId)
      .then((detail) => {
        if (cancelled) return;
        setStatusText(`Task ${detail.state}: ${detail.objective}`);
        if (detail.steps?.length) {
          const next: Record<string, StepState> = {};
          const order: string[] = [];
          for (const s of detail.steps) {
            next[s.id] = s;
            order.push(s.id);
          }
          setSteps(next);
          setStepOrder(order);
        }
      })
      .catch(() => {
        // Backend may not be up yet; fail gracefully.
      });
    return () => {
      cancelled = true;
    };
  }, [activeTaskId]);

  function upsertStep(stepId: string, description: string | undefined, status: string) {
    if (!stepId) return;
    setSteps((prev) => {
      const existing = prev[stepId];
      return {
        ...prev,
        [stepId]: {
          id: stepId,
          description: description ?? existing?.description ?? stepId,
          status,
          risk_level: existing?.risk_level,
        },
      };
    });
    setStepOrder((prev) => (prev.includes(stepId) ? prev : [...prev, stepId]));
  }

  useEffect(() => {
    const handlers: Array<() => void> = [];

    handlers.push(
      subscribe("objective_received", (e: AssistantEvent) => {
        if (activeTaskId && e.task_id !== activeTaskId) return;
        setStatusText(`Planning: ${(e.payload.objective as string) ?? ""}`);
      }),
    );
    handlers.push(
      subscribe("plan_generated", (e: AssistantEvent) => {
        if (activeTaskId && e.task_id !== activeTaskId) return;
        setStatusText(`Plan ready: ${e.payload.step_count ?? "?"} steps`);
      }),
    );
    handlers.push(
      subscribe("step_started", (e: AssistantEvent) => {
        if (activeTaskId && e.task_id !== activeTaskId) return;
        upsertStep(e.payload.step_id as string, e.payload.description as string, "running");
        maybeUpdatePreview(e);
      }),
    );
    handlers.push(
      subscribe("step_verified", (e: AssistantEvent) => {
        if (activeTaskId && e.task_id !== activeTaskId) return;
        upsertStep(e.payload.step_id as string, undefined, "verified");
        maybeUpdatePreview(e);
      }),
    );
    handlers.push(
      subscribe("step_failed", (e: AssistantEvent) => {
        if (activeTaskId && e.task_id !== activeTaskId) return;
        upsertStep(e.payload.step_id as string, undefined, "failed");
        maybeUpdatePreview(e);
      }),
    );
    handlers.push(
      subscribe("replanned", (e: AssistantEvent) => {
        if (activeTaskId && e.task_id !== activeTaskId) return;
        setStatusText("Replanning after failure...");
      }),
    );
    handlers.push(
      subscribe("approval_required", (e: AssistantEvent) => {
        if (activeTaskId && e.task_id !== activeTaskId) return;
        const stepId = e.payload.step_id as string;
        const description =
          (e.payload.description as string) || stepsRef.current[stepId]?.description || stepId;
        setApproval({ stepId, description });
      }),
    );
    handlers.push(
      subscribe("task_completed", (e: AssistantEvent) => {
        if (activeTaskId && e.task_id !== activeTaskId) return;
        setStatusText((e.payload.summary as string) || "Task completed.");
      }),
    );
    handlers.push(
      subscribe("task_failed", (e: AssistantEvent) => {
        if (activeTaskId && e.task_id !== activeTaskId) return;
        setStatusText(`Task failed: ${(e.payload.reason as string) || "unknown"}`);
      }),
    );

    return () => handlers.forEach((unsub) => unsub());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTaskId]);

  function maybeUpdatePreview(e: AssistantEvent) {
    const path =
      (e.payload.screenshot_ref as string) ||
      (e.payload.screenshot as string) ||
      (e.payload.screenshot_path as string);
    if (path) setPreviewSrc(path);
  }

  const orderedSteps = useMemo(() => stepOrder.map((id) => steps[id]).filter(Boolean), [
    stepOrder,
    steps,
  ]);

  async function togglePause() {
    // NOTE: pause/resume has no dedicated backend endpoint in the
    // documented contract (only cancel exists). This toggles local UI
    // state only, as a best-effort placeholder until the backend exposes
    // a real pause endpoint -- reconcile in src/api/client.ts if/when it does.
    setPaused((p) => !p);
    setStatusText(paused ? "Resumed" : "Paused");
  }

  async function cancelTask() {
    if (!activeTaskId) return;
    try {
      await api.cancelTask(activeTaskId);
      setStatusText("Cancelled");
    } catch {
      setStatusText("Cancel request failed (backend unavailable?)");
    }
  }

  async function resolveApproval(approved: boolean) {
    if (!activeTaskId || !approval) return;
    const { stepId } = approval;
    try {
      await api.approveStep(activeTaskId, { step_id: stepId, approved });
    } catch {
      // best-effort; UI still reflects the local decision
    }
    upsertStep(stepId, undefined, approved ? "running" : "failed");
    setApproval(null);
  }

  return (
    <div className="page">
      <div className="task-status-bar">{statusText}</div>

      <div className="task-columns">
        <div className="task-plan-col panel">
          <div className="col-heading">Plan</div>
          {orderedSteps.length === 0 ? (
            <div className="empty-state">No steps yet.</div>
          ) : (
            <div className="step-list">
              {orderedSteps.map((step) => (
                <div className="step-row" key={step.id}>
                  <span className="step-icon">{STATUS_ICON[step.status] ?? "?"}</span>
                  <div className="step-body">
                    <span className="step-desc">{step.description}</span>
                    <span className="step-substatus">{step.status}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="task-preview-col panel">
          <div className="col-heading">Screen preview</div>
          <div className="preview-frame">
            {previewSrc ? <img src={previewSrc} alt="Latest screenshot" /> : "No preview yet"}
          </div>
        </div>
      </div>

      <div className="task-controls">
        <button onClick={togglePause}>{paused ? "Resume" : "Pause"}</button>
        <button className="danger" onClick={cancelTask}>
          Cancel
        </button>
      </div>

      {approval && (
        <div className="modal-overlay">
          <div className="modal-box">
            <h2 className="modal-title">Approval Required</h2>
            <p className="modal-desc">
              This step is flagged high-risk and needs your approval:
              <br />
              <strong>{approval.description}</strong>
            </p>
            <div className="modal-actions">
              <button className="danger" onClick={() => resolveApproval(false)}>
                Deny
              </button>
              <button className="primary" onClick={() => resolveApproval(true)}>
                Approve
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
