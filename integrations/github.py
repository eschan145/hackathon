"""GitHubIntegration — thin adapter over the "github" MCP server.

ASSUMED TOOL SCHEMA — based on the official GitHub MCP server's commonly
documented tool set (names may differ slightly by version; verify against
the deployed server):

    create_issue(owner: str, repo: str, title: str, body: str | None = None) -> {number, html_url}
    list_issues(owner: str, repo: str, state: str = "open") -> {issues: [{number, title, state, html_url}, ...]}
    create_pull_request(owner: str, repo: str, title: str, head: str, base: str, body: str | None = None) -> {number, html_url}
    search_repositories(query: str) -> {repositories: [{full_name, html_url, description}, ...]}
"""

from __future__ import annotations

from typing import Any, Optional

from integrations.mcp_client_manager import MCPClientManager

SERVER_NAME = "github"


class GitHubIntegration:
    def __init__(self, manager: MCPClientManager) -> None:
        self._manager = manager

    async def create_issue(
        self, owner: str, repo: str, title: str, body: Optional[str] = None
    ) -> dict[str, Any]:
        args: dict[str, Any] = {"owner": owner, "repo": repo, "title": title}
        if body is not None:
            args["body"] = body
        return await self._manager.call_tool(SERVER_NAME, "create_issue", args)

    async def list_issues(
        self, owner: str, repo: str, state: str = "open"
    ) -> list[dict]:
        result = await self._manager.call_tool(
            SERVER_NAME,
            "list_issues",
            {"owner": owner, "repo": repo, "state": state},
        )
        content = result.get("content")
        if isinstance(content, dict) and "issues" in content:
            return list(content["issues"])
        if isinstance(content, list):
            return content
        return []

    async def create_pull_request(
        self,
        owner: str,
        repo: str,
        title: str,
        head: str,
        base: str,
        body: Optional[str] = None,
    ) -> dict[str, Any]:
        args: dict[str, Any] = {
            "owner": owner,
            "repo": repo,
            "title": title,
            "head": head,
            "base": base,
        }
        if body is not None:
            args["body"] = body
        return await self._manager.call_tool(SERVER_NAME, "create_pull_request", args)

    async def search_repositories(self, query: str) -> list[dict]:
        result = await self._manager.call_tool(
            SERVER_NAME, "search_repositories", {"query": query}
        )
        content = result.get("content")
        if isinstance(content, dict) and "repositories" in content:
            return list(content["repositories"])
        if isinstance(content, list):
            return content
        return []
