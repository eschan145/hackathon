import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api, AssistantEvent, TaskRecord, TaskStep } from "./api/client";
import { eventSocket } from "./hooks/useEventSocket";

/**
 * Single app-wide store. Every view (Tasks, Chat, Notifications) renders
 * off this: REST gives the durable task list, the /ws/events websocket
 * layers live step + state updates on top so the UI reacts without polling.
 */

/**
 * How approval requests are handled. The orchestrator only ever asks for
 * steps it classified `risk_level: "high"` (core/orchestrator.py), so
 * "ask" already means "ask on high-risk only".
 *
 * Auto-approval is resolved by this client against POST /api/tasks/{id}/approve,
 * so it only applies while the app is open — a run started and left
 * unattended still blocks if the window is closed.
 */
export type ApprovalMode = "ask" | "auto";

export interface NotificationItem {
  id: string;
  kind: "info" | "warning" | "success";
  title: string;
  body: string;
  ts: number;
  taskId: string;
}

export interface ReasoningEntry {
  id: string;
  lead: string;
  detail: string;
  ts: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  ts: number;
}

export interface PendingApproval {
  stepId: string;
  description: string;
}

interface StoreValue {
  tasks: TaskRecord[];
  tasksLoaded: boolean;
  error: string | null;
  connected: boolean;
  refresh: () => Promise<void>;
  getTask: (taskId: string) => TaskRecord | undefined;
  notifications: NotificationItem[];
  unreadCount: number;
  markNotificationsRead: () => void;
  reasoning: Record<string, ReasoningEntry[]>;
  chat: Record<string, ChatMessage[]>;
  appendChat: (taskId: string, message: Omit<ChatMessage, "id" | "ts">) => void;
  approvals: Record<string, PendingApproval | undefined>;
  resolveApproval: (taskId: string, approved: boolean) => Promise<void>;
  approvalMode: ApprovalMode;
  setApprovalMode: (mode: ApprovalMode) => void;
  createTask: (objective: string, source: string) => Promise<string>;
  cancelTask: (taskId: string) => Promise<void>;
  completeTask: (taskId: string) => Promise<void>;
  deleteTask: (taskId: string) => Promise<void>;
  clearAllTasks: () => Promise<number>;
  restartTask: (taskId: string) => Promise<string>;
  taskTitles: Record<string, string>;
  titleFor: (task: TaskRecord) => string;
  renameTask: (taskId: string, title: string) => void;
  quickAddOpen: boolean;
  setQuickAddOpen: React.Dispatch<React.SetStateAction<boolean>>;
}

const StoreContext = createContext<StoreValue | undefined>(undefined);

let seq = 0;
const nextId = () => `${Date.now().toString(36)}-${(seq++).toString(36)}`;

const str = (v: unknown, fallback = ""): string => (typeof v === "string" ? v : fallback);

function readStored<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

/** A task the websocket told us about but that REST hasn't returned yet. */
function placeholderTask(taskId: string, objective: string, source: string): TaskRecord {
  return {
    task_id: taskId,
    objective: objective || "New objective",
    state: "RECEIVED",
    source: source || "gui",
    created_at: Date.now() / 1000,
    steps: [],
    history: [],
  };
}

export function StoreProvider({ children }: { children: React.ReactNode }) {
  const [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [tasksLoaded, setTasksLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(eventSocket.isConnected);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [readAt, setReadAt] = useState(0);
  const [reasoning, setReasoning] = useState<Record<string, ReasoningEntry[]>>(() =>
    readStored("orchestratr.activity.v2", {}),
  );
  const [chat, setChat] = useState<Record<string, ChatMessage[]>>(() =>
    readStored("orchestratr.chat.v2", {}),
  );
  const [taskTitles, setTaskTitles] = useState<Record<string, string>>(() =>
    readStored("orchestratr.titles.v2", {}),
  );
  const [approvals, setApprovals] = useState<Record<string, PendingApproval | undefined>>({});
  const [quickAddOpen, setQuickAddOpen] = useState(false);
  const [approvalMode, setApprovalModeState] = useState<ApprovalMode>("ask");

  // Read inside the websocket handler, which must not re-subscribe when the
  // mode changes mid-run.
  const approvalModeRef = useRef(approvalMode);
  approvalModeRef.current = approvalMode;
  const resolveRef =
    useRef<(taskId: string, approved: boolean, stepIdOverride?: string) => Promise<void>>();
  const tasksRef = useRef(tasks);
  tasksRef.current = tasks;
  const approvalsRef = useRef(approvals);
  approvalsRef.current = approvals;

  /** Look up a step's description from the plan we already hold. */
  const stepDescription = useCallback(
    (taskId: string, stepId: string) =>
      tasksRef.current.find((t) => t.task_id === taskId)?.steps.find((s) => s.id === stepId)
        ?.description ?? "",
    [],
  );

  const refresh = useCallback(async () => {
    try {
      const list = await api.listTasks();
      setTasks((prev) => {
        // Keep websocket-only tasks that the backend hasn't persisted yet.
        const byId = new Map(list.map((t) => [t.task_id, t]));
        for (const t of prev) {
          if (!byId.has(t.task_id)) byId.set(t.task_id, t);
        }
        return [...byId.values()].sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0));
      });
      const conversations = await Promise.allSettled(
        list.map(async (task) => ({
          taskId: task.task_id,
          messages: (await api.getConversation(task.task_id)).messages,
        })),
      );
      setChat((prev) => {
        const next = { ...prev };
        for (const result of conversations) {
          if (result.status !== "fulfilled" || !result.value.messages.length) continue;
          const local = next[result.value.taskId] ?? [];
          const byId = new Map(local.map((message) => [message.id, message]));
          for (const message of result.value.messages) {
            byId.set(message.id, {
              id: message.id,
              role: message.role,
              text: message.text,
              ts: message.created_at,
            });
          }
          next[result.value.taskId] = [...byId.values()].sort((a, b) => a.ts - b.ts);
        }
        return next;
      });
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Backend unavailable");
    } finally {
      setTasksLoaded(true);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    localStorage.setItem("orchestratr.chat.v2", JSON.stringify(chat));
  }, [chat]);

  useEffect(() => {
    localStorage.setItem("orchestratr.activity.v2", JSON.stringify(reasoning));
  }, [reasoning]);

  useEffect(() => {
    localStorage.setItem("orchestratr.titles.v2", JSON.stringify(taskTitles));
  }, [taskTitles]);

  useEffect(() => {
    api
      .getSettings()
      .then((s) => {
        const mode = (s as { approval_mode?: ApprovalMode }).approval_mode;
        if (mode === "ask" || mode === "auto") setApprovalModeState(mode);
      })
      .catch(() => {
        // Backend down: keep the safe default ("ask").
      });
  }, []);

  // ---- live event wiring ------------------------------------------------

  const pushNotification = useCallback((n: Omit<NotificationItem, "id" | "ts">) => {
    setNotifications((prev) => [{ ...n, id: nextId(), ts: Date.now() }, ...prev].slice(0, 60));
  }, []);

  const pushReasoning = useCallback((taskId: string, lead: string, detail: string) => {
    if (!taskId) return;
    setReasoning((prev) => {
      const list = prev[taskId] ?? [];
      return { ...prev, [taskId]: [...list, { id: nextId(), lead, detail, ts: Date.now() }] };
    });
  }, []);

  const pushAssistantMessage = useCallback((taskId: string, text: string) => {
    if (!taskId) return;
    const message: ChatMessage = {
      id: nextId(),
      role: "assistant",
      text,
      ts: Date.now(),
    };
    setChat((prev) => {
      const list = prev[taskId] ?? [];
      return {
        ...prev,
        [taskId]: [...list, message],
      };
    });
    void api
      .appendConversation(taskId, {
        id: message.id,
        role: message.role,
        text: message.text,
        created_at: message.ts,
      })
      .catch(() => {
        // Local storage remains the offline fallback and will merge on reconnect.
      });
  }, []);

  /** Merge a partial task update coming off the websocket. */
  const patchTask = useCallback(
    (taskId: string, patch: Partial<TaskRecord>, fallback?: Partial<TaskRecord>) => {
      if (!taskId) return;
      setTasks((prev) => {
        const idx = prev.findIndex((t) => t.task_id === taskId);
        if (idx === -1) {
          const created = {
            ...placeholderTask(taskId, str(fallback?.objective), str(fallback?.source, "gui")),
            ...patch,
          };
          return [created, ...prev];
        }
        const next = [...prev];
        next[idx] = { ...next[idx], ...patch };
        return next;
      });
    },
    [],
  );

  /** Upsert one step's status on a task without clobbering the rest. */
  const patchStep = useCallback((taskId: string, stepId: string, patch: Partial<TaskStep>) => {
    if (!taskId || !stepId) return;
    setTasks((prev) => {
      const idx = prev.findIndex((t) => t.task_id === taskId);
      if (idx === -1) return prev;
      const task = prev[idx];
      const steps = [...task.steps];
      const sIdx = steps.findIndex((s) => s.id === stepId);
      if (sIdx === -1) {
        steps.push({
          id: stepId,
          description: patch.description ?? stepId,
          status: patch.status ?? "pending",
          ...patch,
        });
      } else {
        steps[sIdx] = { ...steps[sIdx], ...patch };
      }
      const next = [...prev];
      next[idx] = { ...task, steps };
      return next;
    });
  }, []);

  useEffect(() => {
    eventSocket.connect();
    const offConn = eventSocket.onConnectionChange(setConnected);

    const off = eventSocket.subscribe("*", (e: AssistantEvent) => {
      const taskId = e.task_id;
      const p = e.payload ?? {};

      switch (e.type) {
        case "objective_received": {
          const objective = str(p.objective, "New objective");
          patchTask(taskId, { state: "PLANNING" }, { objective, source: str(p.source, "gui") });
          pushReasoning(taskId, "Objective received", objective);
          pushNotification({
            kind: "info",
            title: "New objective received",
            body: objective,
            taskId,
          });
          break;
        }
        case "plan_generated": {
          const count = Number(p.step_count ?? 0);
          patchTask(taskId, { state: "EXECUTING" });
          pushReasoning(
            taskId,
            "Plan generated",
            `Decomposed the objective into ${count || "several"} step${count === 1 ? "" : "s"}.`,
          );
          pushNotification({
            kind: "info",
            title: "Plan ready",
            body: `Planner produced ${count || "a"} step${count === 1 ? "" : "s"} for this objective.`,
            taskId,
          });
          // Plan details land in REST; pull the authoritative step list.
          refresh();
          break;
        }
        case "planning_next_step": {
          patchTask(taskId, { state: "PLANNING" });
          pushReasoning(taskId, "Planning", "Deciding the next action.");
          break;
        }
        case "step_started": {
          const desc = str(p.description, str(p.step_id));
          patchTask(taskId, { state: "EXECUTING" });
          patchStep(taskId, str(p.step_id), { status: "running", description: desc || undefined });
          pushReasoning(taskId, "Executing", desc);
          break;
        }
        case "step_verified": {
          const desc = str(p.description);
          patchStep(taskId, str(p.step_id), { status: "verified" });
          pushReasoning(taskId, "Verified", desc || "Step passed verification.");
          break;
        }
        case "step_failed": {
          const reason = str(p.reason, str(p.error, "Verification failed."));
          patchStep(taskId, str(p.step_id), { status: "failed" });
          pushReasoning(taskId, "Step failed", reason);
          pushNotification({ kind: "warning", title: "Step failed", body: reason, taskId });
          break;
        }
        case "replanned": {
          patchTask(taskId, { state: "REPLANNING" });
          pushReasoning(taskId, "Replanning", str(p.reason, "Adjusting the plan after a failure."));
          refresh();
          break;
        }
        case "approval_required": {
          const stepId = str(p.step_id);
          // The orchestrator emits only step_id, so recover the human-readable
          // action from the plan we already hold.
          const known = stepDescription(taskId, stepId);
          const description = str(p.description, known || "This step needs your approval.");
          const mode = approvalModeRef.current;
          patchTask(taskId, { state: "AWAITING_APPROVAL" });

          if (mode === "auto") {
            pushReasoning(taskId, "Auto-approved", `${description} (autonomous mode)`);
            pushNotification({
              kind: "info",
              title: "Auto-approved a high-risk step",
              body: description,
              taskId,
            });
            resolveRef.current?.(taskId, true, stepId);
            break;
          }

          setApprovals((prev) => ({ ...prev, [taskId]: { stepId, description } }));
          pushReasoning(taskId, "Approval required", description);
          pushAssistantMessage(
            taskId,
            `This step is flagged high-risk and needs your approval before I continue: ${description}`,
          );
          pushNotification({
            kind: "warning",
            title: "Approval needed",
            body: description,
            taskId,
          });
          break;
        }
        case "task_completed": {
          const summary = str(p.summary, "Task completed.");
          patchTask(taskId, { state: "COMPLETED" });
          setApprovals((prev) => ({ ...prev, [taskId]: undefined }));
          pushReasoning(taskId, "Completed", summary);
          pushAssistantMessage(taskId, summary);
          pushNotification({ kind: "success", title: "Task completed", body: summary, taskId });
          refresh();
          break;
        }
        case "task_failed": {
          const reason = str(p.reason, "Unknown failure.");
          patchTask(taskId, { state: "FAILED" });
          setApprovals((prev) => ({ ...prev, [taskId]: undefined }));
          pushReasoning(taskId, "Failed", reason);
          pushAssistantMessage(taskId, `I couldn't finish this task: ${reason}`);
          pushNotification({ kind: "warning", title: "Task failed", body: reason, taskId });
          refresh();
          break;
        }
        case "task_cancelled": {
          // The real, backend-confirmed cancellation - supersedes the
          // optimistic "FAILED" patch cancelTask() applies immediately on
          // click (see below), which fires before the orchestrator has
          // actually unwound and can't know whether cancellation truly
          // took effect.
          patchTask(taskId, { state: "CANCELLED" });
          setApprovals((prev) => ({ ...prev, [taskId]: undefined }));
          refresh();
          break;
        }
        default:
          break;
      }
    });

    return () => {
      off();
      offConn();
    };
  }, [patchTask, patchStep, pushNotification, pushReasoning, pushAssistantMessage, refresh]);

  // ---- actions ----------------------------------------------------------

  const createTask = useCallback(
    async (objective: string, source: string) => {
      const res = await api.createObjective({ objective, source });
      patchTask(res.task_id, {}, { objective, source });
      refresh();
      return res.task_id;
    },
    [patchTask, refresh],
  );

  const cancelTask = useCallback(
    async (taskId: string) => {
      await api.cancelTask(taskId);
      // Optimistic - the orchestrator hasn't actually unwound yet at this
      // point (it may be mid-await on a model call), so this is a guess.
      // The "task_cancelled" websocket event (emitted once
      // core/orchestrator.py's run_task actually catches the
      // CancelledError and persists it) is what makes this authoritative.
      patchTask(taskId, { state: "CANCELLED" });
      pushReasoning(taskId, "Cancelled", "Run stopped from the UI.");
    },
    [patchTask, pushReasoning],
  );

  const completeTask = useCallback(
    async (taskId: string) => {
      await api.completeTask(taskId);
      const steps = tasksRef.current.find((task) => task.task_id === taskId)?.steps.map((step) => ({
        ...step,
        status:
          step.status === "pending" || step.status === "ready" || step.status === "running"
            ? "skipped"
            : step.status,
      }));
      patchTask(taskId, { state: "COMPLETED", steps });
      pushReasoning(taskId, "Completed manually", "Marked complete from the task list.");
    },
    [patchTask, pushReasoning],
  );

  const deleteTask = useCallback(async (taskId: string) => {
    await api.deleteTask(taskId);
    setTasks((prev) => prev.filter((task) => task.task_id !== taskId));
    setApprovals((prev) => ({ ...prev, [taskId]: undefined }));
    setReasoning((prev) => {
      const { [taskId]: _removed, ...remaining } = prev;
      return remaining;
    });
    setChat((prev) => {
      const { [taskId]: _removed, ...remaining } = prev;
      return remaining;
    });
    setTaskTitles((prev) => {
      const { [taskId]: _removed, ...remaining } = prev;
      return remaining;
    });
  }, []);

  const clearAllTasks = useCallback(async () => {
    const { deleted_count } = await api.clearAllTasks();
    setTasks([]);
    setApprovals({});
    setReasoning({});
    setChat({});
    setTaskTitles({});
    setNotifications([]);
    return deleted_count;
  }, []);

  const restartTask = useCallback(
    async (taskId: string) => {
      const source = tasksRef.current.find((task) => task.task_id === taskId);
      if (!source) throw new Error("Task not found");
      return createTask(source.objective, `restart:${taskId}`);
    },
    [createTask],
  );

  const renameTask = useCallback((taskId: string, title: string) => {
    const next = title.trim();
    setTaskTitles((prev) => {
      if (!next) {
        const { [taskId]: _removed, ...remaining } = prev;
        return remaining;
      }
      return { ...prev, [taskId]: next };
    });
  }, []);

  const titleFor = useCallback(
    (task: TaskRecord) => taskTitles[task.task_id] || firstLine(task.objective),
    [taskTitles],
  );

  /**
   * Resolve an approval. `stepIdOverride` lets autonomous mode answer an
   * approval that was never parked in state for the user to see.
   */
  const resolveApproval = useCallback(
    async (taskId: string, approved: boolean, stepIdOverride?: string) => {
      const pending = approvalsRef.current[taskId];
      const stepId = stepIdOverride ?? pending?.stepId;
      if (!stepId) return;
      const description = pending?.description ?? stepDescription(taskId, stepId) ?? "step";
      try {
        await api.approveStep(taskId, { step_id: stepId, approved });
      } finally {
        setApprovals((prev) => ({ ...prev, [taskId]: undefined }));
        patchStep(taskId, stepId, { status: approved ? "running" : "skipped" });
        patchTask(taskId, { state: approved ? "EXECUTING" : "REPLANNING" });
        if (pending) {
          pushReasoning(
            taskId,
            approved ? "Approved" : "Denied",
            `${description} — ${approved ? "proceeding" : "skipped by you"}.`,
          );
        }
      }
    },
    [patchStep, patchTask, pushReasoning, stepDescription],
  );
  resolveRef.current = resolveApproval;

  const setApprovalMode = useCallback((mode: ApprovalMode) => {
    setApprovalModeState(mode);
    // Persist alongside the rest of the settings; SettingsModel allows extra
    // keys, so approval_mode round-trips through config/settings.yaml.
    api
      .getSettings()
      .then((s) => api.saveSettings({ ...s, approval_mode: mode }))
      .catch(() => {
        // Backend down: the mode still applies for this session.
      });
  }, []);

  const appendChat = useCallback((taskId: string, message: Omit<ChatMessage, "id" | "ts">) => {
    const fullMessage: ChatMessage = { ...message, id: nextId(), ts: Date.now() };
    setChat((prev) => {
      const list = prev[taskId] ?? [];
      return { ...prev, [taskId]: [...list, fullMessage] };
    });
    void api
      .appendConversation(taskId, {
        id: fullMessage.id,
        role: fullMessage.role,
        text: fullMessage.text,
        created_at: fullMessage.ts,
      })
      .catch(() => {
        // Keep the message locally until the backend is available.
      });
  }, []);

  const markNotificationsRead = useCallback(() => setReadAt(Date.now()), []);

  const getTaskById = useCallback(
    (taskId: string) => tasks.find((t) => t.task_id === taskId),
    [tasks],
  );

  const unreadCount = useMemo(
    () => notifications.filter((n) => n.ts > readAt).length,
    [notifications, readAt],
  );

  const value: StoreValue = {
    tasks,
    tasksLoaded,
    error,
    connected,
    refresh,
    getTask: getTaskById,
    notifications,
    unreadCount,
    markNotificationsRead,
    reasoning,
    chat,
    appendChat,
    approvals,
    resolveApproval,
    approvalMode,
    setApprovalMode,
    createTask,
    cancelTask,
    completeTask,
    deleteTask,
    clearAllTasks,
    restartTask,
    taskTitles,
    titleFor,
    renameTask,
    quickAddOpen,
    setQuickAddOpen,
  };

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>;
}

export function useStore(): StoreValue {
  const ctx = useContext(StoreContext);
  if (!ctx) throw new Error("useStore must be used within StoreProvider");
  return ctx;
}

// ---- shared task presentation helpers ------------------------------------

export type Column = "ongoing" | "next" | "done";

export function columnFor(state: string): Column {
  const s = state.toUpperCase();
  if (s === "COMPLETED" || s === "FAILED" || s === "CANCELLED") return "done";
  if (s === "AWAITING_APPROVAL" || s === "RECEIVED") return "next";
  return "ongoing";
}

export interface StatusBadge {
  label: string;
  tone: "blue" | "amber" | "green" | "red";
}

export function badgeFor(state: string): StatusBadge {
  switch (state.toUpperCase()) {
    case "COMPLETED":
      return { label: "Completed", tone: "green" };
    case "FAILED":
    case "CANCELLED":
      return { label: "Failed", tone: "red" };
    case "AWAITING_APPROVAL":
      return { label: "Needs approval", tone: "amber" };
    case "RECEIVED":
      return { label: "Up Next", tone: "amber" };
    case "REPLANNING":
      return { label: "Replanning", tone: "blue" };
    case "PLANNING":
      return { label: "Planning", tone: "blue" };
    default:
      return { label: "Running", tone: "blue" };
  }
}

export function taskProgress(task: TaskRecord): { done: number; total: number } {
  const total = task.steps.length;
  const done = task.steps.filter((s) => s.status === "verified" || s.status === "skipped").length;
  return { done, total };
}

/** First non-empty line — objectives carry attachment context on later lines. */
export function firstLine(text: string): string {
  return text.split("\n").find((l) => l.trim()) ?? text;
}

/**
 * Planner replans embed the entire prior-failure history inside the next
 * step's description, which is unreadable in a table cell or reasoning list.
 * Keep the human-meaningful head of it.
 */
export function cleanStepText(text: string): string {
  let out = text.split(/,?\s*taking into account this prior failure/i)[0];
  const retry = out.match(/^Retry the objective ['"]?([\s\S]+?)['"]?[,\s]*$/i);
  if (retry) out = `Retry: ${firstLine(retry[1])}`;
  return firstLine(out).trim();
}

/** Short description line for a task — first pending/running step, else summary. */
export function taskSubtitle(task: TaskRecord): string {
  const active = task.steps.find((s) => s.status === "running");
  if (active) return cleanStepText(active.description);
  const nextUp = task.steps.find((s) => s.status === "pending" || s.status === "ready");
  if (nextUp) return cleanStepText(nextUp.description);
  if (task.steps.length) return cleanStepText(task.steps[task.steps.length - 1].description);
  return "Waiting for the planner to decompose this objective.";
}

export function formatDate(ts: number | null): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleDateString(undefined, { month: "short", day: "2-digit" });
}

export function formatRelative(ms: number): string {
  const diff = Date.now() - ms;
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return days === 1 ? "Yesterday" : `${days}d ago`;
}

/** Re-renders on an interval and hands back the current epoch ms. */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

/** Compact elapsed-time label for a live run: 8s, 4m 12s, 1h 03m. */
export function formatElapsed(fromMs: number, now: number): string {
  const total = Math.max(0, Math.floor((now - fromMs) / 1000));
  if (total < 60) return `${total}s`;
  const mins = Math.floor(total / 60);
  if (mins < 60) return `${mins}m ${String(total % 60).padStart(2, "0")}s`;
  return `${Math.floor(mins / 60)}h ${String(mins % 60).padStart(2, "0")}m`;
}

/** True while the orchestrator is actively working the task. */
export function isRunning(state: string): boolean {
  const s = state.toUpperCase();
  return s === "PLANNING" || s === "EXECUTING" || s === "VERIFYING" || s === "REPLANNING";
}
