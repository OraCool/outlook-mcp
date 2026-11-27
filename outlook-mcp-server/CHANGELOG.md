# Changelog

All notable changes to `outlook-multi-tenant-mcp`. Versions follow [SemVer](https://semver.org/) (pre-1.0: minor = features).

## 0.14.0 — 2026-11-27

### Added
- **Tool-aware server instructions.** The MCP `instructions` returned by `initialize` are now generated from the
  tools that are actually registered (after `MCP_ENABLED_TOOLS` / `MCP_DISABLED_TOOLS` and prerequisite settings):
  KQL hints for `search_emails`, thread checks, `create_draft` / `create_reply_draft` / `delete_draft` pitfalls,
  folder-name resolution, attachment tools, and a "this deployment does not allow sending" line when no send tool
  is registered. A line appears only when its tool is registered. The old static text (which mentioned a
  specific product and header auth only) is gone.
- **`MCP_INSTRUCTIONS_APPEND`**: optional deployment-specific text appended to the generated instructions
  (capped at 4000 characters, never logged).

## 0.13.1 — 2026-11-27

### Changed
- **Behaviour change: `create_draft` now returns a compact response by default** (new `compact: bool = True`,
  mirroring `move_email`). The default response is `{ok, id, webLink, isDraft, to_count, cc_count, bcc_count}`
  (`webLink` when Graph returned it) plus the `attachments` summary (id/name/size/contentType) when files were
  attached — no recipients, subject or body. Pass `compact=false` for the full Graph message under `message`
  (recipients and body included), now also with `to_count`. Callers that read `message` must pass `compact=false`.
- Docs: "never echoes addresses" applies to validation errors; a successful call with `compact=true` carries counts
  only, with `compact=false` the Graph message (including recipients) is returned. `to_count` is the raw length of
  `to_addresses` (not validated or de-duplicated); Graph error messages on failure paths may echo request details.

## 0.13.0 — 2026-11-27

### Added
- **`create_draft`: `cc_addresses` / `bcc_addresses`** (optional lists) mapped to Graph `ccRecipients` /
  `bccRecipients`. Each address is trimmed and checked (one `@`, non-empty local part, dotted domain, no
  whitespace or control characters); each list is de-duplicated case-insensitively; to + cc + bcc is capped at
  500 (Exchange limit). Invalid input returns `validation_error` with the `field` and `invalid_count`, never the
  addresses. A BCC-only draft is allowed (group reminders: put everyone in `bcc_addresses`). The response gains
  `cc_count` / `bcc_count`; logs carry counts only.

## 0.12.0 — 2026-11-27

### Added
- **`delete_draft`** (write tool): deletes a draft by Graph message id. The message is fetched first
  (`$select=id,isDraft`); anything that is not a draft returns `{"ok": false, "error": "not_a_draft"}` and is
  never deleted. Success returns `{"ok": true, "deleted": true}`, an unknown id `{"ok": false, "error": "not_found"}`.
  Graph's `DELETE` does not purge: Exchange keeps the item recoverable (normally in Deleted Items, per the
  mailbox's retention policy). If the draft is sent between the check and the delete, the sent item may be
  moved to Deleted Items (narrow race). Needs `ENABLE_WRITE_OPERATIONS=true` and `Mail.ReadWrite`. Logs only the id preview.

## 0.11.0 — 2026-11-24

### Added
- **Cloud application mode:** `GRAPH_APPLICATION_CREDENTIAL=managed_identity` acquires Graph tokens from the
  host's user-assigned managed identity (`AZURE_CLIENT_ID`, `IDENTITY_ENDPOINT`/`IDENTITY_HEADER`) — no client
  secret. `GRAPH_TRUST_REQUEST_HEADERS=false` ignores caller-supplied token/session/mode/secret headers, and
  `GRAPH_ALLOWED_MAILBOXES` restricts which mailboxes application mode can reach; it is required with
  `managed_identity` (any header trust setting), optional with `client_secret`. Fail-closed rules (tool calls return `configuration_error`);
  new error payloads `mailbox_not_allowed`, `managed_identity_error`, `configuration_error`.
- **Tool selection:** `MCP_ENABLED_TOOLS` / `MCP_DISABLED_TOOLS` (unknown names are a startup error; disabled
  wins; enabling a write tool while `ENABLE_WRITE_OPERATIONS=false` is a startup error).
- **`save_attachment_to_storage`:** writes an attachment to a private Azure Blob container with the managed
  identity (`ATTACHMENT_STORAGE=azure_blob`, `ATTACHMENT_BLOB_CONTAINER_URL`, `ATTACHMENT_ALLOWED_PREFIXES`).
  Strict key validation (NFC; refuses absolute, `.`/`..`, backslash, empty segments, control/format/bidi
  characters, NFKC confusables, leading/trailing space or trailing dot in a segment, > 1024 characters).
  The result means "queued", not delivered. Refused (`configuration_error`) unless
  `GRAPH_TRUST_REQUEST_HEADERS=false`, so the storage identity and the Graph identity are both the server's.
- **`save_attachment_to_path` (security):** when `path` is a directory, the attachment's own name is reduced
  to a plain file name (last component, no control characters; empty, `.` and `..` are refused) and the
  resolved target must stay inside that directory.
- **`get_attachment_text`:** PDF text extraction with `ATTACHMENT_TEXT_MAX_BYTES` (15 MB),
  `ATTACHMENT_TEXT_MAX_PAGES` (200), `ATTACHMENT_TEXT_TIMEOUT_SECONDS` (30); `max_chars` clamped to 1..1,000,000. Runs on a dedicated 2-thread pool
  (a timed-out extraction finishes in the background and holds its slot; no free slot within the timeout ->
  `unreadable`).
- **`LOG_LEVEL`** setting (default: logging unchanged).

### Changed
- INFO logs no longer contain search queries, rule/category/folder names or full message/folder/attachment ids
  (`search_emails`, `list_inbox`, rule and category tools, `create_mail_folder`, `create_reply_draft`, move/flag/read tools).
- `httpx`/`httpcore` loggers are set to `WARNING` and `pypdf` to `ERROR` so blob keys and attachment data
  stay out of logs.

### Dependencies
- Added `pypdf>=7.1`.

## 0.10.0 — 2026-10-03

### Added
- **Inbox rules:** `list_message_rules`, `create_message_rule`, `update_message_rule`, `delete_message_rule`
  (Graph `/mailFolders/inbox/messageRules`). Conditions/actions are validated locally; `fromAddresses`,
  `sentToAddresses`, `forwardTo`, `redirectTo` accept plain email strings; `moveToFolder` / `copyToFolder`
  accept a folder id, well-known name, display name or path (`Auto/DMARC`). Graph 400s are returned as
  `graph_code` / `graph_message`; 401/403 include a missing-scope `hint`.
- **Master categories:** `create_master_category` (color as `preset0`..`preset24`, `none`, or a color name)
  and `delete_master_category`.
- **Batch operations:** `move_emails` and `set_messages_categories` via Graph JSON `$batch` — 20 per batch,
  bounded concurrency, retries of throttled sub-requests honouring `Retry-After` (429/503/504 for
  category updates; 429 only for moves, which are not idempotent),
  compact per-item results plus a `summary`.
- Folder references by **path** (`Parent/Child`) for moves and rule actions.

### Changed
- `move_email` returns a compact `{ok, new_id, parent_folder_id, subject}` by default; pass
  `compact=false` for the previous full-message response.
- `move_email` `destination_folder_id` also accepts a display name or path. Short strings that are not
  well-known folder names are now resolved as display names instead of being sent to Graph as ids.

### Requirements
- Rules and master-category writes need delegated **`MailboxSettings.ReadWrite`**. It is not added to the
  OAuth scope list automatically — add it to `GRAPH_OAUTH_SCOPES` and sign in again.
