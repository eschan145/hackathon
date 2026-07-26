"""GmailIntegration — thin adapter over the "gmail" MCP server.

ASSUMED TOOL SCHEMA (community Gmail MCP servers vary; verify against the
actual server you deploy and adjust the tool names/args below):

    send_email(to: str, subject: str, body: str, cc: str | None = None) -> {message_id}
    search_emails(query: str, max_results: int = 20) -> {messages: [{id, subject, from, snippet, date}, ...]}
    read_email(message_id: str) -> {id, subject, from, to, date, body}
    list_unread(max_results: int = 20) -> {messages: [{id, subject, from, snippet, date}, ...]}

If your chosen Gmail MCP server uses different tool/arg names, this is the
only file that needs to change.
"""

from __future__ import annotations

from typing import Any, Optional

from integrations.mcp_client_manager import MCPClientManager

SERVER_NAME = "gmail"


class GmailIntegration:
    def __init__(self, manager: MCPClientManager) -> None:
        self._manager = manager

    async def send_email(self, to: str, subject: str, body: str) -> dict[str, Any]:
        return await self._manager.call_tool(
            SERVER_NAME,
            "send_email",
            {"to": to, "subject": subject, "body": body},
        )

    async def search(self, query: str) -> list[dict]:
        result = await self._manager.call_tool(
            SERVER_NAME, "search_emails", {"query": query}
        )
        return _extract_messages(result)

    async def list_unread(self) -> list[dict]:
        result = await self._manager.call_tool(SERVER_NAME, "list_unread", {})
        return _extract_messages(result)


def _extract_messages(result: dict[str, Any]) -> list[dict]:
    """Best-effort normalization: unwrap `{"content": ...}` MCP responses
    into a plain list of message dicts, tolerating slightly different
    server response shapes."""
    content = result.get("content")
    if isinstance(content, dict) and "messages" in content:
        return list(content["messages"])
    if isinstance(content, list):
        return content
    return []
