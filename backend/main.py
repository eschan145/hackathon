"""FastAPI app: HTTP + WebSocket API for the Electron/React frontend.

Wires up the Orchestrator via backend/orchestrator_factory.py's
build_orchestrator() (real VisionAgentPlanner/ActionExecutor/
DeterministicVerifier, with only Memory falling back to an in-process stub
if memory/'s sqlite dir isn't set up yet).

Run with:
    python backend/main.py
    # or
    python -m backend.main
"""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from pathlib import Path
from typing import Any, Optional

# Allow running as `python backend/main.py` (script, not module) by ensuring
# the project root is on sys.path so `core`, `backend`, etc. resolve.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

try:
    import yaml
    _YAML_AVAILABLE = True
except Exception:  # pragma: no cover
    yaml = None  # type: ignore[assignment]
    _YAML_AVAILABLE = False

from core.events import Event, EventType
from core.models import Task
from integrations.email_router import (
    EmailCandidate,
    EmailRouter,
    EmailRoutingPolicy,
    objective_from_contract,
)
from planning.openclaw_client import LOCAL_MODEL_ID, get_model_status
from vision.capture import default_frame_store

from backend.orchestrator_factory import build_orchestrator
from backend.schemas import (
    ApprovalRequest,
    ApprovalResponse,
    CancelResponse,
    ClearHistoryResponse,
    ConversationMessage,
    ConversationMessageCreate,
    ConversationResponse,
    EmailRoutingIngestRequest,
    EmailRoutingIngestResponse,
    EmailRoutingPreviewRequest,
    EmailRoutingPreviewResponse,
    EventMessage,
    ModelStatusResponse,
    ObjectiveRequest,
    ObjectiveResponse,
    ProcedureDecisionRequest,
    ProcedureDecisionResponse,
    SettingsModel,
    TaskMutationResponse,
    TaskListResponse,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

HOST = "127.0.0.1"
PORT = 8765

SETTINGS_PATH = _PROJECT_ROOT / "config" / "user_settings.yaml"

DEFAULT_SETTINGS: dict[str, Any] = {
    "model": "ollama/qwen3-vl:30b-a3b",
    "thinking_level": "low",
    "show_reasoning": True,
    "allowed_directories": [
        str(Path.home() / "Documents"),
        str(Path.home() / "Downloads"),
    ],
    "email_routing_enabled": False,
    "email_routing_prompt": "",
    "email_authorized_senders": [],
    "email_require_document": True,
}

# Base URL the frontend can reach this backend at, used to rewrite bare
# frame ref_ids into fully-qualified, browser-loadable image URLs before
# broadcasting events over the websocket (see _event_to_message below).
FRAMES_BASE_URL = f"http://{HOST}:{PORT}/api/frames"

ALL_EVENT_TYPES = list(EventType)


class ConnectionManager:
    """Tracks connected /ws/events websockets and broadcasts Events to all."""

    def __init__(self) -> None:
        self.active: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self.active.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self.active.discard(ws)

    async def broadcast(self, message: dict[str, Any]) -> None:
        dead = []
        for ws in list(self.active):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)


def _event_to_message(event: Event) -> dict[str, Any]:
    payload = dict(event.payload)

    # Rewrite a bare frame ref_id into a fully-qualified URL the frontend
    # can drop straight into an <img src> (see Task.tsx's
    # maybeUpdatePreview(), which reads payload.screenshot_ref verbatim).
    # core/orchestrator.py's _run_step() threads ActionResult.screenshot_ref
    # into its STEP_VERIFIED/STEP_FAILED self._emit(...) calls.
    screenshot_ref = payload.get("screenshot_ref")
    if isinstance(screenshot_ref, str) and screenshot_ref:
        payload["screenshot_ref"] = f"{FRAMES_BASE_URL}/{screenshot_ref}.png"

    details = payload.get("details")
    if isinstance(details, dict):
        nested_ref = details.get("screenshot_ref")
        if isinstance(nested_ref, str) and nested_ref:
            details = dict(details)
            details["screenshot_ref"] = f"{FRAMES_BASE_URL}/{nested_ref}.png"
            payload["details"] = details

    return {
        "type": event.type.value if isinstance(event.type, EventType) else str(event.type),
        "task_id": event.task_id,
        "payload": payload,
        "timestamp": event.timestamp,
    }


def create_app() -> FastAPI:
    app = FastAPI(title="Orchestratr Backend")

    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Serve saved vision frames so the frontend's screen-preview <img> can
    # load them directly, e.g. a ref_id "1234_abcd1234" is servable at
    # /api/frames/1234_abcd1234.png (FrameStore.save() writes "{ref_id}.png").
    default_frame_store.directory.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/api/frames",
        StaticFiles(directory=str(default_frame_store.directory)),
        name="frames",
    )

    @app.on_event("startup")
    async def _startup() -> None:
        orchestrator, memory = build_orchestrator()
        app.state.orchestrator = orchestrator
        app.state.memory = memory
        app.state.event_bus = orchestrator.event_bus
        app.state.running_tasks: dict[str, asyncio.Task] = {}
        app.state.results: dict[str, Task] = {}
        app.state.connections = ConnectionManager()
        app.state.email_router = EmailRouter(orchestrator.planner._client)

        # Bind the bus to *this* running loop so publish()/publish_threadsafe
        # both work correctly on FastAPI's own event loop.
        app.state.event_bus.bind_loop(asyncio.get_running_loop())

        async def _on_event(event: Event) -> None:
            await app.state.connections.broadcast(_event_to_message(event))

        for event_type in ALL_EVENT_TYPES:
            app.state.event_bus.subscribe(event_type, _on_event)

        logger.info("Backend started; orchestrator wired with %s", type(orchestrator.planner).__name__)

    async def _schedule_objective(
        objective: str,
        source: str,
        objective_contract: Any = None,
    ) -> str:
        orchestrator = app.state.orchestrator
        loop = asyncio.get_event_loop()
        id_future: "asyncio.Future[str]" = loop.create_future()

        async def _capture_id(event: Event) -> None:
            if (
                not id_future.done()
                and event.payload.get("objective") == objective
                and event.payload.get("source") == source
            ):
                id_future.set_result(event.task_id)

        orchestrator.event_bus.subscribe(EventType.OBJECTIVE_RECEIVED, _capture_id)
        aio_task = asyncio.ensure_future(
            orchestrator.run_task(
                objective,
                source=source,
                objective_contract=objective_contract,
            )
        )

        def _on_done(t: "asyncio.Task[Task]") -> None:
            try:
                result = t.result()
                app.state.results[result.id] = result
            except asyncio.CancelledError:
                logger.info("Task cancelled")
            except Exception:
                logger.exception("run_task failed for objective: %s", objective)

        aio_task.add_done_callback(_on_done)
        try:
            task_id = await asyncio.wait_for(id_future, timeout=5.0)
        except asyncio.TimeoutError:
            task_id = f"unknown-{uuid.uuid4().hex[:12]}"
        finally:
            orchestrator.event_bus.unsubscribe(EventType.OBJECTIVE_RECEIVED, _capture_id)
        app.state.running_tasks[task_id] = aio_task
        return task_id

    # -- objectives -----------------------------------------------------

    @app.post("/api/objectives", response_model=ObjectiveResponse)
    async def submit_objective(req: ObjectiveRequest) -> ObjectiveResponse:
        return ObjectiveResponse(
            task_id=await _schedule_objective(req.objective, req.source)
        )

    def _email_policy(settings: SettingsModel) -> EmailRoutingPolicy:
        return EmailRoutingPolicy(
            enabled=settings.email_routing_enabled,
            prompt=settings.email_routing_prompt,
            authorized_senders=settings.email_authorized_senders,
            require_document=settings.email_require_document,
        )

    @app.post("/api/email-routing/preview", response_model=EmailRoutingPreviewResponse)
    async def preview_email_route(
        req: EmailRoutingPreviewRequest,
    ) -> EmailRoutingPreviewResponse:
        settings = await get_settings()
        decision = await app.state.email_router.evaluate(
            req.email, _email_policy(settings)
        )
        contract = (
            app.state.email_router.create_contract(req.email, decision)
            if decision.matched
            else None
        )
        return EmailRoutingPreviewResponse(decision=decision, contract=contract)

    @app.post("/api/email-routing/ingest", response_model=EmailRoutingIngestResponse)
    async def ingest_email_route(
        req: EmailRoutingIngestRequest,
    ) -> EmailRoutingIngestResponse:
        settings = await get_settings()
        policy = _email_policy(settings)
        decision = await app.state.email_router.evaluate(req.email, policy)
        if not decision.matched:
            return EmailRoutingIngestResponse(decision=decision)

        missing = [
            str(item.get("filename") or item.get("name") or "attachment")
            for item in req.email.attachments
            if not (item.get("local_path") or item.get("path"))
        ]
        if missing:
            raise HTTPException(
                status_code=422,
                detail=(
                    "The email event provider must materialize attachments locally "
                    f"before ingestion. Missing local paths for: {', '.join(missing)}"
                ),
            )
        contract = app.state.email_router.create_contract(req.email, decision)
        task_id = await _schedule_objective(
            objective_from_contract(contract, req.email),
            source=f"email-event:{req.email.id}",
            objective_contract=contract,
        )
        return EmailRoutingIngestResponse(
            decision=decision,
            contract=contract,
            task_id=task_id,
        )

    @app.get("/api/tasks", response_model=TaskListResponse)
    async def list_tasks() -> TaskListResponse:
        memory = app.state.memory
        tasks: list[Task] = []
        try:
            result = memory.list_recent_tasks(limit=25)
            if asyncio.iscoroutine(result):
                result = await result
            tasks = list(result or [])
        except Exception:
            logger.exception("list_recent_tasks failed; falling back to in-process results")
            tasks = list(app.state.results.values())
        return TaskListResponse(tasks=tasks)

    @app.get("/api/tasks/{task_id}")
    async def get_task(task_id: str) -> Task:
        memory = app.state.memory
        try:
            get_task_fn = getattr(memory, "get_task", None)
            if get_task_fn is not None:
                result = get_task_fn(task_id)
                if asyncio.iscoroutine(result):
                    result = await result
                if result is not None:
                    return result
        except Exception:
            logger.exception("memory.get_task failed for %s", task_id)

        if task_id in app.state.results:
            return app.state.results[task_id]

        raise HTTPException(status_code=404, detail=f"Unknown task_id: {task_id}")

    async def _load_task(task_id: str) -> Task | None:
        memory = app.state.memory
        try:
            result = memory.get_task(task_id)
            if asyncio.iscoroutine(result):
                result = await result
            if result is not None:
                return result
        except Exception:
            logger.exception("memory.get_task failed for %s", task_id)
        return app.state.results.get(task_id)

    @app.post("/api/tasks/{task_id}/approve", response_model=ApprovalResponse)
    async def approve_task(task_id: str, req: ApprovalRequest) -> ApprovalResponse:
        orchestrator = app.state.orchestrator
        resolved = await orchestrator.resolve_approval(task_id, req.step_id, req.approved)
        return ApprovalResponse(resolved=resolved)

    @app.post(
        "/api/tasks/{task_id}/procedure",
        response_model=ProcedureDecisionResponse,
    )
    async def decide_procedure(
        task_id: str, req: ProcedureDecisionRequest
    ) -> ProcedureDecisionResponse:
        task = await _load_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail=f"Unknown task_id: {task_id}")
        if task.procedure_candidate is None:
            raise HTTPException(status_code=409, detail="No procedure is offered for this task")
        method_name = "save_procedure" if req.save else "dismiss_procedure"
        method = getattr(app.state.memory, method_name, None)
        if method is None:
            task.procedure_candidate.status = "saved" if req.save else "dismissed"
            await app.state.memory.save_task(task)
            candidate = task.procedure_candidate
        else:
            candidate = method(task)
            if asyncio.iscoroutine(candidate):
                candidate = await candidate
        app.state.orchestrator._emit(
            EventType.PROCEDURE_UPDATED,
            task,
            procedure=candidate.model_dump(),
        )
        return ProcedureDecisionResponse(procedure=candidate)

    @app.post("/api/tasks/{task_id}/cancel", response_model=CancelResponse)
    async def cancel_task(task_id: str) -> CancelResponse:
        aio_task = app.state.running_tasks.get(task_id)
        if aio_task is None:
            return CancelResponse(cancelled=False)
        cancelled = aio_task.cancel()
        return CancelResponse(cancelled=cancelled)

    @app.post("/api/tasks/{task_id}/complete", response_model=TaskMutationResponse)
    async def complete_task(task_id: str) -> TaskMutationResponse:
        task = await _load_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail=f"Unknown task_id: {task_id}")

        aio_task = app.state.running_tasks.pop(task_id, None)
        if aio_task is not None and not aio_task.done():
            aio_task.cancel()

        if task.graph is not None:
            for step in task.graph.steps:
                if step.status not in ("verified", "failed", "skipped"):
                    step.status = "skipped"
        task.state = "COMPLETED"
        task.record("manually_completed")
        await app.state.memory.save_task(task)
        app.state.results[task_id] = task
        return TaskMutationResponse(completed=True)

    @app.delete("/api/tasks/{task_id}", response_model=TaskMutationResponse)
    async def delete_task(task_id: str) -> TaskMutationResponse:
        task = await _load_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail=f"Unknown task_id: {task_id}")

        aio_task = app.state.running_tasks.pop(task_id, None)
        if aio_task is not None and not aio_task.done():
            aio_task.cancel()

        delete_task_fn = getattr(app.state.memory, "delete_task", None)
        if delete_task_fn is not None:
            result = delete_task_fn(task_id)
            if asyncio.iscoroutine(result):
                await result
        app.state.results.pop(task_id, None)
        return TaskMutationResponse(deleted=True)

    @app.delete("/api/tasks", response_model=ClearHistoryResponse)
    async def clear_all_tasks() -> ClearHistoryResponse:
        """Delete every task, chat, and cached workflow - the Settings page's
        "Delete all chats" action. Cancels any still-running tasks first, the
        same way delete_task() does for a single task, so nothing tries to
        save_task() a row back into existence right after this wipes it.
        """
        for aio_task in list(app.state.running_tasks.values()):
            if not aio_task.done():
                aio_task.cancel()
        app.state.running_tasks.clear()
        app.state.results.clear()

        deleted_count = await app.state.memory.delete_all_tasks()
        return ClearHistoryResponse(deleted_count=deleted_count)

    # -- persistent task conversations -----------------------------------

    @app.get("/api/tasks/{task_id}/conversation", response_model=ConversationResponse)
    async def get_conversation(task_id: str) -> ConversationResponse:
        list_messages = getattr(app.state.memory, "list_conversation_messages", None)
        if list_messages is None:
            return ConversationResponse(messages=[])
        result = list_messages(task_id)
        if asyncio.iscoroutine(result):
            result = await result
        return ConversationResponse(
            messages=[ConversationMessage(**message) for message in (result or [])]
        )

    @app.post("/api/tasks/{task_id}/conversation", response_model=ConversationMessage)
    async def append_conversation(
        task_id: str, message: ConversationMessageCreate
    ) -> ConversationMessage:
        append_message = getattr(app.state.memory, "append_conversation_message", None)
        if append_message is None:
            raise HTTPException(status_code=501, detail="Conversation persistence unavailable")
        result = append_message(
            task_id,
            message.id,
            message.role,
            message.text,
            message.created_at,
        )
        if asyncio.iscoroutine(result):
            result = await result
        return ConversationMessage(**result)

    # -- settings ---------------------------------------------------------

    @app.get("/api/settings", response_model=SettingsModel)
    async def get_settings() -> SettingsModel:
        if _YAML_AVAILABLE and SETTINGS_PATH.exists():
            try:
                with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                merged = dict(DEFAULT_SETTINGS)
                merged.update(data)
                return SettingsModel(**merged)
            except Exception:
                logger.exception("Failed to read %s, using defaults", SETTINGS_PATH)
        return SettingsModel(**DEFAULT_SETTINGS)

    @app.post("/api/settings", response_model=SettingsModel)
    async def save_settings(settings: SettingsModel) -> SettingsModel:
        if settings.model != LOCAL_MODEL_ID:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Only the local model {LOCAL_MODEL_ID!r} is supported; "
                    "this project does not support cloud models."
                ),
            )
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = settings.model_dump()
        if _YAML_AVAILABLE:
            try:
                with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
                    yaml.safe_dump(data, f, default_flow_style=False)
            except Exception:
                logger.exception("Failed to write %s", SETTINGS_PATH)
                raise HTTPException(status_code=500, detail="Failed to persist settings")
        else:
            raise HTTPException(status_code=500, detail="PyYAML not installed; cannot persist settings")
        return settings

    # -- model status ------------------------------------------------------

    @app.get("/api/model-status", response_model=ModelStatusResponse)
    async def model_status() -> ModelStatusResponse:
        status = await get_model_status()
        return ModelStatusResponse(**status)

    # -- websocket ----------------------------------------------------------

    @app.websocket("/ws/events")
    async def ws_events(ws: WebSocket) -> None:
        await app.state.connections.connect(ws)
        try:
            while True:
                # We don't expect inbound messages, but keep the connection
                # alive and detect client disconnects.
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        except Exception:
            logger.exception("ws/events connection error")
        finally:
            await app.state.connections.disconnect(ws)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host=HOST, port=PORT, reload=False, factory=False)
