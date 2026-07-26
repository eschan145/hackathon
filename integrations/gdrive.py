"""GDriveIntegration — thin adapter over the "gdrive" MCP server.

ASSUMED TOOL SCHEMA (verify against the actual server deployed):

    list_files(query: str | None = None) -> {files: [{id, name, mime_type, modified_time}, ...]}
    read_file(file_id: str) -> {id, name, content}   # content is text-extracted where possible
    upload_file(path: str) -> {id, name, web_view_link}
"""

from __future__ import annotations

from typing import Any, Optional

from integrations.mcp_client_manager import MCPClientManager

SERVER_NAME = "gdrive"


class GDriveIntegration:
    def __init__(self, manager: MCPClientManager) -> None:
        self._manager = manager

    async def list_files(self, query: Optional[str] = None) -> list[dict]:
        args: dict[str, Any] = {}
        if query is not None:
            args["query"] = query
        result = await self._manager.call_tool(SERVER_NAME, "list_files", args)
        content = result.get("content")
        if isinstance(content, dict) and "files" in content:
            return list(content["files"])
        if isinstance(content, list):
            return content
        return []

    async def read_file(self, file_id: str) -> dict[str, Any]:
        result = await self._manager.call_tool(
            SERVER_NAME, "read_file", {"file_id": file_id}
        )
        content = result.get("content")
        return content if isinstance(content, dict) else {"raw": content}

    async def upload_file(self, path: str) -> dict[str, Any]:
        return await self._manager.call_tool(SERVER_NAME, "upload_file", {"path": path})
