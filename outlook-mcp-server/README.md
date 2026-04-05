# Outlook MCP Server

MCP server for **Microsoft Outlook / Microsoft Graph** mail operations, built for the AR Email Management solution (Path C — delegated token via `X-Graph-Token`, per ADR-006).

## Features

- **Read tools**: `get_email`, `get_thread`, `search_emails`, `list_inbox`, `get_attachments`
- **AI tools** (MCP sampling): `categorize_email`, `extract_email_data` — fall back to returning raw email JSON if the client does not support sampling
- **Write tools** (optional): `send_email`, `create_draft` — disabled unless `ENABLE_WRITE_OPERATIONS=true` (ADR-005 prefers the Graph API Bridge for send)
- **Transports**: `stdio` (CodeMie MCP-Connect Bridge, local dev) and `streamable-http` (AKS / Traefik)
- **Auth**: delegated Graph token via `X-Graph-Token` (or `GRAPH_DEV_TOKEN` for local dev)

## Requirements

- Python 3.12+
- Microsoft Graph permissions on the token: at least `Mail.Read` for read tools; `Mail.Send` for write tools when enabled

## Install (development, uv)

```bash
cd outlook-mcp-server
uv sync --extra dev
```

If you prefer pip/venv, `pip install -e ".[dev]"` still works.

## Configuration

See [`.env.example`](.env.example). Important variables:

| Variable | Description |
| -------- | ----------- |
| `MCP_TRANSPORT` | `stdio` (default) or `streamable-http` |
| `MCP_HOST` / `MCP_PORT` | Bind address for Streamable HTTP (default `127.0.0.1:8000`; use `0.0.0.0` in containers) |
| `MCP_STATELESS_HTTP` | `true` for stateless Streamable HTTP (better behind LB; sampling may be limited) |
| `GRAPH_DEV_TOKEN` | Optional static delegated token for local testing only (never production) |
| `ENABLE_WRITE_OPERATIONS` | `true` to enable `send_email` / `create_draft` |

## Run

**stdio** (default):

```bash
MCP_TRANSPORT=stdio uv run outlook-mcp-server
# or: MCP_TRANSPORT=stdio uv run python -m outlook_mcp.server
```

**Streamable HTTP** (MCP endpoint default path `/mcp`, health `GET /health`):

```bash
MCP_TRANSPORT=streamable-http MCP_HOST=0.0.0.0 MCP_PORT=8000 uv run outlook-mcp-server
```

Point an MCP client at `http://<host>:8000/mcp` (Streamable HTTP).

## Docker

```bash
docker build -t outlook-mcp-server .
docker run --rm -p 8000:8000 \
  -e GRAPH_DEV_TOKEN="..." \
  outlook-mcp-server
```

## Token handling

1. **Streamable HTTP**: Send header `X-Graph-Token: <Microsoft Entra access token>`. Starlette exposes it on the MCP request context; the server validates JWT `exp` before calling Graph.
2. **Expired token**: Tools return a JSON payload with `code: ERR_GRAPH_TOKEN_EXPIRED` (ADR-006).
3. **Logging**: Never log `X-Graph-Token` or email bodies in production.

### Obtaining a Graph token (delegated)

For **Path C** / production-style testing you need a **user-delegated** Graph access token (JWT) with scopes such as `Mail.Read`.

- **[Graph Explorer](https://developer.microsoft.com/en-us/graph/graph-explorer)** — Sign in and copy the access token for quick manual tests.
- **Your own app registration** — Create an app in [Entra ID](https://entra.microsoft.com/), configure redirect URIs and **API permissions** (Microsoft Graph delegated: `Mail.Read`, etc.), then use the [OAuth 2.0 authorization code flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow) or [MSAL](https://learn.microsoft.com/en-us/entra/msal/overview) to acquire tokens. The **Application (client) ID** belongs to that OAuth client (your UI or gateway); this MCP server does **not** read tenant/client secrets from `.env` — only the per-request delegated token (`X-Graph-Token`) or `GRAPH_DEV_TOKEN` for local dev.

## Tests

```bash
uv run pytest
```

## References

- [Microsoft Graph Mail API overview](https://learn.microsoft.com/en-us/graph/api/resources/mail-api-overview?view=graph-rest-1.0)
- AR architecture: `../ar-mail-management/` (ADR-005, ADR-006)
