"""Follow-up flag and reminder support (Graph ``flag`` / ``reminderDateTime``)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from outlook_mcp.tools._common import graph_message_to_model
from outlook_mcp.tools.email_writer import set_message_flag
from outlook_mcp.tools.mail_query_params import graph_flag_for_patch


def _ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.log = AsyncMock()
    ctx.report_progress = AsyncMock()
    return ctx


def test_complete_and_notflagged_are_distinct_outcomes() -> None:
    """Outlook's "mark complete" keeps a record; clearing erases the flag. Not interchangeable."""
    assert graph_flag_for_patch("COMPLETE")["flagStatus"] == "complete"
    assert graph_flag_for_patch("NOTFLAGGED")["flagStatus"] == "notFlagged"


def test_bare_due_date_is_widened_to_end_of_business() -> None:
    """Midnight would make a due date overdue the instant it is set."""
    flag = graph_flag_for_patch("FLAGGED", due_date="2026-08-05")
    assert flag["dueDateTime"] == {"dateTime": "2026-08-05T17:00:00", "timeZone": "UTC"}


def test_due_date_implies_start_date() -> None:
    """Graph rejects dueDateTime without startDateTime, so one is supplied."""
    flag = graph_flag_for_patch("FLAGGED", due_date="2026-08-05")
    assert flag["startDateTime"] == flag["dueDateTime"]


def test_time_zone_is_carried_through() -> None:
    flag = graph_flag_for_patch("FLAGGED", due_date="2026-08-05", time_zone="Europe/Warsaw")
    assert flag["dueDateTime"]["timeZone"] == "Europe/Warsaw"


def test_invalid_status_is_rejected() -> None:
    with pytest.raises(ValueError, match="FLAGGED"):
        graph_flag_for_patch("bogus")


def test_due_date_with_clear_is_rejected() -> None:
    with pytest.raises(ValueError, match="NOTFLAGGED"):
        graph_flag_for_patch("NOTFLAGGED", due_date="2026-08-05")


def test_graph_message_to_model_surfaces_flag() -> None:
    raw = {"id": "m1", "body": {}, "flag": {"flagStatus": "complete"}}
    m = graph_message_to_model(raw)
    assert m.flag is not None and m.flag.flag_status == "complete"


@pytest.mark.asyncio
async def test_set_message_flag_requires_write_operations() -> None:
    with patch("outlook_mcp.tools.email_writer.get_settings") as gs:
        gs.return_value = MagicMock(enable_write_operations=False)
        out = json.loads(await set_message_flag(_ctx(), "m1", "COMPLETE"))
    assert out["error"] == "write_disabled"


@pytest.mark.asyncio
async def test_set_message_flag_complete_patches_graph() -> None:
    client = AsyncMock()
    client.update_message = AsyncMock(return_value={})
    with (
        patch("outlook_mcp.tools.email_writer.get_settings") as gs,
        patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=client),
    ):
        gs.return_value = MagicMock(enable_write_operations=True)
        out = json.loads(await set_message_flag(_ctx(), "m1", "COMPLETE"))

    assert out["ok"] is True
    payload = client.update_message.await_args.args[1]
    assert payload["flag"]["flagStatus"] == "complete"
    assert "isReminderOn" not in payload, "messages have no reminder fields in Graph"


@pytest.mark.asyncio
async def test_set_message_flag_sends_only_the_flag() -> None:
    """Graph 400s on isReminderOn/reminderDateTime for messages — those are event properties."""
    client = AsyncMock()
    client.update_message = AsyncMock(return_value={})
    with (
        patch("outlook_mcp.tools.email_writer.get_settings") as gs,
        patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=client),
    ):
        gs.return_value = MagicMock(enable_write_operations=True)
        await set_message_flag(_ctx(), "m1", "FLAGGED", due_date="2026-08-05")

    payload = client.update_message.await_args.args[1]
    assert set(payload) == {"flag"}
