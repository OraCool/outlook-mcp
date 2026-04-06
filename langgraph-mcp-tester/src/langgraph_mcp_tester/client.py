"""Direct MCP ``ClientSession`` with LLM ``sampling_callback`` for Outlook MCP."""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from mcp import StdioServerParameters
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import (
    CreateMessageRequestParams,
    CreateMessageResult,
    Implementation,
    LoggingMessageNotificationParams,
    SamplingMessage,
    TextContent,
)

from langgraph_mcp_tester.config import OutlookAgentSettings, get_settings
from langgraph_mcp_tester.llm_factory import create_chat_model

if TYPE_CHECKING:
    from mcp.shared.context import RequestContext

LLM_MCP_CLIENT_INFO = Implementation(name="langgraph-mcp-tester-client", version="0.1.0")
_BEARER = "bearer "


async def _stderr_mcp_logging(params: LoggingMessageNotificationParams) -> None:
    data = params.data
    text = data if isinstance(data, str) else str(data)
    prefix = f"[outlook-mcp {params.level}]"
    if params.logger:
        prefix += f" ({params.logger})"
    sys.stderr.write(f"{prefix} {text}\n")


def _sampling_block_text(msg: SamplingMessage) -> str:
    parts: list[str] = []
    for block in msg.content_as_list:
        if isinstance(block, TextContent):
            parts.append(block.text)
    return "\n".join(parts)


def _flatten_ai_message_content(content: Any) -> str:
    """Use only assistant-visible text blocks (skip thinking / tool blocks)."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict):
            typ = block.get("type")
            if typ == "thinking":
                continue
            text_val = block.get("text")
            if isinstance(text_val, str) and typ in (None, "text"):
                parts.append(text_val)
        else:
            parts.append(str(block))
    return "".join(parts)


def _model_display_name(settings: OutlookAgentSettings) -> str:
    prov = settings.llm_provider.strip().lower()
    if prov == "openai":
        return settings.openai_model
    return settings.anthropic_model


def build_sampling_callback(settings: OutlookAgentSettings):
    """Build an async MCP sampling handler that forwards prompts to the configured LangChain chat model."""
    model = create_chat_model(settings)
    if settings.llm_provider.strip().lower() == "openai":
        model = model.bind(response_format={"type": "json_object"})
    label = _model_display_name(settings)

    async def _sampling_callback(
        context: RequestContext[ClientSession, Any],
        params: CreateMessageRequestParams,
    ) -> CreateMessageResult:
        lc_messages: list[SystemMessage | HumanMessage | AIMessage] = []
        if params.systemPrompt:
            lc_messages.append(SystemMessage(content=params.systemPrompt))
        for msg in params.messages:
            text = _sampling_block_text(msg)
            if msg.role == "user":
                lc_messages.append(HumanMessage(content=text))
            else:
                lc_messages.append(AIMessage(content=text))

        invoke_kw: dict[str, Any] = {}
        if params.maxTokens is not None:
            invoke_kw["max_tokens"] = params.maxTokens
        if params.temperature is not None:
            invoke_kw["temperature"] = params.temperature
        resp = await model.ainvoke(lc_messages, **invoke_kw)
        out_text = _flatten_ai_message_content(resp.content)

        return CreateMessageResult(
            role="assistant",
            content=TextContent(type="text", text=out_text),
            model=label,
            stopReason="endTurn",
        )

    return _sampling_callback


def _normalize_transport(raw: str) -> str:
    return raw.strip().lower().replace("-", "_")


def _http_headers(settings: OutlookAgentSettings) -> dict[str, str]:
    headers: dict[str, str] = {}
    if settings.x_graph_token:
        tok = settings.x_graph_token.get_secret_value().strip()
        if tok.lower().startswith(_BEARER):
            tok = tok[7:].strip()
        headers["X-Graph-Token"] = tok
    return headers


@asynccontextmanager
async def outlook_mcp_client(
    settings: OutlookAgentSettings | None = None,
) -> AsyncIterator[ClientSession]:
    """Connect to Outlook MCP over stdio or streamable HTTP with LLM-backed sampling."""
    import shlex

    s = settings if settings is not None else get_settings()
    transport = _normalize_transport(s.mcp_transport)
    cb = build_sampling_callback(s)

    if transport == "streamable_http":
        headers = _http_headers(s)
        async with httpx.AsyncClient(headers=headers or None) as http_client:
            async with streamable_http_client(s.mcp_url, http_client=http_client) as (
                read_stream,
                write_stream,
                _,  # session id callback (unused)
            ):
                async with ClientSession(
                    read_stream,
                    write_stream,
                    sampling_callback=cb,
                    logging_callback=_stderr_mcp_logging,
                    client_info=LLM_MCP_CLIENT_INFO,
                ) as session:
                    await session.initialize()
                    yield session
        return

    if transport == "stdio":
        parts = shlex.split(s.mcp_stdio_command, posix=os.name != "nt")
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
                sampling_callback=cb,
                logging_callback=_stderr_mcp_logging,
                client_info=LLM_MCP_CLIENT_INFO,
            ) as session:
                await session.initialize()
                yield session
        return

    msg = f"Unknown MCP_TRANSPORT={s.mcp_transport!r}; use streamable_http or stdio"
    raise ValueError(msg)
