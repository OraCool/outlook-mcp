# ResponseDrafter — CodeMie Assistant

## Configuration

| Field                   | Value                                                                                                                     |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| **Name**                | `ResponseDrafter`                                                                                                         |
| **Slug**                | `ar-response-drafter`                                                                                                     |
| **Description**         | Drafts customer-facing email responses. Skipped for ESCALATION_LEGAL, UNCLASSIFIED, AUTO_REPLY, INTERNAL_NOTE categories. |
| **Model**               | `claude-sonnet-4-6`                                                                                                       |
| **Temperature**         | `0.3` ← **only non-zero agent in the pipeline**                                                                           |
| **System Instructions** | Paste full contents of `ar-mail-management/prompts/ResponseDrafter.md`                                                    |
| **Skills**              | None                                                                                                                      |

---

## Responsibility

Drafts a professional, customer-facing AR reply based on the email classification and thread context. **Conditionally skipped** for 4 no-draft categories (ESCALATION_LEGAL, UNCLASSIFIED, AUTO_REPLY, INTERNAL_NOTE) — the workflow routes directly to ActionRouter in those cases.

---

## Input

| Key | Source | Required |
|-----|--------|----------|
| `category` | EmailClassifier output | Yes |
| `sub_category` | EmailClassifier output | No |
| `confidence` | EmailClassifier output | Yes |
| `intent` | EmailClassifier output | Yes |
| `email_body` | Orchestrator output | Yes |
| `summary` | ThreadSummarizer output | Yes |
| `customer_context` | Trigger payload | Yes — `{ company_name, total_outstanding }` |
| `invoice_data` | Trigger payload | No |
| `sap_template` | Trigger payload | No — null if no SAP template provided |

---

## Output Schema

> `architecture-overview.md` incorrectly describes the output as `action_type: "reply"/"no_reply_needed"`. The real field is `has_draft_response: true/false`.

```json
{
  "draft_subject": "Re: ...",
  "draft_body": "<300 word max>",
  "tone": "FORMAL | EMPATHETIC | FIRM",
  "template_used": "<SAP template ID or null>",
  "personalization_applied": true,
  "word_count": 0,
  "language": "EN | DE | ...",
  "has_draft_response": true,
  "warnings": []
}
```

---

## Notes

### No-Draft Categories (skip this assistant)

When `category` is one of the following, the workflow routes directly to `route-actions-nodraft`, bypassing ResponseDrafter entirely. ActionRouter receives `has_draft_response: false`.

| Category | Reason |
|----------|--------|
| `ESCALATION_LEGAL` | Legal team handles all communication |
| `UNCLASSIFIED` | Supervisor must classify before any response |
| `AUTO_REPLY` | No reply sent to automated messages |
| `INTERNAL_NOTE` | Internal only, NO_ACTION |

### Temperature Rationale

ResponseDrafter is the **only agent in the pipeline running at temperature > 0** (0.3 vs. 0 for all others). A small amount of sampling variability is intentional here — it allows the model to produce natural, human-sounding prose rather than mechanically templated output. All other agents (classification, routing, review) run at 0 for deterministic, reproducible decisions.

### Context Variables Consumed

| Key | Source |
|-----|--------|
| `category` | EmailClassifier output |
| `sub_category` | EmailClassifier output |
| `confidence` | EmailClassifier output |
| `intent` | EmailClassifier output |
| `summary` | ThreadSummarizer output |
| `customer_context` | Trigger payload |
| `invoice_data` | Trigger payload |
| `sap_template` | Trigger payload (null if not provided) |
| `email_body` | Orchestrator output |
