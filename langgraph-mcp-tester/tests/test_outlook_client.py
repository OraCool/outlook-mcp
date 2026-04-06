"""Tests for LLM-backed MCP client sampling callback."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage
from mcp.types import CreateMessageRequestParams, SamplingMessage, TextContent

from langgraph_mcp_tester.client import build_sampling_callback
from langgraph_mcp_tester.config import OutlookAgentSettings, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_build_sampling_callback_forwards_to_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")

    class FakeModel:
        async def ainvoke(self, messages: list) -> AIMessage:
            assert any(getattr(m, "content", None) == "user says hi" for m in messages)
            return AIMessage(content="model-reply-text")

    monkeypatch.setattr("langgraph_mcp_tester.client.create_chat_model", lambda _s: FakeModel())

    s = OutlookAgentSettings()
    cb = build_sampling_callback(s)
    params = CreateMessageRequestParams(
        messages=[
            SamplingMessage(
                role="user",
                content=TextContent(type="text", text="user says hi"),
            )
        ],
        maxTokens=32,
    )
    result = await cb(MagicMock(), params)
    assert result.content.text == "model-reply-text"
    assert result.model == "gpt-4o-mini"
