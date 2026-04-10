"""Predefined test scenarios exercising Outlook MCP tool combinations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Scenario:
    """A predefined natural-language scenario for the ReAct agent.

    ``expected_tools`` lists the MCP tool names the scenario is designed
    to exercise.  This is **documentation only** — the agent may call
    different or additional tools depending on the LLM's reasoning.
    """

    name: str
    description: str
    prompt: str
    expected_tools: tuple[str, ...]


# ---------------------------------------------------------------------------
# All 19 MCP tools must appear in at least one scenario's expected_tools.
# test_scenarios.py enforces this.
# ---------------------------------------------------------------------------

SCENARIOS: tuple[Scenario, ...] = (
    # --- Read & Classify workflows ---
    Scenario(
        name="triage",
        description="Inbox triage: list recent messages, classify and summarize the most recent one",
        prompt=(
            "Check my inbox for the most recent unread message. "
            "Classify it into an AR category and give me a short summary of what it's about."
        ),
        expected_tools=("list_inbox", "categorize_email", "summarize_email"),
    ),
    Scenario(
        name="thread-summary",
        description="Summarize an entire email thread by conversation ID",
        prompt=(
            "I have a long email thread I need to catch up on. "
            "First list my inbox to find a recent thread, then get the full thread "
            "and provide a summary of its progression, key facts, and current state."
        ),
        expected_tools=("get_thread", "summarize_thread"),
    ),
    Scenario(
        name="search-and-analyze",
        description="Search for emails matching a query, then summarize the top result",
        prompt=(
            "Search my mailbox for emails about 'invoice' from the last month. "
            "Pick the most relevant result and summarize it for me."
        ),
        expected_tools=("search_emails", "summarize_email"),
    ),
    Scenario(
        name="email-details",
        description="Deep-dive into a single email with attachment metadata",
        prompt=(
            "Get the most recent message from my inbox. Show me the full email content "
            "including sender, subject, body, and list any attachments it has."
        ),
        expected_tools=("get_email", "get_attachments"),
    ),
    # --- Classification & Extraction ---
    Scenario(
        name="classify-and-tag",
        description="Classify an email and apply the AI category as an Outlook tag",
        prompt=(
            "Take the most recent inbox message, classify it, "
            "and apply the classification as an Outlook category tag on the message."
        ),
        expected_tools=("categorize_email", "apply_llm_category_to_email"),
    ),
    Scenario(
        name="full-processing",
        description="Full AR processing: classify, extract data, draft a reply, and create reply draft",
        prompt=(
            "Process the most recent inbox message end-to-end: "
            "classify it, extract any invoice numbers and amounts, "
            "generate a professional reply draft, and create the reply draft in Outlook."
        ),
        expected_tools=(
            "categorize_email",
            "extract_email_data",
            "draft_reply",
            "create_reply_draft",
        ),
    ),
    Scenario(
        name="complete-ar",
        description="Complete AR workflow from inbox to reply draft",
        prompt=(
            "Run the full AR email workflow: check my inbox for the latest message, "
            "classify it into an AR category, extract structured data like invoice numbers "
            "and amounts, draft an appropriate reply, and create the reply draft in Outlook "
            "so I can review and send it."
        ),
        expected_tools=(
            "list_inbox",
            "categorize_email",
            "extract_email_data",
            "draft_reply",
            "create_reply_draft",
        ),
    ),
    # --- Drafting ---
    Scenario(
        name="ai-draft-reply",
        description="Generate an AI-powered reply without creating an Outlook draft",
        prompt=(
            "Get the most recent email from my inbox and generate a professional "
            "AR reply for it. Just show me the draft text — don't create it in Outlook yet."
        ),
        expected_tools=("get_email", "draft_reply"),
    ),
    # --- Write operations ---
    Scenario(
        name="organize",
        description="Organize emails: list folders, mark as read, move to a folder",
        prompt=(
            "Show me my mail folders. Then take the most recent inbox message, "
            "mark it as read, and move it to the Archive folder."
        ),
        expected_tools=("list_folders", "mark_as_read", "move_email"),
    ),
    Scenario(
        name="send-new",
        description="Compose and send a new email",
        prompt=(
            "Send a test email to test@example.com with subject 'Test from AR Agent' "
            "and body 'This is a test email sent via the AR email management agent.'"
        ),
        expected_tools=("send_email",),
    ),
    Scenario(
        name="create-draft-email",
        description="Create a new draft email in the Drafts folder",
        prompt=(
            "Create a draft email to test@example.com with subject 'Follow-up on Invoice' "
            "and body 'Dear Customer, this is a follow-up regarding your outstanding invoice. "
            "Please let us know if you need any additional information.'"
        ),
        expected_tools=("create_draft",),
    ),
    # --- Metadata & folder tools ---
    Scenario(
        name="master-categories",
        description="List Outlook master categories configured for the mailbox",
        prompt="Show me all the Outlook master categories configured for my mailbox, including their colors.",
        expected_tools=("list_master_categories",),
    ),
    Scenario(
        name="list-all-folders",
        description="List all mail folders with item counts",
        prompt="List all my mail folders and show how many items and unread items are in each one.",
        expected_tools=("list_folders",),
    ),
    Scenario(
        name="set-categories",
        description="Manually set Outlook category tags on a message",
        prompt=(
            "Get the most recent inbox message and set its Outlook categories "
            "to 'Invoice Dispute' and 'High Priority'."
        ),
        expected_tools=("set_message_categories",),
    ),
)


def get_scenario(name: str) -> Scenario | None:
    """Look up a scenario by name (case-insensitive)."""
    key = name.strip().lower()
    for s in SCENARIOS:
        if s.name.lower() == key:
            return s
    return None


def list_scenarios() -> tuple[Scenario, ...]:
    """Return all predefined scenarios."""
    return SCENARIOS
