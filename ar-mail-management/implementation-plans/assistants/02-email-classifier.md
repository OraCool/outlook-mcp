# EmailClassifier — CodeMie Assistant

## Configuration

| Field                   | Value                                                                                                                  |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| **Name**                | `EmailClassifier`                                                                                                      |
| **Slug**                | `ar-email-classifier`                                                                                                  |
| **Description**         | Classifies inbound AR emails into 15 categories with confidence score, sub-category (ADR-008), and extracted entities. |
| **Model**               | `claude-sonnet-4-6`                                                                                                    |
| **Temperature**         | `0`                                                                                                                    |
| **System Instructions** | Paste full contents of `ar-mail-management/prompts/EmailClassifier.md`                                                 |
| **Skills**              | Attach: `ar-taxonomy`                                                                                                  |

---

## Responsibility

Classifies the inbound email into one of 15 AR taxonomy categories with a confidence score, optional sub-category, extracted entities (invoice numbers, dates, amounts), and a routing flag. Its `category` output determines whether ResponseDrafter runs.

---

## Input

| Key | Source | Required |
|-----|--------|----------|
| `email_body` | Orchestrator output | Yes |
| `subject` | Orchestrator output (`email.subject`) | Yes |
| `from` | Orchestrator output (`email.from`, `email.sender_name`) | Yes |
| `summary` | ThreadSummarizer output | No — null if first email in thread |
| `thread_id` | Orchestrator output | Yes |
| `invoice_references` | Trigger payload or Orchestrator output | No — may be empty |
| `previous_classifications` | Context store (prior runs) | No — empty on first run |

---

## Output Schema

```json
{
  "category": "INVOICE_DISPUTE | PAYMENT_PROMISE | PAYMENT_CONFIRMATION | PAYMENT_REMINDER_SENT | PARTIAL_PAYMENT_NOTE | REMITTANCE_ADVICE | INVOICE_NOT_RECEIVED | CREDIT_NOTE_REQUEST | EXTENSION_REQUEST | BALANCE_INQUIRY | BILLING_UPDATE | ESCALATION_LEGAL | AUTO_REPLY | INTERNAL_NOTE | UNCLASSIFIED",
  "sub_category": "PRICING | SHORT_PAYMENT | RETURNS_DAMAGES | GENERAL | null",
  "categories": ["PRIMARY_CATEGORY", "SECONDARY_CATEGORY"],
  "confidence": 0.0,
  "priority": "HIGH | MEDIUM | LOW",
  "summary": "<1-2 sentence summary>",
  "language": "EN | DE | FR | ES | IT",
  "intent": {
    "customer_statement": "...",
    "required_action": "...",
    "urgency": "HIGH | MEDIUM | LOW"
  },
  "reasoning": "...",
  "extracted_data": {
    "invoice_numbers": [],
    "disputed_amount": null,
    "promised_date": null,
    "payment_reference": null
  },
  "suggested_actions": [],
  "escalation": null
}
```

---

## Notes

### Confidence Threshold (E1)

- `confidence ≥ 0.90` → HIGH — proceed normally
- `confidence 0.75–0.89` → MEDIUM — proceed; ReviewPresenter shows MEDIUM indicator
- `confidence < 0.75` → LOW — force `category = UNCLASSIFIED`, escalate to supervisor

### Escalation Conditions (E1–E7)

| Code | Condition | Result |
|------|-----------|--------|
| E1 | confidence < 0.75 | UNCLASSIFIED → SUPERVISOR |
| E2 | Legal keywords detected (formal notice, proceedings, counsel, without prejudice) | ESCALATION_LEGAL → LEGAL |
| E3 | Unsupported language (not EN/DE/FR/ES/IT) | UNCLASSIFIED → SUPERVISOR |
| E4 | Conflicting intents with equal signals | UNCLASSIFIED → SUPERVISOR |
| E5 | Garbled or truncated body | UNCLASSIFIED → SUPERVISOR |
| E6 | Email references prior commitment not in thread | Add warning to review package |
| E7 | Amount > EUR 100,000 | Add to escalation context; ActionRouter applies Rule 6 |

### Multi-Label Classification (ADR-008)

- `category` = primary (highest-priority) category
- `categories[]` = ordered list: `[primary, secondary, ...]`, max 3 labels
- Reduce `confidence` by 0.05–0.10 per additional label
- Priority hierarchy (highest wins): `ESCALATION_LEGAL > INVOICE_DISPUTE > CREDIT_NOTE_REQUEST > EXTENSION_REQUEST > INVOICE_NOT_RECEIVED > PARTIAL_PAYMENT_NOTE > PAYMENT_PROMISE > PAYMENT_CONFIRMATION > REMITTANCE_ADVICE > BALANCE_INQUIRY > BILLING_UPDATE > PAYMENT_REMINDER_SENT > AUTO_REPLY > INTERNAL_NOTE > UNCLASSIFIED`

### Routing Gate

The `classify-email` state's conditional transition determines the downstream path:
- `category` ∈ `{ESCALATION_LEGAL, UNCLASSIFIED, AUTO_REPLY, INTERNAL_NOTE}` → `route-actions-nodraft` (skips ResponseDrafter)
- All other categories → `draft-response`
