"""Inbox rules, master categories, folder references, Graph $batch and compact move responses."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from outlook_mcp.auth.graph_client import GraphMailClient, MailFolderNotFoundError
from outlook_mcp.tools import mailbox_settings
from outlook_mcp.tools._batch import BatchOutcome, run_graph_batch
from outlook_mcp.tools._folders import resolve_folder_reference
from outlook_mcp.tools.email_writer import move_email, move_emails, set_messages_categories
from outlook_mcp.tools.mailbox_settings import (
    create_master_category,
    create_message_rule,
    delete_master_category,
    delete_message_rule,
    list_message_rules,
    normalize_category_color,
    update_message_rule,
)

_FOLDER_ID = "AAMkADAwATM0MDAAMS1iNWQ3LTI2ODQtMDACLTAwCgAuAAADdV/Xk+gw1E2DmyqP1nTd8gEA" + "B" * 20 + "="


class _Enabled:
    enable_write_operations = True


class _Disabled:
    enable_write_operations = False


def _response(*, json_body=None, status_code=200, headers=None) -> MagicMock:
    r = MagicMock(status_code=status_code, content=b"x", headers=headers or {})
    r.json = MagicMock(return_value=json_body if json_body is not None else {})
    r.raise_for_status = MagicMock()
    return r


def _fake_http(get_routes: dict[str, dict] | None = None, **responses: MagicMock) -> MagicMock:
    """Stand-in for ``httpx.AsyncClient``; ``get_routes`` maps a URL suffix to the JSON body returned."""
    http = MagicMock()
    for method, response in responses.items():
        setattr(http, method, AsyncMock(return_value=response))
    if get_routes is not None:

        async def get(url, params=None):  # noqa: ARG001
            for suffix, body in get_routes.items():
                if url.endswith(suffix):
                    return _response(json_body=body)
            raise AssertionError(f"unexpected GET {url}")

        http.get = AsyncMock(side_effect=get)
    http.__aenter__ = AsyncMock(return_value=http)
    http.__aexit__ = AsyncMock(return_value=False)
    return http


def _status_error(status: int, body: dict | str, headers: dict | None = None) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://graph.microsoft.com/v1.0/x")
    if isinstance(body, dict):
        response = httpx.Response(status, json=body, headers=headers, request=request)
    else:
        response = httpx.Response(status, text=body, headers=headers, request=request)
    return httpx.HTTPStatusError(str(status), request=request, response=response)


def _patched(module: str, client):
    return (
        patch(f"outlook_mcp.tools.{module}.get_settings", return_value=_Enabled()),
        patch(f"outlook_mcp.tools.{module}.make_graph_client", return_value=client),
    )


# --- folder references -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_folder_reference_passes_through_ids_and_well_known_names() -> None:
    client = AsyncMock()
    assert await resolve_folder_reference(client, _FOLDER_ID) == _FOLDER_ID
    assert await resolve_folder_reference(client, "Archive") == "Archive"
    client.resolve_mail_folder_path.assert_not_called()
    client.resolve_mail_folder_id_by_display_name.assert_not_called()


@pytest.mark.asyncio
async def test_folder_reference_well_known_resolved_to_id_when_required() -> None:
    client = AsyncMock()
    client.get_mail_folder = AsyncMock(return_value={"id": "inbox-real-id"})
    assert await resolve_folder_reference(client, "inbox", require_id=True) == "inbox-real-id"


@pytest.mark.asyncio
async def test_folder_reference_display_name_and_path_dispatch() -> None:
    client = AsyncMock()
    client.resolve_mail_folder_id_by_display_name = AsyncMock(return_value="id-by-name")
    client.resolve_mail_folder_path = AsyncMock(return_value="id-by-path")
    assert await resolve_folder_reference(client, "DMARC") == "id-by-name"
    assert await resolve_folder_reference(client, "Авто/DMARC") == "id-by-path"
    client.resolve_mail_folder_path.assert_awaited_once_with("Авто/DMARC")


@pytest.mark.asyncio
async def test_graph_client_resolves_nested_folder_path() -> None:
    http = _fake_http(
        get_routes={
            "/me/mailFolders": {"value": [{"id": "root-auto", "displayName": "Авто"}, {"id": "i", "displayName": "Inbox"}]},
            "/mailFolders/root-auto/childFolders": {"value": [{"id": "dmarc-id", "displayName": "dmarc"}]},
            "/mailFolders/dmarc-id/childFolders": {"value": []},
            "/mailFolders/i/childFolders": {"value": []},
        }
    )
    with patch.object(GraphMailClient, "_client", return_value=http):
        assert await GraphMailClient("tok").resolve_mail_folder_path("Авто/DMARC") == "dmarc-id"


@pytest.mark.asyncio
async def test_graph_client_folder_path_missing_segment_raises() -> None:
    http = _fake_http(
        get_routes={
            "/me/mailFolders": {"value": [{"id": "root-auto", "displayName": "Авто"}]},
            "/mailFolders/root-auto/childFolders": {"value": [{"id": "x", "displayName": "Other"}]},
            "/mailFolders/x/childFolders": {"value": []},
        }
    )
    with patch.object(GraphMailClient, "_client", return_value=http), pytest.raises(MailFolderNotFoundError) as ei:
        await GraphMailClient("tok").resolve_mail_folder_path("Авто/DMARC")
    assert ei.value.display_name == "Авто/DMARC"


# --- message rules -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graph_client_message_rule_crud_urls() -> None:
    client = GraphMailClient("tok")
    http = _fake_http(
        get=_response(json_body={"value": []}),
        post=_response(json_body={"id": "r1"}),
        patch=_response(json_body={"id": "r1", "isEnabled": False}),
        delete=_response(),
    )
    with patch.object(GraphMailClient, "_client", return_value=http):
        await client.list_message_rules()
        await client.create_message_rule({"displayName": "x"})
        await client.update_message_rule("r1", {"isEnabled": False})
        await client.delete_message_rule("r1")
    base = "/me/mailFolders/inbox/messageRules"
    assert http.get.await_args.args == (base,)
    assert http.post.await_args.args == (base,)
    assert http.patch.await_args.args == (f"{base}/r1",)
    assert http.delete.await_args.args == (f"{base}/r1",)


@pytest.mark.asyncio
async def test_list_message_rules_sorted_by_sequence() -> None:
    client = AsyncMock()
    client.list_message_rules = AsyncMock(
        return_value={
            "value": [
                {"id": "b", "displayName": "B", "sequence": 2, "isEnabled": True, "@odata.etag": "x"},
                {"id": "a", "displayName": "A", "sequence": 1, "isEnabled": False},
            ]
        }
    )
    with patch("outlook_mcp.tools.mailbox_settings.make_graph_client", return_value=client):
        data = json.loads(await list_message_rules(ctx=None))
    assert [r["id"] for r in data["rules"]] == ["a", "b"]
    assert "@odata.etag" not in data["rules"][1]


@pytest.mark.asyncio
async def test_create_message_rule_dmarc_example_normalizes_payload() -> None:
    client = AsyncMock()
    client.resolve_mail_folder_path = AsyncMock(return_value="dmarc-folder-id")
    client.create_message_rule = AsyncMock(return_value={"id": "rule-1", "displayName": "DMARC reports"})
    gs, mk = _patched("mailbox_settings", client)
    with gs, mk:
        data = json.loads(
            await create_message_rule(
                ctx=None,
                display_name="DMARC reports",
                sequence=1,
                conditions={"fromAddresses": ["noreply-dmarc-support@google.com"], "subjectContains": "Report domain"},
                actions={"moveToFolder": "Авто/DMARC", "markAsRead": True, "stopProcessingRules": True},
            )
        )
    assert data["ok"] is True and data["rule"]["id"] == "rule-1"
    payload = client.create_message_rule.await_args.args[0]
    assert payload == {
        "displayName": "DMARC reports",
        "sequence": 1,
        "conditions": {
            "fromAddresses": [{"emailAddress": {"address": "noreply-dmarc-support@google.com"}}],
            "subjectContains": ["Report domain"],
        },
        "actions": {"moveToFolder": "dmarc-folder-id", "markAsRead": True, "stopProcessingRules": True},
        "isEnabled": True,
    }


@pytest.mark.asyncio
async def test_create_message_rule_rejects_unknown_predicate_without_calling_graph() -> None:
    client = AsyncMock()
    gs, mk = _patched("mailbox_settings", client)
    with gs, mk:
        data = json.loads(
            await create_message_rule(
                ctx=None, display_name="x", sequence=1, conditions={"fromContains": "a"}, actions={"markAsRead": True}
            )
        )
    assert data["error"] == "validation_error"
    assert "fromContains" in data["message"] and "senderContains" in data["message"]
    client.create_message_rule.assert_not_called()


@pytest.mark.asyncio
async def test_create_message_rule_folder_not_found() -> None:
    client = AsyncMock()
    client.resolve_mail_folder_id_by_display_name = AsyncMock(side_effect=MailFolderNotFoundError("Nope"))
    gs, mk = _patched("mailbox_settings", client)
    with gs, mk:
        data = json.loads(
            await create_message_rule(
                ctx=None, display_name="x", sequence=1, conditions={}, actions={"moveToFolder": "Nope"}
            )
        )
    assert data["error"] == "folder_not_found"


@pytest.mark.asyncio
async def test_create_message_rule_graph_400_is_readable() -> None:
    client = AsyncMock()
    client.create_message_rule = AsyncMock(
        side_effect=_status_error(
            400, {"error": {"code": "ErrorInvalidRuleCondition", "message": "The rule condition is invalid."}}
        )
    )
    gs, mk = _patched("mailbox_settings", client)
    with gs, mk:
        data = json.loads(
            await create_message_rule(
                ctx=None, display_name="x", sequence=1, conditions={"sentToMe": True}, actions={"markAsRead": True}
            )
        )
    assert data["status_code"] == 400
    assert data["graph_code"] == "ErrorInvalidRuleCondition"
    assert data["graph_message"] == "The rule condition is invalid."
    assert "hint" not in data


@pytest.mark.asyncio
async def test_create_message_rule_403_carries_scope_hint() -> None:
    client = AsyncMock()
    client.create_message_rule = AsyncMock(side_effect=_status_error(403, {"error": {"code": "ErrorAccessDenied"}}))
    gs, mk = _patched("mailbox_settings", client)
    with gs, mk:
        data = json.loads(
            await create_message_rule(ctx=None, display_name="x", sequence=1, conditions={}, actions={"delete": True})
        )
    assert "MailboxSettings.ReadWrite" in data["hint"]


@pytest.mark.asyncio
async def test_update_message_rule_patches_only_given_fields() -> None:
    client = AsyncMock()
    client.update_message_rule = AsyncMock(return_value={"id": "r1", "isEnabled": False, "sequence": 3})
    gs, mk = _patched("mailbox_settings", client)
    with gs, mk:
        data = json.loads(await update_message_rule(ctx=None, rule_id="r1", is_enabled=False, sequence=3))
    assert data["ok"] is True
    client.update_message_rule.assert_awaited_once_with("r1", {"sequence": 3, "isEnabled": False})


@pytest.mark.asyncio
async def test_update_message_rule_requires_a_field() -> None:
    client = AsyncMock()
    gs, mk = _patched("mailbox_settings", client)
    with gs, mk:
        data = json.loads(await update_message_rule(ctx=None, rule_id="r1"))
    assert data["error"] == "validation_error"
    client.update_message_rule.assert_not_called()


@pytest.mark.asyncio
async def test_delete_message_rule() -> None:
    client = AsyncMock()
    gs, mk = _patched("mailbox_settings", client)
    with gs, mk:
        data = json.loads(await delete_message_rule(ctx=None, rule_id="r1"))
    assert data == {"ok": True, "deleted_rule_id": "r1"}
    client.delete_message_rule.assert_awaited_once_with("r1")


@pytest.mark.asyncio
async def test_rule_writes_disabled() -> None:
    with patch("outlook_mcp.tools.mailbox_settings.get_settings", return_value=_Disabled()):
        for coro in (
            create_message_rule(ctx=None, display_name="x", sequence=1, conditions={}, actions={"delete": True}),
            update_message_rule(ctx=None, rule_id="r1", is_enabled=True),
            delete_message_rule(ctx=None, rule_id="r1"),
            create_master_category(ctx=None, display_name="X"),
            delete_master_category(ctx=None, category_id="c1"),
        ):
            assert json.loads(await coro)["error"] == "write_disabled"


# --- master categories -------------------------------------------------------------------


def test_category_color_accepts_presets_names_and_none() -> None:
    assert normalize_category_color("preset24") == "preset24"
    assert normalize_category_color("Preset7") == "preset7"
    assert normalize_category_color("red") == "preset0"
    assert normalize_category_color("Dark Blue") == "preset22"
    assert normalize_category_color("none") == "none"
    with pytest.raises(ValueError):
        normalize_category_color("preset25")


@pytest.mark.asyncio
async def test_create_and_delete_master_category() -> None:
    client = AsyncMock()
    client.create_master_category = AsyncMock(return_value={"id": "c1", "displayName": "DMARC", "color": "preset7"})
    gs, mk = _patched("mailbox_settings", client)
    with gs, mk:
        created = json.loads(await create_master_category(ctx=None, display_name=" DMARC ", color="blue"))
        deleted = json.loads(await delete_master_category(ctx=None, category_id="c1"))
    assert created["ok"] is True
    client.create_master_category.assert_awaited_once_with("DMARC", "preset7")
    assert deleted == {"ok": True, "deleted_category_id": "c1"}


@pytest.mark.asyncio
async def test_create_master_category_invalid_color() -> None:
    client = AsyncMock()
    gs, mk = _patched("mailbox_settings", client)
    with gs, mk:
        data = json.loads(await create_master_category(ctx=None, display_name="X", color="ultraviolet"))
    assert data["error"] == "validation_error"
    client.create_master_category.assert_not_called()


# --- $batch orchestration ----------------------------------------------------------------


def _batch_ok(requests: list[dict]) -> dict:
    return {"responses": [{"id": r["id"], "status": 201, "body": {"id": f"new-{r['id']}"}} for r in requests]}


@pytest.mark.asyncio
async def test_batch_chunks_45_requests_into_20_20_5() -> None:
    client = AsyncMock()
    client.batch = AsyncMock(side_effect=_batch_ok)
    reqs = [{"id": str(i), "method": "POST", "url": f"/me/messages/m{i}/move"} for i in range(45)]
    out = await run_graph_batch(client, reqs, sleep=AsyncMock())
    sizes = sorted((len(c.args[0]) for c in client.batch.await_args_list), reverse=True)
    assert sizes == [20, 20, 5]
    assert len(out) == 45 and all(o.ok for o in out.values())


@pytest.mark.asyncio
async def test_batch_retries_only_throttled_subrequests_after_retry_after() -> None:
    calls: list[list[str]] = []

    async def batch(requests):
        calls.append([r["id"] for r in requests])
        if len(calls) == 1:
            return {
                "responses": [
                    {"id": "0", "status": 201, "body": {"id": "new-0"}},
                    {
                        "id": "1",
                        "status": 429,
                        "headers": {"Retry-After": "7"},
                        "body": {"error": {"code": "ApplicationThrottled", "message": "MailboxConcurrency"}},
                    },
                    {"id": "2", "status": 429, "headers": {"retry-after": "3"}},
                ]
            }
        return _batch_ok(requests)

    client = AsyncMock()
    client.batch = AsyncMock(side_effect=batch)
    sleep = AsyncMock()
    out = await run_graph_batch(client, [{"id": str(i)} for i in range(3)], sleep=sleep)
    assert calls == [["0", "1", "2"], ["1", "2"]]
    sleep.assert_awaited_once_with(7.0)
    assert out["1"] == BatchOutcome(201, {"id": "new-1"})


@pytest.mark.asyncio
async def test_batch_envelope_429_is_retried_with_backoff() -> None:
    client = AsyncMock()
    client.batch = AsyncMock(side_effect=[_status_error(429, "slow down"), {"responses": [{"id": "0", "status": 200}]}])
    sleep = AsyncMock()
    out = await run_graph_batch(client, [{"id": "0"}], sleep=sleep, base_delay=2.0)
    sleep.assert_awaited_once_with(2.0)  # no Retry-After → exponential backoff, first step
    assert out["0"].ok


@pytest.mark.asyncio
async def test_batch_gives_up_after_max_attempts() -> None:
    client = AsyncMock()
    client.batch = AsyncMock(side_effect=lambda reqs: {"responses": [{"id": "0", "status": 429}]})
    sleep = AsyncMock()
    out = await run_graph_batch(client, [{"id": "0"}], max_attempts=3, sleep=sleep)
    assert client.batch.await_count == 3 and sleep.await_count == 2
    assert out["0"].status == 429 and not out["0"].ok


# --- move / categories tools -------------------------------------------------------------

_FULL_MESSAGE = {
    "id": "new-id",
    "parentFolderId": "dest-id",
    "subject": "Report domain: example.com",
    "body": {"contentType": "html", "content": "<html>" + "x" * 50_000 + "</html>"},
    "toRecipients": [{"emailAddress": {"address": "a@b.com"}}],
}


@pytest.mark.asyncio
async def test_move_email_compact_by_default() -> None:
    client = AsyncMock()
    client.move_message = AsyncMock(return_value=_FULL_MESSAGE)
    gs, mk = _patched("email_writer", client)
    with gs, mk:
        raw = await move_email(ctx=None, message_id="m1", destination_folder_id="archive")
    assert json.loads(raw) == {
        "ok": True,
        "new_id": "new-id",
        "parent_folder_id": "dest-id",
        "subject": "Report domain: example.com",
    }
    assert len(raw) < 200


@pytest.mark.asyncio
async def test_move_email_full_when_not_compact() -> None:
    client = AsyncMock()
    client.move_message = AsyncMock(return_value=_FULL_MESSAGE)
    gs, mk = _patched("email_writer", client)
    with gs, mk:
        data = json.loads(await move_email(ctx=None, message_id="m1", destination_folder_id="archive", compact=False))
    assert data["message"]["body"]["content"].startswith("<html>")


@pytest.mark.asyncio
async def test_move_email_resolves_folder_path() -> None:
    client = AsyncMock()
    client.resolve_mail_folder_path = AsyncMock(return_value="dmarc-id")
    client.move_message = AsyncMock(return_value=_FULL_MESSAGE)
    gs, mk = _patched("email_writer", client)
    with gs, mk:
        await move_email(ctx=None, message_id="m1", destination_folder_id="Авто/DMARC")
    client.move_message.assert_awaited_once_with("m1", "dmarc-id")


@pytest.mark.asyncio
async def test_move_emails_45_ids_compact_results() -> None:
    client = GraphMailClient("tok")
    seen: list[dict] = []

    async def batch(requests):
        seen.extend(requests)
        responses = []
        for r in requests:
            if r["id"] == "44":
                responses.append(
                    {"id": r["id"], "status": 404, "body": {"error": {"code": "ErrorItemNotFound", "message": "gone"}}}
                )
            else:
                responses.append({"id": r["id"], "status": 201, "body": {"id": f"new-{r['id']}", "body": "huge"}})
        return {"responses": responses}

    ids = [f"msg+{i}/x=" for i in range(45)]
    with (
        patch.object(GraphMailClient, "batch", side_effect=batch) as batch_mock,
        patch("outlook_mcp.tools.email_writer.get_settings", return_value=_Enabled()),
        patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=client),
    ):
        data = json.loads(await move_emails(ctx=None, message_ids=ids, destination_folder_id="archive"))

    assert batch_mock.await_count == 3
    assert data["summary"] == {"total": 45, "succeeded": 44, "failed": 1}
    assert data["ok"] is False
    assert data["results"][0] == {"old_id": "msg+0/x=", "new_id": "new-0", "status": 201, "error": None}
    assert data["results"][44] == {"old_id": "msg+44/x=", "new_id": None, "status": 404, "error": "ErrorItemNotFound: gone"}
    first = next(r for r in seen if r["id"] == "0")
    assert first["url"] == "/me/messages/msg%2B0%2Fx%3D/move"
    assert first["body"] == {"destinationId": "archive"}


@pytest.mark.asyncio
async def test_move_emails_dedupes_ids() -> None:
    client = AsyncMock()
    client.message_path = MagicMock(side_effect=lambda m: f"/me/messages/{m}")
    gs, mk = _patched("email_writer", client)
    with gs, mk, patch("outlook_mcp.tools.email_writer.run_graph_batch", AsyncMock(return_value={})) as rb:
        data = json.loads(await move_emails(ctx=None, message_ids=["a", "a", "b"], destination_folder_id="archive"))
    assert len(rb.await_args.args[1]) == 2
    assert data["summary"]["total"] == 2


@pytest.mark.asyncio
async def test_set_messages_categories_batch() -> None:
    client = AsyncMock()
    client.message_path = MagicMock(side_effect=lambda m: f"/me/messages/{m}")
    client.batch = AsyncMock(
        side_effect=lambda reqs: {"responses": [{"id": r["id"], "status": 200, "body": {"id": "x"}} for r in reqs]}
    )
    gs, mk = _patched("email_writer", client)
    with gs, mk:
        data = json.loads(
            await set_messages_categories(
                ctx=None,
                items=[{"message_id": "m1", "categories": [" DMARC "]}, {"message_id": "m2", "categories": ["A", "B"]}],
            )
        )
    assert data["ok"] is True
    assert data["results"] == [
        {"message_id": "m1", "status": 200, "error": None},
        {"message_id": "m2", "status": 200, "error": None},
    ]
    sent = client.batch.await_args.args[0]
    assert sent[0] == {
        "id": "0",
        "method": "PATCH",
        "url": "/me/messages/m1",
        "body": {"categories": ["DMARC"]},
        "headers": {"Content-Type": "application/json"},
    }


@pytest.mark.asyncio
async def test_set_messages_categories_validates_each_item() -> None:
    client = AsyncMock()
    gs, mk = _patched("email_writer", client)
    with gs, mk:
        data = json.loads(
            await set_messages_categories(ctx=None, items=[{"message_id": "m1", "categories": ["ok"]}, {"message_id": "m2"}])
        )
    assert data["error"] == "validation_error" and "items[1]" in data["message"]
    client.batch.assert_not_called()


def test_new_tools_are_registered() -> None:
    from outlook_mcp.server import build_mcp

    names = {t.name for t in build_mcp()._tool_manager.list_tools()}
    assert {
        "list_message_rules",
        "create_message_rule",
        "update_message_rule",
        "delete_message_rule",
        "create_master_category",
        "delete_master_category",
        "move_emails",
        "set_messages_categories",
    } <= names
    assert mailbox_settings.CATEGORY_PRESET_COLORS["preset0"] == "Red"


@pytest.mark.asyncio
async def test_batch_retry_after_zero_still_waits() -> None:
    client = AsyncMock()
    client.batch = AsyncMock(
        side_effect=[{"responses": [{"id": "0", "status": 429, "headers": {"Retry-After": "0"}}]}, _batch_ok([{"id": "0"}])]
    )
    sleep = AsyncMock()
    await run_graph_batch(client, [{"id": "0"}], sleep=sleep, base_delay=1.5)
    sleep.assert_awaited_once_with(1.5)


@pytest.mark.asyncio
async def test_batch_throttle_only_does_not_retry_504() -> None:
    from outlook_mcp.tools._batch import THROTTLE_ONLY_STATUSES

    client = AsyncMock()
    client.batch = AsyncMock(return_value={"responses": [{"id": "0", "status": 504}]})
    out = await run_graph_batch(client, [{"id": "0"}], sleep=AsyncMock(), retry_statuses=THROTTLE_ONLY_STATUSES)
    assert client.batch.await_count == 1 and out["0"].status == 504


@pytest.mark.asyncio
async def test_batch_malformed_envelope_becomes_outcome_not_exception() -> None:
    client = AsyncMock()
    client.batch = AsyncMock(side_effect=ValueError("not json"))
    out = await run_graph_batch(client, [{"id": "0"}], max_attempts=2, sleep=AsyncMock())
    assert out["0"].status == 0 and out["0"].body["error"]["code"] == "network_error"
