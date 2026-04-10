# ThreadSummarizer — CodeMie Assistant

## Configuration

| Field                   | Value                                                                                                                                                 |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Name**                | `ThreadSummarizer`                                                                                                                                    |
| **Slug**                | `ar-thread-summarizer`                                                                                                                                |
| **Description**         | Reconstructs thread context from full email history. Produces structured summary with key facts, open items, and sentiment trend for the AR pipeline. |
| **Model**               | `claude-sonnet-4-6`                                                                                                                                   |
| **Temperature**         | `0`                                                                                                                                                   |
| **System Instructions** | Paste full contents of `ar-mail-management/prompts/ThreadSummarizer.md`                                                                               |
| **Skills**              | None                                                                                                                                                  |

---

## Responsibility

Reads the full email thread history and produces a structured summary — key facts, open items, and sentiment trend — that serves as the shared memory layer for all downstream agents. Always runs; never skipped.

---

## Input

| Key | Source | Required |
|-----|--------|----------|
| `thread_emails` | Orchestrator output | Yes — array of all emails in thread, oldest first |
| `message_id` | Orchestrator output | Yes |
| `existing_summary` | Context store (prior run) or null | No — null on first processing; used for incremental updates |
| `customer_context` | Trigger payload | Yes — `{ customer_id, company_name, total_outstanding, payment_history }` |

---

## Output Schema

> Use these field names — `architecture-overview.md` incorrectly calls them `thread_state` and `email_count`.

```json
{
  "summary": "<500-word narrative>",
  "key_facts": [],
  "open_items": [],
  "sentiment_trend": "NEUTRAL | FRUSTRATED | COOPERATIVE | ESCALATING",
  "thread_age_days": 0,
  "total_emails": 0
}
```

| Field | Type | Description |
|-------|------|-------------|
| `summary` | string | Narrative overview of the thread (≤500 words) |
| `key_facts` | array | Structured: invoice refs, amounts, dates, commitments |
| `open_items` | array | Unresolved AR items remaining at end of thread |
| `sentiment_trend` | string | Customer tone over the thread lifecycle |
| `thread_age_days` | number | Days since first email in thread |
| `total_emails` | number | Total email count in thread |

---

## Notes

- Always called — never skipped, regardless of email category.
- Input `thread_emails` comes from Orchestrator output (array of all emails in thread, oldest first).
- `existing_summary` is null on first processing; populated if the thread was previously processed (progressive summarization).
- `customer_context` is passed in the trigger payload: `{ customer_id, company_name, ar_balance }`.
- If `total_emails > 3`, the full thread is summarized narratively. For ≤3 emails the prompt may return a shorter summary.
- Output key `summary` flows into EmailClassifier and ResponseDrafter.
