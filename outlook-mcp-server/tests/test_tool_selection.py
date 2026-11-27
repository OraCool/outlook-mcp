"""MCP_ENABLED_TOOLS / MCP_DISABLED_TOOLS selection."""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest

from outlook_mcp import server
from outlook_mcp.config import get_settings

BASELINE = frozenset(
    {
        "apply_llm_category_to_email",
        "categorize_email",
        "create_draft",
        "create_mail_folder",
        "create_master_category",
        "create_message_rule",
        "create_reply_draft",
        "delete_draft",
        "delete_master_category",
        "delete_message_rule",
        "draft_reply",
        "extract_email_data",
        "get_attachment_content",
        "get_attachment_text",
        "get_attachments",
        "get_email",
        "get_thread",
        "list_folders",
        "list_inbox",
        "list_master_categories",
        "list_message_rules",
        "mark_as_read",
        "move_email",
        "move_emails",
        "save_attachment_to_path",
        "search_emails",
        "send_draft_email",
        "send_email",
        "set_email_priority",
        "set_message_categories",
        "set_message_flag",
        "set_messages_categories",
        "summarize_email",
        "summarize_thread",
        "update_message_rule",
    }
)


def _names(monkeypatch, **env: str) -> set[str]:
    for key in ("MCP_ENABLED_TOOLS", "MCP_DISABLED_TOOLS"):
        monkeypatch.delenv(key, raising=False)
    # Explicit so a developer's local .env cannot change the outcome.
    monkeypatch.setenv("ENABLE_WRITE_OPERATIONS", "false")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    try:
        app = server.build_mcp()
        return {t.name for t in asyncio.run(app.list_tools())}
    finally:
        get_settings.cache_clear()


def test_default_unchanged(monkeypatch):
    assert _names(monkeypatch) == BASELINE


def test_enabled_allowlist(monkeypatch):
    assert _names(monkeypatch, MCP_ENABLED_TOOLS="list_inbox,get_email") == {
        "list_inbox",
        "get_email",
    }


def test_disabled_denylist(monkeypatch):
    names = _names(monkeypatch, MCP_DISABLED_TOOLS="send_email,send_draft_email")
    assert names == BASELINE - {"send_email", "send_draft_email"}


def test_disabled_applies_after_enabled(monkeypatch):
    names = _names(
        monkeypatch,
        MCP_ENABLED_TOOLS="list_inbox,get_email",
        MCP_DISABLED_TOOLS="get_email",
    )
    assert names == {"list_inbox"}


def test_unknown_tool_name_fails(monkeypatch):
    with pytest.raises(ValueError, match="nope"):
        _names(monkeypatch, MCP_ENABLED_TOOLS="list_inbox,nope")


def test_unknown_disabled_name_fails(monkeypatch):
    with pytest.raises(ValueError, match="nope"):
        _names(monkeypatch, MCP_DISABLED_TOOLS="nope")


def test_write_tool_enabled_without_writes_fails(monkeypatch):
    with pytest.raises(ValueError, match="ENABLE_WRITE_OPERATIONS"):
        _names(monkeypatch, MCP_ENABLED_TOOLS="send_email")


def test_write_tool_enabled_with_writes_ok(monkeypatch):
    names = _names(
        monkeypatch, MCP_ENABLED_TOOLS="send_email", ENABLE_WRITE_OPERATIONS="true"
    )
    assert names == {"send_email"}


def test_write_tool_disabled_listing_ok_without_writes(monkeypatch):
    # Denylisting a write tool is fine when writes are off.
    assert "send_email" not in _names(monkeypatch, MCP_DISABLED_TOOLS="send_email")


def test_startup_log_lists_names_only(monkeypatch, caplog):
    caplog.set_level("WARNING", logger="outlook_mcp.server")
    _names(monkeypatch, MCP_ENABLED_TOOLS="list_inbox,get_email")
    records = [r for r in caplog.records if "registered tools:" in r.getMessage()]
    assert len(records) == 1
    assert records[0].levelname == "WARNING"
    assert records[0].getMessage() == "registered tools: get_email, list_inbox"


# --- conditional tool hook (R1) ---------------------------------------------------------------


def _build_with_conditional(monkeypatch, *, condition: bool, **env: str) -> set[str]:
    for key in ("MCP_ENABLED_TOOLS", "MCP_DISABLED_TOOLS"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ENABLE_WRITE_OPERATIONS", "false")
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    def extra(tool):
        @tool(condition=condition, reason="STORAGE_ACCOUNT_URL is not set")
        async def conditional_tool() -> str:
            """Test-only conditional tool."""
            return "ok"

    get_settings.cache_clear()
    try:
        app = server.build_mcp(_extra_tools=extra)
        return {t.name for t in asyncio.run(app.list_tools())}
    finally:
        get_settings.cache_clear()


def test_conditional_tool_registered_when_condition_met(monkeypatch):
    assert "conditional_tool" in _build_with_conditional(monkeypatch, condition=True)


def test_conditional_tool_skipped_silently_when_unselected(monkeypatch):
    # Prerequisite missing but not explicitly enabled: skipped, and the name is still "known".
    names = _build_with_conditional(monkeypatch, condition=False)
    assert names == BASELINE
    names = _build_with_conditional(monkeypatch, condition=False, MCP_DISABLED_TOOLS="conditional_tool")
    assert names == BASELINE


def test_conditional_tool_enabled_without_prerequisite_fails(monkeypatch):
    with pytest.raises(ValueError, match="STORAGE_ACCOUNT_URL is not set"):
        _build_with_conditional(monkeypatch, condition=False, MCP_ENABLED_TOOLS="conditional_tool,get_email")


def test_enabled_and_disabled_means_disabled(monkeypatch):
    # Disabled wins, so neither the conditional nor the write-gated check fires.
    names = _build_with_conditional(
        monkeypatch,
        condition=False,
        MCP_ENABLED_TOOLS="conditional_tool,send_email,get_email",
        MCP_DISABLED_TOOLS="conditional_tool,send_email",
    )
    assert names == {"get_email"}


# --- write-gated list guard (R2) --------------------------------------------------------------


def _write_gated_by_decorator() -> set[str]:
    tree = ast.parse(Path(server.__file__).read_text(encoding="utf-8"))
    gated = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            for dec in node.decorator_list:
                if (
                    isinstance(dec, ast.Call)
                    and isinstance(dec.func, ast.Name)
                    and dec.func.id == "tool"
                    and any(k.arg == "requires_writes" and getattr(k.value, "value", None) is True for k in dec.keywords)
                ):
                    gated.add(node.name)
    return gated


def _tool_names_in_server() -> dict[str, ast.AsyncFunctionDef]:
    tree = ast.parse(Path(server.__file__).read_text(encoding="utf-8"))
    return {
        n.name: n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef)
        and any(isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "tool" for d in n.decorator_list)
    }


def _calls(node: ast.AST) -> set[str]:
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return out


def _checks_write_setting(node: ast.AST) -> bool:
    return any(isinstance(n, ast.Attribute) and n.attr == "enable_write_operations" for n in ast.walk(node))


def test_requires_writes_matches_implementations():
    """Every tool whose implementation (transitively) checks enable_write_operations is flagged, and vice versa."""
    tools_dir = Path(server.__file__).parent / "tools"
    defs: dict[str, list[ast.AST]] = {}
    for path in tools_dir.glob("*.py"):
        for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef):
                defs.setdefault(n.name, []).append(n)

    def reaches_write_check(name: str, seen: set[str]) -> bool:
        if name in seen:
            return False
        seen.add(name)
        for fn in defs.get(name, []):
            if _checks_write_setting(fn) or any(reaches_write_check(c, seen) for c in _calls(fn)):
                return True
        return False

    actual = {
        name
        for name, node in _tool_names_in_server().items()
        if any(reaches_write_check(c, set()) for c in _calls(node))
    }
    assert actual, "analysis found no write-gated tools; the AST walk is broken"
    assert _write_gated_by_decorator() == actual
