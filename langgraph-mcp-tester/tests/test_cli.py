"""Tests for CLI argument parsing and dispatch (no live MCP)."""

from __future__ import annotations

from io import StringIO
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage

from langgraph_mcp_tester.cli import amain
from langgraph_mcp_tester.config import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_no_args_returns_2() -> None:
    rc = await amain([])
    assert rc == 2


@pytest.mark.asyncio
async def test_list_scenarios_returns_0(capsys: pytest.CaptureFixture[str]) -> None:
    rc = await amain(["--list-scenarios"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "triage" in out
    assert "thread-summary" in out


@pytest.mark.asyncio
async def test_scenario_not_found_returns_2(capsys: pytest.CaptureFixture[str]) -> None:
    rc = await amain(["--scenario", "nonexistent"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "nonexistent" in err


@pytest.mark.asyncio
async def test_scenario_found_runs_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify --scenario looks up the prompt and invokes the graph."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    captured_text: list[str] = []

    async def fake_setup(settings: Any) -> tuple[Any, list[Any]]:
        graph = MagicMock()

        async def fake_invoke(state: dict) -> dict:
            msg = state["messages"][0]
            captured_text.append(msg.content)
            return {"messages": [AIMessage(content="agent-result")]}

        graph.ainvoke = fake_invoke
        return graph, [MagicMock()]  # 1 fake tool

    monkeypatch.setattr("langgraph_mcp_tester.cli._setup_agent", fake_setup)
    rc = await amain(["--scenario", "triage"])
    assert rc == 0
    assert captured_text
    assert "inbox" in captured_text[0].lower() or "classify" in captured_text[0].lower()


@pytest.mark.asyncio
async def test_positional_args_backward_compat(monkeypatch: pytest.MonkeyPatch) -> None:
    """Positional args should be joined and used as the query (existing behavior)."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    captured_text: list[str] = []

    async def fake_setup(settings: Any) -> tuple[Any, list[Any]]:
        graph = MagicMock()

        async def fake_invoke(state: dict) -> dict:
            captured_text.append(state["messages"][0].content)
            return {"messages": [AIMessage(content="ok")]}

        graph.ainvoke = fake_invoke
        return graph, [MagicMock()]

    monkeypatch.setattr("langgraph_mcp_tester.cli._setup_agent", fake_setup)
    rc = await amain(["List", "my", "inbox"])
    assert rc == 0
    assert captured_text == ["List my inbox"]


@pytest.mark.asyncio
async def test_list_tools_connects_to_mcp(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """--list-tools should discover and print tool names."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    fake_tool = MagicMock()
    fake_tool.name = "list_inbox"
    fake_tool.description = "List recent Inbox messages."

    fake_client = MagicMock()
    fake_client.get_tools = AsyncMock(return_value=[fake_tool])

    monkeypatch.setattr(
        "langgraph_mcp_tester.cli.MultiServerMCPClient",
        lambda conns: fake_client,
    )
    rc = await amain(["--list-tools"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "list_inbox" in out


@pytest.mark.asyncio
async def test_interactive_accumulates_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Interactive mode should accumulate messages across turns."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    invoke_calls: list[int] = []

    async def fake_setup(settings: Any) -> tuple[Any, list[Any]]:
        graph = MagicMock()

        async def fake_invoke(state: dict) -> dict:
            msg_count = len(state["messages"])
            invoke_calls.append(msg_count)
            return {
                "messages": list(state["messages"]) + [AIMessage(content=f"reply-{msg_count}")]
            }

        graph.ainvoke = fake_invoke
        return graph, [MagicMock()]

    monkeypatch.setattr("langgraph_mcp_tester.cli._setup_agent", fake_setup)

    # Simulate stdin: two lines then EOF
    fake_stdin = StringIO("hello\nworld\nexit\n")
    monkeypatch.setattr("sys.stdin", fake_stdin)

    rc = await amain(["--interactive"])
    assert rc == 0
    # First call: 1 message (just "hello")
    # Second call: 3 messages (hello + reply-1 + world)
    assert len(invoke_calls) == 2
    assert invoke_calls[0] == 1
    assert invoke_calls[1] == 3
