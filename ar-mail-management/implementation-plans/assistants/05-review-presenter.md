# ReviewPresenter — CodeMie Assistant

## Configuration

| Field                   | Value                                                                                                                                           |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| **Name**                | `ReviewPresenter`                                                                                                                               |
| **Slug**                | `ar-review-presenter`                                                                                                                           |
| **Description**         | Assembles all pipeline outputs into a human-readable review package for AR specialist approval. Runs at temperature=0 for deterministic output. |
| **Model**               | `claude-sonnet-4-6`                                                                                                                             |
| **Temperature**         | `0`                                                                                                                                             |
| **System Instructions** | Paste full contents of `ar-mail-management/prompts/ReviewPresenter.md`                                                                          |
| **Skills**              | Attach: `ar-taxonomy`                                                                                                                           |

---

## Responsibility

Assembles all pipeline outputs into a single structured review package for the AR specialist. Formats the email context, classification, draft response, and proposed system actions into a human-readable card. Its output is what the approver sees in the CodeMie / Alevate approval UI before deciding to approve, edit, reject, or escalate.

---

## Input

| Key | Source | Required |
|-----|--------|----------|
| `email` | Orchestrator output — `{ from, sender_name, subject, body, received_at }` | Yes |
| `has_attachments`, `attachment_metadata` | Orchestrator output | Yes |
| `summary`, `key_facts`, `open_items`, `sentiment_trend` | ThreadSummarizer output | Yes |
| `category`, `sub_category`, `confidence`, `priority`, `intent`, `reasoning`, `suggested_actions`, `escalation` | EmailClassifier output | Yes |
| `draft_subject`, `draft_body`, `tone`, `has_draft_response` | ResponseDrafter output | No — null if ResponseDrafter was skipped |
| `actions[]`, `approval_route` | ActionRouter output | Yes |
| `customer_context` | Trigger payload | Yes |

---

## Output Schema

```json
{
  "review_package": {
    "header": {
      "email_id": "...",
      "priority_badge": "STANDARD | URGENT | CRITICAL",
      "category_label": "<human-readable label>",
      "confidence_indicator": "HIGH | MEDIUM | LOW",
      "received_at": "...",
      "approval_route": "..."
    },
    "context_section": {
      "customer_email_summary": "...",
      "thread_context": "...",
      "ai_reasoning": "..."
    },
    "action_section": {
      "proposed_response": { "subject": "...", "body": "..." },
      "proposed_system_actions": []
    },
    "decision_buttons": ["APPROVE", "EDIT_AND_APPROVE", "REJECT", "ESCALATE"],
    "warnings": []
  }
}
```

---

## Notes

### Decision Buttons by Category

| Category | Decision buttons |
|----------|-----------------|
| `AUTO_REPLY` | `["APPROVE", "REJECT"]` |
| `ESCALATION_LEGAL`, `UNCLASSIFIED` | `["ESCALATE", "REJECT"]` |
| All others | `["APPROVE", "EDIT_AND_APPROVE", "REJECT", "ESCALATE"]` |

### PII Rules

- Never show raw confidence score — only `HIGH | MEDIUM | LOW` text
- Never show SAP IDs or internal system codes
- Use roles not individual names in summaries (e.g., "the customer's finance director")
- All output in English regardless of email language

### Human Approval Checkpoint

- `interrupt_before: true` pauses the workflow after `present-review` completes.
- The AR specialist sees the `review_package` in the CodeMie / Alevate UI.
- **Continue** → workflow resumes → downstream actions execute (email send, SAP update).
- **Cancel** → workflow ends → manual handling required; outcome logged to audit store.
- `requires_approval` is always `true` per ADR-002 — never auto-approve on timeout.

### Category Labels (human-readable display)

| Category | Label |
|----------|-------|
| PAYMENT_REMINDER_SENT | Payment Reminder |
| PAYMENT_PROMISE | Payment Promise |
| PAYMENT_CONFIRMATION | Payment Confirmation |
| PARTIAL_PAYMENT_NOTE | Partial Payment Note |
| REMITTANCE_ADVICE | Remittance Advice |
| INVOICE_NOT_RECEIVED | Invoice Not Received |
| INVOICE_DISPUTE | Invoice Dispute |
| CREDIT_NOTE_REQUEST | Credit Note Request |
| EXTENSION_REQUEST | Extension Request |
| BALANCE_INQUIRY | Balance Inquiry |
| BILLING_UPDATE | Billing Update |
| AUTO_REPLY | Automatic Reply |
| INTERNAL_NOTE | Internal Note |
| ESCALATION_LEGAL | Legal Escalation |
| UNCLASSIFIED | Unclassified — Requires Manual Review |
