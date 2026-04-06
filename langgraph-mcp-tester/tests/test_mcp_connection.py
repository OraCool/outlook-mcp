"""Tests for build_outlook_connection (no live MCP)."""

from __future__ import annotations

import os

import pytest

from langgraph_mcp_tester.config import OutlookAgentSettings
from langgraph_mcp_tester.mcp_connection import build_outlook_connection


def test_streamable_http_default_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("MCP_TRANSPORT", "streamable_http")
    monkeypatch.delenv("X_GRAPH_TOKEN", raising=False)
    s = OutlookAgentSettings(_env_file=None)
    conns = build_outlook_connection(s)
    assert "outlook" in conns
    c = conns["outlook"]
    assert c["transport"] == "streamable_http"
    assert c["url"] == "http://127.0.0.1:8000/mcp"
    assert "headers" not in c or c.get("headers") is None
    sk = c.get("session_kwargs") or {}
    assert callable(sk.get("sampling_callback"))
    assert sk.get("client_info") is not None


def test_streamable_http_with_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("MCP_TRANSPORT", "streamable_http")
    monkeypatch.setenv("X_GRAPH_TOKEN", "Bearer abc.def.ghi")
    s = OutlookAgentSettings(_env_file=None)
    c = build_outlook_connection(s)["outlook"]
    assert c["headers"]["X-Graph-Token"] == "abc.def.ghi"


def test_stdio_split_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    monkeypatch.setenv("MCP_STDIO_COMMAND", 'python -m outlook_mcp.server --help')
    s = OutlookAgentSettings(_env_file=None)
    c = build_outlook_connection(s)["outlook"]
    assert c["transport"] == "stdio"
    assert c["command"] == "python"
    assert c["args"] == ["-m", "outlook_mcp.server", "--help"]
    assert c["env"]["MCP_TRANSPORT"] == "stdio"
    sk = c.get("session_kwargs") or {}
    assert callable(sk.get("sampling_callback"))


def test_unknown_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("MCP_TRANSPORT", "sse")
    s = OutlookAgentSettings(_env_file=None)
    with pytest.raises(ValueError, match="Unknown MCP_TRANSPORT"):
        build_outlook_connection(s)


def test_stdio_empty_command_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    monkeypatch.setenv("MCP_STDIO_COMMAND", "   ")
    s = OutlookAgentSettings(_env_file=None)
    with pytest.raises(ValueError, match="MCP_STDIO_COMMAND is empty"):
        build_outlook_connection(s)


def test_streamable_http_raw_token_no_bearer_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("MCP_TRANSPORT", "streamable_http")
    monkeypatch.setenv("X_GRAPH_TOKEN", "rawtoken123")
    s = OutlookAgentSettings(_env_file=None)
    c = build_outlook_connection(s)["outlook"]
    assert c["headers"]["X-Graph-Token"] == "rawtoken123"


def test_stdio_injects_mcp_transport_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    monkeypatch.setenv("MCP_STDIO_COMMAND", "outlook-mcp-server")
    s = OutlookAgentSettings(_env_file=None)
    c = build_outlook_connection(s)["outlook"]
    assert c["env"]["MCP_TRANSPORT"] == "stdio"
