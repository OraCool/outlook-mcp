"""CLI: natural-language requests against Outlook MCP via ReAct."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_mcp_adapters.client import MultiServerMCPClient

from langgraph_mcp_tester.agent import build_react_graph
from langgraph_mcp_tester.config import OutlookAgentSettings, get_settings
from langgraph_mcp_tester.llm_factory import create_chat_model
from langgraph_mcp_tester.mcp_connection import build_outlook_connection
from langgraph_mcp_tester.scenarios import get_scenario, list_scenarios


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="langgraph-mcp-tester",
        description="LangGraph ReAct agent for Outlook MCP tools",
    )
    p.add_argument("query", nargs="*", help="Natural language request (default mode)")
    p.add_argument(
        "-s", "--scenario", metavar="NAME", help="Run a predefined scenario by name"
    )
    p.add_argument(
        "--list-scenarios", action="store_true", help="Print available scenarios and exit"
    )
    p.add_argument(
        "--list-tools", action="store_true", help="Connect to MCP server, print discovered tools, and exit"
    )
    p.add_argument(
        "-i", "--interactive", action="store_true", help="Multi-turn conversation mode"
    )
    return p


async def _setup_agent(
    settings: OutlookAgentSettings,
) -> tuple[Any, Sequence[Any]]:
    """Build the ReAct graph and return ``(graph, tools)``."""
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
    return graph, tools


def _print_last_message(messages: list[BaseMessage]) -> None:
    if messages:
        last = messages[-1]
        content = getattr(last, "content", str(last))
        print(content)


async def _run_single(graph: Any, user_text: str) -> int:
    """Run a single query and print the result."""
    result = await graph.ainvoke({"messages": [HumanMessage(content=user_text)]})
    _print_last_message(result.get("messages", []))
    return 0


async def _run_interactive(graph: Any) -> int:
    """Multi-turn conversation loop reading from stdin."""
    messages: list[BaseMessage] = []
    loop = asyncio.get_event_loop()
    print("Interactive mode. Type 'exit' or 'quit' to stop.", file=sys.stderr)
    while True:
        sys.stderr.write("> ")
        sys.stderr.flush()
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            break
        text = line.strip()
        if text.lower() in ("exit", "quit", ""):
            if text.lower() in ("exit", "quit"):
                break
            continue
        messages.append(HumanMessage(content=text))
        result = await graph.ainvoke({"messages": messages})
        all_msgs: list[BaseMessage] = result.get("messages", [])
        messages = list(all_msgs)
        _print_last_message(messages)
    return 0


def _handle_list_scenarios() -> int:
    """Print scenarios table and exit."""
    scenarios = list_scenarios()
    if not scenarios:
        print("No scenarios defined.", file=sys.stderr)
        return 1
    name_w = max(len(s.name) for s in scenarios)
    desc_w = max(len(s.description) for s in scenarios)
    header = f"{'Name':<{name_w}}  {'Description':<{desc_w}}  Expected Tools"
    print(header)
    print("-" * len(header))
    for s in scenarios:
        tools_str = ", ".join(s.expected_tools)
        print(f"{s.name:<{name_w}}  {s.description:<{desc_w}}  {tools_str}")
    return 0


async def _handle_list_tools(settings: OutlookAgentSettings) -> int:
    """Connect to MCP server, print tool names, and exit."""
    connections = build_outlook_connection(settings)
    client = MultiServerMCPClient(connections)
    tools = await client.get_tools()
    if not tools:
        print("No tools discovered from MCP server.", file=sys.stderr)
        return 1
    for t in tools:
        name = getattr(t, "name", str(t))
        desc = getattr(t, "description", "")
        if desc:
            first_line = desc.strip().split("\n")[0][:80]
            print(f"  {name:<35} {first_line}")
        else:
            print(f"  {name}")
    print(f"\n{len(tools)} tools discovered.", file=sys.stderr)
    return 0


async def amain(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = _build_parser()
    args = parser.parse_args(argv)

    # --list-scenarios: no MCP connection needed
    if args.list_scenarios:
        return _handle_list_scenarios()

    settings = get_settings()

    # --list-tools: connect to MCP, print, exit
    if args.list_tools:
        return await _handle_list_tools(settings)

    # Determine user text
    user_text: str | None = None

    if args.scenario:
        scenario = get_scenario(args.scenario)
        if scenario is None:
            names = ", ".join(s.name for s in list_scenarios())
            print(
                f"Unknown scenario: {args.scenario!r}. Available: {names}",
                file=sys.stderr,
            )
            return 2
        user_text = scenario.prompt
        print(f"Running scenario: {scenario.name} — {scenario.description}", file=sys.stderr)
    elif args.interactive:
        user_text = None  # handled below
    elif args.query:
        user_text = " ".join(args.query)
    else:
        parser.print_usage(sys.stderr)
        return 2

    graph, tools = await _setup_agent(settings)
    print(f"{len(tools)} tools loaded from MCP server.", file=sys.stderr)

    if args.interactive:
        return await _run_interactive(graph)

    assert user_text is not None
    return await _run_single(graph, user_text)


def main() -> None:
    raise SystemExit(asyncio.run(amain()))
