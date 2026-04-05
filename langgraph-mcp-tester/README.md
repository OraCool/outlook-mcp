# langgraph-mcp-tester

Small [LangGraph](https://github.com/langchain-ai/langgraph) ReAct agent that loads tools from the sibling **outlook-mcp-server** via [langchain-mcp-adapters](https://github.com/langchain-ai/langchain-mcp-adapters) (`MultiServerMCPClient`). Choose **OpenAI** or **Anthropic** with `LLM_PROVIDER` and the matching API key.

## Prerequisites

- Python 3.12+
- Running Outlook MCP server, either:
  - **Streamable HTTP** (default): start [outlook-mcp-server](../outlook-mcp-server/) with `MCP_TRANSPORT=streamable-http` (or `streamable_http` in the server’s env, depending on how you launch it — the server normalizes to `streamable-http` in code), or
  - **stdio**: the tester spawns the server subprocess; ensure `outlook-mcp-server` or `python -m outlook_mcp.server` is on your PATH / venv.

## Setup

```bash
cd langgraph-mcp-tester
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env
# Edit .env: LLM_PROVIDER, API key, MCP_URL or MCP_STDIO_COMMAND, optional X_GRAPH_TOKEN
```

## Run

With the MCP server listening on the default URL:

```bash
langgraph-mcp-tester "List the 5 most recent messages in my inbox"
```

For **delegated Graph** access over HTTP, set `X_GRAPH_TOKEN` in `.env` to the raw JWT or `Bearer <token>`; it is sent as the `X-Graph-Token` header (see AR mail management ADR).

## Tests

```bash
pytest
```
