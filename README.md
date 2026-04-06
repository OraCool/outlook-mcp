# outlook-mcp

Monorepo with a **Model Context Protocol (MCP)** server for Microsoft Outlook mail via [Microsoft Graph](https://learn.microsoft.com/en-us/graph/), plus an optional **LangGraph** agent used to exercise the server locally.

**Upstream:** [github.com/OraCool/outlook-mcp](https://github.com/OraCool/outlook-mcp) · **PyPI:** [`outlook-mcp-server`](https://pypi.org/project/outlook-mcp-server/) (after first release)

## Packages

| Directory | Description |
| --------- | ----------- |
| [`outlook-mcp-server/`](outlook-mcp-server/) | MCP server: read/search mail, optional writes, OAuth and token modes, stdio or Streamable HTTP. |
| [`langgraph-mcp-tester/`](langgraph-mcp-tester/) | Small ReAct agent that connects to the MCP server (HTTP or stdio) with OpenAI or Anthropic. |

## Quick start

### Server from PyPI ([`uvx`](https://docs.astral.sh/uv/guides/tools/))

After the package is on PyPI, you can run the MCP server without cloning (requires [uv](https://docs.astral.sh/uv/)):

```bash
uvx outlook-mcp-server
```

Pin a version:

```bash
uvx outlook-mcp-server==0.1.0
```

Set Microsoft Graph–related environment variables the same way as in development (see [`outlook-mcp-server/.env.example`](outlook-mcp-server/.env.example)). Client-specific setup (Cursor, Claude Code, VS Code Copilot, OpenAI Codex) is documented in [`outlook-mcp-server/README.md`](outlook-mcp-server/README.md).

### Server from a clone

```bash
cd outlook-mcp-server
cp .env.example .env
# Configure Graph auth — see outlook-mcp-server/README.md
uv sync --extra dev
MCP_TRANSPORT=stdio uv run outlook-mcp-server
```

### Tester (optional)

```bash
cd langgraph-mcp-tester
cp .env.example .env
uv sync --extra dev
uv run langgraph-mcp-tester "List the 5 most recent messages in my inbox"
```

## Requirements

- Python **3.12+** (see each package’s `pyproject.toml`)
- [uv](https://docs.astral.sh/uv/) recommended for installs and runs

## CI and releases

- **Tests:** [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs `pytest` in both packages on push and pull requests to `main` / `master`.
- **PyPI:** [`.github/workflows/publish-pypi.yml`](.github/workflows/publish-pypi.yml) builds and publishes **`outlook-mcp-server`** when you push a tag matching `v*.*.*` or run the workflow manually (**Actions → Publish to PyPI → Run workflow**). Bump the version in [`outlook-mcp-server/pyproject.toml`](outlook-mcp-server/pyproject.toml) before each release (PyPI rejects duplicate file versions).

## First-time publish to GitHub (single commit, no history)

Use this when you want the remote to contain **only one commit** (no prior history), e.g. a clean public drop under [OraCool](https://github.com/OraCool).

1. Create an **empty** repository on GitHub (example: `OraCool/outlook-mcp`), default branch **`main`**.
2. Locally, ensure the tree matches what you want in that single commit.
3. Replace branch history with one orphan commit (adjust branch names if you are not on `main`):

   ```bash
   git checkout --orphan main-temp
   git add -A
   git commit -m "Initial release"
   git branch -D main
   git branch -m main main-temp
   ```

4. Point `origin` at the new repo and push:

   ```bash
   git remote add origin https://github.com/OraCool/outlook-mcp.git
   # or: git remote set-url origin https://github.com/OraCool/outlook-mcp.git
   git push -u origin main --force
   ```

**Warning:** `--force` overwrites the remote history. Anyone with an old clone should re-clone or reset.

## PyPI trusted publishing (maintainers)

Avoid long-lived PyPI passwords in GitHub:

1. In [PyPI](https://pypi.org/manage/account/publishing/) (or TestPyPI for a dry run), add a **pending** trusted publisher: **GitHub** as the provider, owner **`OraCool`**, repository name (e.g. **`outlook-mcp`**), workflow **`publish-pypi.yml`**, environment name **leave empty** unless you create a matching [GitHub Environment](https://docs.github.com/en/actions/deployment/targeting-different-environments/using-environments-for-deployment) and configure the same name on PyPI.
2. Run **Publish to PyPI** once (tag or `workflow_dispatch`). A successful OIDC upload **creates** the PyPI project if it does not exist yet.
3. **Fallback:** add a repository secret **`UV_PUBLISH_TOKEN`** (PyPI API token) and set `UV_PUBLISH_TOKEN: ${{ secrets.UV_PUBLISH_TOKEN }}` in the publish job only if you are not using trusted publishing.

Details: [PyPI trusted publishers](https://docs.pypi.org/trusted-publishers/), [`uv publish`](https://docs.astral.sh/uv/guides/package/#publishing-your-package).

## Security

- **Never commit** `.env` files or tokens. Examples live in `.env.example` only.
- Treat mail content as **untrusted** when passed to LLMs (prompt injection). See [`outlook-mcp-server/README.md`](outlook-mcp-server/README.md) for sampling and logging guidance.

## License

This repository is released under the [MIT License](LICENSE).
