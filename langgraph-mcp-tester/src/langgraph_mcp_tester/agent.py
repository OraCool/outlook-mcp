"""ReAct graph wired to MCP tools."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.language_models import LanguageModelLike
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, trim_messages
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import create_react_agent

DEFAULT_SYSTEM_PROMPT = (
    "You help the user work with Microsoft Outlook mail through MCP tools. "
    "Use tools to read, search, classify, or extract data from mail; do not claim you "
    "accessed mail without calling a tool. Send or draft email only when the user asks "
    "and only if those tools exist (server may disable writes). "
    "When summarizing tool results, match the tool output JSON: for apply_llm_category_to_email "
    "or set_message_categories, only say categories were applied if the tool returned "
    "\"ok\": true (or equivalent success); if the tool returned error, write_disabled, "
    "classification_failed, or http_error, say that explicitly—do not invent success."
)

_TRUNCATION_SUFFIX = "\n\n...(truncated for LLM context)"


def _clip_message_content(message: BaseMessage, max_chars: int) -> BaseMessage:
    """Cap per-message text so tool results (str or MCP content blocks) cannot overflow context."""
    if max_chars <= 0:
        return message
    suffix_len = len(_TRUNCATION_SUFFIX)
    budget = max(64, max_chars - suffix_len)
    content: Any = message.content

    if isinstance(content, str):
        if len(content) > max_chars:
            return message.model_copy(update={"content": content[:budget] + _TRUNCATION_SUFFIX})
        return message

    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        merged = "".join(parts)
        if len(merged) <= max_chars:
            return message
        return message.model_copy(
            update={"content": [{"type": "text", "text": merged[:budget] + _TRUNCATION_SUFFIX}]}
        )

    return message


def _clip_all_messages(messages: Sequence[BaseMessage], max_chars: int) -> list[BaseMessage]:
    """Apply the per-message character cap to every message in the sequence."""
    return [_clip_message_content(m, max_chars) for m in messages]


def _count_tokens_safe(
    counter: LanguageModelLike, messages: list[BaseMessage]
) -> int | None:
    """Return tokenizer-based token count, or ``None`` if the model cannot count this payload."""
    try:
        return int(counter.get_num_tokens_from_messages(messages))
    except (TypeError, AttributeError, NotImplementedError, ValueError):
        return None


def _trim_to_hard_ceiling(
    clipped: list[BaseMessage],
    token_counter: LanguageModelLike,
    *,
    max_llm_input_tokens: int,
    hard_input_token_ceiling: int,
) -> list[BaseMessage]:
    """If model token count still exceeds ceiling, reduce trim_messages budget (binary search)."""
    trimmed = trim_messages(
        clipped,
        max_tokens=max_llm_input_tokens,
        token_counter=token_counter,
        strategy="last",
        start_on="human",
        allow_partial=False,
    )
    if not clipped:
        return trimmed
    counted = _count_tokens_safe(token_counter, trimmed)
    if counted is None or counted <= hard_input_token_ceiling:
        return trimmed

    lo, hi = 1024, max_llm_input_tokens
    best = trimmed
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = trim_messages(
            clipped,
            max_tokens=mid,
            token_counter=token_counter,
            strategy="last",
            start_on="human",
            allow_partial=False,
        )
        c = _count_tokens_safe(token_counter, candidate)
        if c is None:
            return trimmed
        if c <= hard_input_token_ceiling:
            best = candidate
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _make_pre_model_hook(
    *,
    token_counter: LanguageModelLike,
    max_llm_input_tokens: int,
    max_message_chars: int,
    hard_input_token_ceiling: int,
) -> Callable[..., dict[str, list[BaseMessage]]]:
    """Trim chat history before each LLM call (full history stays in graph state)."""

    def pre_model_hook(state: dict) -> dict[str, list[BaseMessage]]:
        messages = list(state["messages"])
        clipped = _clip_all_messages(messages, max_message_chars)
        trimmed = _trim_to_hard_ceiling(
            clipped,
            token_counter,
            max_llm_input_tokens=max_llm_input_tokens,
            hard_input_token_ceiling=hard_input_token_ceiling,
        )
        if not trimmed and messages:
            trimmed = _clip_all_messages(messages, max_message_chars)[-8:]
        return {"llm_input_messages": trimmed}

    return pre_model_hook


def build_react_graph(
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    *,
    system_prompt: str | None = None,
    max_llm_input_tokens: int = 100_000,
    max_message_chars: int = 36_000,
    hard_input_token_ceiling: int = 110_000,
) -> CompiledStateGraph:
    """Compile a LangGraph ReAct agent with the given model and MCP-backed tools."""
    prompt = system_prompt if system_prompt is not None else DEFAULT_SYSTEM_PROMPT
    pre_hook = _make_pre_model_hook(
        token_counter=model,
        max_llm_input_tokens=max_llm_input_tokens,
        max_message_chars=max_message_chars,
        hard_input_token_ceiling=hard_input_token_ceiling,
    )
    return create_react_agent(
        model,
        list(tools),
        prompt=prompt,
        pre_model_hook=pre_hook,
    )
