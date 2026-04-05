# Outlook MCP Server

MCP server for **Microsoft Outlook / Microsoft Graph** mail operations, built for the AR Email Management solution (Path C — delegated token via `X-Graph-Token`, per ADR-006).

## Features

- **Read tools**: `get_email`, `get_thread`, `search_emails`, `list_inbox`, `get_attachments`
- **AI tools** (MCP sampling): `categorize_email`, `extract_email_data` — fall back to returning raw email JSON if the client does not support sampling
- **Write tools** (optional): `send_email`, `create_draft` — disabled unless `ENABLE_WRITE_OPERATIONS=true` (ADR-005 prefers the Graph API Bridge for send)
- **Transports**: `stdio` (CodeMie MCP-Connect Bridge, local dev) and `streamable-http` (AKS / Traefik)
- **Auth**: `X-Graph-Token` (delegated Graph token), or `GRAPH_DEV_TOKEN`, or Azure **client credentials** for dev/tests

## Requirements

- Python 3.12+
- Microsoft Graph permissions on the token: at least `Mail.Read` for read tools; `Mail.Send` for write tools when enabled

## Install (development)

```bash
cd outlook-mcp-server
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Configuration

See [`.env.example`](.env.example). Important variables:

| Variable | Description |
|----------|-------------|
| `MCP_TRANSPORT` | `stdio` (default) or `streamable-http` |
| `MCP_HOST` / `MCP_PORT` | Bind address for Streamable HTTP (default `127.0.0.1:8000`; use `0.0.0.0` in containers) |
| `MCP_STATELESS_HTTP` | `true` for stateless Streamable HTTP (better behind LB; sampling may be limited) |
| `GRAPH_DEV_TOKEN` | Optional static token for local testing only |
| `AZURE_TENANT_ID` / `AZURE_CLIENT_ID` / `AZURE_CLIENT_SECRET` | Optional client-credentials fallback |
| `ENABLE_WRITE_OPERATIONS` | `true` to enable `send_email` / `create_draft` |

## Run

**stdio** (default):

```bash
export MCP_TRANSPORT=stdio
outlook-mcp-server
# or: python -m outlook_mcp.server
```

**Streamable HTTP** (MCP endpoint default path `/mcp`, health `GET /health`):

```bash
export MCP_TRANSPORT=streamable-http
export MCP_HOST=0.0.0.0
export MCP_PORT=8000
outlook-mcp-server
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

## Tests

```bash
pytest
```

## References

- [Microsoft Graph Mail API overview](https://learn.microsoft.com/en-us/graph/api/resources/mail-api-overview?view=graph-rest-1.0)
- AR architecture: `../ar-mail-management/` (ADR-005, ADR-006)
