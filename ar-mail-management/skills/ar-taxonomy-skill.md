---
name: ar-taxonomy
description: >
  Complete 15-category AR email taxonomy for the Accounts Receivable email management pipeline.
  Load this skill whenever you are classifying an inbound AR email, routing it to an approval
  tier, or assembling a review package for human approval. Specifically: load when you need
  the category definitions (INVOICE_DISPUTE, PAYMENT_PROMISE, EXTENSION_REQUEST, etc.),
  sub-category breakdowns, multi-label classification rules, priority hierarchy,
  confidence thresholds, escalation conditions (E1–E7), ActionRouter override rules (1–7),
  no-draft category list, or ReviewPresenter decision-button mappings.
  Attach to: EmailClassifier, ActionRouter, ReviewPresenter.
---

# AR Email Taxonomy

---

## 15-Category Primary Taxonomy

| Category                | Description                                                             | Urgency  | Approval Route     | Tone       |
| ----------------------- | ----------------------------------------------------------------------- | -------- | ------------------ | ---------- |
| `PAYMENT_REMINDER_SENT` | We sent a reminder; customer replies to acknowledge or ignore           | LOW      | STANDARD (4h)      | FIRM       |
| `PAYMENT_PROMISE`       | Customer commits to paying by a specific date                           | LOW      | STANDARD (4h)      | FORMAL     |
| `PAYMENT_CONFIRMATION`  | Customer confirms payment has been sent                                 | LOW      | STANDARD (4h)      | FORMAL     |
| `PARTIAL_PAYMENT_NOTE`  | Customer indicates only partial payment will be made                    | MEDIUM   | STANDARD (4h)      | FORMAL     |
| `REMITTANCE_ADVICE`     | Customer sends remittance details for matching                          | LOW      | STANDARD (4h)      | FORMAL     |
| `INVOICE_NOT_RECEIVED`  | Customer claims they never received the invoice                         | MEDIUM   | STANDARD (4h)      | FORMAL     |
| `INVOICE_DISPUTE`       | Customer disputes the amount, quantity, or validity of an invoice       | HIGH     | PRIORITY (1h)      | EMPATHETIC |
| `CREDIT_NOTE_REQUEST`   | Customer requests a credit note or invoice adjustment                   | HIGH     | SUPERVISOR (30min) | EMPATHETIC |
| `EXTENSION_REQUEST`     | Customer requests more time to pay                                      | HIGH     | SUPERVISOR (30min) | EMPATHETIC |
| `BALANCE_INQUIRY`       | Customer asks about outstanding balance or account status               | MEDIUM   | STANDARD (4h)      | FORMAL     |
| `BILLING_UPDATE`        | Customer requests change of billing address, contact, or payment method | LOW      | STANDARD (4h)      | FORMAL     |
| `AUTO_REPLY`            | Automated out-of-office, delivery receipt, or read receipt              | LOW      | STANDARD (4h)      | —          |
| `INTERNAL_NOTE`         | Internal team communication within the thread                           | LOW      | STANDARD (4h)      | —          |
| `ESCALATION_LEGAL`      | Email contains legal threats, formal notices, or mentions legal counsel | CRITICAL | LEGAL (15min)      | —          |
| `UNCLASSIFIED`          | Intent is unclear or confidence < 0.75; requires human review           | MEDIUM   | SUPERVISOR (30min) | —          |

---

## Sub-Categories (ADR-008 Hierarchical Taxonomy)

### INVOICE_DISPUTE sub-categories

| sub_category      | Description                                                 |
| ----------------- | ----------------------------------------------------------- |
| `PRICING`         | Customer disputes the unit price or total price             |
| `SHORT_PAYMENT`   | Customer claims they paid but for a lower amount            |
| `RETURNS_DAMAGES` | Customer disputes due to returned goods or damaged delivery |
| `GENERAL`         | Dispute reason not covered by above sub-types               |

### INVOICE_NOT_RECEIVED sub-categories

| sub_category   | Description                                           |
| -------------- | ----------------------------------------------------- |
| `NOT_RECEIVED` | Customer claims invoice was never delivered           |
| `COPY_REQUEST` | Customer explicitly requests a copy/duplicate invoice |

### BALANCE_INQUIRY sub-categories

| sub_category        | Description                                             |
| ------------------- | ------------------------------------------------------- |
| `BALANCE_QUESTION`  | Customer asks about total outstanding amount            |
| `STATEMENT_REQUEST` | Customer explicitly requests a formal account statement |

### BILLING_UPDATE sub-categories

| sub_category             | Description                                      |
| ------------------------ | ------------------------------------------------ |
| `ADDRESS_CHANGE`         | Billing address update                           |
| `CONTACT_CHANGE`         | Contact person or email update                   |
| `PAYMENT_METHOD_INQUIRY` | Question about payment method or banking details |

### PAYMENT_PROMISE sub-categories

| sub_category | Description                                                             |
| ------------ | ----------------------------------------------------------------------- |
| `WITH_DATE`  | Promise includes a specific payment date                                |
| `NO_DATE`    | Promise given but no specific date mentioned (triggers Override Rule 5) |

---

## Multi-Label Classification Rules (ADR-008)

When an email contains signals for more than one category:

- Output `category` as the **primary** (highest-priority) category
- Output `categories[]` as an ordered list: `[primary, secondary, ...]`
- Maximum 3 labels
- Reduce `confidence` by 0.05–0.10 per additional label

**Priority hierarchy** (highest wins in multi-label):

```
ESCALATION_LEGAL > INVOICE_DISPUTE > CREDIT_NOTE_REQUEST > EXTENSION_REQUEST
  > INVOICE_NOT_RECEIVED > PARTIAL_PAYMENT_NOTE > PAYMENT_PROMISE
  > PAYMENT_CONFIRMATION > REMITTANCE_ADVICE > BALANCE_INQUIRY
  > BILLING_UPDATE > PAYMENT_REMINDER_SENT > AUTO_REPLY
  > INTERNAL_NOTE > UNCLASSIFIED
```

---

## No-Draft Categories

The following categories do **not** generate a ResponseDrafter draft. ActionRouter receives `has_draft_response: false`:

- `ESCALATION_LEGAL` — legal team handles all communication
- `UNCLASSIFIED` — supervisor must classify before any response
- `AUTO_REPLY` — no reply sent to automated messages
- `INTERNAL_NOTE` — internal only, NO_ACTION

---

## ActionRouter Override Rules

| Rule       | Condition                               | Effect                                                                  |
| ---------- | --------------------------------------- | ----------------------------------------------------------------------- |
| **Rule 1** | Category = ESCALATION_LEGAL             | Strip ALL actions except ESCALATE to legal_team                         |
| **Rule 2** | Category = UNCLASSIFIED                 | Strip ALL actions except ESCALATE to supervisor                         |
| **Rule 3** | `has_draft_response = false`            | Remove SEND_EMAIL; add LOG_EVENT noting no draft                        |
| **Rule 4** | INVOICE_DISPUTE with no invoice_numbers | Mark invoice as UNKNOWN, require manual lookup                          |
| **Rule 5** | PAYMENT_PROMISE with no `promised_date` | Drop UPDATE_SAP_DATE; keep LOG_EVENT only                               |
| **Rule 6** | Amount > EUR 100,000                    | Upgrade `approval_route` to SUPERVISOR minimum                          |
| **Rule 7** | Multiple `invoice_numbers`              | Fan-out: generate per-invoice actions; shared SEND_EMAIL stays singular |

---

## Confidence Thresholds

| Score     | Indicator | Action                                              |
| --------- | --------- | --------------------------------------------------- |
| ≥ 0.90    | HIGH      | Proceed normally                                    |
| 0.75–0.89 | MEDIUM    | Proceed; ReviewPresenter shows MEDIUM indicator     |
| < 0.75    | LOW       | Set category = UNCLASSIFIED; escalate to supervisor |

---

## Escalation Conditions (EmailClassifier E1-E7)

| Code | Condition                                                                        | Result                                                 |
| ---- | -------------------------------------------------------------------------------- | ------------------------------------------------------ |
| E1   | Confidence < 0.75                                                                | UNCLASSIFIED → SUPERVISOR                              |
| E2   | Legal keywords detected (formal notice, proceedings, counsel, without prejudice) | ESCALATION_LEGAL → LEGAL                               |
| E3   | Unsupported language (not EN/DE/FR/ES/IT)                                        | UNCLASSIFIED → SUPERVISOR                              |
| E4   | Conflicting intents with equal signals                                           | UNCLASSIFIED → SUPERVISOR                              |
| E5   | Garbled or truncated body                                                        | UNCLASSIFIED → SUPERVISOR                              |
| E6   | Email references prior commitment not in thread                                  | Add warning to review package                          |
| E7   | Amount > EUR 100,000                                                             | Add to escalation context; ActionRouter applies Rule 6 |

---

## ReviewPresenter Category Labels & Decision Buttons

| Category              | Human-readable label                  | Decision buttons                            |
| --------------------- | ------------------------------------- | ------------------------------------------- |
| PAYMENT_REMINDER_SENT | Payment Reminder                      | APPROVE, EDIT_AND_APPROVE, REJECT, ESCALATE |
| PAYMENT_PROMISE       | Payment Promise                       | APPROVE, EDIT_AND_APPROVE, REJECT, ESCALATE |
| PAYMENT_CONFIRMATION  | Payment Confirmation                  | APPROVE, EDIT_AND_APPROVE, REJECT, ESCALATE |
| PARTIAL_PAYMENT_NOTE  | Partial Payment Note                  | APPROVE, EDIT_AND_APPROVE, REJECT, ESCALATE |
| REMITTANCE_ADVICE     | Remittance Advice                     | APPROVE, EDIT_AND_APPROVE, REJECT, ESCALATE |
| INVOICE_NOT_RECEIVED  | Invoice Not Received                  | APPROVE, EDIT_AND_APPROVE, REJECT, ESCALATE |
| INVOICE_DISPUTE       | Invoice Dispute                       | APPROVE, EDIT_AND_APPROVE, REJECT, ESCALATE |
| CREDIT_NOTE_REQUEST   | Credit Note Request                   | APPROVE, EDIT_AND_APPROVE, REJECT, ESCALATE |
| EXTENSION_REQUEST     | Extension Request                     | APPROVE, EDIT_AND_APPROVE, REJECT, ESCALATE |
| BALANCE_INQUIRY       | Balance Inquiry                       | APPROVE, EDIT_AND_APPROVE, REJECT, ESCALATE |
| BILLING_UPDATE        | Billing Update                        | APPROVE, EDIT_AND_APPROVE, REJECT, ESCALATE |
| AUTO_REPLY            | Automatic Reply                       | APPROVE, REJECT                             |
| INTERNAL_NOTE         | Internal Note                         | APPROVE, REJECT                             |
| ESCALATION_LEGAL      | Legal Escalation                      | ESCALATE, REJECT                            |
| UNCLASSIFIED          | Unclassified — Requires Manual Review | ESCALATE, REJECT                            |
