"""Select ChatModel from LLM_PROVIDER (.env)."""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel

from langgraph_mcp_tester.config import OutlookAgentSettings


class UnknownLLMProviderError(ValueError):
    pass


def create_chat_model(settings: OutlookAgentSettings) -> BaseChatModel:
    """Return a LangChain chat model for OpenAI or Anthropic."""
    provider = settings.llm_provider.strip().lower()
    if provider == "openai":
        if not settings.openai_api_key:
            msg = "OPENAI_API_KEY is required when LLM_PROVIDER=openai"
            raise ValueError(msg)
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=settings.openai_model, api_key=settings.openai_api_key.get_secret_value())
    if provider in ("anthropic", "claude"):
        if not settings.anthropic_api_key:
            msg = "ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic"
            raise ValueError(msg)
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=settings.anthropic_model, api_key=settings.anthropic_api_key.get_secret_value())
    msg = f"Unknown LLM_PROVIDER={settings.llm_provider!r}; use openai or anthropic"
    raise UnknownLLMProviderError(msg)
