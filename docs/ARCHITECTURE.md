# Autonomous Desktop Assistant — Architecture (DGX Spark / Local Inference)

## 1. Overall System Architecture

Layered, event-driven, fully local:

```
┌─────────────────────────────────────────────────────────────────┐
│  GUI Layer (Kivy)  — objective input, live plan/step view,      │
│  approval prompts, screen-share preview, history                │
├─────────────────────────────────────────────────────────────────┤
│  Orchestrator (core/) — task lifecycle FSM, event bus, scheduler │
├───────────────┬───────────────┬───────────────┬─────────────────┤
│ Planning      │ Execution     │ Verification  │ Memory           │
│ Subsystem     │ Subsystem     │ Subsystem     │ Subsystem        │
│ (LLM planner, │ (Control      │ (Vision model,│ (SQLite +        │
│ dependency    │ Layer:        │ OCR, DOM/     │ vector store,    │
│ graph, replan)│ OpenClaw/     │ a11y tree     │ preference store,│
│               │ NemoClaw +    │ diffing)      │ episodic log)    │
│               │ native APIs)  │               │                  │
├───────────────┴───────────────┴───────────────┴─────────────────┤
│ Vision Subsystem — screen capture, OCR, element detection,       │
│ shared by Verification and Execution                             │
├───────────────────────────────────────────────────────────────────┤
│ Integration Layer — MCP servers (Gmail, Todoist, Notion, Drive,   │
│ GitHub, Calendar) + local filesystem connectors                  │
├───────────────────────────────────────────────────────────────────┤
│ Local Inference Runtime — NIM / TensorRT-LLM / Ollama on DGX      │
│ Spark GPUs: reasoning LLM, VLM, embedding model, OCR model        │
└───────────────────────────────────────────────────────────────────┘
```

All inference (planning LLM, vision-language model, embeddings, OCR) runs on-box via NVIDIA NIM containers or TensorRT-LLM engines served over local gRPC/HTTP — no external API calls. This satisfies the "no cloud inference" constraint while still allowing MCP for *local* tool/data connectors (Gmail/Todoist APIs still require network egress to those services themselves, but no user data goes through a third-party LLM API).

## 2. Core Modules

- `core/orchestrator.py` — central FSM driving the task lifecycle, owns the event bus (asyncio queues), dispatches to planner/executor/verifier, persists task state to Memory.
- `core/events.py` — typed events (ObjectiveReceived, PlanGenerated, StepStarted, StepVerified, StepFailed, Replanned, TaskCompleted).
- `planning/` — planner engine, task graph, dependency resolver, replanning policy.
- `execution/` — control layer abstraction (`ControlBackend` interface) with adapters for OpenClaw/NemoClaw, plus native OS APIs (input injection, window mgmt, clipboard, filesystem).
- `verification/` — post-action checkers: screenshot diff, VLM-based success classifier, accessibility-tree assertions, retry/recovery policy.
- `memory/` — SQLite (structured: preferences, contacts, app usage, credentials metadata) + vector DB (episodic: past workflows, embeddings of screen/task context) via a unified `MemoryStore` facade.
- `vision/` — screen capture (mss/DXGI), OCR (PaddleOCR/EasyOCR or NIM VLM), element/icon detection, UI diffing.
- `gui/` — Kivy app: objective bar, live step tracker, plan tree view, screen preview panel, approval modal for sensitive actions, history browser.
- `integrations/` — MCP client manager + per-service adapters (Gmail, Todoist, Notion, Drive, GitHub, Calendar) and a local-file/objective-scanner.
- `config/` — model registry, backend selection (OpenClaw vs NemoClaw vs OpenShell), security policy (allowed actions, sandbox rules).

## 3. Data Flow (single objective)

1. GUI or Integration layer emits `ObjectiveReceived(text, source)` onto the event bus.
2. Orchestrator creates a `Task` record in Memory, sets state `PLANNING`.
3. Planner pulls relevant Memory context (past similar tasks, preferences, contact book) and calls the local reasoning LLM to produce a `TaskGraph` (DAG of subtasks with pre/postconditions).
4. Orchestrator walks the graph in topological + parallel-eligible order, dispatching each ready `Step` to the Execution subsystem.
5. Execution subsystem calls the active `ControlBackend` (OpenClaw/NemoClaw/native) to perform the action (click, type, launch app, API call).
6. Immediately after, Verification subsystem captures a new screenshot/a11y snapshot, runs VLM+OCR+diff against the step's expected postcondition, emits `StepVerified` or `StepFailed`.
7. On failure: Recovery policy decides retry / alternate strategy / replan / escalate-to-user (only for irreversible or high-risk actions).
8. On completion of all steps: Orchestrator emits `TaskCompleted`, writes the workflow (success or failure) to Memory for future reuse, and asks the summarizer LLM to produce a natural-language completion summary shown in the GUI.

## 4. Task Lifecycle (FSM)

`RECEIVED → PLANNING → EXECUTING ⇄ VERIFYING → (REPLANNING ↺) → COMPLETED | FAILED | AWAITING_APPROVAL`

Each state transition is logged as an event and persisted, so a crashed/restarted assistant can resume mid-task from Memory (important for long-running tasks like "research cheapest flight").

## 5. Planning Subsystem

- **Decomposition**: local reasoning LLM (e.g., Llama-3.1-70B-Instruct or Nemotron via NIM) prompted with a structured-output schema (Pydantic) to emit a `TaskGraph`: list of `Step{id, description, tool_hint, depends_on[], risk_level, success_criteria}`.
- **Dependency management**: DAG stored in-memory (networkx); orchestrator only dispatches steps whose dependencies are `VERIFIED`.
- **Parallel execution**: independent branches (e.g., "search 3 flight sites") dispatched concurrently via asyncio tasks, each bound to its own virtual desktop/browser context to avoid input contention.
- **Dynamic replanning**: on `StepFailed` with recovery exhausted, planner re-invoked with the failure context (screenshot + error) appended to produce a patched subgraph rather than restarting the whole task.
- **Prioritization**: for multi-objective sessions (e.g., batch of Todoist tasks), a priority queue orders tasks by deadline/importance metadata pulled from the source integration.
- **Long-running tasks**: steps that involve waiting (e.g., "wait for shipping confirmation email") are modeled as polling steps with backoff, persisted so they survive app restarts.

## 6. Execution Subsystem — Computer Control

**Recommendation: hybrid architecture.**

| Layer | Use for | Why |
|---|---|---|
| Native OS APIs (Win32/UIAutomation, `pyautogui`/`pynput`, `pyperclip`, `psutil`) | Mouse/keyboard injection, window management, clipboard, filesystem | Lowest latency, no extra process hop, most reliable for primitive actions |
| OpenClaw/NemoClaw (agentic control layer) | High-level "click the Submit button", "fill this form", app-aware macros, screen-grounded action translation | Provides the grounding loop (screenshot → element → action) so the planner doesn't need to hand-compute pixel coordinates |
| MCP servers | External SaaS integrations (Gmail, Todoist, Notion, Drive, GitHub, Calendar) | Standardized tool schema, auth handling, already-built connectors — avoids reinventing API clients |

- **Why not pure MCP for computer control**: MCP is a tool-invocation protocol, not a low-latency input-injection mechanism; wrapping every mouse move/keystroke as an MCP round trip adds serialization + IPC overhead unsuitable for real-time GUI interaction and OCR-driven retries.
- **Why not pure native APIs everywhere**: native APIs give you pixels and coordinates, not semantic understanding ("find and click Buy Now"); you'd have to hand-roll the vision-grounding loop that OpenClaw/NemoClaw already provide.
- **Chosen split**: `ControlBackend` interface in `execution/control_backend.py` with three implementations — `NativeInputBackend`, `OpenClawBackend`, `NemoClawBackend` — selected per-action by risk/complexity: primitive/low-risk actions go native for speed; semantic/ambiguous UI actions go through OpenClaw/NemoClaw's grounding; anything hitting a cloud SaaS goes through an MCP client.
- **Planner↔Executor communication**: Planner never talks to hardware directly. It emits abstract `Action{type, target_description, params, risk_level}`; the Executor resolves `target_description` to concrete coordinates/elements via the Vision subsystem + chosen backend, executes, and returns an `ActionResult{screenshot_ref, a11y_snapshot, raw_output}` back on the event bus for Verification.
- **OCR**: local model (PaddleOCR or a NIM-hosted VLM with OCR capability) used both for verification (reading confirmation text) and for execution grounding when accessibility trees are unavailable (e.g., canvas-based web apps).
- **Screen capture**: `mss`/DXGI-based capture at low resolution/throttled FPS during idle polling, full-res on-demand before/after each action; frames diffed to detect UI settle before verifying.
- **Window management**: `pywinauto`/UIAutomation for enumerating, focusing, resizing windows so multi-app tasks (email + spreadsheet) don't collide.
- **Clipboard**: `pyperclip` wrapped with an audit log (every clipboard write/read tied to a task-step id) since clipboard is a common covert-exfil vector.
- **Filesystem**: a scoped `FileOps` module restricted to an allow-listed set of directories (Documents, Downloads, project workspace) with path-traversal checks before any write/delete.

## 7. Verification Subsystem

Every action goes through a verify-before-proceed loop:

1. **Screenshot analysis**: capture post-action frame, VLM (local, e.g., a NIM-hosted vision model) answers a structured yes/no/confidence question: "Does this screenshot show the email in the Sent folder?"
2. **UI understanding**: prefer accessibility tree / DOM query when available (faster, deterministic) — VLM is the fallback for opaque UIs (canvas, games, some Electron apps).
3. **OCR cross-check**: for text-critical confirmations (order totals, confirmation numbers), OCR extracts text and regex/LLM-checks it against expected postcondition.
4. **Success detection**: each `Step.success_criteria` is a small predicate (declarative: "element X visible", "process Y exited 0", "text matches regex Z") evaluated against the combined VLM+OCR+a11y evidence; falls back to LLM judge only when predicates are ambiguous.
5. **Retry strategy**: exponential backoff up to N attempts; each retry may vary the action (re-locate element, scroll, alternate selector) rather than blindly repeating.
6. **Recovery logic**: on exhausted retries — classify failure (transient/UI-changed/blocked/needs-auth) and either (a) trigger replanning with failure context, (b) escalate to GUI approval modal for irreversible/ambiguous actions (e.g., "confirm purchase"), or (c) mark step failed and continue if non-blocking.

## 8. Memory Subsystem

Unified `MemoryStore` facade over:

- **SQLite** (structured, ACID): user preferences, contact book, app-usage frequency, shopping preferences, browser preferences, task/step history, credential *metadata* (never raw secrets — see Security).
- **Vector store** (local, e.g., Chroma/LanceDB with a local embedding model): episodic memory of past workflows (successful and failed) embedded by objective+context, enabling few-shot retrieval ("last time you ordered soap, you preferred fragrance-free") to seed the planner.
- **Workflow cache**: successful `TaskGraph`s keyed by objective embedding similarity, replayed with parameter substitution instead of re-planning from scratch when similarity is high — big latency/cost win.
- **Auth state**: OAuth tokens for integrations stored via OS credential vault (Windows Credential Manager / DPAPI), never in plaintext SQLite; MemoryStore only stores a reference key.

## 9. Vision Subsystem

- Capture: `mss` (cross-platform) or DXGI duplication (Windows, lower overhead) for screen frames.
- Preprocessing: downscale + crop to active window before VLM/OCR to cut inference cost.
- Element detection: accessibility API first (UIAutomation/AT-SPI), VLM-based grounding ("Set-of-Marks" style prompting with detected candidate boxes) as fallback for non-instrumented UIs.
- Shared cache: last N frames + a11y snapshots kept in a ring buffer so Verification can diff against pre-action state without re-capturing.

## 10. GUI Architecture (Kivy)

- `gui/app.py` — Kivy `App` subclass, screens managed via `ScreenManager`: `HomeScreen` (objective input + quick source pickers), `TaskScreen` (live plan tree, step status icons, screen preview thumbnail, pause/approve/cancel controls), `HistoryScreen` (past tasks, replay/reuse), `SettingsScreen` (backend selection, allow-listed apps/dirs, model selection).
- GUI runs on the main thread; orchestrator runs in an asyncio loop on a background thread, communicating via a thread-safe queue (`Clock.schedule_once` to marshal events back to Kivy's main loop) — keeps the UI responsive during long-running autonomous execution.
- Approval modal: blocking widget shown only for actions flagged `risk_level=HIGH` (payments, sending mail, deleting files) unless the user has pre-authorized that category in Settings.

## 11. Error Recovery (cross-cutting)

- Idempotency keys on side-effecting actions (e.g., don't double-send an email on retry).
- Checkpointing: task/step state persisted after every transition, so process crash/restart resumes rather than restarts.
- Circuit breaker: repeated failures on the same app/backend within a window pause that backend and surface the issue instead of looping indefinitely.
- Human-in-the-loop escalation only for irreversible or explicitly high-risk actions; everything else is fully autonomous, matching the "no human assistance after initial objective" goal.

## 12. Security Considerations

- Principle of least privilege: `FileOps`, clipboard, and network egress are allow-listed per task/category in `config/security_policy.yaml`.
- No raw credentials in Memory or logs; OAuth tokens live in the OS credential vault, referenced by opaque key.
- All MCP servers run as local subprocesses with scoped tool permissions (e.g., Gmail MCP server can send/read mail but not manage account settings).
- Action audit log (immutable append-only) for every input-injection and file/clipboard/network action, viewable in the GUI History screen — critical for a system that "controls the user's computer."
- Sandboxed execution profile per task (separate browser profile/container where possible) to limit blast radius of a misbehaving step.
- Explicit deny-list for destructive OS operations (disk formatting, registry edits, uninstalling software) regardless of planner output.

## 13. Performance Considerations

- All inference local via NVIDIA NIM/TensorRT-LLM on DGX Spark GPUs; use a smaller/faster model for verification (quick yes/no VLM calls) and a larger model only for planning/replanning to balance latency vs. quality.
- Batch/parallelize independent verification calls; cache OCR/VLM results per unchanged frame (hash-based) to avoid redundant inference.
- Workflow-cache reuse (Section 8) skips full re-planning for previously-seen objective patterns.
- Throttled idle-state screen polling to conserve GPU cycles when no task is active.

## 14. Scalability / Extensibility

- New computer-control backends: implement `ControlBackend` interface, register in `config/backends.yaml` — no orchestrator changes needed.
- New integrations: implement an MCP server (or reuse community ones) + a thin adapter in `integrations/`; planner discovers available tools via MCP tool-list at startup, so new integrations are usable without planner code changes.
- Multi-task concurrency: orchestrator can run multiple independent `Task` FSMs concurrently (separate asyncio tasks), bounded by a configurable concurrency limit and per-app locks to avoid two tasks fighting over the same window.
- Future multi-machine scaling: event bus and MemoryStore are designed behind interfaces so a Redis/Postgres-backed implementation could replace the local SQLite/in-proc bus if scaling beyond one DGX Spark box is ever needed.

## 15. External Integrations — MCP vs Native

| Service | Mechanism | Rationale |
|---|---|---|
| Gmail | MCP server (Gmail MCP) | Well-defined API, auth flow, structured tool calls — MCP's standard schema fits well |
| Todoist | MCP server | Same — REST API naturally maps to MCP tools (list/create/complete tasks) |
| Notion | MCP server | Notion API is well-suited to MCP's resource+tool model |
| Google Drive | MCP server | File listing/read/write maps cleanly to MCP resources/tools |
| GitHub | MCP server (official GitHub MCP) | Mature existing server, avoids reimplementing auth/rate-limiting |
| Calendars | MCP server (Google Calendar MCP or CalDAV adapter) | Structured event CRUD fits MCP well |
| Local documents/files | **Native**, not MCP | Local filesystem access needs no network protocol/auth negotiation — direct `FileOps` calls are faster and simpler; MCP adds unneeded indirection for same-machine file I/O |

MCP is appropriate wherever a well-defined external API/auth flow exists and a community/official server is available or easy to build. It's unnecessary (and adds latency) for same-machine primitives: input injection, clipboard, local file I/O, window management — these go through native APIs directly inside the Execution subsystem.
