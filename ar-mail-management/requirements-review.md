# Requirements Review — AR Email Management Solution

**Document Type:** Requirements Analysis & Traceability
**Date:** 2026-03-31
**Status:** Proposed
**Domain:** AR Email Management
**Author:** Architecture Team

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Scenario Gap Analysis](#2-scenario-gap-analysis)
3. [Taxonomy Validation](#3-taxonomy-validation)
4. [Functional Requirements Gap Analysis](#4-functional-requirements-gap-analysis)
5. [UC Requirements Traceability Matrix](#5-uc-requirements-traceability-matrix)
6. [Findings and Decisions](#6-findings-and-decisions)

---

## 1. Executive Summary

This document presents a structured review of the requirements, business scenarios, and email category taxonomy defined for the AI-powered AR Email Management solution. The review was conducted against the agent prompt specification (Task 1 scope) and the Confluence UC page requirements (UC 2: AR - AI Agent for E-Mail Handling / Collections Management).

**Key findings:**

- **Seven additional scenarios** identified beyond the initial S1-S8 set, covering invoice copy requests, remittance advice, balance inquiries, auto-replies, multi-invoice threads, credit note requests, and billing contact changes.
- **Five new taxonomy categories** proposed to close coverage gaps: `REMITTANCE_ADVICE`, `BALANCE_INQUIRY`, `CREDIT_NOTE_REQUEST`, `AUTO_REPLY`, and `BILLING_UPDATE`.
- **Three functional requirement ambiguities** identified in FR1-FR12, primarily around the boundary between FR1 (Outlook Integration) and FR5 (Response Generation) for SAP template handling, the confidence threshold definition in FR4/FR8, and the audit trail granularity in FR9.
- **Full traceability** established between all scenarios/FRs and the UC page requirements. Two UC requirements (UC-M1 through UC-M5 metrics) lack direct scenario coverage and are addressed as non-functional cross-cutting concerns.
- **No UC requirements are left uncovered**, though several require architectural decisions (ADR-005, ADR-002) to fully satisfy.

---

## 2. Scenario Gap Analysis

### 2.1 Existing Scenarios (S1-S8) Assessment

All eight seed scenarios are valid and well-defined. Each maps to a clear trigger, expected action, and at least one email category. No existing scenarios should be removed.


| Scenario                                     | Assessment | Notes                                                    |
| -------------------------------------------- | ---------- | -------------------------------------------------------- |
| S1 — Payment overdue, no customer response   | Valid      | Outbound-initiated; relies on SAP aging data             |
| S2 — Customer claims invoice not received    | Valid      | Must distinguish "not received" from "requesting a copy" |
| S3 — Customer promises to pay on a date      | Valid      | Date extraction critical; must handle ambiguous dates    |
| S4 — Customer disputes invoice amount        | Valid      | Primary UC use case; triggers FS2/S4 dispute logging     |
| S5 — Payment received but not matched in SAP | Valid      | Trigger originates from SAP event, not email             |
| S6 — Customer requests invoice extension     | Valid      | Requires approval routing; decision authority unclear    |
| S7 — Customer confirms payment sent          | Valid      | Must not be conflated with remittance advice (see S10)   |
| S8 — Escalation / legal tone detected        | Valid      | No auto-draft; immediate human routing                   |


### 2.2 Missing Scenarios

The following scenarios are not covered by S1-S8 but occur regularly in AR email workflows. Each is assigned an identifier for traceability.


| #   | Scenario                                                       | Trigger                                                                                | Expected Action                                                                                  | Rationale for Inclusion                                                                                                                    |
| --- | -------------------------------------------------------------- | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------ |
| S9  | Customer requests copy of invoice                              | Inbound: "Can you send me a copy of invoice #X?"                                       | Retrieve invoice from SAP; attach to reply draft; route for approval                             | Distinct from S2: customer is NOT claiming non-receipt; they need a duplicate. High frequency in AR operations.                            |
| S10 | Customer sends payment remittance advice                       | Inbound: remittance details, bank reference, or payment proof attached                 | Log remittance data; trigger SAP matching/reconciliation; draft acknowledgement                  | Differs from S7 (confirmation of intent to pay) in that S10 provides actionable payment details for reconciliation.                        |
| S11 | Customer queries outstanding balance                           | Inbound: "What is our current balance?" or "Please send a statement"                   | Retrieve balance/statement from SAP; draft response with balance details; route for approval     | Common inquiry not covered by dispute (S4) or payment scenarios. Requires SAP master data access.                                          |
| S12 | Auto-reply or out-of-office detected                           | Inbound: automated reply (OOO, delivery receipt, read receipt)                         | Classify as non-actionable; log; suppress from processing queue; do NOT generate draft           | Without this scenario, auto-replies would be classified as UNCLASSIFIED and escalated unnecessarily, creating noise for human reviewers.   |
| S13 | Multi-invoice thread (one email referencing multiple invoices) | Inbound: email references 2+ invoice numbers or disputes                               | Split into per-invoice processing units; classify and draft individually; present grouped review | S1-S8 implicitly assume one invoice per email. Multi-invoice threads require explicit handling to avoid partial processing.                |
| S14 | Customer requests a credit note                                | Inbound: "We need a credit note for invoice #X because..."                             | Log credit note request; flag for finance review; draft acknowledgement                          | Distinct from dispute (S4): customer is not contesting the invoice but requesting a financial correction. Requires different SAP workflow. |
| S15 | Customer notifies change of billing contact or address         | Inbound: "Please update our billing address to..." or "New contact for invoices is..." | Flag for master data update in SAP; draft confirmation; route to master data team                | Administrative change that does not fit any existing category. Incorrect handling could cause future invoice delivery failures.            |


### 2.3 Scenario Coverage Assessment


| Coverage Area                                                       | S1-S8          | S9-S15   | Gap Severity                                                      |
| ------------------------------------------------------------------- | -------------- | -------- | ----------------------------------------------------------------- |
| Payment lifecycle (reminder, promise, confirmation, reconciliation) | S1, S3, S5, S7 | S10      | Low — S10 adds remittance detail handling                         |
| Invoice lifecycle (not received, dispute, extension)                | S2, S4, S6     | S9, S14  | Medium — copy requests and credit notes are frequent              |
| Escalation and safety                                               | S8             | --       | None                                                              |
| Non-actionable email handling                                       | --             | S12      | High — auto-replies will pollute the processing queue without S12 |
| Complex thread handling                                             | --             | S13      | High — multi-invoice emails are common in enterprise AR           |
| Administrative / master data                                        | --             | S11, S15 | Medium — balance inquiries and contact changes are routine        |


**Recommendation:** Adopt S9-S15 as in-scope scenarios. S12 (auto-reply detection) and S13 (multi-invoice handling) are highest priority due to their impact on system reliability and processing accuracy.

---

## 3. Taxonomy Validation

### 3.1 Existing Category Assessment


| Category                | Covers Scenarios | Assessment         | Notes                                                                                                         |
| ----------------------- | ---------------- | ------------------ | ------------------------------------------------------------------------------------------------------------- |
| `PAYMENT_REMINDER_SENT` | S1               | Valid              | Outbound-initiated category; tracks our action, not customer intent                                           |
| `INVOICE_NOT_RECEIVED`  | S2               | Valid              | Consider clarifying boundary with proposed `INVOICE_COPY_REQUEST` (see S9)                                    |
| `INVOICE_DISPUTE`       | S4               | Valid              | Primary UC use case; well-defined                                                                             |
| `PAYMENT_PROMISE`       | S3               | Valid              | Must extract date; NLP confidence critical                                                                    |
| `PAYMENT_CONFIRMATION`  | S7               | Valid              | Distinct from `REMITTANCE_ADVICE` (proof vs. statement of intent)                                             |
| `EXTENSION_REQUEST`     | S6               | Valid              | Requires approval routing metadata                                                                            |
| `PARTIAL_PAYMENT_NOTE`  | --               | Valid but orphaned | No explicit scenario covers partial payment; consider adding a scenario or documenting as a sub-case of S3/S7 |
| `ESCALATION_LEGAL`      | S8               | Valid              | Hard escalation; no auto-draft permitted                                                                      |
| `INTERNAL_NOTE`         | --               | Valid              | Covers internal team communication within threads                                                             |
| `UNCLASSIFIED`          | --               | Valid              | Catch-all; triggers escalation per FR8                                                                        |


### 3.2 Proposed New Categories


| Category              | Description                                                                                             | Covers Scenario | Justification                                                                                                                                                                                                                                                                                    |
| --------------------- | ------------------------------------------------------------------------------------------------------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `REMITTANCE_ADVICE`   | Customer sends proof or details of payment (bank reference, transfer confirmation, attached remittance) | S10             | Distinct from `PAYMENT_CONFIRMATION`: contains actionable reconciliation data (amounts, references, dates) vs. a simple statement of intent. SAP reconciliation requires structured remittance data extraction.                                                                                  |
| `BALANCE_INQUIRY`     | Customer asks about outstanding balance or requests an account statement                                | S11             | Not a dispute, not a payment action. Requires SAP balance retrieval, which is a different data path than invoice-level operations.                                                                                                                                                               |
| `CREDIT_NOTE_REQUEST` | Customer requests issuance of a credit note or credit memo                                              | S14             | Distinct from `INVOICE_DISPUTE`: the customer accepts the invoice was issued but requests a financial correction (e.g., returned goods, service not delivered). Triggers a different SAP document type (credit memo vs. dispute case).                                                           |
| `AUTO_REPLY`          | Automated out-of-office reply, delivery receipt, or read receipt                                        | S12             | Essential for filtering non-actionable emails. Without this category, auto-replies would be classified as `UNCLASSIFIED` and consume human reviewer capacity. Detection is rule-based (headers: `X-Auto-Reply`, `Auto-Submitted`, `X-MS-Exchange-Organization-AutoReply`) rather than LLM-based. |
| `BILLING_UPDATE`      | Customer requests change of billing address, contact person, or payment details                         | S15             | Administrative request that does not fit payment or invoice categories. Triggers SAP master data change workflow, which requires a separate approval path (master data governance).                                                                                                              |


### 3.3 Categories Considered but Not Proposed


| Category               | Reason for Exclusion                                                                                                                                                                                                                                                                                                                                                         |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `INVOICE_COPY_REQUEST` | After analysis, S9 (customer requesting invoice copy) can be handled as a sub-classification of `INVOICE_NOT_RECEIVED` with a flag (`is_copy_request: true`) in the intent extraction output. Adding a separate top-level category would fragment the taxonomy. The `EmailClassifier` prompt should include decision rules to distinguish "not received" from "need a copy." |
| `FOLLOW_UP_NEEDED`     | This is a workflow state, not an email intent category. Thread completeness tracking (FR7) handles follow-up logic.                                                                                                                                                                                                                                                          |
| `PAYMENT_DECLINED`     | Rare in AR email workflows (payment declines typically surface through bank/payment processor channels, not customer email). If encountered, the `EmailClassifier` should map to `UNCLASSIFIED` for human review.                                                                                                                                                            |


### 3.4 Taxonomy Summary

**Final proposed taxonomy (15 categories):**


| #   | Category                | Type                        | Auto-Draft Permitted       |
| --- | ----------------------- | --------------------------- | -------------------------- |
| 1   | `PAYMENT_REMINDER_SENT` | Outbound tracking           | N/A (our action)           |
| 2   | `INVOICE_NOT_RECEIVED`  | Inbound — invoice lifecycle | Yes                        |
| 3   | `INVOICE_DISPUTE`       | Inbound — dispute           | Yes (acknowledgement only) |
| 4   | `PAYMENT_PROMISE`       | Inbound — payment lifecycle | Yes                        |
| 5   | `PAYMENT_CONFIRMATION`  | Inbound — payment lifecycle | Yes                        |
| 6   | `EXTENSION_REQUEST`     | Inbound — payment lifecycle | Yes                        |
| 7   | `PARTIAL_PAYMENT_NOTE`  | Inbound — payment lifecycle | Yes                        |
| 8   | `ESCALATION_LEGAL`      | Inbound — safety            | No (immediate escalation)  |
| 9   | `INTERNAL_NOTE`         | Internal                    | N/A (not customer-facing)  |
| 10  | `UNCLASSIFIED`          | Catch-all                   | No (escalation required)   |
| 11  | `REMITTANCE_ADVICE`     | Inbound — payment lifecycle | Yes                        |
| 12  | `BALANCE_INQUIRY`       | Inbound — inquiry           | Yes                        |
| 13  | `CREDIT_NOTE_REQUEST`   | Inbound — invoice lifecycle | Yes (acknowledgement only) |
| 14  | `AUTO_REPLY`            | Inbound — non-actionable    | No (suppress; log only)    |
| 15  | `BILLING_UPDATE`        | Inbound — administrative    | Yes (confirmation only)    |


### 3.5 Confluence PRD Taxonomy Delta (Added 2026-04-08)

The Confluence "Basic use case and Fiori UI" page defines a **16-category taxonomy** that diverges from the 15-category taxonomy above. A full reconciliation is documented in **[ADR-008](decisions/ADR-008-taxonomy-reconciliation.md)**.

**Summary of gaps:**


| Confluence Category                                              | Local Equivalent            | Resolution (ADR-008)                                                                                         |
| ---------------------------------------------------------------- | --------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Proof of Delivery Request                                        | **MISSING**                 | `INVOICE_NOT_RECEIVED` + sub-category `POD_REQUEST`                                                          |
| Account Statement Request                                        | `BALANCE_INQUIRY` (partial) | `BALANCE_INQUIRY` + sub-category `STATEMENT_REQUEST`                                                         |
| Payment Method / Banking Inquiry                                 | **MISSING**                 | `BILLING_UPDATE` + sub-category `PAYMENT_METHOD_INQUIRY`                                                     |
| Stalling / Under Review                                          | **MISSING**                 | `PAYMENT_PROMISE` + sub-category `STALLING_UNDER_REVIEW`                                                     |
| 4 Dispute subtypes (Pricing, Short Payment, Returns, General)    | Single `INVOICE_DISPUTE`    | `INVOICE_DISPUTE` + sub-categories `PRICING`, `SHORT_PAYMENT`, `RETURNS_DAMAGES`, `GENERAL`                  |
| 3 Approval subtypes (Credit Memo, Write-Off, Dispute Resolution) | `INTERNAL_NOTE` (too broad) | `INTERNAL_NOTE` + sub-categories `APPROVAL_CREDIT_MEMO`, `APPROVAL_WRITE_OFF`, `APPROVAL_DISPUTE_RESOLUTION` |


**Multi-label requirement:** Confluence states "Multilabel should be possible for more complex scenarios." ADR-008 addresses this via a `categories` list field (all applicable labels), with the primary `category` driving routing. This supersedes D4 (section 6.2).

---

## 4. Functional Requirements Gap Analysis

### 4.1 Requirement-by-Requirement Review


| FR   | Title                           | Status    | Issues Identified                                                                                                                                                                                                                                                                                                                                                                                         |
| ---- | ------------------------------- | --------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| FR1  | Outlook Integration (Graph API) | Ambiguity | **A1:** The requirement specifies "read and send" but does not define whether "send" occurs through Graph API directly or through SAP/Alevate correspondence functionality. If SAP correspondence templates (FR11) are used, the send path may go through SAP, not Graph API. Resolution needed in ADR-005.                                                                                               |
| FR2  | Thread Awareness                | Ambiguity | **A2:** "No email in a thread may be silently ignored" is a strong constraint. It is unclear how this interacts with `AUTO_REPLY` emails (S12) — are they "ignored" or "acknowledged and suppressed"? Recommend clarifying that AUTO_REPLY emails are logged but exempt from draft generation.                                                                                                            |
| FR3  | Email Categorization            | Gap       | **G1:** The requirement references "the taxonomy defined below" but does not specify whether classification is single-label or multi-label. An email could simultaneously be a dispute AND a request for extension. The architecture must define whether multi-label classification is supported or whether a primary category with secondary intents is the model.                                       |
| FR4  | Intent Extraction               | Ambiguity | **A3:** Confidence level is defined as "numeric, 0-1" but the threshold for escalation (FR8) is not co-located. The non-functional requirements section mentions 0.75 as an example but frames it as a suggestion ("e.g., 0.75"). A definitive threshold must be set and documented in ADR-001.                                                                                                           |
| FR5  | Response Generation             | Gap       | **G2:** The requirement says "Where applicable, use SAP correspondence templates" but does not define the fallback when no template exists for a category. Must clarify: Does the system always require a template? Can it generate freeform responses for categories without templates? What is the approval difference?                                                                                 |
| FR6  | Human-in-the-Loop Approval      | Ambiguity | **A4:** "Every AI-generated response or system action must pass through an explicit approval step" — does this include logging actions (S7 confirmation logging, S10 remittance logging)? Pure logging with no outbound communication may not require the same approval gate. Recommend defining two tiers: (a) outbound communication approval (mandatory), (b) internal action approval (configurable). |
| FR7  | Completeness Tracking           | Valid     | No issues. Well-defined with clear outcome states.                                                                                                                                                                                                                                                                                                                                                        |
| FR8  | Escalation                      | Ambiguity | **A5:** "Low-confidence classifications" and "unrecognized intents" are listed as escalation triggers, but the requirement does not address high-confidence classifications of sensitive categories (e.g., `ESCALATION_LEGAL` at confidence 0.95). S8 specifies immediate escalation regardless of confidence. This exception should be codified in FR8.                                                  |
| FR9  | Audit Trail                     | Gap       | **G3:** The requirement specifies logging "the identity of the approver" but does not address the case where an email is auto-suppressed (AUTO_REPLY) or auto-classified with no approval needed. Must define audit requirements for all processing outcomes, not only approved ones.                                                                                                                     |
| FR10 | UC Requirements Traceability    | Valid     | This document satisfies FR10.                                                                                                                                                                                                                                                                                                                                                                             |
| FR11 | SAP Correspondence Templates    | Gap       | **G4:** No specification of how templates are versioned or how the system handles template changes between the time a draft is generated and the time it is approved. Stale template risk must be addressed.                                                                                                                                                                                              |
| FR12 | EU AI Act Compliance            | Valid     | Covered in `data-privacy.md` (Task 5). The five-step checklist from the UC page provides sufficient structure.                                                                                                                                                                                                                                                                                            |


### 4.2 Cross-Requirement Contradictions


| #   | Contradiction                                                                                                                                                                | Requirements Involved | Resolution                                                                                                                                                                                                                                                                                                      |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C1  | FR6 states "every action must pass through approval" but S8 states "escalate immediately." If escalation itself is an action, does it require approval before escalation?    | FR6 vs. S8            | **Resolution:** Escalation is a routing action, not a customer-facing action. FR6 approval applies only to outbound communications and ERP record updates. Escalation routing is exempt from approval but must be logged per FR9. Document in ADR-002.                                                          |
| C2  | FR2 states "no email may be silently ignored" but S12 (auto-reply) requires suppression.                                                                                     | FR2 vs. S12           | **Resolution:** Suppression is not the same as ignoring. An auto-reply is classified (`AUTO_REPLY`), logged, and marked as "no action required" — satisfying FR7 completeness tracking. FR2's constraint is met because the email is processed, just not drafted against. Clarify in the architecture overview. |
| C3  | FR5 references SAP correspondence templates but FR1 defines the send path through Graph API. If SAP templates are used, the send mechanism may be SAP-native, not Graph API. | FR1 vs. FR5 vs. FR11  | **Resolution:** The architecture must support two send paths: (a) Graph API for freeform/AI-drafted responses, (b) SAP correspondence for template-based responses. ADR-005 must address this dual-path design.                                                                                                 |


### 4.3 Ambiguities Requiring Architectural Decision


| #   | Ambiguity                                             | Affected FRs   | Resolution Vehicle    |
| --- | ----------------------------------------------------- | -------------- | --------------------- |
| A1  | Send path (Graph API vs. SAP correspondence)          | FR1, FR5, FR11 | ADR-005               |
| A2  | AUTO_REPLY handling vs. "no email ignored" constraint | FR2, FR7       | Architecture overview |
| A3  | Confidence threshold definition and ownership         | FR4, FR8       | ADR-001               |
| A4  | Approval tiers (outbound vs. internal actions)        | FR6            | ADR-002               |
| A5  | Category-based vs. confidence-based escalation logic  | FR8            | ADR-001               |


---

## 5. UC Requirements Traceability Matrix

### 5.1 UC Problem Statements Traceability

This table maps each UC Problem Statement to the scenarios and functional requirements that address it.


| UC Problem Statement | Description                                      | Addressed By Scenarios | Addressed By FRs    | Coverage Assessment                                                                              |
| -------------------- | ------------------------------------------------ | ---------------------- | ------------------- | ------------------------------------------------------------------------------------------------ |
| UC-PS1               | Operational Inefficiency — 50-200+ emails daily  | S1-S15 (all)           | FR1, FR3, FR4, FR5  | **Full** — Automated classification and draft generation directly reduce per-email handling time |
| UC-PS2               | Inconsistency and Errors — Manual classification | S4, S8, S12, S13       | FR3, FR4, FR8, FR9  | **Full** — Standardized taxonomy and confidence-based routing enforce consistency                |
| UC-PS3               | Workflow Bottlenecks — Email triage              | S1-S8, S12             | FR3, FR4, FR7, FR8  | **Full** — Automated categorization eliminates manual triage as bottleneck                       |
| UC-PS4               | Cognitive Overload — Context switching           | S2, S4, S9, S11, S13   | FR2, FR5, FR7, FR11 | **Full** — Thread awareness and context injection reduce cognitive burden on reviewers           |


### 5.2 UC Functional Requirements Traceability


| UC Functional Requirement | Description                                                                                                     | Addressed By Scenarios           | Addressed By FRs                                                        | Coverage Assessment                                                                                                                                                    |
| ------------------------- | --------------------------------------------------------------------------------------------------------------- | -------------------------------- | ----------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| UC-FR1                    | Instantly interprets incoming emails using contextual understanding across full threads                         | S1-S8, S10, S13                  | FR2 (Thread Awareness), FR4 (Intent Extraction)                         | **Full** — FR2 provides thread grouping; FR4 provides per-email interpretation                                                                                         |
| UC-FR2                    | Classifies messages into actionable categories (payment confirmation, dispute, invoice request, promise to pay) | S1-S8, S9-S15                    | FR3 (Email Categorization)                                              | **Full** — Taxonomy covers all four UC-cited categories plus eleven additional ones                                                                                    |
| UC-FR3                    | Provides transparent reasoning for categorization                                                               | S4, S8 (highest reasoning value) | FR4 (confidence level), FR9 (Audit Trail)                               | **Full** — FR4 outputs confidence scores; FR9 logs reasoning. ADR-001 must ensure the classifier prompt outputs chain-of-thought reasoning.                            |
| UC-FR4                    | Recommends most appropriate next step aligned with AR best practices                                            | S1-S8                            | FR5 (Response Generation), FR8 (Escalation)                             | **Full** — FR5 drafts responses; FR8 routes low-confidence cases. The ActionRouter agent (Task 7) maps intents to SAP/Alevate actions.                                 |
| UC-FR5                    | Generates accurate, professional response drafts using invoice data and historical context                      | S1-S7, S9-S11, S14-S15           | FR5 (Response Generation), FR2 (Thread Awareness), FR11 (SAP Templates) | **Full** — FR5 covers draft generation; FR2 provides history; FR11 provides templates. Context injection design (Task 7.4) defines how invoice data enters the prompt. |
| UC-FR6                    | Requires explicit user approval before taking any action                                                        | All scenarios                    | FR6 (Human-in-the-Loop Approval)                                        | **Full** — FR6 is the most prescriptive requirement. ADR-002 must define the approval UX and timeout behavior.                                                         |


### 5.3 UC Non-Autonomous Constraints Traceability


| UC Constraint | Description                               | Enforced By                       | Coverage Assessment                                                                                                                                                                                    |
| ------------- | ----------------------------------------- | --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| UC-C1         | Does not send emails automatically        | FR6 (approval gate before send)   | **Full** — Every outbound email requires human approval. Architecture must ensure no bypass path exists.                                                                                               |
| UC-C2         | Does not update ERP records independently | FR6 (approval gate before action) | **Partial** — FR6 covers this, but ambiguity A4 (approval tiers for logging vs. outbound) must be resolved. Pure logging actions (S7, S10) may be treated differently than record updates.             |
| UC-C3         | Does not escalate accounts without review | FR8 (escalation routing)          | **Full** — FR8 routes to human review. S8 explicitly prohibits auto-draft on legal/escalation emails. Contradiction C1 clarifies that escalation routing itself is exempt from approval but is logged. |


### 5.4 UC Metrics Traceability


| UC Metric | Description                                                        | Measured By                                                       | Architectural Support                                                                                                             |
| --------- | ------------------------------------------------------------------ | ----------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| UC-M1     | Increase AR Productivity (Emails per FTE, AHT)                     | FR7 (Completeness Tracking), FR9 (Audit Trail)                    | Audit trail timestamps enable AHT calculation. Completeness tracking provides throughput data.                                    |
| UC-M2     | Improve Accuracy & Reduce Risk (Error rate, Missed follow-up rate) | FR3 (Categorization), FR4 (Intent Extraction), FR7 (Completeness) | Classification accuracy measured via approval overrides (human corrects AI). Completeness tracking catches missed follow-ups.     |
| UC-M3     | Standardize Communication (SLA compliance rate)                    | FR5 (Response Generation), FR11 (SAP Templates)                   | Template-based drafting ensures standardization. SLA measured via processing timestamps in FR9.                                   |
| UC-M4     | Reduce Cognitive Load (% reduction in manual drafting time)        | FR5 (Response Generation), FR2 (Thread Awareness)                 | Draft acceptance rate (approved without edit vs. edited) is the key proxy metric. Thread summaries reduce context-switching cost. |
| UC-M5     | Maintain Full Control (% of emails sent with human approval)       | FR6 (Human-in-the-Loop)                                           | Must be 100% by design. Any value below 100% indicates a system defect. Audit trail (FR9) provides the data.                      |


### 5.5 UC Data & Inputs Traceability


| UC Data Requirement | Description                                                 | Addressed By FRs                                                   | Architectural Component                                                                 |
| ------------------- | ----------------------------------------------------------- | ------------------------------------------------------------------ | --------------------------------------------------------------------------------------- |
| UC-D1               | Connection to Email inbox (Outlook - Microsoft Graph)       | FR1 (Outlook Integration)                                          | ADR-005 defines the integration pattern (MCP tool, external bridge, or workflow node)   |
| UC-D2               | Connection to SAP for Customer master data and invoice data | FR4 (Intent Extraction context), FR5 (Response Generation context) | Context injection design (Task 7.4); SAP integration via existing ADR-003 (PAT Gateway) |
| UC-D3               | Connection to SAP for specific correspondence templates     | FR11 (SAP Correspondence Templates)                                | Template retrieval mechanism defined in architecture overview; caching strategy TBD     |


### 5.6 UC EU AI Act Checklist Traceability


| EU AI Act Step | Description                     | Addressed By            | Coverage Assessment                                                                                                                           |
| -------------- | ------------------------------- | ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| Step 1         | AI system identification        | FR12, `data-privacy.md` | **Full** — System is identified as an AI-assisted decision-support tool                                                                       |
| Step 2         | Prohibited AI practices check   | FR12, `data-privacy.md` | **Full** — System does not perform social scoring, manipulation, or real-time biometric identification                                        |
| Step 3         | High-risk categories assessment | FR12, `data-privacy.md` | **Requires analysis** — Financial services AI may qualify as high-risk under Annex III. Assessment must be documented.                        |
| Step 4         | Personal data processing check  | FR12, `data-privacy.md` | **Full** — Email content contains PII (names, addresses, account numbers). GDPR controls required.                                            |
| Step 5         | Anonymized training data check  | FR12, `data-privacy.md` | **Requires analysis** — If the system uses fine-tuned models or few-shot examples derived from real emails, anonymization requirements apply. |


### 5.7 Scenario-to-UC Mapping (Complete Matrix)


| Scenario                   | UC-FR1 | UC-FR2 | UC-FR3 | UC-FR4 | UC-FR5 | UC-FR6 | UC-C1 | UC-C2 | UC-C3 |
| -------------------------- | ------ | ------ | ------ | ------ | ------ | ------ | ----- | ----- | ----- |
| S1 — Payment overdue       | X      | X      |        | X      | X      | X      | X     |       |       |
| S2 — Invoice not received  | X      | X      | X      | X      | X      | X      | X     | X     |       |
| S3 — Promise to pay        | X      | X      | X      | X      | X      | X      |       | X     |       |
| S4 — Invoice dispute       | X      | X      | X      | X      | X      | X      | X     | X     |       |
| S5 — Unmatched payment     | X      | X      | X      | X      | X      | X      | X     |       |       |
| S6 — Extension request     | X      | X      | X      | X      | X      | X      | X     |       |       |
| S7 — Payment confirmation  | X      | X      | X      | X      | X      | X      |       | X     |       |
| S8 — Escalation/legal      | X      | X      | X      | X      |        | X      |       |       | X     |
| S9 — Invoice copy request  | X      | X      | X      | X      | X      | X      | X     | X     |       |
| S10 — Remittance advice    | X      | X      | X      | X      | X      | X      |       | X     |       |
| S11 — Balance inquiry      | X      | X      | X      | X      | X      | X      | X     |       |       |
| S12 — Auto-reply/OOO       | X      | X      |        |        |        |        |       |       |       |
| S13 — Multi-invoice thread | X      | X      | X      | X      | X      | X      | X     | X     |       |
| S14 — Credit note request  | X      | X      | X      | X      | X      | X      | X     | X     |       |
| S15 — Billing update       | X      | X      | X      | X      | X      | X      |       | X     |       |


**Legend:** X = Scenario exercises this UC requirement.

### 5.8 FR-to-UC Mapping (Complete Matrix)


| Functional Requirement      | UC-FR1 | UC-FR2 | UC-FR3 | UC-FR4 | UC-FR5 | UC-FR6 | UC-C1 | UC-C2 | UC-C3 | UC-D1 | UC-D2 | UC-D3 |
| --------------------------- | ------ | ------ | ------ | ------ | ------ | ------ | ----- | ----- | ----- | ----- | ----- | ----- |
| FR1 — Outlook Integration   | X      |        |        |        |        |        |       |       |       | X     |       |       |
| FR2 — Thread Awareness      | X      |        |        |        | X      |        |       |       |       |       |       |       |
| FR3 — Email Categorization  |        | X      |        |        |        |        |       |       |       |       |       |       |
| FR4 — Intent Extraction     | X      |        | X      | X      |        |        |       |       |       |       | X     |       |
| FR5 — Response Generation   |        |        |        | X      | X      |        |       |       |       |       | X     | X     |
| FR6 — Human-in-the-Loop     |        |        |        |        |        | X      | X     | X     | X     |       |       |       |
| FR7 — Completeness Tracking |        |        |        |        |        |        |       |       |       |       |       |       |
| FR8 — Escalation            |        |        | X      | X      |        |        |       |       | X     |       |       |       |
| FR9 — Audit Trail           |        |        | X      |        |        |        |       |       |       |       |       |       |
| FR10 — UC Traceability      |        |        |        |        |        |        |       |       |       |       |       |       |
| FR11 — SAP Templates        |        |        |        |        | X      |        |       |       |       |       |       | X     |
| FR12 — EU AI Act            |        |        |        |        |        | X      |       |       |       |       |       |       |


**Legend:** X = FR directly addresses this UC requirement.

### 5.9 UC Requirements Not Covered by Prompt Scenarios


| UC Requirement                              | Gap Description                                                                                                                                                                                                                         | Recommendation                                                                                                                                                                                 |
| ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| UC-M1 through UC-M5 (Metrics)               | Metrics are non-functional cross-cutting concerns. No single scenario "covers" a metric — they are measured across all scenarios.                                                                                                       | Ensure the audit trail (FR9) captures sufficient data for all five metrics. Define metric calculation formulas in `architecture-overview.md`.                                                  |
| UC-PS4 (Cognitive Overload)                 | While all scenarios benefit from reduced cognitive load, no scenario explicitly addresses the "context switching" dimension — i.e., how the system presents consolidated context to reduce switching between SAP, Outlook, and Alevate. | Address in the ReviewPresenter prompt (Task 7): the approval UI must present all relevant context (email, thread summary, SAP data, AI reasoning) in a single view.                            |
| EU AI Act Step 3 (High-risk assessment)     | The prompt acknowledges the EU AI Act checklist but does not pre-determine the high-risk classification outcome.                                                                                                                        | Document the assessment in `data-privacy.md`. If classified as high-risk, additional requirements (conformity assessment, CE marking, quality management system) must be added to the FR list. |
| EU AI Act Step 5 (Anonymized training data) | No scenario or FR explicitly addresses how training/fine-tuning data is sourced and anonymized.                                                                                                                                         | Add a recommendation to `data-privacy.md` specifying that any real email data used for prompt engineering or model fine-tuning must be anonymized per GDPR Article 89.                         |


---

## 6. Findings and Decisions

### 6.1 Summary of All Findings


| #   | Type                         | Finding                                                                     | Severity | Resolution                                                                                        | Status                      |
| --- | ---------------------------- | --------------------------------------------------------------------------- | -------- | ------------------------------------------------------------------------------------------------- | --------------------------- |
| F1  | Gap — Scenario               | Seven scenarios missing from S1-S8 (S9-S15)                                 | High     | Adopt all seven; S12 and S13 highest priority                                                     | Proposed                    |
| F2  | Gap — Taxonomy               | Five categories missing from seed taxonomy                                  | High     | Add `REMITTANCE_ADVICE`, `BALANCE_INQUIRY`, `CREDIT_NOTE_REQUEST`, `AUTO_REPLY`, `BILLING_UPDATE` | Proposed                    |
| F3  | Orphan — Taxonomy            | `PARTIAL_PAYMENT_NOTE` has no explicit scenario                             | Low      | Retain category; partial payment is a sub-case of S3/S7 that the classifier must handle           | Accepted                    |
| F4  | Ambiguity — FR1              | Send path unclear (Graph API vs. SAP correspondence)                        | Medium   | Resolve in ADR-005; support dual send path                                                        | Deferred to ADR-005         |
| F5  | Ambiguity — FR2              | "No email ignored" vs. AUTO_REPLY suppression                               | Low      | Suppression is not ignoring; clarify in architecture overview                                     | Accepted                    |
| F6  | Gap — FR3                    | Single-label vs. multi-label classification not specified                   | Medium   | Recommend single primary category with secondary intents in intent extraction output              | Proposed                    |
| F7  | Ambiguity — FR4/FR8          | Confidence threshold not definitively set                                   | Medium   | Define threshold in ADR-001; recommend 0.75 as default with per-category overrides                | Deferred to ADR-001         |
| F8  | Gap — FR5                    | No fallback defined when SAP template unavailable                           | Medium   | Define fallback to AI-generated freeform draft with explicit "no template" flag in approval UI    | Proposed                    |
| F9  | Ambiguity — FR6              | Approval scope unclear (outbound vs. logging actions)                       | Medium   | Define two approval tiers in ADR-002                                                              | Deferred to ADR-002         |
| F10 | Contradiction — FR6/S8       | Escalation routing vs. approval requirement                                 | Low      | Escalation is routing, not customer-facing action; exempt from approval                           | Accepted                    |
| F11 | Contradiction — FR2/S12      | Thread completeness vs. auto-reply suppression                              | Low      | Same as F5; suppression logged as "no action required" outcome                                    | Accepted                    |
| F12 | Contradiction — FR1/FR5/FR11 | Dual send path (Graph API vs. SAP correspondence)                           | Medium   | Same as F4; ADR-005 must address                                                                  | Deferred to ADR-005         |
| F13 | Gap — FR9                    | Audit trail does not cover non-approved outcomes                            | Low      | Extend FR9 to require audit logging for all processing outcomes                                   | Proposed                    |
| F14 | Gap — FR11                   | Template versioning and staleness not addressed                             | Low      | Add cache TTL and version check to template retrieval design                                      | Proposed                    |
| F15 | Gap — UC                     | EU AI Act high-risk classification not pre-determined                       | Medium   | Assess in `data-privacy.md`; if high-risk, add conformity requirements                            | Deferred to data-privacy.md |
| F16 | Gap — UC                     | Training data anonymization not addressed in FRs                            | Medium   | Add recommendation to `data-privacy.md`                                                           | Deferred to data-privacy.md |
| F17 | Gap — UC-PS4                 | Consolidated context presentation for cognitive load reduction not explicit | Medium   | Address in ReviewPresenter prompt design (Task 7)                                                 | Deferred to Task 7          |


### 6.2 Decisions Made in This Review


| Decision                                                                                                                                        | Rationale                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | Impact                                                                                                                           |
| ----------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| **D1:** Adopt S9-S15 as in-scope scenarios                                                                                                      | All seven represent real-world AR email patterns that would otherwise fall to UNCLASSIFIED, creating noise for human reviewers                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | Taxonomy expanded; classifier prompt must cover 15 categories; state machine grows                                               |
| **D2:** Add five new taxonomy categories                                                                                                        | Direct consequence of D1; each new scenario requires a distinct classification to enable appropriate routing and response generation                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | ADR-001 must define the complete 15-category taxonomy as the baseline                                                            |
| **D3:** Retain `PARTIAL_PAYMENT_NOTE` without dedicated scenario                                                                                | Partial payments are a recognized AR pattern; the category should exist even if triggered as a variant of S3/S7                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | No new scenario needed; classifier prompt must include partial payment examples                                                  |
| **D4:** ~~Define single-label classification with secondary intents~~ **Superseded by [ADR-008](decisions/ADR-008-taxonomy-reconciliation.md)** | ~~Multi-label classification increases system complexity and makes approval routing ambiguous (which category drives the response?)~~ **Update (2026-04-08):** The Confluence PRD ("Basic use case and Fiori UI") explicitly requires multi-label classification for complex scenarios (e.g., dispute + promise to pay in same email). ADR-008 adopts a hierarchical taxonomy: primary `category` (single label, drives routing) + `sub_category` (optional refinement) + `categories` list (all applicable labels). The primary label resolves the routing ambiguity D4 was designed to avoid, while the `categories` list satisfies the Confluence multi-label requirement. | FR3 updated; EmailClassifier outputs primary category + sub_category + multi-label categories list; primary label drives routing |
| **D5:** Escalation routing exempt from FR6 approval gate                                                                                        | Escalation is a safety mechanism that must not be delayed by approval queues                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | FR6 scope narrowed to outbound communications and ERP record updates                                                             |
| **D6:** AUTO_REPLY suppression satisfies FR2 completeness                                                                                       | Logging + "no action required" outcome meets the "no email ignored" constraint                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | FR2 interpretation clarified                                                                                                     |


### 6.3 Open Questions


| #   | Question                                                                                    | Owner                | Target Resolution               | Affects                          |
| --- | ------------------------------------------------------------------------------------------- | -------------------- | ------------------------------- | -------------------------------- |
| OQ1 | What is the definitive confidence threshold for escalation?                                 | Architecture Team    | ADR-001                         | FR4, FR8, EmailClassifier prompt |
| OQ2 | Should logging actions (S7, S10) require human approval?                                    | Product Owner        | ADR-002                         | FR6, ActionRouter prompt         |
| OQ3 | How are SAP correspondence templates versioned and cached?                                  | SAP Integration Team | Architecture overview           | FR11                             |
| OQ4 | Does the EU AI Act high-risk assessment (Annex III) apply to this system?                   | Legal/Compliance     | data-privacy.md                 | FR12                             |
| OQ5 | What languages beyond English must be supported at launch?                                  | Product Owner        | Non-functional requirements     | All prompts                      |
| OQ6 | What is the processing SLA (minutes from email receipt to draft availability)?              | Product Owner        | Non-functional requirements     | FR1, ADR-005                     |
| OQ7 | How should the system handle emails with attachments (PDFs, images) referenced in disputes? | Architecture Team    | ADR-001 / architecture overview | FR4, S4, S14                     |


---

*Part of the AR Email Management Domain — Financial System Modernization Project*