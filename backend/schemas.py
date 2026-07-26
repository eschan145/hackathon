"""Pydantic request/response models for the backend API.

Reuses core.models (Task/TaskGraph/Step) wherever they already have what's
needed instead of redefining shapes.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from core.models import Task


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
    backend: str = "OpenClaw"
    planning_model: str = "llama-3.1-70b-instruct"
    verification_model: str = "nemotron-vision-small"
    allowed_directories: list[str] = Field(default_factory=list)

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
