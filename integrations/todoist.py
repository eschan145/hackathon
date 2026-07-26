"""TodoistIntegration — thin adapter over the "todoist" MCP server.

ASSUMED TOOL SCHEMA (verify against the actual server deployed):

    list_tasks(filter: str | None = None) -> {tasks: [{id, content, due, priority, project_id}, ...]}
    complete_task(task_id: str) -> {ok: bool}
    create_task(content: str, due: str | None = None) -> {id, content, due}

`filter` follows Todoist's own filter query syntax (e.g. "today", "overdue",
"p1") when the underlying server passes it straight through to the REST API.
"""

from __future__ import annotations

from typing import Any, Optional

from integrations.mcp_client_manager import MCPClientManager

SERVER_NAME = "todoist"


class TodoistIntegration:
    def __init__(self, manager: MCPClientManager) -> None:
        self._manager = manager

    async def list_tasks(self, filter: Optional[str] = None) -> list[dict]:
        args: dict[str, Any] = {}
        if filter is not None:
            args["filter"] = filter
        result = await self._manager.call_tool(SERVER_NAME, "list_tasks", args)
        content = result.get("content")
        if isinstance(content, dict) and "tasks" in content:
            return list(content["tasks"])
        if isinstance(content, list):
            return content
        return []

    async def complete_task(self, task_id: str) -> dict[str, Any]:
        return await self._manager.call_tool(
            SERVER_NAME, "complete_task", {"task_id": task_id}
        )

    async def create_task(
        self, content: str, due: Optional[str] = None
    ) -> dict[str, Any]:
        args: dict[str, Any] = {"content": content}
        if due is not None:
            args["due"] = due
        return await self._manager.call_tool(SERVER_NAME, "create_task", args)
