"""Build langchain_mcp_adapters connection config for Outlook MCP."""

from __future__ import annotations

import os
import shlex

from langchain_mcp_adapters.sessions import Connection, StdioConnection, StreamableHttpConnection

from langgraph_mcp_tester.config import OutlookAgentSettings


def build_outlook_connection(settings: OutlookAgentSettings) -> dict[str, Connection]:
    """Return MultiServerMCPClient connections dict with a single server named ``outlook``."""
    transport = settings.mcp_transport.strip().lower().replace("-", "_")
    if transport == "streamable_http":
        headers: dict[str, str] = {}
        if settings.x_graph_token:
            tok = settings.x_graph_token.get_secret_value().strip()
            if tok.lower().startswith("bearer "):
                tok = tok[7:].strip()
            headers["X-Graph-Token"] = tok
        conn: StreamableHttpConnection = {
            "transport": "streamable_http",
            "url": settings.mcp_url,
        }
        if headers:
            conn["headers"] = headers
        return {"outlook": conn}

    if transport == "stdio":
        parts = shlex.split(settings.mcp_stdio_command, posix=os.name != "nt")
        if not parts:
            msg = "MCP_STDIO_COMMAND is empty"
            raise ValueError(msg)
        command, args = parts[0], parts[1:]
        env = dict(os.environ)
        env["MCP_TRANSPORT"] = "stdio"
        stdio: StdioConnection = {
            "transport": "stdio",
            "command": command,
            "args": args,
            "env": env,
        }
        return {"outlook": stdio}

    msg = f"Unknown MCP_TRANSPORT={settings.mcp_transport!r}; use streamable_http or stdio"
    raise ValueError(msg)
