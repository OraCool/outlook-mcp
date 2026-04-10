# AR Email Management — CodeMie Workflow

## How to create

Navigate to **Workflows → + Create Workflow** → **Workflow Config → YAML tab** and paste the YAML below.

## How context flows between states

CodeMie's context store is a key-value store that persists across all states. When an assistant outputs valid JSON, **all root-level keys automatically become `{{variable}}` placeholders** available in every subsequent state. No manual wiring needed — structured JSON output from each agent populates the shared context.

## State flow

```
fetch-email (Orchestrator)
  ↓ error? → end
  ↓
summarize-thread (ThreadSummarizer)
  ↓
classify-email (EmailClassifier)
  ↓ category in {ESCALATION_LEGAL, UNCLASSIFIED, AUTO_REPLY, INTERNAL_NOTE}?
  ├─ yes → route-actions-nodraft (ActionRouter, has_draft_response=false)
  │            ↓
  └─ no  → draft-response (ResponseDrafter)
               ↓
           route-actions (ActionRouter, has_draft_response=true)
               ↓ (both paths join here)
           present-review (ReviewPresenter)
               ↓
           human-approval [interrupt_before=true]
               ↓
           end
```

---

## Complete Workflow YAML

> Before pasting, replace all `REPLACE_WITH_*_ID` placeholders with the actual CodeMie assistant IDs from Phase 4, and replace the MCP server URL.

```yaml
# ============================================================
# AR Email Management Pipeline
# Orchestrator (MCP fetch) → ThreadSummarizer → EmailClassifier
#   → ResponseDrafter (cond.) → ActionRouter
#   → ReviewPresenter → Human Approval
#
# Trigger: SAP UI / Alevate UI passes message_id(s) to CodeMie
# MCP: Orchestrator fetches email content from Outlook
# ADR-002: Human-in-the-loop (all actions require approval)
# ADR-008: Multi-label classification (categories[] array)
# ============================================================

messages_limit_before_summarization: 25
tokens_limit_before_summarization: 50000
recursion_limit: 50
max_concurrency: 1

assistants:
  # ── Entry point: fetches email from Outlook via MCP ───────
  # NOTE: The Outlook MCP server is configured in the Orchestrator ASSISTANT UI
  # (Available tools → External tools → Manual Setup), NOT here in the workflow YAML.
  # See assistants/00-orchestrator.md → MCP Server Setup for the exact steps.
  - id: orchestrator
    assistant_id: REPLACE_WITH_ORCHESTRATOR_ID
    model: claude-sonnet-4-6
    temperature: 0

  - id: thread-summarizer
    assistant_id: REPLACE_WITH_THREAD_SUMMARIZER_ID
    model: claude-sonnet-4-6
    temperature: 0

  - id: email-classifier
    assistant_id: REPLACE_WITH_EMAIL_CLASSIFIER_ID
    model: claude-sonnet-4-6
    temperature: 0

  - id: response-drafter
    assistant_id: REPLACE_WITH_RESPONSE_DRAFTER_ID
    model: claude-sonnet-4-6
    temperature: 0.3

  - id: action-router
    assistant_id: REPLACE_WITH_ACTION_ROUTER_ID
    model: claude-sonnet-4-6
    temperature: 0

  - id: review-presenter
    assistant_id: REPLACE_WITH_REVIEW_PRESENTER_ID
    model: claude-sonnet-4-6
    temperature: 0

states:
  # ── Step 0: Orchestrator — fetch email from Outlook via MCP
  - id: fetch-email
    assistant_id: orchestrator
    task: |
      Fetch the email and its thread history from Outlook.
      Message ID: {{message_id}}
      Use the get_email tool to fetch the email, then get_thread using the conversationId.
      If hasAttachments is true, also call get_attachments.
      Output structured JSON with the email content ready for ThreadSummarizer.
    resolve_dynamic_values_in_prompt: true
    output_schema: |
      {
        "type": "object",
        "properties": {
          "email":               {"type": "object"},
          "email_body":          {"type": "string"},
          "thread_id":           {"type": "string"},
          "thread_emails":       {"type": "array"},
          "has_attachments":     {"type": "boolean"},
          "attachment_metadata": {"type": "array"}
        },
        "required": ["email", "email_body", "thread_id", "thread_emails"]
      }
    next:
      # Check for fetch error before continuing
      condition:
        expression: "error == true"
        then: end
        otherwise: summarize-thread

  # ── Step 1: Thread Summarization ──────────────────────────
  - id: summarize-thread
    assistant_id: thread-summarizer
    task: |
      Summarize the email thread for email {{message_id}}.
      Thread emails: {{thread_emails}}
      Existing summary (if any): {{existing_summary}}
      Customer context: {{customer_context}}
    resolve_dynamic_values_in_prompt: true
    output_schema: |
      {
        "type": "object",
        "properties": {
          "summary":          {"type": "string"},
          "key_facts":        {"type": "array"},
          "open_items":       {"type": "array"},
          "sentiment_trend":  {"type": "string"},
          "thread_age_days":  {"type": "number"},
          "total_emails":     {"type": "number"}
        },
        "required": ["summary", "key_facts", "open_items", "sentiment_trend"]
      }
    next:
      state_id: classify-email

  # ── Step 2: Email Classification ──────────────────────────
  - id: classify-email
    assistant_id: email-classifier
    task: |
      Classify the following email.
      Email: {{email}}
      Thread summary: {{summary}}
      Customer ID: {{customer_id}}
    resolve_dynamic_values_in_prompt: true
    output_schema: |
      {
        "type": "object",
        "properties": {
          "category":       {"type": "string"},
          "sub_category":   {},
          "categories":     {"type": "array"},
          "confidence":     {"type": "number"},
          "priority":       {"type": "string"},
          "language":       {"type": "string"},
          "intent":         {"type": "object"},
          "reasoning":      {"type": "string"},
          "extracted_data": {"type": "object"},
          "suggested_actions": {"type": "array"},
          "escalation":     {}
        },
        "required": ["category", "confidence", "reasoning", "extracted_data"]
      }
    next:
      # Skip ResponseDrafter for no-draft categories (ADR-002 / Override Rules 1-2)
      condition:
        expression: "category in ('ESCALATION_LEGAL', 'UNCLASSIFIED', 'AUTO_REPLY', 'INTERNAL_NOTE')"
        then: route-actions-nodraft
        otherwise: draft-response

  # ── Step 3a: Response Drafting (draft path only) ──────────
  - id: draft-response
    assistant_id: response-drafter
    task: |
      Draft a customer response for this email.
      Category: {{category}}
      Sub-category: {{sub_category}}
      Confidence: {{confidence}}
      Intent: {{intent}}
      Thread summary: {{summary}}
      Customer context: {{customer_context}}
      Invoice data: {{invoice_data}}
      SAP template: {{sap_template}}
      Original email body: {{email_body}}
    resolve_dynamic_values_in_prompt: true
    output_schema: |
      {
        "type": "object",
        "properties": {
          "draft_subject":           {"type": "string"},
          "draft_body":              {"type": "string"},
          "tone":                    {"type": "string"},
          "template_used":           {},
          "personalization_applied": {"type": "boolean"},
          "word_count":              {"type": "number"},
          "language":                {"type": "string"},
          "has_draft_response":      {"type": "boolean"},
          "warnings":                {"type": "array"}
        },
        "required": ["has_draft_response"]
      }
    next:
      state_id: route-actions

  # ── Step 3b: ActionRouter — no-draft path ─────────────────
  # has_draft_response=false is explicit in the task prompt
  - id: route-actions-nodraft
    assistant_id: action-router
    task: |
      Route actions for this email. No draft was generated (category requires no automated response).
      Category: {{category}}
      Sub-category: {{sub_category}}
      Extracted data: {{extracted_data}}
      Customer ID: {{customer_id}}
      has_draft_response: false
    resolve_dynamic_values_in_prompt: true
    output_schema: |
      {
        "type": "object",
        "properties": {
          "actions":        {"type": "array"},
          "approval_route": {"type": "string"},
          "reasoning":      {"type": "string"}
        },
        "required": ["actions", "approval_route"]
      }
    next:
      state_id: present-review

  # ── Step 4: ActionRouter — draft path ─────────────────────
  - id: route-actions
    assistant_id: action-router
    task: |
      Route actions for this email.
      Category: {{category}}
      Sub-category: {{sub_category}}
      Extracted data: {{extracted_data}}
      Customer ID: {{customer_id}}
      has_draft_response: {{has_draft_response}}
    resolve_dynamic_values_in_prompt: true
    output_schema: |
      {
        "type": "object",
        "properties": {
          "actions":        {"type": "array"},
          "approval_route": {"type": "string"},
          "reasoning":      {"type": "string"}
        },
        "required": ["actions", "approval_route"]
      }
    next:
      state_id: present-review

  # ── Step 5: ReviewPresenter ───────────────────────────────
  - id: present-review
    assistant_id: review-presenter
    task: |
      Assemble the review package for human approval.
      Email ID: {{message_id}}
      Original email: {{email}}
      Classification: category={{category}}, confidence={{confidence}}, reasoning={{reasoning}}
      Thread summary: {{summary}}
      Draft subject: {{draft_subject}}
      Draft body: {{draft_body}}
      Draft tone: {{tone}}
      Proposed actions: {{actions}}
      Approval route: {{approval_route}}
    resolve_dynamic_values_in_prompt: true
    output_schema: |
      {
        "type": "object",
        "properties": {
          "review_package": {"type": "object"}
        },
        "required": ["review_package"]
      }
    next:
      state_id: human-approval

  # ── Step 6: Human Approval Checkpoint ─────────────────────
  # interrupt_before=true pauses the workflow here.
  # The AR specialist reviews review_package and clicks
  # Continue (approve) or Cancel (reject) in the CodeMie UI.
  # SLA enforcement is handled externally by Alevate workflow
  # engine based on approval_route value.
  - id: human-approval
    assistant_id: review-presenter
    interrupt_before: true
    task: |
      HUMAN APPROVAL REQUIRED — Approval route: {{approval_route}}

      Review package:
      {{review_package}}

      AR Specialist: review the classification, proposed response, and
      system actions above. Click Continue to approve or Cancel to reject.
    resolve_dynamic_values_in_prompt: true
    next:
      state_id: end
```

---

## Trigger Payloads

All root-level keys in the payload are automatically available as `{{variable}}` in every state.

### Path B — SAP UI

SAP UI passes the message ID and `X-Graph-Token` (Microsoft Entra access token). The token identifies the user and their mailbox — without it the MCP Server cannot authenticate against the correct inbox.

```json
{
  "message_id": "msg-abc123",
  "graph_token": "<entra-access-token>",
  "customer_id": "CUST-001",
  "customer_context": {
    "company_name": "Acme GmbH",
    "ar_balance": "EUR 42,000",
    "ar_aging_bucket": "30-60 days"
  },
  "invoice_data": {
    "invoice_number": "INV-2024-001",
    "amount": 42000,
    "currency": "EUR",
    "due_date": "2024-02-28",
    "status": "OVERDUE"
  },
  "sap_template": null,
  "existing_summary": null
}
```

> `email`, `email_body`, `thread_emails`, `thread_id` are **not** in the payload — the Orchestrator populates them via MCP tool calls using `graph_token`.

### Path C — Alevate UI

Identical structure to Path B. `graph_token` is acquired via MSAL.js PKCE in the browser rather than via the SAP/Entra integration.

```json
{
  "message_id": "msg-abc123",
  "graph_token": "<entra-access-token>",
  "customer_id": "CUST-001",
  "customer_context": { "company_name": "Acme GmbH", "ar_balance": "EUR 42,000" },
  "invoice_data": { "invoice_number": "INV-2024-001", "amount": 42000, "currency": "EUR" },
  "sap_template": null,
  "existing_summary": null
}
```

### Path A — Webhook (Email Ingestion Service)

Email content is pre-fetched by the Email Ingestion Service. No `graph_token` needed — the MCP step is skipped.

```json
{
  "message_id": "msg-abc123",
  "email": {
    "from": "ap@customer.com",
    "sender_name": "John Smith",
    "subject": "Re: Invoice INV-2024-001",
    "body": "<full email body>",
    "received_at": "2024-03-10T14:22:00Z"
  },
  "email_body": "<full email body>",
  "thread_id": "thread-xyz",
  "thread_emails": [],
  "customer_id": "CUST-001",
  "customer_context": { "company_name": "Acme GmbH", "ar_balance": "EUR 42,000" },
  "invoice_data": { "invoice_number": "INV-2024-001", "amount": 42000, "currency": "EUR" },
  "sap_template": null,
  "existing_summary": null
}
```

---

## Approval SLA Configuration

Configure SLA enforcement externally in the Alevate workflow engine using the `approval_route` value from the review package.

| Route | SLA | Escalation target |
|-------|-----|-------------------|
| STANDARD | 4 hours | Supervisor |
| PRIORITY | 1 hour | Supervisor |
| SUPERVISOR | 30 minutes | Legal / senior management |
| LEGAL | 15 minutes | Legal team |

> CodeMie does not enforce timeouts natively. Never auto-approve on timeout — ADR-002 requires human approval for all actions.
