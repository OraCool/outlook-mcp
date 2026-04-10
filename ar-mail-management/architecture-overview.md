# AR Email Management — Architecture Overview

## Executive Summary

The AR Email Management solution is an AI-powered decision-support layer that automates the triage, classification, and response drafting of inbound Accounts Receivable emails. It connects to the AR team's Microsoft Outlook inbox via the Graph API, processes each email through a multi-agent pipeline (classification, summarization, drafting, routing), and presents AI-generated recommendations to a human approver in the Serrala SAP or Alevate UI.

The system addresses a concrete operational problem: AR teams spend 60-70% of their time on repetitive email handling — reading, categorizing, and drafting replies for routine scenarios like payment reminders, dispute acknowledgements, and extension requests. By automating the cognitive work while keeping humans in the decision loop, the solution targets a reduction in average handling time (AHT) from minutes to seconds per email, while maintaining full audit trail and compliance.

The architecture is built on CodeMie's AI engine, which provides Assistants API, Workflows with PAUSED state for human approval, and A2A (agent-to-agent) chaining for multi-step pipelines. Two integration paths are supported: Alevate (interactive browser UI + headless SDK API via PingOne JWT) and SAP (headless-only via PAT Gateway token exchange).

No email is sent, no ERP record is updated, and no account is escalated without explicit human approval.

---

## System Boundaries

### In Scope

- **Email ingestion**: Detecting new emails in the AR team's Outlook inbox via Microsoft Graph API (webhook or polling)
- **Email classification**: Categorizing emails into a 15-category taxonomy with confidence scoring
- **Intent extraction**: Identifying what the customer is stating or requesting, and what action is required
- **Thread summarization**: Reconstructing and summarizing email thread context for long conversations
- **Response drafting**: Generating reply emails using SAP correspondence templates combined with AI-generated content
- **Action routing**: Mapping classifications to SAP/Alevate actions (log dispute, update payment date, etc.)
- **Human approval**: Presenting AI recommendations to approvers in SAP or Alevate UI
- **Audit logging**: Recording every classification, draft, action, and approval decision
- **Completeness tracking**: Ensuring every email thread has a logged outcome

### Out of Scope

- **Payment processing**: The system does not initiate, process, or reconcile payments
- **ERP updates beyond logging**: The system recommends SAP/Alevate actions but does not execute write operations to the ERP autonomously — all writes require human approval and are executed by the ERP system after approval
- **Direct customer communication without approval**: No email is sent to a customer without explicit human approval
- **Attachment processing**: Attachments are not analyzed by the AI pipeline (future enhancement); invoice-related attachments are passed through to the approval UI for human review
- **Credit scoring or risk assessment**: The system categorizes emails and suggests actions but does not assess customer creditworthiness
- **Outbound campaign management**: The system handles inbound email responses and sends approved replies; it does not generate outbound collection campaigns

---

## Architecture Principles


| Principle                               | Description                                                                                                            | Rationale                                                                                                                   |
| --------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| **Human-in-the-loop always**            | Every AI-generated output passes through human approval before any external action is taken                            | Regulatory compliance (EU AI Act), risk mitigation, customer relationship protection                                        |
| **No autonomous actions**               | The system recommends but never executes — it is a decision-support layer, not an autonomous agent                     | Business requirement: AR team retains full control over customer communication and ERP updates                              |
| **Audit everything**                    | Every classification, draft, action, and approval decision is logged with reasoning, confidence, and approver identity | SOC 2 compliance, 7-year retention for financial records, operational transparency                                          |
| **Idempotent processing**               | Reprocessing the same email produces the same result without duplicate actions or drafts                               | Resilience: retries after failures must be safe; Graph API message ID is the deduplication key                              |
| **Graceful degradation**                | When external systems are unavailable (SAP, Outlook, LLM), the system degrades gracefully rather than failing silently | Operational continuity: queued processing, cached context, human fallback                                                   |
| **Separation of concerns**              | Each agent has a single, well-defined responsibility with strict input/output contracts                                | Maintainability: agents can be updated, tested, and scaled independently                                                    |
| **Least privilege**                     | Each component accesses only the data and systems it needs                                                             | Security: Email Ingestion Service has Graph API access but not SAP; ResponseDrafter has SAP templates but not raw email PII |
| **PII minimization at source (Path C)** | The Outlook MCP Server can redact sampling payloads (Presidio, opt-in) and return minimized/redacted tool JSON         | GDPR Art. 5(1)(c); see [ADR-007](decisions/ADR-007-mcp-pii-redaction-strategy.md) and `data-privacy.md`                     |


---

## High-Level Architecture

The end-to-end flow from email arrival to approved action:

```
1. Email arrives in Outlook inbox
          |
          v
2. Graph API webhook/polling detects new email
          |
          v
3. Email Ingestion Service fetches email content and metadata
   - Extracts: sender, subject, body (text), thread references, timestamps
   - Looks up customer identifier from sender address
   - Fetches thread history (previous emails in conversation)
          |
          v
4. ThreadSummarizer reconstructs thread context
   - Receives full thread history
   - Produces concise summary for context injection
   - Progressive summarization for threads exceeding context window
          |
          v
5. EmailClassifier categorizes and extracts intent
   - Receives: new email + thread summary + customer context
   - Outputs: category, confidence score (0-1), extracted intent, reasoning
   - If confidence < 0.75: routes to UNCLASSIFIED with escalation flag
          |
          v
6. ResponseDrafter generates reply
   - Receives: classification + intent + customer data + SAP correspondence template
   - Produces: draft email reply in approved tone, or "no reply needed" signal
   - Anchors response to SAP template structure where applicable
          |
          v
7. ActionRouter determines SAP/Alevate action
   - Receives: classification + intent
   - Outputs: action type (e.g., "log_dispute", "update_payment_date"),
     action parameters, target system (SAP or Alevate)
          |
          v
8. ReviewPresenter formats output for approval UI
   - Assembles: original email, thread summary, classification + confidence,
     reasoning, draft reply, suggested action
   - Formats for SAP UI or Alevate UI depending on calling path
          |
          v
9. CodeMie workflow enters PAUSED state — awaiting human approval
          |
          v
10. Human reviews in SAP or Alevate UI
    - Approves (action executed as-is)
    - Edits (modifies draft/action, then approves)
    - Rejects (no action taken, logged as rejected with reason)
          |
          v
11. Approved action executed
    - Email sent via Graph API (if reply was approved)
    - SAP/Alevate updated (if system action was approved)
    - Audit trail updated with final outcome and approver identity
```

---

## Component Architecture

### Email Ingestion Service

**Type**: External microservice (not a CodeMie component)
**Decision**: [ADR-005 Option B](decisions/ADR-005-outlook-integration-pattern.md) — External microservice as Graph API bridge

The Email Ingestion Service is a dedicated microservice deployed on AKS that serves as the bridge between Microsoft Outlook and the CodeMie AI pipeline. It decouples email ingestion from AI processing, enabling both the Alevate and SAP calling paths to share the same ingestion logic.

**Responsibilities**:

- Register and maintain Graph API webhook subscriptions for new-email detection (with automated 3-day renewal)
- Fetch email content and metadata via Graph API on webhook notification
- Extract thread references (In-Reply-To, References headers) for thread reconstruction
- Look up customer identifier from sender email address (via Alevate or SAP customer master)
- Assemble context package: email content, thread history, customer metadata
- Submit assembled context to CodeMie pipeline via A2A API (`POST /v1/a2a/assistants/{assistant_id}`)
- Implement deduplication by Graph API message ID (idempotency)
- Handle Graph API rate limiting with exponential backoff
- Polling fallback when webhook subscription is unhealthy

**Authentication**:

- Graph API: OAuth 2.0 application permissions (separate from PingOne identity)
- CodeMie: Service identity via PingOne JWT (machine-to-machine token)

### EmailClassifier

**Type**: CodeMie assistant
**Decision**: [ADR-001](decisions/ADR-001-email-categorization-approach.md) — Hybrid rule+LLM classification

The EmailClassifier receives an email (with thread summary and customer context) and produces a structured classification output.

**15-Category Taxonomy**:


| Category                | Description                                                              |
| ----------------------- | ------------------------------------------------------------------------ |
| `PAYMENT_REMINDER_SENT` | We sent a reminder; awaiting customer response                           |
| `INVOICE_NOT_RECEIVED`  | Customer claims they never received the invoice                          |
| `INVOICE_DISPUTE`       | Customer disputes the amount or validity of an invoice                   |
| `PAYMENT_PROMISE`       | Customer commits to paying by a specific date                            |
| `PAYMENT_CONFIRMATION`  | Customer confirms payment has been sent                                  |
| `EXTENSION_REQUEST`     | Customer requests more time to pay                                       |
| `PARTIAL_PAYMENT_NOTE`  | Customer indicates only partial payment will be made                     |
| `ESCALATION_LEGAL`      | Email contains threatening or legal language                             |
| `INTERNAL_NOTE`         | Internal team communication within the thread                            |
| `BALANCE_INQUIRY`       | Customer asks about outstanding balance or payment status                |
| `CREDIT_NOTE_REQUEST`   | Customer requests a credit note or adjustment                            |
| `REMITTANCE_ADVICE`     | Customer sends remittance details for matching                           |
| `BILLING_UPDATE`        | Customer requests change of billing address, contact, or payment details |
| `AUTO_REPLY`            | Automated out-of-office reply, delivery receipt, or read receipt         |
| `UNCLASSIFIED`          | Intent unclear; requires human review                                    |


**Classification approach**: Hybrid rule+LLM. A rule layer handles deterministic patterns (out-of-office auto-replies, known legal keywords) before the LLM processes ambiguous cases. This improves latency for obvious cases and provides a fallback when the LLM is unavailable.

**Output**: JSON with `category`, `confidence` (0-1), `intent_summary`, `reasoning`, `escalation_flag`.

### ThreadSummarizer

**Type**: CodeMie assistant
**Decision**: [ADR-003](decisions/ADR-003-thread-context-management.md) — Progressive summarization

The ThreadSummarizer handles the challenge of long email threads that may exceed the LLM context window. It produces a concise summary that captures the key facts and state of the conversation.

**Approach**: Progressive summarization — each new email in a thread is summarized incrementally against the existing thread summary, rather than re-processing the entire thread from scratch. This keeps token usage bounded regardless of thread length.

**Output**: JSON with `thread_summary` (narrative), `key_facts` (structured: customer name, invoice references, amounts, dates, commitments), `thread_state` (current status of the AR case), `email_count` (number of emails in thread).

### ResponseDrafter

**Type**: CodeMie assistant

The ResponseDrafter generates a reply email (or determines that no reply is needed) based on the classification, intent, customer context, and SAP correspondence templates.

**Template integration**: SAP correspondence templates are retrieved from SAP and injected as context. The AI uses the template structure and language as an anchor, adding case-specific details. This ensures consistency with existing organizational communication standards while personalizing the response.

**Output**: JSON with `reply_text` (the draft email), `template_used` (SAP template ID if applicable), `tone` (formal/empathetic/neutral), `action_type` ("reply" / "no_reply_needed"), `language` (detected language of the original email).

**Constraints**:

- Must never include internal SAP IDs, system references, or AR team notes in customer-facing text
- Must not fabricate invoice amounts, dates, or payment terms — these must come from SAP data
- If insufficient context to draft a reply, outputs `action_type: "no_reply_needed"` with an escalation note

### ActionRouter

**Type**: CodeMie assistant

The ActionRouter maps the email classification and extracted intent to a concrete SAP or Alevate action.

**Action mapping examples**:


| Category               | Action Type                    | Target System | Parameters                                     |
| ---------------------- | ------------------------------ | ------------- | ---------------------------------------------- |
| `INVOICE_DISPUTE`      | `log_dispute`                  | SAP FS2/S4    | invoice_number, dispute_reason, dispute_amount |
| `PAYMENT_PROMISE`      | `update_expected_payment_date` | SAP/Alevate   | invoice_number, promised_date                  |
| `PAYMENT_CONFIRMATION` | `trigger_reconciliation_check` | SAP           | payment_reference, amount                      |
| `EXTENSION_REQUEST`    | `route_extension_approval`     | Alevate       | invoice_number, requested_date, reason         |
| `ESCALATION_LEGAL`     | `escalate_to_legal`            | Alevate       | thread_id, urgency: high                       |


**Output**: JSON with `action_type`, `target_system`, `action_parameters`, `requires_approval` (always true), `priority` (normal/high/urgent).

### ReviewPresenter

**Type**: CodeMie assistant

The ReviewPresenter assembles all outputs from the preceding agents into a single, human-readable review package suitable for display in the SAP or Alevate approval UI.

**Output structure** (presented to human approver):

1. **Original email** — sender, subject, body (truncated if long, with link to full thread)
2. **Thread summary** — from ThreadSummarizer
3. **Classification** — category, confidence score, reasoning
4. **Draft reply** — from ResponseDrafter (editable in the approval UI)
5. **Suggested action** — from ActionRouter (action type, parameters, target system)
6. **Approval options** — Approve / Edit & Approve / Reject (with reason field)
7. **Confidence indicator** — visual indicator (green/yellow/red) based on classification confidence

The ReviewPresenter output must contain enough information for a human approver to make a decision without needing to open the original email separately.

---

## PRD Alignment — Functional Gaps

*Added 2026-04-08. Cross-references the Confluence PRD ([Collections Email Agent](https://serrala.atlassian.net/wiki/spaces/SAA/pages/6333104138), [Basic use case and Fiori UI](https://serrala.atlassian.net/wiki/spaces/SAA/pages/6332284990)) against the architecture and Outlook MCP Server implementation.*

### Taxonomy Alignment

The Confluence PRD defines a 16-category taxonomy with granular dispute subtypes and internal approval categories. The local architecture uses a 15-category taxonomy. These are reconciled in **[ADR-008](decisions/ADR-008-taxonomy-reconciliation.md)** via a hierarchical model: 15 primary categories + `sub_category` field + multi-label `categories` list.

### Functional Gap Matrix


| PRD Requirement                          | Architecture Status                                                         | MCP Implementation Status                                          | Gap                                                                                               |
| ---------------------------------------- | --------------------------------------------------------------------------- | ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------- |
| **Top-level priority (HIGH/MEDIUM/LOW)** | Partially covered: `intent.urgency` is nested inside EmailClassifier output | `ClassificationResult.intent.urgency` exists but is not top-level  | Needs top-level `priority` field in both architecture output schema and MCP model                 |
| **Per-email summary (1-2 sentences)**    | ThreadSummarizer produces thread-level summaries; no per-email summary      | No dedicated summarization tool                                    | New `summarize_email` MCP tool needed; alternatively, add `summary` field to ClassificationResult |
| **AI-generated draft reply**             | ResponseDrafter agent designed (component architecture above)               | `create_draft` creates blank drafts; no AI content generation tool | New `draft_reply` MCP tool needed (sampling-based, returns generated text)                        |
| **Suggested actions (2-4 per email)**    | ActionRouter agent designed (component architecture above)                  | No MCP tool outputs suggested actions                              | New `suggested_actions` field in ClassificationResult or dedicated tool                           |
| **Confidence score (0-1)**               | EmailClassifier outputs `confidence`                                        | `ClassificationResult.confidence` implemented                      | OK — no gap                                                                                       |
| **Language detection**                   | Not addressed                                                               | Not implemented                                                    | New `language` field needed in classification output                                              |
| **Multi-label classification**           | D4 in requirements-review.md chose single-label                             | Single `category` field only                                       | ADR-008 adds `categories` list and `sub_category` field                                           |
| **Thread summarization**                 | ThreadSummarizer agent designed; ADR-003 details progressive summarization  | `get_thread` tool exists but no summary generation                 | New `summarize_thread` MCP tool needed                                                            |
| **Batch processing**                     | Not addressed in architecture                                               | No batch tools                                                     | New `classify_batch` tool needed for operational scale (P1)                                       |
| **Mark as read / move / archive**        | Not addressed                                                               | Not implemented                                                    | `mark_as_read`, `move_email` tools needed (P1)                                                    |
| **Idempotent processing**                | Designed (Graph message ID deduplication)                                   | No deduplication in MCP server                                     | MCP server is stateless; deduplication belongs in Email Ingestion Service or orchestrator         |
| **Near real-time sync (webhooks)**       | ADR-005 designs webhook + polling via Graph API Bridge                      | MCP is pull-only (by design — ADR-006 path)                        | No gap: webhook path is separate infra (Graph API Bridge); MCP serves the on-demand pull path     |
| **Audit trail**                          | Designed (PostgreSQL audit store)                                           | No audit persistence in MCP server                                 | MCP server is stateless; audit belongs in orchestrator/Core — no MCP gap                          |


### PRD JSON Output Schema vs MCP ClassificationResult

The Confluence PRD defines a target JSON output schema that the AI Agent must produce. Comparing to the MCP `ClassificationResult`:


| PRD Field                | MCP Equivalent                       | Status                                       |
| ------------------------ | ------------------------------------ | -------------------------------------------- |
| `emailId`                | `email_id`                           | OK                                           |
| `threadId`               | Not in ClassificationResult          | **Gap** — add `thread_id`                    |
| `sender.company`         | Not extracted                        | **Gap** — add `sender_company`               |
| `category`               | `category`                           | OK                                           |
| `priority`               | `intent.urgency` (nested)            | **Gap** — needs top-level field              |
| `summary`                | Not in ClassificationResult          | **Gap** — add `summary` field                |
| `reasoning`              | `reasoning`                          | OK                                           |
| `confidence`             | `confidence`                         | OK                                           |
| `entities.invoiceNumber` | `extracted_data.invoice_numbers`     | OK (different format: list vs single)        |
| `entities.amount`        | `extracted_data.disputed_amount`     | Partial — only disputed amount, not general  |
| `entities.currency`      | Not extracted                        | **Gap** — add to `extracted_data`            |
| `entities.dueDate`       | Not extracted (only `promised_date`) | **Gap** — add `due_date` to `extracted_data` |
| `suggestedActions`       | Not in ClassificationResult          | **Gap** — add field                          |
| `draftReply`             | Not in ClassificationResult          | **Gap** — separate `draft_reply` tool        |


---

## Edge Cases and Domain-Specific Risks

*Added 2026-04-08. Supplements the Error Handling and Resilience section with AR-domain-specific edge cases identified during Confluence PRD review.*

### 1. Multi-Invoice Emails (S13)

A single email may reference 3+ invoices with different intended actions: dispute on invoice A, promise to pay on invoice B, copy request for invoice C. The classification pipeline processes one email → one classification result. Without explicit handling, only the dominant intent is captured; secondary intents are lost.

**Mitigation:** The `categories` multi-label list (ADR-008) captures all applicable labels. The ActionRouter must generate **per-invoice action items** when `extracted_data.invoice_numbers` contains multiple entries with different intent signals. The ReviewPresenter must display these as a grouped set for batch approval.

### 2. Mixed-Intent Emails

Same email is both a dispute AND contains a promise to pay. The primary `category` determines routing, but the secondary intent must not be dropped.

**Mitigation:** The `categories` list in ADR-008 captures both labels. The approval UI must present both intents. The ResponseDrafter must address both concerns in the draft reply (acknowledge dispute AND confirm promise).

### 3. Non-English Emails

The Confluence UC page references 5 languages for out-of-office detection (EN, DE, FR, ES, IT). The LLM classifier must handle emails in these languages. Draft replies must match the incoming email's language.

**Mitigation:** Add `language` field to ClassificationResult. The ResponseDrafter prompt must include language-matching instructions. Few-shot examples should include non-English samples for high-volume languages. PII redaction accuracy varies by language (Presidio's English NER is strongest); document known limitations.

### 4. Attachment-Dependent Classification

Dispute evidence or invoice copies may be attached as PDF/image, with the email body containing only a brief reference ("see attached"). The classifier cannot read attachments.

**Mitigation:** `get_attachments` tool provides metadata (filename, size, content-type). The classifier prompt can infer attachment relevance from metadata (e.g., filename contains "invoice" or "dispute"). Full attachment content analysis is out of scope (Phase 1) but should be flagged in the ReviewPresenter output when attachments are present.

### 5. Auto-Reply and Bounce Loops

Sending a reply to an auto-reply may trigger another auto-reply, creating a loop. The system must detect and break these loops.

**Mitigation:** The rule engine (ADR-001) detects auto-reply headers (`X-Auto-Reply`, `Auto-Submitted`). If the system's own outbound email receives an auto-reply, the Email Ingestion Service must check the `In-Reply-To` header against recently sent message IDs and suppress reprocessing. A maximum of 1 auto-reply acknowledgement per thread per 24-hour period should be enforced.

### 6. Long Threads (20+ Messages)

AR email threads spanning weeks may contain 20-50+ messages. Full thread context exceeds the 16K token budget (ADR-003).

**Mitigation:** Progressive summarization (ADR-003) is designed for this. Validation needed: test with real 30+ message threads to confirm summary quality doesn't degrade beyond acceptable levels. Thread summary re-compression should be triggered when assembled context exceeds 12K tokens (leaving 4K for system prompt + output buffer).

### 7. Shared Mailbox Permission Scoping

Application-level permissions (`client_credentials`) see all mailboxes in the tenant. Delegated permissions (Path C, ADR-006) see only the signed-in user's mailbox. If the AR team uses a shared mailbox, the Graph API path differs (`/users/{shared-mailbox-id}/messages` vs `/me/messages`).

**Mitigation:** The Outlook MCP Server currently uses `/me/messages` (delegated). For shared mailbox support, the server must support a configurable mailbox target or accept a `mailbox_id` parameter. This is a future enhancement; document as a known limitation.

### 8. Graph API Rate Limits Under High Volume

Microsoft Graph API enforces per-app rate limits (10,000 requests per 10 minutes per app per tenant for application permissions; lower limits for delegated). Batch classification of 100+ emails could hit these limits.

**Mitigation:** The Email Ingestion Service (ADR-005) must implement exponential backoff with `Retry-After` header respect. The MCP server should expose a configurable `BATCH_CONCURRENCY_LIMIT` for the `classify_batch` tool. Graph API batch requests (`/$batch`) can reduce call count by 20x.

### 9. Stale SAP Correspondence Templates

A SAP correspondence template may be updated between the time the ResponseDrafter generates a draft and the time the human approver reviews it. The draft would reference an outdated template.

**Mitigation:** The ReviewPresenter should display the template version/timestamp used for drafting. The approval UI should re-validate template currency at approval time. If the template has changed, the approver should be offered the option to regenerate the draft with the updated template.

### 10. PII in Non-Body Fields

Email subject lines frequently contain customer names, invoice numbers, and amounts (e.g., "RE: Invoice #12345 - Payment of $50,000 overdue"). Attachment filenames may contain similar PII. The current Presidio redaction in ADR-007 covers body, body_preview, subject, and address fields, but attachment filenames are not redacted in MCP tool responses.

**Mitigation:** Extend the PII redaction scope in the Outlook MCP Server to include attachment metadata (filename field) when `PII_RESPONSE_LEVEL=redacted`. Document that subject-line PII is already covered by the existing redaction implementation.

---

## Integration Architecture

### Alevate Integration Path

```
Alevate Browser UI                    Alevate Headless SDK
       |                                      |
       v                                      v
  PingOne OIDC login              PingOne M2M token exchange
       |                                      |
       v                                      v
  Authorization: Bearer <jwt>       Authorization: Bearer <jwt>
  X-PingOne-Token: <jwt>           X-PingOne-Token: <jwt>
       |                                      |
       +-------- CodeMie Assistants API ------+
                         |
       POST /v1/assistants/{assistantId}/model  (interactive)
       POST /v1/conversations                    (headless)
```

- **Interactive path**: User triggers email review from Alevate browser UI; CodeMie assistant response is displayed inline
- **Headless path**: Automated service (e.g., Email Ingestion Service) calls CodeMie via Alevate SDK API without user interaction
- **Authentication**: PingOne JWT bearer token, propagated via `Authorization` and `X-PingOne-Token` headers (per ADR-002 and ADR-020)

### SAP Integration Path

```
SAP FS2/S4 (on-premise)
       |
       v
  SAP PAT (Personal Access Token)
       |
       v
  PAT Gateway (token exchange)
       |
       v
  CodeMie JWT (short-lived)
       |
       v
  POST /v1/a2a/assistants/{assistant_id}   (A2A endpoint)
```

- **Headless only**: No interactive UI from SAP; all invocations are API-based
- **Authentication**: SAP PAT exchanged for CodeMie JWT via PAT Gateway (per ADR-003)
- **A2A protocol**: JSON-RPC 2.0 request/response over HTTP

### Graph API Integration

```
Email Ingestion Service
       |
       v
  Azure AD App Registration
       |
       v
  OAuth 2.0 client_credentials flow (application permissions)
       |
       v
  Microsoft Graph API
       |
       +-- GET /me/messages (fetch emails)
       +-- POST /subscriptions (webhook registration)
       +-- POST /me/sendMail (send approved replies)
```

- **Authentication**: OAuth 2.0 application permissions via Azure AD app registration — this is a **separate** identity from PingOne
- **Permissions required**: `Mail.Read`, `Mail.Send`, `Mail.ReadWrite` (application-level)
- **The Graph API OAuth token is NOT the same as the PingOne JWT** — these are independent identity systems. The Email Ingestion Service holds the Graph API token; CodeMie uses the PingOne JWT.

### Path C — UI-Triggered Processing via Delegated MCP

**Decision**: [ADR-006](decisions/ADR-006-ui-triggered-email-processing-delegated-mcp.md) — UI-Triggered Email Processing via Delegated MCP

A second trigger path for on-demand processing initiated by the AR specialist directly in the Serrala/Alevate UI. Unlike the automatic webhook push path (Email Ingestion Service), this path is **pull-based**: the user selects a specific email and explicitly requests AI processing.

**When to use:**

- Re-processing a previously skipped or already-handled email
- Processing emails from non-monitored folders or personal mailboxes
- On-demand testing or re-classification of a specific email

**Flow:**

```
1. User selects email in Serrala/Alevate UI
          |
          v
2. UI acquires Microsoft Entra delegated token via MSAL.js PKCE
   (scope: Mail.Read — user's own mailbox access)
          |
          v
3. UI calls CodeMie Assistants API:
   POST /v1/assistants/{id}/chat
   Authorization: Bearer <pingone-jwt>
   X-PingOne-Token: <pingone-jwt>
   X-Graph-Token: <entra-access-token>     ← new header; NOT on MCP_BLOCKED_HEADERS
   {"message": "Process email <msg-id>", "propagate_headers": true}
          |
          v
4. LangGraph ReAct assistant invokes Outlook MCP tool
          |
          v
5. MCP-Connect Bridge relays X-Graph-Token to Outlook MCP Server
   (same mechanism as X-PingOne-Token relay per Multi-Tenancy ADR-012)
          |
          v
6. Outlook MCP Server: Graph API call with delegated token
   GET /me/messages/{id}
   Authorization: Bearer <entra-access-token>
          |
          v
7. Email content returned as MCP tool result → joins standard pipeline
   (ThreadSummarizer → EmailClassifier → ResponseDrafter → ActionRouter → ReviewPresenter)
          |
          v
8. Workflow PAUSED — same approval queue as webhook path
```

**Key differences from the webhook path:**


| Dimension              | Webhook Path (ADR-005)                   | UI-Triggered Path (ADR-006)                   |
| ---------------------- | ---------------------------------------- | --------------------------------------------- |
| Trigger                | Automatic (Graph API webhook)            | User action in Serrala/Alevate UI             |
| CodeMie entry point    | `POST /v1/workflows/{id}/executions`     | `POST /v1/assistants/{id}/chat`               |
| Graph permissions      | Application-level (`client_credentials`) | User-delegated (PKCE, `Mail.Read`)            |
| Email read via         | Email Ingestion Service microservice     | Outlook MCP Server (tool call from assistant) |
| Email send via         | Graph API Bridge (shared mailbox)        | Graph API Bridge (unchanged — shared mailbox) |
| Audit `trigger_source` | `webhook_push`                           | `ui_pull`                                     |


**Authentication summary:**


| System                    | Identity Provider  | Auth Flow                              | Token Carrier                       |
| ------------------------- | ------------------ | -------------------------------------- | ----------------------------------- |
| CodeMie (Path C)          | PingOne            | Browser session (existing Path A)      | `Authorization` + `X-PingOne-Token` |
| Graph API (Path C)        | Microsoft Entra ID | PKCE (MSAL.js, lazy consent)           | `X-Graph-Token`                     |
| Graph API (Path A Bridge) | Microsoft Entra ID | `client_credentials` (service account) | Held by bridge service              |


The `X-Graph-Token` side-channel follows the same design rationale as `X-PingOne-Token` (Multi-Tenancy ADR-012): `Authorization` is blocked at the MCP layer for security; a named custom header is the documented, reviewed propagation mechanism. Both tokens are relayed through CodeMie in-memory only — neither is persisted server-side within the CodeMie platform.

**Outlook MCP PII controls ([ADR-007](decisions/ADR-007-mcp-pii-redaction-strategy.md)):** The Outlook MCP Server can (1) run **Microsoft Presidio** on email JSON **before** it is embedded in MCP sampling for `categorize_email` / `extract_email_data` when `PII_REDACTION_ENABLED` is set, and (2) apply `**PII_RESPONSE_LEVEL`** (`full` / `minimal` / `redacted`) to every mail-related **tool result** so orchestrators receive less raw PII by default in hardened deployments. Details: [data-privacy.md](data-privacy.md) and [diagrams/flows/ar-mail-flow-pii-redaction.mermaid](diagrams/flows/ar-mail-flow-pii-redaction.mermaid).

---

## Data Flow

Step-by-step data transformation through the pipeline:


| Step | Component                                  | Input                                                  | Output                                                                  | Data Sensitivity                                                                                                                                    |
| ---- | ------------------------------------------ | ------------------------------------------------------ | ----------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1    | Graph API webhook                          | New email notification (subscription ID, resource URL) | Trigger signal                                                          | Low (no email content in notification)                                                                                                              |
| 2    | Email Ingestion Service                    | Graph API message resource                             | Structured email object: sender, subject, body, thread refs, timestamps | High (contains PII: email addresses, names, potentially financial data)                                                                             |
| 2b   | Outlook MCP Server (Path C / UI-triggered) | Graph API message resource                             | MCP tool JSON + optional sampling payload                               | High inbound; **outbound** tool payloads and sampling text can be minimized/redacted per [ADR-007](decisions/ADR-007-mcp-pii-redaction-strategy.md) |
| 3    | Email Ingestion Service                    | Sender email address                                   | Customer identifier, customer master data (company name, AR balance)    | Medium (customer business data from SAP)                                                                                                            |
| 4    | ThreadSummarizer                           | Full thread history (all emails in conversation)       | Thread summary: narrative + key facts + thread state                    | Medium (summarized PII, reduced from raw email)                                                                                                     |
| 5    | EmailClassifier                            | New email + thread summary + customer context          | Classification: category, confidence, intent, reasoning                 | Low (structured metadata, no raw PII in output)                                                                                                     |
| 6    | ResponseDrafter                            | Classification + intent + customer data + SAP template | Draft reply text + template reference + tone                            | Medium (customer-facing text, may reference amounts/dates)                                                                                          |
| 7    | ActionRouter                               | Classification + intent                                | Action type + parameters + target system                                | Low (structured action metadata)                                                                                                                    |
| 8    | ReviewPresenter                            | All preceding outputs                                  | Formatted review package for approval UI                                | Medium (aggregated view of all pipeline outputs)                                                                                                    |
| 9    | Approval UI                                | Review package                                         | Human decision: approve/edit/reject + edits + reason                    | Medium (includes human approver identity)                                                                                                           |
| 10   | Execution                                  | Approved action + approved draft                       | Email sent via Graph API + SAP/Alevate updated                          | High (final customer communication + ERP write)                                                                                                     |


---

## Context and Memory Design

### Data Injected Per Agent Call

Each agent in the pipeline receives a specific context package assembled by the Email Ingestion Service and enriched at each pipeline step:


| Agent                | Context Injected                                                                                                                                                                                                                                           |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **ThreadSummarizer** | Full thread history (all emails), customer identifier, previous thread summary (if incremental update)                                                                                                                                                     |
| **EmailClassifier**  | New email body + metadata, thread summary (from ThreadSummarizer), customer master data (company name, AR aging bucket, open invoices count), previous classifications for this thread                                                                     |
| **ResponseDrafter**  | Classification result, extracted intent, customer master data (name, address, account number), relevant invoice details (number, amount, due date, status), SAP correspondence template (retrieved from SAP), previous AI-drafted responses in this thread |
| **ActionRouter**     | Classification result, extracted intent, current SAP/Alevate state for this customer/invoice, available action types for the category                                                                                                                      |
| **ReviewPresenter**  | All preceding outputs (thread summary, classification, draft, action), original email for display, confidence thresholds for visual indicators                                                                                                             |


### Progressive Summarization for Long Threads

Email threads in AR can extend over weeks or months with 20+ messages. The ThreadSummarizer uses progressive summarization to keep token usage bounded:

1. **First email**: Full email is the "summary"
2. **Second email**: Summary of email 1 + full email 2 = new summary
3. **Nth email**: Previous summary + full email N = updated summary

This approach ensures that the summary token count grows logarithmically rather than linearly with thread length. The summary preserves key facts (invoice numbers, amounts, dates, commitments) while compressing conversational filler.

### Maximum Safe Context

- **Assumed context window**: 16K tokens (configurable per LLM provider via LiteLLM)
- **Token budget allocation**:
  - System prompt: ~2K tokens
  - Thread summary: ~4K tokens (capped; triggers re-summarization if exceeded)
  - New email body: ~4K tokens (truncated with notice if exceeded)
  - SAP context (customer data, invoice details, templates): ~3K tokens
  - Output buffer: ~3K tokens
- **Enforcement**: The Email Ingestion Service counts tokens before submission and triggers ThreadSummarizer re-compression if the assembled context exceeds the budget

### Context Assembly Responsibility

The **Email Ingestion Service** is the context assembler:

1. Fetches email content from Graph API
2. Fetches customer master data from SAP/Alevate (cached with 15-minute TTL)
3. Fetches thread history from Graph API (or from audit store for previously processed threads)
4. Calls ThreadSummarizer if thread history exceeds context budget
5. Fetches SAP correspondence template for the expected category (if predictable from thread state)
6. Assembles the full context package
7. Submits to the CodeMie workflow entry point

The CodeMie workflow then injects the appropriate subset of context at each pipeline step — not every agent receives the full context package.

---

## Audit Trail

### What Is Logged

Every step in the pipeline produces an audit record in the PostgreSQL audit store:


| Audit Event           | Fields Logged                                                                                                                                          |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Email received**    | Graph message ID, sender, subject (no body), timestamp, customer identifier, thread ID                                                                 |
| **Classification**    | Category, confidence score, reasoning text, classification model version, processing time (ms)                                                         |
| **Thread summary**    | Summary text (stored for re-use), email count, key facts extracted                                                                                     |
| **Draft generated**   | Full draft text, SAP template ID used, tone, language, model version                                                                                   |
| **Action determined** | Action type, target system, action parameters, priority                                                                                                |
| **Review presented**  | Review package hash, presentation timestamp, target UI (SAP/Alevate)                                                                                   |
| **Approval decision** | Approver identity (PingOne user ID), decision (approve/edit/reject), changes made (diff if edited), rejection reason (if rejected), decision timestamp |
| **Action executed**   | Execution timestamp, Graph API send confirmation (message ID), SAP/Alevate update confirmation, execution status                                       |
| **Error**             | Error type, component, error message, retry count, resolution                                                                                          |


### Audit Record Schema

Each audit record includes:

- `id` (UUID, primary key)
- `thread_id` (Graph conversation ID)
- `message_id` (Graph message ID)
- `event_type` (enum of events above)
- `event_data` (JSONB — event-specific fields)
- `tenant_id` (for multi-tenant isolation)
- `user_id` (PingOne user ID, null for system events)
- `created_at` (timestamp with timezone)
- `processing_pipeline_id` (UUID — correlates all events for a single email processing run)

### Retention

- Audit records: 7 years (legal requirement for financial records)
- Thread summaries: Duration of active AR case + 90 days
- Raw email content: NOT stored in the audit trail (remains in Outlook)

---

## Error Handling and Resilience

### Token Expiry Handling


| Token                 | TTL                             | Refresh Strategy                                                                                |
| --------------------- | ------------------------------- | ----------------------------------------------------------------------------------------------- |
| Graph API OAuth token | 1 hour (default)                | Pre-refresh 5 minutes before expiry; automatic retry with fresh token on 401                    |
| PingOne JWT           | Configurable (typically 1 hour) | Pre-refresh before pipeline start; if expired mid-pipeline, retry current step with fresh token |
| SAP PAT Gateway token | Short-lived                     | PAT Gateway issues fresh JWT per request; no caching                                            |


### Graph API Failures


| Failure                      | Handling                                                                                                                             |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| Rate limiting (429)          | Exponential backoff with jitter; respect `Retry-After` header; queue excess requests                                                 |
| Webhook subscription expired | Automated renewal service runs every 2 days; polling fallback activates within 5 minutes of detected subscription failure            |
| Webhook notification missed  | Polling catch-up runs every 5 minutes as secondary detection mechanism                                                               |
| Email fetch failure          | Retry 3 times with exponential backoff; if persistent, log error and skip (email remains unprocessed in Outlook for next poll cycle) |


### LLM Errors


| Failure                      | Handling                                                                                                                |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| LLM timeout                  | Retry once with same context; if second attempt fails, route to human review with "AI processing unavailable" note      |
| LLM content filter triggered | Log the trigger; route to human review with original email and note that AI could not process                           |
| LLM returns malformed output | Validate output against JSON schema; if invalid, retry once; if still invalid, route to human review                    |
| LLM hallucination (detected) | Confidence scoring acts as partial guard; human approval is the final guard; no fully automated hallucination detection |


### SAP/Alevate Unavailability


| Failure                                | Handling                                                                                                                                 |
| -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| SAP unavailable for customer data      | Use cached customer master data (15-minute TTL cache); if cache miss, proceed with classification only (no drafting) and flag for review |
| SAP unavailable for template retrieval | Draft without SAP template (AI-only draft); flag in review package that template was unavailable                                         |
| Alevate approval UI unavailable        | Queue approved actions for retry; alert operations team; approval backlog visible in monitoring dashboard                                |


---

## Idempotency

### Email Deduplication

The **Graph API message ID** is the primary deduplication key. Before processing any email:

1. Check audit store for existing record with this message ID
2. If found and status is "completed" or "in_progress": skip processing, return existing result
3. If found and status is "failed": retry processing (idempotent — same input, same output)
4. If not found: create new audit record with status "in_progress" and proceed

### Action Deduplication

Each action recommended by the pipeline is assigned an **idempotency key** composed of:

- Graph message ID + action type + action parameters hash

Before executing an approved action:

1. Check if an action with this idempotency key has already been executed
2. If yes: skip execution, return existing result
3. If no: execute action and record idempotency key with result

This ensures that reprocessing the same email (e.g., after a retry) does not create duplicate SAP disputes, duplicate emails, or duplicate Alevate entries.

---

*Part of the AR Email Management Domain — Financial System Modernization Project*