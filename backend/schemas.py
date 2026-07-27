"""Pydantic request/response models for the backend API.

Reuses core.models (Task/TaskGraph/Step) wherever they already have what's
needed instead of redefining shapes.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from core.models import ObjectiveContract, ProcedureCandidate, Task
from integrations.email_router import EmailCandidate, EmailRouteDecision


class ObjectiveRequest(BaseModel):
    objective: str
    source: str = "gui"


class ObjectiveResponse(BaseModel):
    task_id: str


class TaskListResponse(BaseModel):
    tasks: list[Task]


class ApprovalRequest(BaseModel):
    step_id: str
    approved: bool


class ApprovalResponse(BaseModel):
    resolved: bool


class CancelResponse(BaseModel):
    cancelled: bool


class TaskMutationResponse(BaseModel):
    completed: bool = False
    deleted: bool = False


class SettingsModel(BaseModel):
    model: str = "ollama/qwen3-vl:30b-a3b"
    thinking_level: str = "low"
    show_reasoning: bool = True
    allowed_directories: list[str] = Field(default_factory=list)
    email_routing_enabled: bool = False
    email_routing_prompt: str = ""
    email_authorized_senders: list[str] = Field(default_factory=list)
    email_require_document: bool = True

    class Config:
        extra = "allow"


class EventMessage(BaseModel):
    """Shape of every message pushed over the /ws/events websocket."""

    type: str
    task_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: float


class ConversationMessageCreate(BaseModel):
    id: str
    role: str
    text: str
    created_at: float


class ConversationMessage(ConversationMessageCreate):
    task_id: str


class ConversationResponse(BaseModel):
    messages: list[ConversationMessage] = Field(default_factory=list)


class ModelStatusResponse(BaseModel):
    """Answers the frontend's "what mode is this running in" question.

    Backed by planning.openclaw_client.get_model_status(), which asks
    OpenClaw's own model catalog (not a guess from the model string)
    whether the configured model is cloud-hosted or local.
    """

    model: str
    provider: str
    display_name: str
    local: Optional[bool] = None
    available: Optional[bool] = None
    mode: str = "unknown"  # "cloud" | "local" | "unknown"
    error: Optional[str] = None


class EmailRoutingPreviewRequest(BaseModel):
    email: EmailCandidate


class EmailRoutingPreviewResponse(BaseModel):
    decision: EmailRouteDecision
    contract: Optional[ObjectiveContract] = None


class EmailRoutingIngestRequest(BaseModel):
    email: EmailCandidate


class EmailRoutingIngestResponse(BaseModel):
    decision: EmailRouteDecision
    contract: Optional[ObjectiveContract] = None
    task_id: Optional[str] = None


class ProcedureDecisionRequest(BaseModel):
    save: bool


class ProcedureDecisionResponse(BaseModel):
    procedure: ProcedureCandidate
