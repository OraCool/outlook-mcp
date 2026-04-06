# langgraph-mcp-tester

Small [LangGraph](https://github.com/langchain-ai/langgraph) ReAct agent that loads tools from the sibling **outlook-mcp-server** via [langchain-mcp-adapters](https://github.com/langchain-ai/langchain-mcp-adapters) (`MultiServerMCPClient`). Choose **OpenAI** or **Anthropic** with `LLM_PROVIDER` and the matching API key.

## Prerequisites

- Python 3.12+
- Running Outlook MCP server, either:
  - **Streamable HTTP** (default): start [outlook-mcp-server](../outlook-mcp-server/) with `MCP_TRANSPORT=streamable-http` (or `streamable_http` in the server’s env, depending on how you launch it — the server normalizes to `streamable-http` in code), or
  - **stdio**: the tester spawns the server subprocess; ensure `outlook-mcp-server` or `python -m outlook_mcp.server` is on your PATH / venv.

## Setup (uv)

```bash
cd langgraph-mcp-tester
uv sync --extra dev
cp .env.example .env
# Edit .env: LLM_PROVIDER, API key, MCP_URL or MCP_STDIO_COMMAND, optional X_GRAPH_TOKEN
```

If you prefer pip/venv, `pip install -e ".[dev]"` is also supported.

## Run

With the MCP server listening on the default URL, run from **`langgraph-mcp-tester/`** so `pydantic-settings` loads this folder’s `.env` (the path is relative to the process working directory).

```bash
cd langgraph-mcp-tester
uv run langgraph-mcp-tester "List the 5 most recent messages in my inbox"
```

Large MCP tool results are clipped and trimmed using your chat model’s tokenizer (`AGENT_MAX_MESSAGE_CHARS`, `AGENT_MAX_LLM_INPUT_TOKENS`, and `AGENT_HARD_INPUT_TOKEN_CEILING` in `.env`).

For **delegated Graph** access over HTTP, set `X_GRAPH_TOKEN` in `.env` to the raw JWT or `Bearer <token>`; it is sent as the `X-Graph-Token` header (see AR mail management ADR).

### Microsoft Graph token (`X_GRAPH_TOKEN`)

The value must be a **Microsoft Graph access token for a signed-in user** (delegated permissions), not your OpenAI or Anthropic API key.

**Do you put a Microsoft client ID in this app’s `.env`?**  
Usually **no**. `langgraph-mcp-tester` only forwards the token string to the MCP server. The **Application (client) ID** belongs to the Entra ID **app registration** that performs the OAuth sign-in and token request (your product, a small test script, Postman, etc.). You configure client ID, tenant, redirect URI, and scopes there; after the user signs in, you copy the resulting **access token** into `X_GRAPH_TOKEN` (or your gateway injects it as `X-Graph-Token` per ADR-006).

#### Ways to obtain a token for local testing

1. **[Graph Explorer](https://developer.microsoft.com/en-us/graph/graph-explorer)** — Sign in, consent to mail-related permissions, use **Access token** (copy the JWT). Quickest for manual checks; token lifetime is short.
2. **Entra app registration** — In [Microsoft Entra admin center](https://entra.microsoft.com/) → App registrations → your app → note **Application (client) ID** and **Directory (tenant) ID**. Implement the [authorization code flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow) or use [MSAL](https://learn.microsoft.com/en-us/entra/msal/overview) in a small script or your UI to acquire a token with delegated scopes such as `Mail.Read` (and `Mail.Send` only if you enable write tools on the server).
3. **Device code flow** — Useful for CLI-only testing without a redirect URI; still uses your app registration’s client ID and delegated scopes.

**Required delegated scopes** (typical): `Mail.Read` for read tools; `Mail.Send` if `ENABLE_WRITE_OPERATIONS=true` on the server. Match what your app registration exposes and what the user consents to.

**Alternative without `X_GRAPH_TOKEN` on the tester** — Run [outlook-mcp-server](../outlook-mcp-server/) with `GRAPH_DEV_TOKEN` set to the same delegated JWT (server-side only, local dev). The server does not use stored Azure app secrets; multi-tenant operation relies on each caller’s token.

## Tests

```bash
uv run pytest
```
