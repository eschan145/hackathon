"""Unified MemoryStore facade (SQLite + vector store), per ARCHITECTURE.md section 8.

Implements the `core.interfaces.Memory` protocol (`save_task`,
`get_similar_workflow`) plus the extra surface described in the
architecture doc: preferences, contacts, app usage, credential
references, and workflow-cache lookups backed by `EpisodicMemory`.

`save_task` / `get_similar_workflow` are declared `async def` to satisfy
the `Memory` Protocol (the Orchestrator awaits them), but the underlying
work is plain synchronous sqlite3 — fine at Orchestratr's scale/latency.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

from core.models import Task, TaskGraph

from .schema import connect
from .vector_store import EpisodicMemory

# Cosine-similarity threshold above which a past successful workflow is
# considered "the same objective" and eligible for replay (the "workflow
# cache" from ARCHITECTURE.md section 8).
SIMILARITY_THRESHOLD = 0.85


class MemoryStore:
    """SQLite-backed structured memory + Chroma-backed episodic memory."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        episodic: Optional[EpisodicMemory] = None,
        similarity_threshold: float = SIMILARITY_THRESHOLD,
    ) -> None:
        self._conn = connect(db_path)
        self._episodic = episodic or EpisodicMemory()
        self._similarity_threshold = similarity_threshold

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    async def save_task(self, task: Task) -> None:
        """Persist/update a Task row and (if completed) index it for the
        workflow cache via EpisodicMemory.
        """
        graph_json = task.graph.model_dump_json() if task.graph else None
        history_json = json.dumps(task.history)
        success = 1 if task.state == "COMPLETED" else (0 if task.state == "FAILED" else None)
        completed_at = time.time() if task.state in ("COMPLETED", "FAILED") else None

        with self._conn:
            self._conn.execute(
                """
                INSERT INTO tasks (id, objective, source, state, created_at, completed_at, graph_json, history_json, success)
                VALUES (:id, :objective, :source, :state, :created_at, :completed_at, :graph_json, :history_json, :success)
                ON CONFLICT(id) DO UPDATE SET
                    objective=excluded.objective,
                    source=excluded.source,
                    state=excluded.state,
                    completed_at=COALESCE(excluded.completed_at, tasks.completed_at),
                    graph_json=excluded.graph_json,
                    history_json=excluded.history_json,
                    success=COALESCE(excluded.success, tasks.success)
                """,
                {
                    "id": task.id,
                    "objective": task.objective,
                    "source": task.source,
                    "state": task.state,
                    "created_at": task.created_at,
                    "completed_at": completed_at,
                    "graph_json": graph_json,
                    "history_json": history_json,
                    "success": success,
                },
            )

        if task.graph is not None and task.state in ("COMPLETED", "FAILED"):
            self._episodic.add_workflow(
                task_id=task.id,
                objective=task.objective,
                task_graph_json=task.graph.model_dump_json(),
                success=(task.state == "COMPLETED"),
            )

    async def get_task(self, task_id: str) -> Optional[Task]:
        row = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_task(row)

    async def delete_task(self, task_id: str) -> bool:
        """Permanently remove one persisted task record."""
        with self._conn:
            self._conn.execute("DELETE FROM conversation_messages WHERE task_id = ?", (task_id,))
            cursor = self._conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        self._episodic.delete_workflow(task_id)
        return cursor.rowcount > 0

    async def delete_all_tasks(self) -> int:
        """Permanently remove every persisted task, chat, and workflow-cache
        entry. Returns the number of task rows deleted.

        Callers (backend/main.py) are responsible for cancelling any
        still-running asyncio task first - deleting rows out from under a
        running Orchestrator loop wouldn't stop it, and its next
        save_task() would just re-insert the row via the upsert in
        save_task() above.
        """
        with self._conn:
            self._conn.execute("DELETE FROM conversation_messages")
            cursor = self._conn.execute("DELETE FROM tasks")
        self._episodic.delete_all()
        return cursor.rowcount

    async def list_recent_tasks(self, limit: int = 20) -> list[Task]:
        rows = self._conn.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._row_to_task(r) for r in rows]

    async def list_conversation_messages(self, task_id: str) -> list[dict[str, Any]]:
        """Return the durable, user-visible conversation for a task."""
        rows = self._conn.execute(
            """
            SELECT id, task_id, role, text, created_at
            FROM conversation_messages
            WHERE task_id = ?
            ORDER BY created_at ASC
            """,
            (task_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    async def append_conversation_message(
        self,
        task_id: str,
        message_id: str,
        role: str,
        text: str,
        created_at: float,
    ) -> dict[str, Any]:
        """Persist one chat message, idempotently by message id."""
        with self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO conversation_messages (id, task_id, role, text, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (message_id, task_id, role, text, created_at),
            )
        return {
            "id": message_id,
            "task_id": task_id,
            "role": role,
            "text": text,
            "created_at": created_at,
        }

    @staticmethod
    def _row_to_task(row: Any) -> Task:
        graph = TaskGraph.model_validate_json(row["graph_json"]) if row["graph_json"] else None
        history = json.loads(row["history_json"]) if row["history_json"] else []
        return Task(
            id=row["id"],
            objective=row["objective"],
            source=row["source"] or "gui",
            state=row["state"] or "RECEIVED",
            created_at=row["created_at"] or time.time(),
            graph=graph,
            history=history,
        )

    async def get_similar_workflow(self, objective: str) -> Optional[TaskGraph]:
        """Workflow cache: find a similar past *successful* task by
        objective-embedding cosine similarity above `SIMILARITY_THRESHOLD`
        and return its TaskGraph for reuse/replay (parameter substitution
        is the caller/planner's responsibility, per ARCHITECTURE.md
        section 8).
        """
        results = self._episodic.find_similar(objective, top_k=3, only_success=True)
        for r in results:
            similarity = r.get("similarity")
            if similarity is None or similarity >= self._similarity_threshold:
                try:
                    return TaskGraph.model_validate_json(r["task_graph_json"])
                except Exception:
                    continue
        return None

    # ------------------------------------------------------------------
    # Preferences
    # ------------------------------------------------------------------

    async def get_preference(self, key: str, category: str = "general") -> Optional[str]:
        row = self._conn.execute(
            "SELECT value FROM preferences WHERE key = ? AND category = ?", (key, category)
        ).fetchone()
        return row["value"] if row else None

    async def set_preference(self, key: str, value: str, category: str = "general") -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO preferences (key, category, value, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key, category) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (key, category, value, time.time()),
            )

    async def list_preferences(self, category: Optional[str] = None) -> list[dict[str, Any]]:
        if category:
            rows = self._conn.execute(
                "SELECT * FROM preferences WHERE category = ?", (category,)
            ).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM preferences").fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Contacts
    # ------------------------------------------------------------------

    async def get_contact(self, name: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute("SELECT * FROM contacts WHERE name = ?", (name,)).fetchone()
        return dict(row) if row else None

    async def upsert_contact(
        self, name: str, email: Optional[str] = None, metadata: Optional[dict[str, Any]] = None
    ) -> None:
        """Insert/update a contact and bump its use_count/last_used_at."""
        metadata_json = json.dumps(metadata) if metadata is not None else None
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO contacts (name, email, metadata_json, last_used_at, use_count)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(name) DO UPDATE SET
                    email=COALESCE(excluded.email, contacts.email),
                    metadata_json=COALESCE(excluded.metadata_json, contacts.metadata_json),
                    last_used_at=excluded.last_used_at,
                    use_count=contacts.use_count + 1
                """,
                (name, email, metadata_json, time.time()),
            )

    # ------------------------------------------------------------------
    # App usage
    # ------------------------------------------------------------------

    async def record_app_use(self, app_name: str) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO app_usage (app_name, use_count, last_used_at)
                VALUES (?, 1, ?)
                ON CONFLICT(app_name) DO UPDATE SET
                    use_count=app_usage.use_count + 1,
                    last_used_at=excluded.last_used_at
                """,
                (app_name, time.time()),
            )

    async def most_frequent_apps(self, limit: int = 10) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM app_usage ORDER BY use_count DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Credential references (opaque only — see memory.credential_vault.CredentialVault)
    # ------------------------------------------------------------------

    async def set_credential_ref(self, service: str, ref_key: str) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO credentials_ref (service, ref_key, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(service) DO UPDATE SET ref_key=excluded.ref_key, updated_at=excluded.updated_at
                """,
                (service, ref_key, time.time()),
            )

    async def get_credential_ref(self, service: str) -> Optional[str]:
        row = self._conn.execute(
            "SELECT ref_key FROM credentials_ref WHERE service = ?", (service,)
        ).fetchone()
        return row["ref_key"] if row else None

    # ------------------------------------------------------------------
    # Shopping / browser preferences
    # ------------------------------------------------------------------

    async def get_shopping_preference(self, category: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT preference_json FROM shopping_preferences WHERE category = ?", (category,)
        ).fetchone()
        return json.loads(row["preference_json"]) if row and row["preference_json"] else None

    async def set_shopping_preference(self, category: str, preference: dict[str, Any]) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO shopping_preferences (category, preference_json)
                VALUES (?, ?)
                ON CONFLICT(category) DO UPDATE SET preference_json=excluded.preference_json
                """,
                (category, json.dumps(preference)),
            )

    async def get_browser_preference(self, key: str) -> Optional[str]:
        row = self._conn.execute(
            "SELECT value FROM browser_preferences WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    async def set_browser_preference(self, key: str, value: str) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO browser_preferences (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, value),
            )

    def close(self) -> None:
        self._conn.close()
