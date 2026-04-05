"""ReAct graph wired to MCP tools."""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import create_react_agent

DEFAULT_SYSTEM_PROMPT = (
    "You help the user work with Microsoft Outlook mail through MCP tools. "
    "Use tools to read, search, classify, or extract data from mail; do not claim you "
    "accessed mail without calling a tool. Send or draft email only when the user asks "
    "and only if those tools exist (server may disable writes)."
)


def build_react_graph(
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    *,
    system_prompt: str | None = None,
) -> CompiledStateGraph:
    """Compile a LangGraph ReAct agent with the given model and MCP-backed tools."""
    prompt = system_prompt if system_prompt is not None else DEFAULT_SYSTEM_PROMPT
    return create_react_agent(model, list(tools), prompt=prompt)
