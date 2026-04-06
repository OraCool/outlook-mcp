# outlook-mcp

Monorepo with a **Model Context Protocol (MCP)** server for Microsoft Outlook mail via [Microsoft Graph](https://learn.microsoft.com/en-us/graph/), plus an optional **LangGraph** agent used to exercise the server locally.

## Packages

| Directory | Description |
| --------- | ----------- |
| [`outlook-mcp-server/`](outlook-mcp-server/) | MCP server: read/search mail, optional writes, OAuth and token modes, stdio or Streamable HTTP. |
| [`langgraph-mcp-tester/`](langgraph-mcp-tester/) | Small ReAct agent that connects to the MCP server (HTTP or stdio) with OpenAI or Anthropic. |

## Quick start

**Server** (from `outlook-mcp-server/`):

```bash
cd outlook-mcp-server
cp .env.example .env
# Configure Graph auth — see outlook-mcp-server/README.md
uv sync --extra dev
MCP_TRANSPORT=stdio uv run outlook-mcp-server
```

**Tester** (optional, from `langgraph-mcp-tester/`):

```bash
cd langgraph-mcp-tester
cp .env.example .env
uv sync --extra dev
uv run langgraph-mcp-tester "List the 5 most recent messages in my inbox"
```

## Requirements

- Python **3.12+** (see each package’s `pyproject.toml`)
- [uv](https://docs.astral.sh/uv/) recommended for installs and runs

## Security

- **Never commit** `.env` files or tokens. Examples live in `.env.example` only.
- Treat mail content as **untrusted** when passed to LLMs (prompt injection). See `outlook-mcp-server/README.md` for sampling and logging guidance.

## CI

GitHub Actions runs `pytest` in both packages on push and pull requests (see `.github/workflows/ci.yml`).

## License

Add a `LICENSE` file at the repository root before publishing if you intend an open-source release; the packages do not declare a SPDX license in `pyproject.toml` yet.
