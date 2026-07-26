"""NotionIntegration — thin adapter over the "notion" MCP server.

ASSUMED TOOL SCHEMA (verify against the actual server deployed):

    search_pages(query: str) -> {pages: [{id, title, url, last_edited}, ...]}
    read_page(page_id: str) -> {id, title, blocks: [...], plain_text: str}
    append_to_page(page_id: str, content: str) -> {ok: bool}
"""

from __future__ import annotations

from typing import Any

from integrations.mcp_client_manager import MCPClientManager

SERVER_NAME = "notion"


class NotionIntegration:
    def __init__(self, manager: MCPClientManager) -> None:
        self._manager = manager

    async def search_pages(self, query: str) -> list[dict]:
        result = await self._manager.call_tool(
            SERVER_NAME, "search_pages", {"query": query}
        )
        content = result.get("content")
        if isinstance(content, dict) and "pages" in content:
            return list(content["pages"])
        if isinstance(content, list):
            return content
        return []

    async def read_page(self, page_id: str) -> dict[str, Any]:
        result = await self._manager.call_tool(
            SERVER_NAME, "read_page", {"page_id": page_id}
        )
        content = result.get("content")
        return content if isinstance(content, dict) else {"raw": content}

    async def append_to_page(self, page_id: str, content: str) -> dict[str, Any]:
        return await self._manager.call_tool(
            SERVER_NAME,
            "append_to_page",
            {"page_id": page_id, "content": content},
        )
