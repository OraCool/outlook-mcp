# Orchestrator — CodeMie Assistant

## Configuration

| Field                   | Value                                                                                                                                                                                                                |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Name**                | `Orchestrator`                                                                                                                                                                                                       |
| **Slug**                | `ar-orchestrator`                                                                                                                                                                                                    |
| **Description**         | Entry point for the AR email pipeline. Receives message_id(s) from SAP UI / Alevate UI, calls Outlook MCP tools to fetch email content and thread history, then initialises the context store for downstream agents. |
| **Model**               | `claude-sonnet-4-6`                                                                                                                                                                                                  |
| **Temperature**         | `0`                                                                                                                                                                                                                  |
| **System Instructions** | See below                                                                                                                                                                                                            |
| **Skills**              | Attach: `ar-mcp-tools`                                                                                                                                                                                               |

---

## Responsibility

Entry point for the AR email pipeline. Receives one or more email message IDs, calls Outlook MCP tools to fetch email content and full thread history, and outputs a structured JSON object that initialises the context store for all downstream agents.

## Input

| Key | Source | Required |
|-----|--------|----------|
| `message_id` / `message_ids` | Trigger payload | Yes — one or more Graph message IDs |
| `graph_token` | Trigger payload (Path B / Path C) | Yes for MCP auth — not needed for Path A (webhook) |
| `customer_id` | Trigger payload | No |
| `customer_context` | Trigger payload | No |

---

## System Instructions

```
You are the Orchestrator for the AR Email Management pipeline.

Your sole responsibility is to receive one or more email message IDs, fetch the email content and
thread history from Microsoft Outlook using MCP tools, and output the result as a structured JSON
object so the pipeline can continue.

## How to fetch

Follow the Standard Fetch Sequence in the ar-mcp-tools skill exactly — including tool parameters,
field extraction, multi-message grouping, and error handling.

## Output Schema

On success:
{
  "message_id": "<primary message ID>",
  "email": {
    "from": "<sender email address>",
    "sender_name": "<sender display name>",
    "subject": "<email subject>",
    "body": "<full email body text>",
    "received_at": "<ISO 8601 timestamp>"
  },
  "email_body": "<full email body text — duplicate for convenience>",
  "thread_id": "<conversationId>",
  "thread_emails": [ /* array of all emails in thread, oldest first */ ],
  "has_attachments": false,
  "attachment_metadata": [ /* array of {name, contentType, size} or empty */ ]
}

On error:
{
  "error": true,
  "error_code": "<see ar-mcp-tools skill for full error code list>",
  "message_id": "<message_id>",
  "message": "<error description>"
}

## Rules

- Do not classify, summarize, or interpret the email content. Fetch and structure only.
- Do not fabricate email content. If a tool call fails, report the error — do not guess the content.
- Output only valid JSON. No explanatory text before or after the JSON object.
```

---

## MCP Server Setup

The Outlook MCP server is attached to this assistant in the **CodeMie assistant UI** (not in the workflow YAML).

### Steps

1. Open **Assistants → Orchestrator → Edit**
2. Scroll to **Available tools** → expand **External tools**
3. Click **Manual Setup** → switch to **JSON format**
4. Paste the following and click **Add Server**:

```json
{
  "name": "outlook-mcp",
  "description": "Outlook / Graph API tools for AR email fetching",
  "url": "https://YOUR_OUTLOOK_MCP_SERVER/mcp",
  "type": "streamable-http",
  "headers": {
    "X-Graph-Token": "{{graph_token}}"
  },
  "resolve_dynamic_values_in_arguments": true,
  "tools_tokens_size_limit": 10000
}
```

5. Replace `https://YOUR_OUTLOOK_MCP_SERVER/mcp` with the actual deployed URL
6. Click **Test Integration** to verify the connection, then **Save**

### Available tools after setup

| Tool | Purpose |
|------|---------|
| `get_email` | Fetch a single email by Graph message ID (full body + metadata) |
| `get_thread` | Fetch all emails in a conversation thread |
| `get_attachments` | List attachment metadata for a message |
| `search_emails` | KQL search across the mailbox |

> **`X-Graph-Token`**: CodeMie passes the `graph_token` value from the workflow context store into this header on each MCP call. It must be present in the trigger payload (Path B / Path C). For Path A (webhook), no token is needed — remove the `headers` block.

---

## Usage Pattern

**Pattern A — Workflow-based pipeline** (this file)

This assistant is used as the `fetch-email` entry state in the CodeMie workflow (`workflow.md`). The workflow engine drives all subsequent states — this assistant only fetches and structures email data. It does not call any downstream agents.

For the sub-assistant orchestration pattern (Pattern B), see [`00-orchestrator-multi-agent.md`](00-orchestrator-multi-agent.md).

---

## Notes

- The Orchestrator is the **only** assistant that calls MCP tools — all other agents work purely from context store data.
- The `ar-mcp-tools` skill is the authoritative reference for tool parameters, response schemas, fetch sequence, error codes, and PII handling. Follow it exactly.
- On error (`error == true`), the workflow terminates at the `end` state. No downstream agents run.
- `email_body` is a convenience duplicate of `email.body` — both are set so downstream agents can reference either key.
- For multi-message processing: if all `message_ids` share the same `conversationId`, treat as one thread; otherwise output separate `pipeline_runs[]` entries.
