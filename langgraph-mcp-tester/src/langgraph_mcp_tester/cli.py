"""CLI: natural-language requests against Outlook MCP via ReAct."""

from __future__ import annotations

import asyncio
import sys

from langchain_core.messages import HumanMessage
from langchain_mcp_adapters.client import MultiServerMCPClient

from langgraph_mcp_tester.agent import build_react_graph
from langgraph_mcp_tester.config import get_settings
from langgraph_mcp_tester.llm_factory import create_chat_model
from langgraph_mcp_tester.mcp_connection import build_outlook_connection


async def amain(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print(
            "Usage: langgraph-mcp-tester <natural language request>",
            file=sys.stderr,
        )
        return 2

    user_text = " ".join(argv)
    settings = get_settings()
    model = create_chat_model(settings)
    connections = build_outlook_connection(settings)
    client = MultiServerMCPClient(connections)
    tools = await client.get_tools()
    graph = build_react_graph(
        model,
        tools,
        max_llm_input_tokens=settings.agent_max_llm_input_tokens,
        max_message_chars=settings.agent_max_message_chars,
        hard_input_token_ceiling=settings.agent_hard_input_token_ceiling,
    )
    result = await graph.ainvoke({"messages": [HumanMessage(content=user_text)]})
    messages = result.get("messages", [])
    if messages:
        last = messages[-1]
        content = getattr(last, "content", str(last))
        print(content)
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(amain()))
