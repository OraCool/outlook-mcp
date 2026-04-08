"""Tests for predefined scenario definitions and coverage."""

from __future__ import annotations

from langgraph_mcp_tester.scenarios import SCENARIOS, Scenario, get_scenario, list_scenarios

# Complete set of 19 MCP tools that the server exposes.
# This set must match the tools registered in outlook-mcp-server/src/outlook_mcp/server.py.
ALL_MCP_TOOLS: frozenset[str] = frozenset(
    {
        # Read (7)
        "get_email",
        "get_thread",
        "search_emails",
        "list_inbox",
        "get_attachments",
        "list_master_categories",
        "list_folders",
        # Classification (2)
        "categorize_email",
        "apply_llm_category_to_email",
        # Extraction (1)
        "extract_email_data",
        # Summarization (2)
        "summarize_email",
        "summarize_thread",
        # Drafting (1)
        "draft_reply",
        # Write (6)
        "set_message_categories",
        "send_email",
        "create_draft",
        "mark_as_read",
        "move_email",
        "create_reply_draft",
    }
)


def test_scenario_names_unique() -> None:
    names = [s.name for s in SCENARIOS]
    assert len(names) == len(set(names)), f"Duplicate scenario names: {names}"


def test_scenario_prompts_non_empty() -> None:
    for s in SCENARIOS:
        assert s.prompt.strip(), f"Scenario {s.name!r} has empty prompt"


def test_scenario_expected_tools_non_empty() -> None:
    for s in SCENARIOS:
        assert s.expected_tools, f"Scenario {s.name!r} has no expected_tools"


def test_all_19_tools_covered() -> None:
    """Every MCP tool must appear in at least one scenario's expected_tools."""
    covered = set()
    for s in SCENARIOS:
        covered.update(s.expected_tools)
    missing = ALL_MCP_TOOLS - covered
    assert not missing, f"MCP tools not covered by any scenario: {sorted(missing)}"


def test_no_unknown_tools_in_scenarios() -> None:
    """Scenarios should not reference tool names that don't exist on the server."""
    all_referenced = set()
    for s in SCENARIOS:
        all_referenced.update(s.expected_tools)
    unknown = all_referenced - ALL_MCP_TOOLS
    assert not unknown, f"Unknown tools in scenarios: {sorted(unknown)}"


def test_get_scenario_found() -> None:
    result = get_scenario("triage")
    assert result is not None
    assert isinstance(result, Scenario)
    assert result.name == "triage"


def test_get_scenario_case_insensitive() -> None:
    result = get_scenario("TRIAGE")
    assert result is not None
    assert result.name == "triage"


def test_get_scenario_not_found() -> None:
    assert get_scenario("nonexistent") is None


def test_list_scenarios_returns_all() -> None:
    result = list_scenarios()
    assert result is SCENARIOS
    assert len(result) >= 13
