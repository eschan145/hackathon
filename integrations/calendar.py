"""CalendarIntegration — thin adapter over the "calendar" MCP server
(Google Calendar MCP server, or a CalDAV-backed equivalent per
ARCHITECTURE.md section 15).

ASSUMED TOOL SCHEMA (verify against the actual server deployed):

    list_events(start: str, end: str) -> {events: [{id, title, start, end, attendees}, ...]}
        start/end are ISO-8601 datetime strings.
    create_event(title: str, start: str, end: str, attendees: list[str] | None = None) -> {id, html_link}
"""

from __future__ import annotations

from typing import Any, Optional

from integrations.mcp_client_manager import MCPClientManager

SERVER_NAME = "calendar"


class CalendarIntegration:
    def __init__(self, manager: MCPClientManager) -> None:
        self._manager = manager

    async def list_events(self, start: str, end: str) -> list[dict]:
        result = await self._manager.call_tool(
            SERVER_NAME, "list_events", {"start": start, "end": end}
        )
        content = result.get("content")
        if isinstance(content, dict) and "events" in content:
            return list(content["events"])
        if isinstance(content, list):
            return content
        return []

    async def create_event(
        self,
        title: str,
        start: str,
        end: str,
        attendees: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        args: dict[str, Any] = {"title": title, "start": start, "end": end}
        if attendees is not None:
            args["attendees"] = attendees
        return await self._manager.call_tool(SERVER_NAME, "create_event", args)
