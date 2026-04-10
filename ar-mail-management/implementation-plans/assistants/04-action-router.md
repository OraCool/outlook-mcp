# ActionRouter — CodeMie Assistant

## Configuration

| Field                   | Value                                                                                                                                                   |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Name**                | `ActionRouter`                                                                                                                                          |
| **Slug**                | `ar-action-router`                                                                                                                                      |
| **Description**         | Maps email classification to ordered SAP/Outlook/Alevate actions. Applies 7 override rules. Outputs approval route: STANDARD/PRIORITY/SUPERVISOR/LEGAL. |
| **Model**               | `claude-sonnet-4-6`                                                                                                                                     |
| **Temperature**         | `0`                                                                                                                                                     |
| **System Instructions** | Paste full contents of `ar-mail-management/prompts/ActionRouter.md`                                                                                     |
| **Skills**              | Attach: `ar-taxonomy`                                                                                                                                   |

---

## Responsibility

Maps the email classification to an ordered list of SAP / Outlook / Alevate system actions and assigns an approval route (STANDARD / PRIORITY / SUPERVISOR / LEGAL). Applies 7 override rules that can strip, add, or modify actions based on category, amounts, and missing data. Always runs — called from both the draft and no-draft workflow paths.

---

## Input

| Key | Source | Required |
|-----|--------|----------|
| `category` | EmailClassifier output | Yes |
| `sub_category` | EmailClassifier output | No |
| `confidence` | EmailClassifier output | Yes |
| `priority` | EmailClassifier output | Yes |
| `extracted_data` | EmailClassifier output — invoice numbers, promised_date, disputed_amount, currency | Yes |
| `has_draft_response` | ResponseDrafter output (`true`) or workflow flag (`false` if skipped) | Yes |
| `draft_subject` | ResponseDrafter output | No — null if skipped |
| `summary` | ThreadSummarizer output | Yes |
| `customer_context` | Trigger payload | Yes |

---

## Output Schema

> `architecture-overview.md` incorrectly describes output as a single action object with `priority: normal/high/urgent`. The real output is `actions[]` (array) + `approval_route` with named tiers.

```json
{
  "actions": [
    {
      "action_type": "LOG_DISPUTE | SEND_EMAIL | TRIGGER_RECONCILIATION | UPDATE_SAP_DATE | LOG_EVENT | ESCALATE | NO_ACTION",
      "target_system": "SAP | OUTLOOK | ALEVATE",
      "parameters": {},
      "priority": "HIGH | LOW",
      "invoice_number": "INV-001"
    }
  ],
  "approval_route": "STANDARD | PRIORITY | SUPERVISOR | LEGAL",
  "reasoning": "..."
}
```

---

## Notes

### Invariants

- `requires_approval` is always `true` — never auto-execute any action
- The `actions[]` array may contain 1–N items; ReviewPresenter and the approval UI must handle N actions

### Override Rules

| Rule | Condition | Effect |
|------|-----------|--------|
| **Rule 1** | Category = ESCALATION_LEGAL | Strip ALL actions except ESCALATE to legal_team |
| **Rule 2** | Category = UNCLASSIFIED | Strip ALL actions except ESCALATE to supervisor |
| **Rule 3** | `has_draft_response = false` | Remove SEND_EMAIL; add LOG_EVENT noting no draft |
| **Rule 4** | INVOICE_DISPUTE with no invoice_numbers | Mark invoice as UNKNOWN, require manual lookup |
| **Rule 5** | PAYMENT_PROMISE with no `promised_date` | Drop UPDATE_SAP_DATE; keep LOG_EVENT only |
| **Rule 6** | Amount > EUR 100,000 | Upgrade `approval_route` to SUPERVISOR minimum |
| **Rule 7** | Multiple `invoice_numbers` | Fan-out: generate per-invoice actions; shared SEND_EMAIL stays singular |

### Approval SLAs

| Route | SLA | Escalation target |
|-------|-----|-------------------|
| STANDARD | 4 hours | Supervisor |
| PRIORITY | 1 hour | Supervisor |
| SUPERVISOR | 30 minutes | Legal / senior management |
| LEGAL | 15 minutes | Legal team |

SLA enforcement is handled **externally** by the Alevate workflow engine or an external scheduler — CodeMie does not enforce timeouts natively. Configure SLA triggers using the `approval_route` value passed in the review package.
