"""Tests for agent message clipping (MCP list-shaped tool content)."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, ToolMessage

from langgraph_mcp_tester.agent import _clip_message_content


def test_clip_tool_message_list_text_blocks() -> None:
    big = "x" * 50_000
    msg = ToolMessage(
        content=[{"type": "text", "text": big}],
        tool_call_id="call-1",
    )
    out = _clip_message_content(msg, max_chars=2000)
    assert isinstance(out.content, list)
    block = out.content[0]
    assert isinstance(block, dict)
    assert block.get("type") == "text"
    text = str(block.get("text", ""))
    assert len(text) < len(big)
    assert "truncated" in text.lower()


def test_clip_human_string_unchanged_when_short() -> None:
    m = HumanMessage(content="hello")
    out = _clip_message_content(m, max_chars=1000)
    assert out is m
    assert out.content == "hello"


def test_clip_human_string_truncates_long() -> None:
    long = "a" * 10_000
    m = HumanMessage(content=long)
    out = _clip_message_content(m, max_chars=500)
    assert isinstance(out.content, str)
    assert len(out.content) <= 500
    assert "truncated" in out.content.lower()
