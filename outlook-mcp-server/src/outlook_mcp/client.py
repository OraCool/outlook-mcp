"""MCP dev client with stub sampling (no LLM) for connectivity and tool testing."""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import httpx
from mcp import StdioServerParameters
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import (
    CallToolResult,
    CreateMessageRequestParams,
    CreateMessageResult,
    Implementation,
    LoggingMessageNotificationParams,
    SamplingMessage,
    TextContent,
)

from outlook_mcp.config import Settings, get_settings

if TYPE_CHECKING:
    from mcp.shared.context import RequestContext

_DEV_CLIENT_INFO = Implementation(name="outlook-mcp-dev-client", version="0.1.0")
_BEARER = "bearer "


async def _stderr_mcp_logging(params: LoggingMessageNotificationParams) -> None:
    data = params.data
    text = data if isinstance(data, str) else str(data)
    prefix = f"[outlook-mcp {params.level}]"
    if params.logger:
        prefix += f" ({params.logger})"
    sys.stderr.write(f"{prefix} {text}\n")


async def _stderr_tool_progress(progress: float, total: float | None, message: str | None) -> None:
    total_s = str(total) if total is not None else "?"
    extra = f" {message}" if message else ""
    sys.stderr.write(f"[outlook-mcp progress] {progress}/{total_s}{extra}\n")


def _collect_prompt_text(params: CreateMessageRequestParams) -> str:
    parts: list[str] = []
    if params.systemPrompt:
        parts.append(params.systemPrompt)
    for msg in params.messages:
        parts.append(_sampling_message_text(msg))
    return "\n".join(parts)


def _sampling_message_text(msg: SamplingMessage) -> str:
    chunks: list[str] = []
    for block in msg.content_as_list:
        if isinstance(block, TextContent):
            chunks.append(block.text)
    return "\n".join(chunks)


def _extract_email_id(full_text: str) -> str:
    m = re.search(r'"id"\s*:\s*"([^"]+)"', full_text)
    return m.group(1) if m else "unknown"


def _is_classification_prompt(text: str) -> bool:
    return (
        "Return only the classification JSON" in text
        or "AR Email Classification Specialist" in text
        or "Allowed categories" in text
    )


def _is_extraction_prompt(text: str) -> bool:
    return "Extract structured AR-relevant facts" in text


def _stub_classification_payload(email_id: str) -> dict[str, Any]:
    return {
        "email_id": email_id,
        "category": "UNCLASSIFIED",
        "confidence": 0.0,
        "intent": {
            "customer_statement": "[STUB]",
            "required_action": "[STUB]",
            "urgency": "LOW",
        },
        "reasoning": "stub_sampling_callback (no LLM)",
        "extracted_data": {
            "promised_date": None,
            "disputed_amount": None,
            "invoice_numbers": [],
            "payment_reference": None,
        },
        "escalation": {"required": False, "reason": None},
    }


def _stub_extraction_payload(email_id: str) -> dict[str, Any]:
    return {
        "email_id": email_id,
        "invoice_numbers": [],
        "amounts": [],
        "dates": [],
        "payment_reference": None,
        "raw_notes": "stub_sampling_callback (no LLM)",
    }


async def stub_sampling_callback(
    context: RequestContext[ClientSession, Any],
    params: CreateMessageRequestParams,
) -> CreateMessageResult:
    """Return valid placeholder JSON so ``categorize_email`` / ``extract_email_data`` complete with sampling."""
    full = _collect_prompt_text(params)
    email_id = _extract_email_id(full)
    if _is_extraction_prompt(full) and not _is_classification_prompt(full):
        payload = _stub_extraction_payload(email_id)
    elif _is_classification_prompt(full):
        payload = _stub_classification_payload(email_id)
    else:
        payload = _stub_classification_payload(email_id)

    text = json.dumps(payload)
    return CreateMessageResult(
        role="assistant",
        content=TextContent(type="text", text=text),
        model="stub",
        stopReason="endTurn",
    )


def _mcp_url(s: Settings, url_override: str | None) -> str:
    if url_override:
        return url_override
    return os.environ.get("MCP_URL", f"http://{s.mcp_host}:{s.mcp_port}/mcp")


def _graph_headers(s: Settings) -> dict[str, str]:
    headers: dict[str, str] = {}
    if s.graph_dev_token:
        tok = s.graph_dev_token.get_secret_value().strip()
        if tok.lower().startswith(_BEARER):
            tok = tok[7:].strip()
        headers["X-Graph-Token"] = tok
    mb = (s.graph_application_mailbox or "").strip()
    if mb:
        headers["X-Graph-Mailbox"] = mb
    return headers


def _normalize_transport(raw: str) -> str:
    return raw.strip().lower().replace("-", "_")


@asynccontextmanager
async def dev_client(
    *,
    settings: Settings | None = None,
    transport: str | None = None,
    url: str | None = None,
    stdio_command: str | None = None,
) -> AsyncIterator[ClientSession]:
    """Connect to the Outlook MCP server (stdio or streamable HTTP) with stub sampling."""
    import shlex

    s = settings if settings is not None else get_settings()
    t = _normalize_transport(transport if transport is not None else s.mcp_transport)

    if t == "streamable_http":
        headers = _graph_headers(s)
        mcp_url = _mcp_url(s, url)
        async with httpx.AsyncClient(headers=headers or None) as http_client:
            async with streamable_http_client(mcp_url, http_client=http_client) as (
                read_stream,
                write_stream,
                _,  # session id callback (unused)
            ):
                async with ClientSession(
                    read_stream,
                    write_stream,
                    sampling_callback=stub_sampling_callback,
                    logging_callback=_stderr_mcp_logging,
                    client_info=_DEV_CLIENT_INFO,
                ) as session:
                    await session.initialize()
                    yield session
        return

    if t == "stdio":
        cmd_str = stdio_command or os.environ.get("MCP_STDIO_COMMAND", "outlook-mcp-server")
        parts = shlex.split(cmd_str, posix=os.name != "nt")
        if not parts:
            msg = "MCP_STDIO_COMMAND is empty"
            raise ValueError(msg)
        command, args = parts[0], parts[1:]
        env = dict(os.environ)
        env.setdefault("MCP_TRANSPORT", "stdio")
        params = StdioServerParameters(command=command, args=args, env=env)
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(
                read_stream,
                write_stream,
                sampling_callback=stub_sampling_callback,
                logging_callback=_stderr_mcp_logging,
                client_info=_DEV_CLIENT_INFO,
            ) as session:
                await session.initialize()
                yield session
        return

    msg = f"Unknown MCP_TRANSPORT={transport or s.mcp_transport!r}; use streamable_http or stdio"
    raise ValueError(msg)


def _print_tool_result(result: CallToolResult) -> None:
    for block in result.content:
        if isinstance(block, TextContent):
            print(block.text)
        else:
            print(block)


async def _cli_amain(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print(
            "Usage:\n"
            "  python -m outlook_mcp.client list-tools\n"
            "  python -m outlook_mcp.client call <tool_name> [json_arguments]\n"
            "Env: MCP_URL, MCP_TRANSPORT, MCP_STDIO_COMMAND, GRAPH_DEV_TOKEN (for X-Graph-Token on HTTP).",
            file=sys.stderr,
        )
        return 2

    async with dev_client() as session:
        if argv[0] == "list-tools":
            listed = await session.list_tools()
            for tool in listed.tools:
                print(tool.name)
            return 0

        if argv[0] == "call":
            if len(argv) < 2:
                print("call requires a tool name", file=sys.stderr)
                return 2
            name = argv[1]
            raw_args = argv[2] if len(argv) > 2 else "{}"
            try:
                arguments = json.loads(raw_args)
            except json.JSONDecodeError as e:
                print(f"Invalid JSON arguments: {e}", file=sys.stderr)
                return 2
            if not isinstance(arguments, dict):
                print("Tool arguments must be a JSON object", file=sys.stderr)
                return 2
            result = await session.call_tool(
                name,
                arguments=arguments,
                progress_callback=_stderr_tool_progress,
            )
            _print_tool_result(result)
            return 1 if result.isError else 0

    print(f"Unknown command: {argv[0]}", file=sys.stderr)
    return 2


def main() -> None:
    import asyncio

    raise SystemExit(asyncio.run(_cli_amain()))


if __name__ == "__main__":
    main()
