"""Tests for create_chat_model."""

from __future__ import annotations

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

from langgraph_mcp_tester.config import OutlookAgentSettings, get_settings
from langgraph_mcp_tester.llm_factory import UnknownLLMProviderError, create_chat_model


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_openai_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    s = OutlookAgentSettings()
    model = create_chat_model(s)
    assert isinstance(model, ChatOpenAI)


def test_anthropic_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
    s = OutlookAgentSettings()
    model = create_chat_model(s)
    assert isinstance(model, ChatAnthropic)


def test_claude_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    s = OutlookAgentSettings()
    model = create_chat_model(s)
    assert isinstance(model, ChatAnthropic)


def test_openai_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    s = OutlookAgentSettings()
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        create_chat_model(s)


def test_unknown_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "mistral")
    s = OutlookAgentSettings()
    with pytest.raises(UnknownLLMProviderError):
        create_chat_model(s)


def test_anthropic_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    s = OutlookAgentSettings()
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        create_chat_model(s)
