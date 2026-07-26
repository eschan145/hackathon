"""MCPClientManager — manages subprocess-based MCP (Model Context Protocol)
server connections over stdio, per ARCHITECTURE.md section 15.

Design notes
------------
- Each registered "server" is a local subprocess (npx / python / docker /
  whatever `command` is) that speaks MCP over stdio. We never hand-roll the
  wire protocol; we lean on the official `mcp` Python SDK
  (`mcp.client.stdio` + `mcp.ClientSession`) when it is installed.
- The `mcp` package is an OPTIONAL dependency for this hackathon build. If
  it's not installed in the current environment, `MCPClientManager` still
  imports and can be constructed (config loading, registration, and the
  planner-facing `list_all_tools_for_planner` all degrade gracefully to
  empty results) so the rest of the app doesn't hard-crash. Real tool calls
  raise a clear `RuntimeError` telling you to `pip install mcp`.
- Per architecture section 5/14: "planner discovers available tools via
  MCP tool-list at startup, so new integrations are usable without planner
  code changes." `list_all_tools_for_planner()` is the hook the planning
  subsystem calls for that discovery step.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

try:
    import yaml
except ImportError:  # pragma: no cover - yaml is a light, near-universal dep
    yaml = None  # type: ignore[assignment]

# --- Optional MCP SDK import -------------------------------------------------
# TODO(integration-owner): `pip install mcp` to enable real MCP connections.
# Until then, MCPClientManager runs in a "config-only" degraded mode: servers
# can be registered and inspected, but connect_all()/call_tool() will raise.
try:
    from mcp import ClientSession, StdioServerParameters  # type: ignore
    from mcp.client.stdio import stdio_client  # type: ignore

    _MCP_SDK_AVAILABLE = True
except ImportError:  # pragma: no cover
    ClientSession = None  # type: ignore[assignment]
    StdioServerParameters = None  # type: ignore[assignment]
    stdio_client = None  # type: ignore[assignment]
    _MCP_SDK_AVAILABLE = False


_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _resolve_env_placeholders(value: Any) -> Any:
    """Resolve ``${VAR}`` placeholders against the current process env.

    Applied recursively to strings inside dict/list config values loaded
    from mcp_servers.yaml, so real secrets never need to be committed to
    the yaml file itself.
    """
    if isinstance(value, str):
        def _sub(match: re.Match) -> str:
            return os.environ.get(match.group(1), "")

        return _ENV_VAR_PATTERN.sub(_sub, value)
    if isinstance(value, dict):
        return {k: _resolve_env_placeholders(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env_placeholders(v) for v in value]
    return value


@dataclass
class MCPServerSpec:
    """Static definition of one MCP server (from config/mcp_servers.yaml)."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class _ServerConnection:
    """Live connection state for one registered server."""

    spec: MCPServerSpec
    session: Optional[Any] = None  # mcp.ClientSession when connected
    _stdio_ctx: Optional[Any] = None
    _exit_stack: Optional[contextlib.AsyncExitStack] = None
    connected: bool = False
    tools_cache: Optional[list[dict]] = None


class MCPClientManager:
    """Owns connections to every configured local MCP server.

    Typical usage::

        mgr = MCPClientManager()
        mgr.load_config("config/mcp_servers.yaml")
        await mgr.connect_all()
        tools = await mgr.list_all_tools_for_planner()
        result = await mgr.call_tool("gmail", "send_email", {...})
    """

    def __init__(self) -> None:
        self._servers: dict[str, _ServerConnection] = {}

    # -- registration ---------------------------------------------------

    def register_server(
        self,
        name: str,
        command: str,
        args: Optional[list[str]] = None,
        env: Optional[dict[str, str]] = None,
    ) -> None:
        """Register (or overwrite) one server definition."""
        spec = MCPServerSpec(name=name, command=command, args=args or [], env=env or {})
        self._servers[name] = _ServerConnection(spec=spec)

    def load_config(self, path: str | Path = "config/mcp_servers.yaml") -> None:
        """Load server definitions from a simple yaml mapping file.

        Expected shape (see config/mcp_servers.yaml for the full example)::

            <server_name>:
              command: "npx"
              args: ["-y", "@modelcontextprotocol/server-foo"]
              env:
                SOME_TOKEN: "${SOME_TOKEN}"
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"MCP server config not found: {path}")
        if yaml is None:
            raise RuntimeError(
                "pyyaml is required to load config/mcp_servers.yaml "
                "(pip install pyyaml)"
            )

        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for name, cfg in raw.items():
            cfg = _resolve_env_placeholders(cfg or {})
            self.register_server(
                name=name,
                command=cfg.get("command", ""),
                args=list(cfg.get("args", [])),
                env=dict(cfg.get("env", {})),
            )

    def registered_servers(self) -> list[str]:
        return list(self._servers.keys())

    # -- connection lifecycle -------------------------------------------

    async def connect_all(self) -> dict[str, bool]:
        """Connect to every registered server. Returns {name: success}.

        Individual server connection failures are caught and reported
        rather than raised, so one misconfigured/unavailable integration
        (e.g. no Notion token set) doesn't prevent the others from coming
        up — matches the "best-effort discovery" spirit of section 14.
        """
        results: dict[str, bool] = {}
        for name in self._servers:
            try:
                await self.connect(name)
                results[name] = True
            except Exception:
                results[name] = False
        return results

    async def connect(self, server_name: str) -> None:
        conn = self._require_server(server_name)
        if conn.connected:
            return
        if not _MCP_SDK_AVAILABLE:
            raise RuntimeError(
                "The `mcp` Python SDK is not installed. "
                "Run `pip install mcp` to enable real MCP server connections. "
                f"(server={server_name!r} was not connected; running in "
                "config-only degraded mode.)"
            )

        server_env = {**os.environ, **conn.spec.env}
        params = StdioServerParameters(
            command=conn.spec.command, args=conn.spec.args, env=server_env
        )

        stack = contextlib.AsyncExitStack()
        read_stream, write_stream = await stack.enter_async_context(
            stdio_client(params)
        )
        session = await stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()

        conn._exit_stack = stack
        conn.session = session
        conn.connected = True

    async def disconnect(self, server_name: str) -> None:
        conn = self._servers.get(server_name)
        if conn is None or not conn.connected:
            return
        if conn._exit_stack is not None:
            await conn._exit_stack.aclose()
        conn.session = None
        conn.connected = False
        conn.tools_cache = None

    async def disconnect_all(self) -> None:
        await asyncio.gather(
            *(self.disconnect(name) for name in self._servers), return_exceptions=True
        )

    # -- tool discovery / invocation --------------------------------------

    async def list_tools(self, server_name: str) -> list[dict]:
        """List tools exposed by one connected MCP server.

        Returns a list of plain dicts: ``{"name": str, "description": str,
        "input_schema": dict}`` — deliberately un-typed (not the raw SDK
        object) so the planning subsystem can consume this without an `mcp`
        import of its own.
        """
        conn = self._require_server(server_name)
        if conn.tools_cache is not None:
            return conn.tools_cache

        if not conn.connected:
            # Degraded mode / not yet connected: no tools known.
            return []

        result = await conn.session.list_tools()  # type: ignore[union-attr]
        tools = [
            {
                "name": t.name,
                "description": getattr(t, "description", "") or "",
                "input_schema": getattr(t, "inputSchema", {}) or {},
            }
            for t in result.tools
        ]
        conn.tools_cache = tools
        return tools

    async def list_all_tools_for_planner(self) -> dict[str, list[dict]]:
        """Aggregate tool listings across all registered servers.

        This is the entry point the planning subsystem calls at startup
        (ARCHITECTURE.md section 5/14: "planner discovers available tools
        via MCP tool-list at startup"). Servers that aren't connected or
        that error out simply contribute an empty list rather than
        aborting discovery for everyone else.
        """
        out: dict[str, list[dict]] = {}
        for name in self._servers:
            try:
                out[name] = await self.list_tools(name)
            except Exception:
                out[name] = []
        return out

    async def call_tool(
        self, server_name: str, tool_name: str, arguments: dict[str, Any]
    ) -> dict:
        """Invoke a tool on a connected MCP server.

        Returns a normalized dict: ``{"ok": bool, "content": ..., "raw": ...}``.
        """
        conn = self._require_server(server_name)
        if not conn.connected:
            raise RuntimeError(
                f"MCP server '{server_name}' is not connected. "
                "Call connect_all()/connect() first "
                f"(mcp SDK available={_MCP_SDK_AVAILABLE})."
            )

        result = await conn.session.call_tool(tool_name, arguments)  # type: ignore[union-attr]
        is_error = bool(getattr(result, "isError", False))
        content = getattr(result, "content", None)
        return {"ok": not is_error, "content": content, "raw": result}

    # -- internals --------------------------------------------------------

    def _require_server(self, server_name: str) -> _ServerConnection:
        conn = self._servers.get(server_name)
        if conn is None:
            raise KeyError(
                f"MCP server '{server_name}' is not registered. "
                f"Known servers: {list(self._servers)}"
            )
        return conn
