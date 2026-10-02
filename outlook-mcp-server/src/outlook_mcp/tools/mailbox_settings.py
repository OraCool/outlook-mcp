"""Inbox rules (Graph ``messageRule``) and Outlook master categories.

Both live under mailbox settings: reads need delegated ``MailboxSettings.Read``, writes need
``MailboxSettings.ReadWrite``. Writes are gated by ENABLE_WRITE_OPERATIONS like every other
mutating tool. The scope is *not* added to the OAuth scope list automatically — add it to
``GRAPH_OAUTH_SCOPES`` (token cache lookups use exactly that list).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx

from outlook_mcp.auth.graph_client import GraphMailClient
from outlook_mcp.auth.token_handler import GraphTokenExpiredError, GraphTokenMissingError
from outlook_mcp.config import get_settings
from outlook_mcp.tools._common import (
    graph_http_error_payload,
    make_graph_client,
    sanitize_client_error_message,
    tool_error_token,
)
from outlook_mcp.tools._folders import FOLDER_RESOLUTION_ERRORS, folder_error_payload, resolve_folder_reference
from outlook_mcp.tools._notify import tool_log_info, tool_log_warning

if TYPE_CHECKING:
    from mcp.server.mcpserver import Context

_READ_SCOPE_HINT = (
    "The token likely lacks MailboxSettings.Read (or .ReadWrite). Grant it on the app registration, "
    "add it to GRAPH_OAUTH_SCOPES and sign in again (e.g. outlook-mcp-oauth-device)."
)
_WRITE_SCOPE_HINT = (
    "The token likely lacks MailboxSettings.ReadWrite. Grant it on the app registration, add it to "
    "GRAPH_OAUTH_SCOPES and sign in again (e.g. outlook-mcp-oauth-device)."
)

# --- messageRulePredicates / messageRuleActions -------------------------------------------

# https://learn.microsoft.com/en-us/graph/api/resources/messagerulepredicates
_PREDICATE_STRING_LISTS = frozenset(
    {
        "bodyContains",
        "bodyOrSubjectContains",
        "categories",
        "headerContains",
        "recipientContains",
        "senderContains",
        "subjectContains",
    }
)
_PREDICATE_RECIPIENT_LISTS = frozenset({"fromAddresses", "sentToAddresses"})
_PREDICATE_SCALARS = frozenset(
    {
        "hasAttachments",
        "importance",
        "isApprovalRequest",
        "isAutomaticForward",
        "isAutomaticReply",
        "isEncrypted",
        "isMeetingRequest",
        "isMeetingResponse",
        "isNonDeliveryReport",
        "isPermissionControlled",
        "isReadReceipt",
        "isSigned",
        "isVoicemail",
        "messageActionFlag",
        "notSentToMe",
        "sensitivity",
        "sentCcMe",
        "sentOnlyToMe",
        "sentToMe",
        "sentToOrCcMe",
        "withinSizeRange",
    }
)
_PREDICATE_KEYS = _PREDICATE_STRING_LISTS | _PREDICATE_RECIPIENT_LISTS | _PREDICATE_SCALARS

# https://learn.microsoft.com/en-us/graph/api/resources/messageruleactions
_ACTION_FOLDERS = frozenset({"moveToFolder", "copyToFolder"})
_ACTION_RECIPIENT_LISTS = frozenset({"forwardTo", "forwardAsAttachmentTo", "redirectTo"})
_ACTION_STRING_LISTS = frozenset({"assignCategories"})
_ACTION_SCALARS = frozenset({"delete", "markAsRead", "markImportance", "permanentDelete", "stopProcessingRules"})
_ACTION_KEYS = _ACTION_FOLDERS | _ACTION_RECIPIENT_LISTS | _ACTION_STRING_LISTS | _ACTION_SCALARS


class RuleValidationError(ValueError):
    """Rule conditions/actions failed local validation before reaching Graph."""


def _recipients(key: str, value: Any) -> list[dict[str, Any]]:
    """``"a@x.com"`` / ``["a@x.com"]`` / ``[{"address": ...}]`` / Graph ``recipient`` → Graph recipients."""
    items = [value] if isinstance(value, (str, dict)) else value
    if not isinstance(items, list):
        raise RuleValidationError(f"{key} must be an email address or a list of them.")
    out: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, str) and item.strip():
            out.append({"emailAddress": {"address": item.strip()}})
        elif isinstance(item, dict) and isinstance(item.get("emailAddress"), dict):
            out.append(item)
        elif isinstance(item, dict) and item.get("address"):
            out.append({"emailAddress": {k: v for k, v in item.items() if k in ("address", "name")}})
        else:
            raise RuleValidationError(f"{key}: each entry must be an email address string or {{'address': ...}}.")
    return out


def _string_list(key: str, value: Any) -> list[str]:
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, list) or not all(isinstance(v, str) and v.strip() for v in items):
        raise RuleValidationError(f"{key} must be a non-empty string or a list of non-empty strings.")
    return [v.strip() for v in items]


def normalize_predicates(predicates: dict[str, Any] | None, *, label: str = "conditions") -> dict[str, Any]:
    """Validate keys and coerce convenience forms into Graph ``messageRulePredicates``."""
    if predicates is None:
        return {}
    if not isinstance(predicates, dict):
        raise RuleValidationError(f"{label} must be an object (messageRulePredicates).")
    unknown = sorted(set(predicates) - _PREDICATE_KEYS)
    if unknown:
        raise RuleValidationError(
            f"Unknown {label} key(s): {', '.join(unknown)}. Allowed: {', '.join(sorted(_PREDICATE_KEYS))}."
        )
    out: dict[str, Any] = {}
    for key, value in predicates.items():
        if key in _PREDICATE_RECIPIENT_LISTS:
            out[key] = _recipients(key, value)
        elif key in _PREDICATE_STRING_LISTS:
            out[key] = _string_list(key, value)
        else:
            out[key] = value
    return out


async def normalize_actions(client: GraphMailClient, actions: dict[str, Any] | None) -> dict[str, Any]:
    """Validate keys, coerce recipients/strings, and resolve ``moveToFolder``/``copyToFolder`` to ids."""
    if actions is None:
        return {}
    if not isinstance(actions, dict):
        raise RuleValidationError("actions must be an object (messageRuleActions).")
    unknown = sorted(set(actions) - _ACTION_KEYS)
    if unknown:
        raise RuleValidationError(
            f"Unknown actions key(s): {', '.join(unknown)}. Allowed: {', '.join(sorted(_ACTION_KEYS))}."
        )
    out: dict[str, Any] = {}
    for key, value in actions.items():
        if key in _ACTION_FOLDERS:
            if not isinstance(value, str) or not value.strip():
                raise RuleValidationError(f"{key} must be a folder id, well-known name, display name or path.")
            out[key] = await resolve_folder_reference(client, value, require_id=True)
        elif key in _ACTION_RECIPIENT_LISTS:
            out[key] = _recipients(key, value)
        elif key in _ACTION_STRING_LISTS:
            out[key] = _string_list(key, value)
        else:
            out[key] = value
    return out


def _rule_summary(rule: dict[str, Any]) -> dict[str, Any]:
    keys = ("id", "displayName", "sequence", "isEnabled", "hasError", "isReadOnly", "conditions", "actions", "exceptions")
    return {k: rule[k] for k in keys if k in rule}


# --- shared tool plumbing ------------------------------------------------------------------


def _write_disabled(tool: str) -> str:
    return json.dumps(
        {
            "error": "write_disabled",
            "message": f"Set ENABLE_WRITE_OPERATIONS=true to enable {tool} (requires MailboxSettings.ReadWrite).",
        }
    )


async def _http_error(ctx: Context, tool: str, e: httpx.HTTPStatusError, hint: str) -> str:
    await tool_log_warning(ctx, f"{tool}: http_error status={e.response.status_code}")
    return json.dumps(graph_http_error_payload(e, hint=hint))


async def _network_error(ctx: Context, tool: str, e: httpx.HTTPError) -> str:
    await tool_log_warning(ctx, f"{tool}: network_error {type(e).__name__}")
    return json.dumps({"error": "network_error", "message": sanitize_client_error_message(str(e))})


async def _build_rule_payload(
    client: GraphMailClient,
    *,
    display_name: str | None,
    sequence: int | None,
    conditions: dict[str, Any] | None,
    actions: dict[str, Any] | None,
    exceptions: dict[str, Any] | None,
    is_enabled: bool | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if display_name is not None:
        if not display_name.strip():
            raise RuleValidationError("display_name must be non-empty.")
        payload["displayName"] = display_name.strip()
    if sequence is not None:
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise RuleValidationError("sequence must be >= 1 (lower runs first).")
        payload["sequence"] = sequence
    if conditions is not None:
        payload["conditions"] = normalize_predicates(conditions)
    if exceptions is not None:
        payload["exceptions"] = normalize_predicates(exceptions, label="exceptions")
    if actions is not None:
        payload["actions"] = await normalize_actions(client, actions)
    if is_enabled is not None:
        payload["isEnabled"] = bool(is_enabled)
    return payload


# --- message rules -------------------------------------------------------------------------


async def list_message_rules(ctx: Context) -> str:
    """List Inbox rules (id, displayName, sequence, isEnabled, conditions, actions, exceptions)."""
    try:
        client = make_graph_client(ctx)
    except (GraphTokenExpiredError, GraphTokenMissingError) as e:
        return json.dumps(tool_error_token(e))
    await tool_log_info(ctx, "list_message_rules: start")
    try:
        data = await client.list_message_rules()
        rules = sorted(
            (_rule_summary(r) for r in data.get("value") or []),
            key=lambda r: (r.get("sequence") is None, r.get("sequence") or 0),
        )
        return json.dumps({"rules": rules, "count": len(rules)}, indent=2)
    except httpx.HTTPStatusError as e:
        return await _http_error(ctx, "list_message_rules", e, _READ_SCOPE_HINT)
    except httpx.HTTPError as e:
        return await _network_error(ctx, "list_message_rules", e)


async def create_message_rule(
    ctx: Context,
    display_name: str,
    sequence: int,
    conditions: dict[str, Any],
    actions: dict[str, Any],
    exceptions: dict[str, Any] | None = None,
    is_enabled: bool = True,
) -> str:
    """Create an Inbox rule. See ``server.create_message_rule`` for the accepted shapes."""
    if not get_settings().enable_write_operations:
        return _write_disabled("create_message_rule")
    if not actions:
        return json.dumps({"error": "validation_error", "message": "actions must contain at least one action."})

    try:
        client = make_graph_client(ctx)
    except (GraphTokenExpiredError, GraphTokenMissingError) as e:
        return json.dumps(tool_error_token(e))

    try:
        payload = await _build_rule_payload(
            client,
            display_name=display_name,
            sequence=sequence,
            conditions=conditions or {},
            actions=actions,
            exceptions=exceptions,
            is_enabled=is_enabled,
        )
    except RuleValidationError as e:
        return json.dumps({"error": "validation_error", "message": str(e)})
    except FOLDER_RESOLUTION_ERRORS as e:
        return json.dumps(folder_error_payload(e))
    except httpx.HTTPStatusError as e:
        return await _http_error(ctx, "create_message_rule", e, _WRITE_SCOPE_HINT)
    except httpx.HTTPError as e:
        return await _network_error(ctx, "create_message_rule", e)

    await tool_log_info(ctx, f"create_message_rule: display_name={display_name!r} sequence={sequence}")
    try:
        created = await client.create_message_rule(payload)
        return json.dumps({"ok": True, "rule": _rule_summary(created)}, indent=2)
    except httpx.HTTPStatusError as e:
        return await _http_error(ctx, "create_message_rule", e, _WRITE_SCOPE_HINT)
    except httpx.HTTPError as e:
        return await _network_error(ctx, "create_message_rule", e)


async def update_message_rule(
    ctx: Context,
    rule_id: str,
    display_name: str | None = None,
    sequence: int | None = None,
    conditions: dict[str, Any] | None = None,
    actions: dict[str, Any] | None = None,
    exceptions: dict[str, Any] | None = None,
    is_enabled: bool | None = None,
) -> str:
    """PATCH an Inbox rule; only the fields given are changed (a given ``conditions`` replaces all conditions)."""
    if not get_settings().enable_write_operations:
        return _write_disabled("update_message_rule")
    if not rule_id or not rule_id.strip():
        return json.dumps({"error": "validation_error", "message": "rule_id must be a non-empty string."})

    try:
        client = make_graph_client(ctx)
    except (GraphTokenExpiredError, GraphTokenMissingError) as e:
        return json.dumps(tool_error_token(e))

    try:
        payload = await _build_rule_payload(
            client,
            display_name=display_name,
            sequence=sequence,
            conditions=conditions,
            actions=actions,
            exceptions=exceptions,
            is_enabled=is_enabled,
        )
    except RuleValidationError as e:
        return json.dumps({"error": "validation_error", "message": str(e)})
    except FOLDER_RESOLUTION_ERRORS as e:
        return json.dumps(folder_error_payload(e))
    except httpx.HTTPStatusError as e:
        return await _http_error(ctx, "update_message_rule", e, _WRITE_SCOPE_HINT)
    except httpx.HTTPError as e:
        return await _network_error(ctx, "update_message_rule", e)
    if not payload:
        return json.dumps({"error": "validation_error", "message": "Nothing to update: pass at least one field."})

    await tool_log_info(ctx, f"update_message_rule: rule_id={rule_id!r} fields={sorted(payload)}")
    try:
        updated = await client.update_message_rule(rule_id, payload)
        return json.dumps({"ok": True, "rule": _rule_summary(updated) if updated else {"id": rule_id}}, indent=2)
    except httpx.HTTPStatusError as e:
        return await _http_error(ctx, "update_message_rule", e, _WRITE_SCOPE_HINT)
    except httpx.HTTPError as e:
        return await _network_error(ctx, "update_message_rule", e)


async def delete_message_rule(ctx: Context, rule_id: str) -> str:
    """Delete an Inbox rule by id."""
    if not get_settings().enable_write_operations:
        return _write_disabled("delete_message_rule")
    if not rule_id or not rule_id.strip():
        return json.dumps({"error": "validation_error", "message": "rule_id must be a non-empty string."})
    try:
        client = make_graph_client(ctx)
    except (GraphTokenExpiredError, GraphTokenMissingError) as e:
        return json.dumps(tool_error_token(e))
    await tool_log_info(ctx, f"delete_message_rule: rule_id={rule_id!r}")
    try:
        await client.delete_message_rule(rule_id)
        return json.dumps({"ok": True, "deleted_rule_id": rule_id})
    except httpx.HTTPStatusError as e:
        return await _http_error(ctx, "delete_message_rule", e, _WRITE_SCOPE_HINT)
    except httpx.HTTPError as e:
        return await _network_error(ctx, "delete_message_rule", e)


# --- master categories ---------------------------------------------------------------------

# https://learn.microsoft.com/en-us/graph/api/resources/outlookcategory (categoryColor)
CATEGORY_PRESET_COLORS: dict[str, str] = {
    "preset0": "Red",
    "preset1": "Orange",
    "preset2": "Brown",
    "preset3": "Yellow",
    "preset4": "Green",
    "preset5": "Teal",
    "preset6": "Olive",
    "preset7": "Blue",
    "preset8": "Purple",
    "preset9": "Cranberry",
    "preset10": "Steel",
    "preset11": "DarkSteel",
    "preset12": "Gray",
    "preset13": "DarkGray",
    "preset14": "Black",
    "preset15": "DarkRed",
    "preset16": "DarkOrange",
    "preset17": "DarkBrown",
    "preset18": "DarkYellow",
    "preset19": "DarkGreen",
    "preset20": "DarkTeal",
    "preset21": "DarkOlive",
    "preset22": "DarkBlue",
    "preset23": "DarkPurple",
    "preset24": "DarkCranberry",
}
_COLOR_NAME_TO_PRESET = {name.casefold(): preset for preset, name in CATEGORY_PRESET_COLORS.items()}


def normalize_category_color(color: str) -> str:
    """Accept ``preset0``..``preset24``, ``none``, or a color name (``red``, ``DarkBlue``)."""
    c = (color or "").strip()
    if c.casefold() == "none":
        return "none"
    if c.casefold() in CATEGORY_PRESET_COLORS:
        return c.casefold()
    preset = _COLOR_NAME_TO_PRESET.get(c.casefold().replace(" ", "").replace("_", ""))
    if preset:
        return preset
    raise ValueError(f"Unknown color {color!r}: use preset0..preset24, none, or a name such as Red / DarkBlue.")


async def create_master_category(ctx: Context, display_name: str, color: str = "preset0") -> str:
    """Create an Outlook master category (POST ``/outlook/masterCategories``)."""
    if not get_settings().enable_write_operations:
        return _write_disabled("create_master_category")
    if not isinstance(display_name, str) or not display_name.strip():
        return json.dumps({"error": "validation_error", "message": "display_name must be a non-empty string."})
    try:
        preset = normalize_category_color(color)
    except ValueError as e:
        return json.dumps({"error": "validation_error", "message": str(e)})
    try:
        client = make_graph_client(ctx)
    except (GraphTokenExpiredError, GraphTokenMissingError) as e:
        return json.dumps(tool_error_token(e))
    await tool_log_info(ctx, f"create_master_category: display_name={display_name!r} color={preset}")
    try:
        created = await client.create_master_category(display_name.strip(), preset)
        return json.dumps({"ok": True, "category": created})
    except httpx.HTTPStatusError as e:
        return await _http_error(ctx, "create_master_category", e, _WRITE_SCOPE_HINT)
    except httpx.HTTPError as e:
        return await _network_error(ctx, "create_master_category", e)


async def delete_master_category(ctx: Context, category_id: str) -> str:
    """Delete an Outlook master category by id (from ``list_master_categories``)."""
    if not get_settings().enable_write_operations:
        return _write_disabled("delete_master_category")
    if not category_id or not category_id.strip():
        return json.dumps({"error": "validation_error", "message": "category_id must be a non-empty string."})
    try:
        client = make_graph_client(ctx)
    except (GraphTokenExpiredError, GraphTokenMissingError) as e:
        return json.dumps(tool_error_token(e))
    await tool_log_info(ctx, f"delete_master_category: category_id={category_id!r}")
    try:
        await client.delete_master_category(category_id)
        return json.dumps({"ok": True, "deleted_category_id": category_id})
    except httpx.HTTPStatusError as e:
        return await _http_error(ctx, "delete_master_category", e, _WRITE_SCOPE_HINT)
    except httpx.HTTPError as e:
        return await _network_error(ctx, "delete_master_category", e)
