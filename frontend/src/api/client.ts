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

export interface TaskStep {
  id: string;
  description: string;
  status: StepStatus;
  risk_level?: RiskLevel;
  depends_on?: string[];
}

export interface TaskSummary {
  task_id: string;
  objective: string;
  state: string;
  source?: string;
  created_at?: string;
  updated_at?: string;
}

export interface TaskDetail extends TaskSummary {
  steps?: TaskStep[];
  history?: Array<Record<string, unknown>>;
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
  backend: "Native" | "OpenClaw" | "NemoClaw" | "OpenShell" | string;
  planning_model: string;
  verification_model: string;
  allowed_directories: string[];
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

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
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
  listTasks(): Promise<TaskSummary[]> {
    return request("/api/tasks");
  },
  getTask(taskId: string): Promise<TaskDetail> {
    return request(`/api/tasks/${encodeURIComponent(taskId)}`);
  },
  approveStep(taskId: string, body: ApproveStepRequest): Promise<void> {
    return request(`/api/tasks/${encodeURIComponent(taskId)}/approve`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },
  cancelTask(taskId: string): Promise<void> {
    return request(`/api/tasks/${encodeURIComponent(taskId)}/cancel`, { method: "POST" });
  },
  getSettings(): Promise<SettingsPayload> {
    return request("/api/settings");
  },
  saveSettings(body: SettingsPayload): Promise<void> {
    return request("/api/settings", { method: "POST", body: JSON.stringify(body) });
  },
};

export { ApiError };
