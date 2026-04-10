---
name: ar-mcp-tools
description: >
  Outlook MCP Server tool reference for fetching email data from Microsoft Outlook via
  the Microsoft Graph API. Load this skill at the start of any processing run where the
  Orchestrator must retrieve email content by message ID — including single-message fetch,
  full thread retrieval, attachment metadata lookup, and email search. Specifically: load
  when calling get_email, get_thread, get_attachments, or search_emails; when handling
  ERR_GRAPH_TOKEN_EXPIRED, ERR_MESSAGE_NOT_FOUND, or rate-limit errors; when processing
  multiple message IDs from a SAP UI or Alevate UI trigger; or when determining the correct
  PII response level (full / minimal / redacted) for the deployment environment.
  Attach to: Orchestrator assistant only.
---

# Outlook MCP Tools


---

## Authentication Context

The Outlook MCP Server handles Graph API authentication automatically. You do NOT set Authorization headers — the MCP server injects them from its configured environment:

- **Path B (SAP UI)**: App-level Graph API token configured in MCP server environment (`GRAPH_APP_TOKEN`)
- **Path C (Alevate UI)**: Delegated `X-Graph-Token` passed from the browser via CodeMie header propagation

You call the tools by name. Authentication is transparent.

---

## Tool: `get_email`

Fetches a single email by its Graph API message ID.

**When to use**: Always call this first when you receive a `message_id`. This retrieves the email body, sender, subject, and metadata.

**Parameters**:
```json
{
  "message_id": "AAMkAGI2..."
}
```

**Returns**:
```json
{
  "id": "AAMkAGI2...",
  "subject": "Re: Invoice INV-2024-001",
  "from": {
    "emailAddress": { "name": "John Smith", "address": "j.smith@customer.com" }
  },
  "toRecipients": [...],
  "body": {
    "contentType": "text",
    "content": "<full email body text>"
  },
  "bodyPreview": "<first 255 characters>",
  "receivedDateTime": "2024-03-10T14:22:00Z",
  "conversationId": "AAQkAGI2...",
  "conversationIndex": "...",
  "hasAttachments": false,
  "importance": "normal",
  "isRead": false
}
```

**Key fields to extract**:
- `body.content` → `email_body` in context store
- `from.emailAddress.address` → sender email
- `from.emailAddress.name` → sender name
- `subject` → email subject
- `receivedDateTime` → received_at timestamp
- `conversationId` → use this as `thread_id` for the next call
- `hasAttachments` → flag for ReviewPresenter attachment warning

---

## Tool: `get_thread`

Fetches all emails in a conversation thread.

**When to use**: After `get_email`, use the `conversationId` to fetch the full thread history for ThreadSummarizer.

**Parameters**:
```json
{
  "thread_id": "AAQkAGI2..."
}
```

**Returns**:
```json
{
  "id": "AAQkAGI2...",
  "emails": [
    {
      "id": "...",
      "subject": "...",
      "from": { "emailAddress": { "name": "...", "address": "..." } },
      "body": { "contentType": "text", "content": "..." },
      "receivedDateTime": "...",
      "sentDateTime": "..."
    }
  ],
  "total_count": 3
}
```

**Key fields to extract**:
- `emails` → `thread_emails` array in context store (pass to ThreadSummarizer)
- `total_count` → helps ThreadSummarizer know if progressive summarization is needed

---

## Tool: `search_emails`

Searches emails using KQL (Keyword Query Language).

**When to use**: Only when you need to find emails by content or metadata without a known message ID. Not needed in the standard pipeline — use `get_email` and `get_thread` instead.

**Important**: This tool requires the `ConsistencyLevel: eventual` header, which the MCP server adds automatically when this tool is invoked.

**Parameters**:
```json
{
  "query": "subject:'Invoice INV-2024-001' from:customer@example.com",
  "folder": "inbox",
  "top": 10
}
```

---

## Tool: `get_attachments`

Fetches attachment metadata (not content) for an email.

**When to use**: When `get_email` returns `hasAttachments: true`, call this to get attachment names and types for the ReviewPresenter to surface to the human approver.

**Parameters**:
```json
{
  "message_id": "AAMkAGI2..."
}
```

**Returns**:
```json
{
  "attachments": [
    {
      "id": "...",
      "name": "goods_receipt.pdf",
      "contentType": "application/pdf",
      "size": 204800
    }
  ]
}
```

**Note**: Attachment content is not analyzed by the AI pipeline (Phase 1 scope). Attachment metadata is passed to ReviewPresenter as a warning indicator.

---

## Standard Fetch Sequence

For every processing run, execute in this exact order:

```
Step 1: get_email(message_id)
   → Extract: email body, sender, subject, received_at, conversationId, hasAttachments

Step 2: get_thread(conversationId from Step 1)
   → Extract: full thread_emails array

Step 3 (conditional): get_attachments(message_id) if hasAttachments=true
   → Extract: attachment names and types for review package warning

Step 4: Store in context:
   {
     "email": { from, subject, body, received_at },
     "email_body": "<body text>",
     "thread_emails": [...],
     "thread_id": "<conversationId>",
     "has_attachments": true/false,
     "attachment_metadata": [...]
   }

Step 5: Pass context to ThreadSummarizer
```

---

## Error Handling

| Error | Meaning | Action |
|-------|---------|--------|
| `ERR_GRAPH_TOKEN_EXPIRED` | App token expired | Retry — token auto-refreshes; if persistent, log and escalate |
| `ERR_MESSAGE_NOT_FOUND` (404) | message_id doesn't exist or no access | Log error; report to audit; do not proceed |
| `ERR_RATE_LIMITED` (429) | Graph API rate limit hit | Respect `Retry-After` header; backoff and retry |
| `ERR_MAILBOX_NOT_FOUND` | Mailbox not accessible | Check mailbox permissions; escalate to ops team |
| MCP tool timeout | MCP server unresponsive | Retry once; if still failing, surface error to human review |

---

## Multi-Message Processing

When SAP UI passes multiple message IDs (e.g., `message_ids: ["msg-1", "msg-2", "msg-3"]`):

```
For each message_id in message_ids:
  1. Call get_email(message_id)
  2. Call get_thread(conversationId)

Then:
  - If all share the same conversationId → single thread, one pipeline run
  - If different conversationIds → multiple independent pipeline runs (one per thread)
```

---

## PII Handling (ADR-007)

The MCP server applies PII controls based on `PII_RESPONSE_LEVEL` configuration:
- `full`: Return all email fields including names and email addresses
- `minimal`: Return metadata only; body is omitted
- `redacted`: Microsoft Presidio redacts PII from body, subject, and address fields before returning

The default for the SAP path is `full` (email content needed for classification). Do not request redaction unless specifically required for the deployment environment.
