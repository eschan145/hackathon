// Typed REST client for the FastAPI backend.
//
// Everything the frontend needs to reconcile against the real backend
// implementation lives in this ONE file: the base URL, endpoint paths,
// and response shapes. If the backend agent's contract differs slightly
// (field names, status codes, etc.) this is the only file that needs edits.

export const BACKEND_HTTP_BASE = "http://127.0.0.1:8765";
export const BACKEND_WS_URL = "ws://127.0.0.1:8765/ws/events";

export type RiskLevel = "low" | "medium" | "high" | string;

export type StepStatus =
  | "pending"
  | "ready"
  | "running"
  | "verified"
  | "failed"
  | "skipped"
  | string;

/** core.models.TaskState — uppercase on the wire. */
export type TaskState =
  | "RECEIVED"
  | "PLANNING"
  | "EXECUTING"
  | "VERIFYING"
  | "REPLANNING"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED"
  | "AWAITING_APPROVAL"
  | string;

export interface TaskStep {
  id: string;
  description: string;
  status: StepStatus;
  risk_level?: RiskLevel;
  depends_on?: string[];
  success_criteria?: string;
  tool_hint?: string;
}

/**
 * Flattened task shape used everywhere in the UI.
 *
 * The backend serializes core.models.Task, which nests steps under
 * `graph.steps`, names the identifier `id` (not `task_id`), and sends
 * `created_at` as a float epoch. normalizeTask() flattens that so no
 * component has to know about the nesting.
 */
export interface TaskRecord {
  task_id: string;
  objective: string;
  state: TaskState;
  source: string;
  created_at: number | null;
  steps: TaskStep[];
  history: Array<Record<string, unknown>>;
}

export interface CreateObjectiveRequest {
  objective: string;
  source: string;
}

export interface CreateObjectiveResponse {
  task_id: string;
}

export interface ApproveStepRequest {
  step_id: string;
  approved: boolean;
}

export interface SettingsPayload {
  model: string;
  thinking_level: "off" | "minimal" | "low" | "medium" | "high" | "xhigh" | "adaptive" | "max" | string;
  show_reasoning: boolean;
  allowed_directories: string[];
  /**
   * How approval requests are handled: "ask" | "auto". Not part of
   * backend/schemas.py's declared fields, but SettingsModel sets
   * `extra = "allow"`, so it persists to config/settings.yaml unchanged.
   */
  approval_mode?: string;
}

export interface ConversationMessagePayload {
  id: string;
  task_id: string;
  role: "user" | "assistant";
  text: string;
  created_at: number;
}

// Matches backend/main.py's WS /ws/events payload exactly: lowercase
// snake_case (EventType enum values serialize lowercase), not the
// uppercase names used internally in core/events.py.
export type AssistantEventType =
  | "objective_received"
  | "plan_generated"
  | "step_started"
  | "step_verified"
  | "step_failed"
  | "replanned"
  | "task_completed"
  | "task_failed"
  | "approval_required"
  | string;

export interface AssistantEvent {
  type: AssistantEventType;
  task_id: string;
  payload: Record<string, unknown>;
  timestamp?: string | number;
}

// Matches backend/main.py's GET /api/model-status (backend/schemas.py's
// ModelStatusResponse). "mode" is derived from OpenClaw's own model
// catalog (openclaw models list --json), not guessed from the model
// string, so it stays correct once a locally-imported model is configured.
export interface ModelStatus {
  model: string;
  provider: string;
  display_name: string;
  local: boolean | null;
  available: boolean | null;
  mode: "cloud" | "local" | "unknown" | string;
  error?: string | null;
}

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function normalizeStep(raw: Record<string, any>): TaskStep {
  return {
    id: String(raw.id ?? raw.step_id ?? ""),
    description: String(raw.description ?? raw.id ?? ""),
    status: String(raw.status ?? "pending"),
    risk_level: raw.risk_level,
    depends_on: raw.depends_on ?? [],
    success_criteria: raw.success_criteria ?? "",
    tool_hint: raw.tool_hint ?? "",
  };
}

/** Accepts either the nested core.models.Task shape or an already-flat one. */
export function normalizeTask(raw: Record<string, any>): TaskRecord {
  const rawSteps: Array<Record<string, any>> = raw?.graph?.steps ?? raw?.steps ?? [];
  const createdAt = raw?.created_at;
  return {
    task_id: String(raw?.id ?? raw?.task_id ?? ""),
    objective: String(raw?.objective ?? raw?.graph?.objective ?? "Untitled objective"),
    state: String(raw?.state ?? "RECEIVED"),
    source: String(raw?.source ?? "gui"),
    created_at:
      typeof createdAt === "number"
        ? createdAt
        : typeof createdAt === "string"
          ? Date.parse(createdAt) / 1000 || null
          : null,
    steps: rawSteps.map(normalizeStep),
    history: raw?.history ?? [],
  };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BACKEND_HTTP_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new ApiError(res.status, text || res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  createObjective(body: CreateObjectiveRequest): Promise<CreateObjectiveResponse> {
    return request("/api/objectives", { method: "POST", body: JSON.stringify(body) });
  },
  async listTasks(): Promise<TaskRecord[]> {
    // backend/main.py's GET /api/tasks returns {"tasks": [...]}, not a bare array.
    const res = await request<{ tasks: Array<Record<string, any>> }>("/api/tasks");
    return (res.tasks ?? []).map(normalizeTask);
  },
  async getTask(taskId: string): Promise<TaskRecord> {
    const raw = await request<Record<string, any>>(`/api/tasks/${encodeURIComponent(taskId)}`);
    return normalizeTask(raw);
  },
  approveStep(taskId: string, body: ApproveStepRequest): Promise<{ resolved: boolean }> {
    return request(`/api/tasks/${encodeURIComponent(taskId)}/approve`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },
  cancelTask(taskId: string): Promise<{ cancelled: boolean }> {
    return request(`/api/tasks/${encodeURIComponent(taskId)}/cancel`, { method: "POST" });
  },
  completeTask(taskId: string): Promise<{ completed: boolean }> {
    return request(`/api/tasks/${encodeURIComponent(taskId)}/complete`, { method: "POST" });
  },
  deleteTask(taskId: string): Promise<{ deleted: boolean }> {
    return request(`/api/tasks/${encodeURIComponent(taskId)}`, { method: "DELETE" });
  },
  clearAllTasks(): Promise<{ deleted_count: number }> {
    return request("/api/tasks", { method: "DELETE" });
  },
  getConversation(taskId: string): Promise<{ messages: ConversationMessagePayload[] }> {
    return request(`/api/tasks/${encodeURIComponent(taskId)}/conversation`);
  },
  appendConversation(
    taskId: string,
    message: Omit<ConversationMessagePayload, "task_id">,
  ): Promise<ConversationMessagePayload> {
    return request(`/api/tasks/${encodeURIComponent(taskId)}/conversation`, {
      method: "POST",
      body: JSON.stringify(message),
    });
  },
  getSettings(): Promise<SettingsPayload> {
    return request("/api/settings");
  },
  saveSettings(body: SettingsPayload): Promise<SettingsPayload> {
    return request("/api/settings", { method: "POST", body: JSON.stringify(body) });
  },
  getModelStatus(): Promise<ModelStatus> {
    return request("/api/model-status");
  },
};

export { ApiError };
