# Confluence PRD Alignment Tracker

**Document Type:** Traceability Matrix
**Date:** 2026-04-08
**Status:** Living Document
**Domain:** AR Email Management

---

## Purpose

Maps every requirement from the Confluence PRD pages to:

1. Local architecture documentation (which ADR/doc covers it)
2. Outlook MCP Server implementation status
3. Gap severity

**Confluence Sources:**

- [UC 2: AR - AI Agent for E-Mail Handling](https://serrala.atlassian.net/wiki/spaces/SAA/pages/6327959630) (Problem Statement, Proposed Solution)
- [Collections Email Agent PRD](https://serrala.atlassian.net/wiki/spaces/SAA/pages/6333104138) (Detailed PRD)
- [Basic use case and Fiori UI](https://serrala.atlassian.net/wiki/spaces/SAA/pages/6332284990) (Categories, Actions, UI Spec)
- [Email Examples](https://serrala.atlassian.net/wiki/spaces/SAA/pages/6332088400) (Test Data)

---

## 1. Email Category Taxonomy


| Confluence Category                      | Local Architecture                                                                     | MCP Implementation                                                                | Severity |
| ---------------------------------------- | -------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- | -------- |
| Invoice Copy Request                     | `INVOICE_NOT_RECEIVED` sub-flag (req-review 3.3) + ADR-008 sub-category `COPY_REQUEST` | `INVOICE_NOT_RECEIVED` in `CLASSIFICATION_CATEGORIES` (no sub-category field yet) | P0       |
| Proof of Delivery (POD) Request          | **ADR-008** → `INVOICE_NOT_RECEIVED` + `POD_REQUEST`                                   | Not implemented (no sub-category)                                                 | P0       |
| Account Statement Request                | **ADR-008** → `BALANCE_INQUIRY` + `STATEMENT_REQUEST`                                  | `BALANCE_INQUIRY` exists (no sub-category)                                        | P0       |
| Payment Method / Banking Inquiry         | **ADR-008** → `BILLING_UPDATE` + `PAYMENT_METHOD_INQUIRY`                              | `BILLING_UPDATE` exists (no sub-category)                                         | P0       |
| Payment Confirmation / Remittance Advice | ADR-001 splits into `PAYMENT_CONFIRMATION` + `REMITTANCE_ADVICE`                       | Both in `CLASSIFICATION_CATEGORIES`                                               | OK       |
| Promise to Pay / Payment Delay           | ADR-001 → `PAYMENT_PROMISE`                                                            | Implemented                                                                       | OK       |
| Stalling / Under Review                  | **ADR-008** → `PAYMENT_PROMISE` + `STALLING_UNDER_REVIEW`                              | Not implemented (no sub-category)                                                 | P1       |
| Dispute -- Pricing Issue                 | **ADR-008** → `INVOICE_DISPUTE` + `PRICING`                                            | `INVOICE_DISPUTE` exists (no sub-category)                                        | P0       |
| Dispute -- Short Payment / Quantity      | **ADR-008** → `INVOICE_DISPUTE` + `SHORT_PAYMENT`                                      | `INVOICE_DISPUTE` exists (no sub-category)                                        | P0       |
| Dispute -- Returns / Damages             | **ADR-008** → `INVOICE_DISPUTE` + `RETURNS_DAMAGES`                                    | `INVOICE_DISPUTE` exists (no sub-category)                                        | P0       |
| Dispute -- General / Unspecified         | **ADR-008** → `INVOICE_DISPUTE` + `GENERAL`                                            | `INVOICE_DISPUTE` exists (no sub-category)                                        | P0       |
| Approval -- Credit Memo                  | **ADR-008** → `INTERNAL_NOTE` + `APPROVAL_CREDIT_MEMO`                                 | `INTERNAL_NOTE` exists (no sub-category)                                          | P1       |
| Approval -- Write-Off                    | **ADR-008** → `INTERNAL_NOTE` + `APPROVAL_WRITE_OFF`                                   | `INTERNAL_NOTE` exists (no sub-category)                                          | P1       |
| Approval -- Dispute Resolution           | **ADR-008** → `INTERNAL_NOTE` + `APPROVAL_DISPUTE_RESOLUTION`                          | `INTERNAL_NOTE` exists (no sub-category)                                          | P1       |
| Escalation / High-Risk                   | ADR-001 → `ESCALATION_LEGAL`                                                           | Implemented                                                                       | OK       |
| Non-AR / Informational                   | ADR-001 → `AUTO_REPLY` + `UNCLASSIFIED`                                                | Implemented                                                                       | OK       |
| **Multi-label**                          | **ADR-008** → `categories` list                                                        | Not implemented                                                                   | P0       |


---

## 2. AI Processing Capabilities


| PRD Requirement               | Confluence Source            | Local Architecture                     | MCP Status                        | Severity                            |
| ----------------------------- | ---------------------------- | -------------------------------------- | --------------------------------- | ----------------------------------- |
| Multi-class classification    | PRD 2.2.1                    | ADR-001 (Hybrid rule+LLM)              | `categorize_email` tool           | OK                                  |
| Priority assignment (H/M/L)   | PRD 2.2.2                    | Not top-level in architecture          | `intent.urgency` exists (nested)  | P0                                  |
| Summarization (1-2 sentences) | PRD 2.2.3                    | ThreadSummarizer (thread-level only)   | No tool                           | P0                                  |
| Reasoning output              | PRD 2.2.4                    | EmailClassifier outputs reasoning      | `ClassificationResult.reasoning`  | OK                                  |
| Entity extraction             | PRD 2.2.5                    | EmailClassifier + dedicated extraction | `extract_email_data` tool         | Partial (missing currency, dueDate) |
| Draft generation              | PRD 2.2.6                    | ResponseDrafter agent designed         | `create_draft` (blank only)       | P0                                  |
| Confidence score              | PRD 2.2.7                    | EmailClassifier outputs confidence     | `ClassificationResult.confidence` | OK                                  |
| Suggested actions (2-4)       | PRD Core 3.2.3               | ActionRouter agent designed            | Not implemented                   | P0                                  |
| Language detection            | PRD 2.2.6 (language-aligned) | Not addressed                          | Not implemented                   | P1                                  |


---

## 3. Structured JSON Output


| PRD Output Field         | MCP Field                        | Status                                 |
| ------------------------ | -------------------------------- | -------------------------------------- |
| `emailId`                | `email_id`                       | OK                                     |
| `threadId`               | —                                | Not in ClassificationResult            |
| `sender.name`            | Available in email JSON          | OK                                     |
| `sender.email`           | Available in email JSON          | OK                                     |
| `sender.company`         | —                                | Not extracted                          |
| `subject`                | Available in email JSON          | OK                                     |
| `receivedAt`             | Available in email JSON          | OK                                     |
| `category`               | `category`                       | OK                                     |
| `priority`               | `intent.urgency` (nested)        | Needs top-level                        |
| `summary`                | —                                | Not implemented                        |
| `reasoning`              | `reasoning`                      | OK                                     |
| `confidence`             | `confidence`                     | OK                                     |
| `entities.invoiceNumber` | `extracted_data.invoice_numbers` | OK (list format)                       |
| `entities.amount`        | `extracted_data.disputed_amount` | Partial                                |
| `entities.currency`      | —                                | Not implemented                        |
| `entities.dueDate`       | —                                | Not implemented (only `promised_date`) |
| `suggestedActions`       | —                                | Not implemented                        |
| `draftReply`             | —                                | Not implemented                        |


---

## 4. Technical & Non-Functional Requirements


| PRD Requirement                | Confluence Source | Local Architecture                     | MCP Status                                          | Severity       |
| ------------------------------ | ----------------- | -------------------------------------- | --------------------------------------------------- | -------------- |
| Multi-tenant                   | PRD 4             | Multi-tenancy ADRs                     | MCP server is stateless; tenant isolation via token | OK             |
| Scalable (100-10K+ emails/day) | PRD 4             | Not explicitly addressed at scale      | No batch tools                                      | P1             |
| <2s analysis time              | PRD 4             | Acknowledged in NFRs                   | MCP sampling timeout 120s (configurable)            | Partial        |
| Full audit trail               | PRD 4             | Designed (audit store)                 | MCP is stateless; audit is orchestrator's job       | OK (by design) |
| Idempotent processing          | PRD 4             | Designed (message ID dedup)            | Not in MCP (stateless)                              | OK (by design) |
| SOC2-ready                     | PRD 8             | Compliance sections in data-privacy.md | Token handling follows security patterns            | OK             |
| GDPR-compliant                 | PRD 8             | data-privacy.md + ADR-007              | PII redaction implemented (optional)                | OK             |
| Human-in-the-loop mandatory    | PRD 8             | ADR-002                                | ENABLE_WRITE_OPERATIONS flag; no auto-send          | OK             |


---

## 5. UI Requirements (Core Team — Not MCP Scope)

These are the Core Application Team's responsibilities per the PRD. Listed for completeness.


| PRD Requirement                           | Status    | Notes                                      |
| ----------------------------------------- | --------- | ------------------------------------------ |
| Inbox View (email list, badges, priority) | Core Team | Fiori app per Confluence UI spec           |
| Email Detail View (two-panel)             | Core Team | AI panel visually distinct                 |
| Draft Email Modal (editable)              | Core Team | Full edit before send                      |
| Sidebar Navigation                        | Core Team | Inbox, Sent, Disputes, Analytics, Settings |
| Filter & Sort                             | Core Team | By category, priority, read/unread         |
| Approval Confirm/Decline buttons          | Core Team | Per Fiori UI spec                          |
| Action History tab                        | Core Team | Per Fiori UI spec                          |
| Overview dashboard                        | Core Team | Per Fiori UI spec                          |


---

## 6. Actions from Confluence Not in MCP

These are SAP/Alevate-side actions triggered after human approval. MCP provides the classification; the orchestrator/Core handles action execution.


| Confluence Action          | MCP Support                                                         | Notes                          |
| -------------------------- | ------------------------------------------------------------------- | ------------------------------ |
| Send invoice copy          | Partial — `send_email` exists but no invoice PDF attachment support | Requires SAP invoice retrieval |
| Send proof of delivery     | Not in MCP                                                          | Requires SAP delivery note     |
| Send account statement     | Not in MCP                                                          | Requires SAP balance data      |
| Provide payment details    | Not in MCP                                                          | Company banking info           |
| Apply payment              | Not in MCP                                                          | SAP posting                    |
| Record promise to pay      | Not in MCP                                                          | SAP dunning update             |
| Create dispute case        | Not in MCP                                                          | SAP FS2/S4 dispute creation    |
| Approve/reject credit memo | Not in MCP                                                          | SAP workflow                   |
| Approve/reject write-off   | Not in MCP                                                          | SAP workflow                   |
| Escalate                   | Not in MCP                                                          | Alevate routing                |


**Note:** These actions are explicitly out of scope for the MCP server (it provides email access + classification tools). Action execution is the Core Application Team's responsibility.

---

## Change Log


| Date       | Change                            |
| ---------- | --------------------------------- |
| 2026-04-08 | Initial alignment tracker created |


---

*Part of the AR Email Management Domain — Financial System Modernization Project*