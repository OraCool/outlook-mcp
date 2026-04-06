"""Browser OAuth routes (streamable-http); register only when ``GRAPH_OAUTH_ENABLED``."""

from __future__ import annotations

import html
import json
from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

from outlook_mcp.auth.oauth_session import get_oauth_session_store
from outlook_mcp.config import get_settings

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register_oauth_routes(mcp: FastMCP) -> None:
    @mcp.custom_route("/oauth/login", methods=["GET"])
    async def oauth_login(_request: Request) -> RedirectResponse | HTMLResponse:  # noqa: ARG001
        s = get_settings()
        if not s.graph_oauth_enabled or not s.graph_oauth_client_id.strip():
            return HTMLResponse("OAuth is not enabled.", status_code=404)
        store = get_oauth_session_store()
        flow = store.start_auth_code_flow(s)
        return RedirectResponse(url=flow["auth_uri"], status_code=302)

    @mcp.custom_route("/oauth/callback", methods=["GET"])
    async def oauth_callback(request: Request) -> HTMLResponse | JSONResponse:
        s = get_settings()
        if not s.graph_oauth_enabled or not s.graph_oauth_client_id.strip():
            return HTMLResponse("OAuth is not enabled.", status_code=404)

        q = dict(request.query_params)
        if err := q.get("error"):
            desc = q.get("error_description") or err
            body = f"<p>Sign-in error: {html.escape(str(desc))}</p>"
            return HTMLResponse(body, status_code=400)

        state = q.get("state")
        if not state:
            return HTMLResponse("<p>Missing state parameter.</p>", status_code=400)

        store = get_oauth_session_store()
        flow = store.pop_flow(state)
        if not flow:
            return HTMLResponse("<p>Invalid or expired sign-in session. Start again from /oauth/login.</p>", status_code=400)

        result = store.complete_auth_code(s, flow, q)
        if "access_token" not in result:
            err = result.get("error_description") or result.get("error") or json.dumps(result)
            return HTMLResponse(f"<p>Token exchange failed: {html.escape(str(err))}</p>", status_code=400)

        session_id = store.create_session_from_msal_result(result, s)
        want_json = "application/json" in (request.headers.get("accept") or "").lower()
        if want_json:
            return JSONResponse(
                {
                    "session_id": session_id,
                    "header_name": "X-OAuth-Session",
                    "instructions": "Add this value as a custom header on MCP Streamable HTTP requests.",
                }
            )

        sid_esc = html.escape(session_id)
        page = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Outlook MCP — signed in</title></head>
<body>
<h1>Signed in</h1>
<p>Add this to MCP Inspector <strong>Custom Headers</strong> (toggle ON):</p>
<ul>
  <li><strong>Name:</strong> <code>X-OAuth-Session</code></li>
  <li><strong>Value:</strong> <code id="sid">{sid_esc}</code></li>
</ul>
<p>Sessions are stored in server memory only (single process). Restart the server → sign in again.</p>
</body></html>"""
        return HTMLResponse(page)
