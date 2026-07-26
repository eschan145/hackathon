"""integrations/ — MCP client manager + per-service adapters + native
local-file connector (ARCHITECTURE.md section 2/15).

`IntegrationRegistry` is the single entry point the rest of the app (GUI,
Orchestrator) should use: it owns one `MCPClientManager`, constructs all the
per-service adapters over it, and exposes `discover_objectives()` — the
concrete implementation of "obtaining objectives from external sources"
(section 3: "GUI or Integration layer emits ObjectiveReceived(text, source)
onto the event bus", section 5: prioritization "pulled from the source
integration").
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from integrations.calendar import CalendarIntegration
from integrations.gdrive import GDriveIntegration
from integrations.github import GitHubIntegration
from integrations.gmail import GmailIntegration
from integrations.local_files import LocalDocumentReader, LocalObjectiveScanner
from integrations.mcp_client_manager import MCPClientManager
from integrations.notion import NotionIntegration
from integrations.todoist import TodoistIntegration

__all__ = [
    "IntegrationRegistry",
    "MCPClientManager",
    "GmailIntegration",
    "TodoistIntegration",
    "NotionIntegration",
    "GDriveIntegration",
    "GitHubIntegration",
    "CalendarIntegration",
    "LocalObjectiveScanner",
    "LocalDocumentReader",
]


class IntegrationRegistry:
    """Aggregates every integration adapter behind one object.

    Usage::

        registry = IntegrationRegistry()
        await registry.connect()
        objectives = await registry.discover_objectives()
        gmail = registry.get("gmail")
    """

    def __init__(
        self,
        mcp_config_path: str = "config/mcp_servers.yaml",
        security_policy_path: str = "config/security_policy.yaml",
    ) -> None:
        self.manager = MCPClientManager()
        self._mcp_config_path = mcp_config_path

        # Loading the yaml config is best-effort: a missing/malformed file
        # shouldn't prevent constructing the registry (e.g. local-only demo
        # runs with no MCP servers configured yet).
        try:
            self.manager.load_config(mcp_config_path)
        except (FileNotFoundError, RuntimeError):
            pass

        self.gmail = GmailIntegration(self.manager)
        self.todoist = TodoistIntegration(self.manager)
        self.notion = NotionIntegration(self.manager)
        self.gdrive = GDriveIntegration(self.manager)
        self.github = GitHubIntegration(self.manager)
        self.calendar = CalendarIntegration(self.manager)

        # Native, not MCP (section 15).
        self.local_files = LocalObjectiveScanner(security_policy_path=security_policy_path)
        self.local_reader = LocalDocumentReader(security_policy_path)

        self._by_name: dict[str, Any] = {
            "gmail": self.gmail,
            "todoist": self.todoist,
            "notion": self.notion,
            "gdrive": self.gdrive,
            "github": self.github,
            "calendar": self.calendar,
            "local_files": self.local_files,
        }

    def get(self, name: str) -> Any:
        """Fetch an integration adapter by name (planner-friendly lookup)."""
        try:
            return self._by_name[name]
        except KeyError as exc:
            raise KeyError(
                f"Unknown integration '{name}'. Known: {list(self._by_name)}"
            ) from exc

    async def connect(self) -> dict[str, bool]:
        """Connect all MCP-backed integrations. Local files need no connection."""
        return await self.manager.connect_all()

    async def list_all_tools_for_planner(self) -> dict[str, list[dict]]:
        return await self.manager.list_all_tools_for_planner()

    async def discover_objectives(self) -> list[dict]:
        """Poll every objective-bearing source and return candidate
        objectives as plain dicts: ``{"text": str, "source": str, "meta": dict}``.

        Sources polled (best-effort — a failure in one source does not
        block the others, matching the recovery philosophy in section 11):
          - Todoist: open tasks (mapped 1:1 to objectives)
          - Gmail: unread messages (surfaced as "reply to / triage email" objectives)
          - Calendar: upcoming events needing prep (next 24h window)
          - Local files: unchecked `- [ ]` todo items in allow-listed notes
        """
        results: list[dict] = []

        async def _todoist() -> list[dict]:
            try:
                tasks = await self.todoist.list_tasks(filter="today | overdue")
            except Exception:
                return []
            out = []
            for t in tasks:
                out.append(
                    {
                        "text": t.get("content", str(t)),
                        "source": "todoist",
                        "meta": t,
                    }
                )
            return out

        async def _gmail() -> list[dict]:
            try:
                unread = await self.gmail.list_unread()
            except Exception:
                return []
            out = []
            for m in unread:
                subject = m.get("subject", "(no subject)")
                out.append(
                    {
                        "text": f"Triage email: {subject}",
                        "source": "gmail",
                        "meta": m,
                    }
                )
            return out

        async def _calendar() -> list[dict]:
            try:
                import datetime

                now = datetime.datetime.utcnow()
                soon = now + datetime.timedelta(hours=24)
                events = await self.calendar.list_events(
                    now.isoformat() + "Z", soon.isoformat() + "Z"
                )
            except Exception:
                return []
            out = []
            for e in events:
                title = e.get("title", "(untitled event)")
                out.append(
                    {
                        "text": f"Prepare for upcoming event: {title}",
                        "source": "calendar",
                        "meta": e,
                    }
                )
            return out

        async def _local() -> list[dict]:
            try:
                candidates = self.local_files.scan()
            except Exception:
                return []
            return [
                {"text": c.text, "source": c.source, "meta": {}} for c in candidates
            ]

        # Run all sources concurrently; each is independently fault-tolerant.
        for chunk in await asyncio.gather(_todoist(), _gmail(), _calendar(), _local()):
            results.extend(chunk)

        return results
