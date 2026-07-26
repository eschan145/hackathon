# Autonomous Desktop Assistant — Context

An AI-powered to-do list that actually completes the work locally. You give it an
objective; it plans, executes on your machine, verifies the result, and asks for
approval only when a step is risky.

Deep design lives in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). This file is
the brief plus where things currently stand.

---

## The brief

We are building an AI-powered to-do list which has the ability to complete things
locally for you. For example: if I enter "AP world notes" into the to-do list,
then I can upload the document which I'm supposed to take notes on.

A to-do list which can take in all inputs — emails, homework, calendar events,
to-do list — and then execute things for you. "I have 5 unread emails" → it goes
through them, drafts replies, and takes earlier context into account. Then you can
add more context so it performs better, and approve its draft for sending. Then it
can schedule time in your calendar (potentially). Similar intent to Claude
dispatch.

For a hackathon, we are building an AI-powered automation that can control your
computer and do tasks for you. One big advantage is that it can run locally on the
NVIDIA DGX Spark (a key requirement). Examples of what it should do:

- Take a prompt or objective — "Write an email to a certain person outlining xyz",
  "Find the best hand soap on Amazon and order it for me."
- Pull objectives from other sources (to-do list apps, documents, etc.) and act on
  them.
- For every task: take the objective as input, think about an action plan, and
  execute on it.
- Work without needing assistance — ideally everything by itself, other than being
  given the primary objective.
- Act as a layer on top of OpenShell, OpenClaw or NemoClaw, running as a GUI app
  optimized for this use case.

**Hard requirements**

- Must use OpenShell, OpenClaw or NemoClaw in some way.
- All computing must be done locally on an NVIDIA DGX Spark.

---

## Current state

End-to-end path works: an objective submitted in the GUI reaches the orchestrator,
gets planned, executes through OpenClaw, and streams state back to the UI live.
Quality of the actual automation is the weak link, not the plumbing (see Known
gaps).

### Layout

| Path | What it is |
|---|---|
| `core/` | Orchestrator FSM, event bus, shared pydantic models (`Task`, `TaskGraph`, `Step`) |
| `planning/` | LLM planner + `OpenClawPlanner`, prompts, task-graph construction |
| `execution/` | Executor, control-backend abstraction, file ops, audit log |
| `verification/` | Verifier, `OpenClawVerifier` stopgap, retry policy, recovery |
| `memory/` | SQLite store, vector store, credential vault |
| `vision/` | Screen capture, OCR, element detection, VLM client |
| `integrations/` | MCP connectors — Gmail, Calendar, Notion, Drive, GitHub, local files |
| `backend/` | FastAPI app: REST + `/ws/events` websocket |
| `frontend/` | Electron + React GUI (the shipped one) |
| `gui/` | Earlier Kivy GUI — superseded by `frontend/`, kept for reference |

### Backend API (`backend/main.py`, port 8765)

```
POST /api/objectives          {objective, source} -> {task_id}
GET  /api/tasks               -> {tasks: [Task]}
GET  /api/tasks/{id}          -> Task
POST /api/tasks/{id}/approve  {step_id, approved}
POST /api/tasks/{id}/cancel
GET  /api/settings            POST /api/settings
WS   /ws/events               orchestrator event stream
```

Tasks serialize as `core.models.Task`: identifier is `id` (not `task_id`), steps
are nested under `graph.steps`, `created_at` is a float epoch. The frontend
flattens this in `frontend/src/api/client.ts` (`normalizeTask`) — that file is the
single place to reconcile if the contract shifts.

`SettingsModel` sets `extra = "allow"`, so the UI persists `approval_mode`
alongside the declared fields without a schema change.

### Frontend (`frontend/`)

Electron 31 + React 18 + Vite, TypeScript, hand-rolled CSS (no UI framework).
Light Notion/ChatGPT-flavoured shell.

- **Tasks** — live table of every objective: status pill, step progress, ticking
  elapsed timer, hover row actions (open chat, cancel). The page uses the shared
  `TaskComposer` at the top: a multiline task description (including any plan
  or procedure), dedicated link input, native file picker, and removable
  resource chips.
  ⌘K/Ctrl+K (or the sidebar button) opens the same composer as a modal from
  anywhere. Electron captures each attachment's absolute path; links are
  normalized to URLs and multiple pasted links are accepted. Because the
  backend still accepts one `objective` string, the composer keeps the task
  description first and appends labeled `Files to work with` and `Links to use`
  sections for the planner.
- **Task chat** — per-task thread showing the orchestrator's chain of thought
  streamed from `/ws/events`, plus approval cards.
- **Notifications** — feed of plans, failures, approvals, completions.
- **Settings** — approval mode, control backend, local model names, allow-listed
  directories.

State lives in one store (`frontend/src/store.tsx`) that merges the REST task list
with the websocket stream — no polling.

**Approval modes** (Settings): *Ask me every time* · *Proceed after 10s* (countdown
with a Hold button) · *Run autonomously*. The orchestrator only ever pauses for
steps it rates `risk_level: high`. Auto-approval is applied client-side, so it only
holds while the app is open — a run left unattended with the window closed still
blocks.

### Running it

```bash
# backend
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8765

# frontend, dev (hot reload, opens devtools)
cd frontend && npm run dev

# frontend, production build + launch
cd frontend && npm run build && NODE_ENV=production ./node_modules/.bin/electron dist-electron/main.js
```

The renderer talks straight to `127.0.0.1:8765` over fetch + websocket; there is no
IPC bridge.

### Known gaps

- **Verification is a stopgap.** No local vision-model endpoint is reachable
  (`config/models.yaml`), so `OpenClawVerifier` asks OpenClaw's own agent to judge
  whether a step succeeded rather than checking independently.
- **Short objectives fail.** A one-word objective ("summarize") gives the planner
  too little; it retries, replans, and gives up. Replanned steps also embed the
  entire prior-failure history in their description — the UI trims this for
  display (`cleanStepText`), but the underlying text stays noisy.
- **No pause/resume endpoint** — only cancel exists.
- **No chat endpoint.** A message in a task chat is submitted as a follow-up
  objective; there is no conversational turn with the agent about a running task.
- **In-memory notifications and chat** reset when the app restarts; tasks persist
  through the memory subsystem.
- `docs/ARCHITECTURE.md` still describes a Kivy GUI layer — the shipped GUI is
  Electron/React under `frontend/`.
- Electron 31's `File.path` is what makes attachment paths work; Electron 32+
  removed it in favour of `webUtils.getPathForFile`.
