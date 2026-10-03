# Changelog

All notable changes to `outlook-multi-tenant-mcp`. Versions follow [SemVer](https://semver.org/) (pre-1.0: minor = features).

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
