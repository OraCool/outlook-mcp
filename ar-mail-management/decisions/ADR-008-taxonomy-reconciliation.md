# ADR-008: Taxonomy Reconciliation with Confluence PRD

**Status:** Accepted
**Date:** 2026-04-08
**Decision Makers:** AR Email Management Architecture Team
**Technical Story:** The Confluence PRD ("Basic use case and Fiori UI") defines a 16-category taxonomy with granular dispute subtypes and internal approval categories. The local architecture (ADR-001) defines a 15-category taxonomy. These have diverged, creating ambiguity about what the MCP server and CodeMie agents should implement.

---

## Context and Problem Statement

The AR Email Management solution has three layers of truth for email categorization:

1. **Confluence PRD** (source of business requirements): 16 categories including 4 dispute subtypes, 3 internal approval subtypes, POD requests, account statement requests, payment method inquiries, and a "stalling" category.
2. **Local architecture docs** (ADR-001, architecture-overview.md): 15 categories derived from scenario gap analysis (S1-S15) predating the finalized Confluence PRD.
3. **Outlook MCP Server** (implementation): 15 categories matching ADR-001 via configurable `CLASSIFICATION_CATEGORIES` env var.

The taxonomies have diverged in three dimensions:

- **Missing categories**: 8+ Confluence categories have no direct equivalent in the local taxonomy
- **Granularity mismatch**: Confluence splits disputes into 4 subtypes; local taxonomy has a single `INVOICE_DISPUTE`
- **Scope mismatch**: Confluence includes internal approval workflows (credit memo, write-off, dispute resolution); local taxonomy collapses these into `INTERNAL_NOTE`

Additionally, the Confluence PRD explicitly states: "Multilabel should be possible for more complex scenarios" — conflicting with decision D4 in `requirements-review.md` which chose single-label classification.

This ADR reconciles the taxonomies and establishes a single source of truth.

## Decision Drivers

- **Business alignment**: The Confluence PRD represents stakeholder-validated requirements; the taxonomy must support all 16 Confluence categories
- **Classification accuracy**: More categories dilute per-category training signal for the LLM; balance granularity vs. accuracy
- **Routing precision**: Dispute subtypes drive different SAP workflows (pricing dispute vs. returns dispute creates different dispute types in FS2/S4)
- **Backward compatibility**: The MCP server's `CLASSIFICATION_CATEGORIES` is configurable; existing deployments should not break
- **Multi-label support**: Complex emails (dispute + promise to pay + invoice copy request) need multi-label classification per Confluence requirement

---

## Taxonomy Delta Analysis

### Categories in Confluence PRD NOT in Local Docs (ADR-001)


| #   | Confluence Category                    | Confluence Action                    | Local Equivalent            | Gap Assessment                                                                |
| --- | -------------------------------------- | ------------------------------------ | --------------------------- | ----------------------------------------------------------------------------- |
| 1   | Proof of Delivery (POD) Request        | Send proof of delivery               | **MISSING**                 | Distinct workflow: requires SAP delivery note retrieval, not invoice          |
| 2   | Account Statement Request              | Send account statement               | BALANCE_INQUIRY (partial)   | BALANCE_INQUIRY covers "what's my balance?" but not "send me a statement PDF" |
| 3   | Payment Method / Banking Inquiry       | Provide payment details              | **MISSING**                 | Administrative query requiring company banking info, not invoice data         |
| 4   | Stalling / Under Review                | Follow up with deadline              | **MISSING**                 | Distinct from PAYMENT_PROMISE: customer is NOT committing to pay              |
| 5   | Dispute -- Pricing Issue               | Create pricing dispute               | INVOICE_DISPUTE (collapsed) | Different SAP dispute reason code                                             |
| 6   | Dispute -- Short Payment / Quantity    | Create short payment dispute         | INVOICE_DISPUTE (collapsed) | Different SAP dispute reason code                                             |
| 7   | Dispute -- Returns / Damages           | Create returns/damages dispute       | INVOICE_DISPUTE (collapsed) | Different SAP dispute reason code                                             |
| 8   | Dispute -- General / Unspecified       | Create and investigate dispute       | INVOICE_DISPUTE (collapsed) | Catch-all dispute subtype                                                     |
| 9   | Approval Request -- Credit Memo        | Approve or reject credit memo        | INTERNAL_NOTE (too broad)   | Distinct approval workflow in SAP                                             |
| 10  | Approval Request -- Write-Off          | Approve or reject write-off          | INTERNAL_NOTE (too broad)   | Distinct approval workflow in SAP                                             |
| 11  | Approval Request -- Dispute Resolution | Approve or reject dispute resolution | INTERNAL_NOTE (too broad)   | Distinct approval workflow in SAP                                             |


### Categories in Local Docs (ADR-001) NOT in Confluence PRD


| #   | Local Category        | Confluence Equivalent                    | Assessment                                                                                                                                                                                 |
| --- | --------------------- | ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | PAYMENT_REMINDER_SENT | N/A (outbound tracking)                  | Tracks our outbound action, not inbound customer intent; Confluence is inbound-only. **Retain** for pipeline completeness but mark as outbound.                                            |
| 2   | EXTENSION_REQUEST     | Promise to Pay / Payment Delay (partial) | Customer requests deadline extension. Confluence's "Promise to Pay / Payment Delay" is broader. **Retain** as distinct — extension requests trigger approval routing, promises are logged. |
| 3   | PARTIAL_PAYMENT_NOTE  | Dispute -- Short Payment (partial)       | Customer notes partial payment. Maps partially to short payment dispute but intent differs (informing vs. disputing). **Retain** as distinct.                                              |
| 4   | BILLING_UPDATE        | Non-AR relevant (partial)                | Customer requests billing info change. Confluence's "Non-AR / Informational" is broader. **Retain** — triggers SAP master data update workflow.                                            |
| 5   | CREDIT_NOTE_REQUEST   | Dispute -- General (partial)             | Customer requests credit note. Distinct from dispute — customer accepts the invoice but requests correction. **Retain** as distinct.                                                       |


---

## Considered Options

### Option A: Expand Flat Taxonomy to ~24 Categories

**Description:** Add all 11 missing Confluence categories to the existing 15, resulting in a flat taxonomy of ~24-26 categories (accounting for overlaps).

**Final category list (24):**

```
PAYMENT_REMINDER_SENT, INVOICE_NOT_RECEIVED, INVOICE_DISPUTE, PAYMENT_PROMISE,
PAYMENT_CONFIRMATION, EXTENSION_REQUEST, PARTIAL_PAYMENT_NOTE, ESCALATION_LEGAL,
INTERNAL_NOTE, UNCLASSIFIED, REMITTANCE_ADVICE, BALANCE_INQUIRY, CREDIT_NOTE_REQUEST,
AUTO_REPLY, BILLING_UPDATE,
+ POD_REQUEST, ACCOUNT_STATEMENT_REQUEST, PAYMENT_METHOD_INQUIRY, STALLING_UNDER_REVIEW,
+ DISPUTE_PRICING, DISPUTE_SHORT_PAYMENT, DISPUTE_RETURNS, DISPUTE_GENERAL,
+ APPROVAL_CREDIT_MEMO, APPROVAL_WRITE_OFF, APPROVAL_DISPUTE_RESOLUTION
```

(Note: `INVOICE_DISPUTE` retained as generic fallback; 4 subtypes are preferred when classifiable.)

**Pros:**

- Full alignment with Confluence PRD
- Each category maps to exactly one SAP workflow / action type
- Simple routing logic: `category -> action` is 1:1

**Cons:**

- 24 categories require 5-7 few-shot examples each = 120-168 examples in the classifier prompt
- Higher misclassification risk between similar categories (e.g., DISPUTE_PRICING vs. DISPUTE_SHORT_PAYMENT)
- Larger system prompt increases LLM cost per classification (~3K tokens -> ~5K tokens)

---

### Option B: Hierarchical Taxonomy with Primary + Sub-Label (Recommended)

**Description:** Maintain the 15 primary categories from ADR-001, but add a `sub_category` field for categories that have Confluence subtypes. The classifier outputs both a primary and an optional sub-category.

**Primary categories (15 — unchanged from ADR-001):**

```
PAYMENT_REMINDER_SENT, INVOICE_NOT_RECEIVED, INVOICE_DISPUTE, PAYMENT_PROMISE,
PAYMENT_CONFIRMATION, EXTENSION_REQUEST, PARTIAL_PAYMENT_NOTE, ESCALATION_LEGAL,
INTERNAL_NOTE, UNCLASSIFIED, REMITTANCE_ADVICE, BALANCE_INQUIRY, CREDIT_NOTE_REQUEST,
AUTO_REPLY, BILLING_UPDATE
```

**Sub-categories (new field, optional):**


| Primary                | Sub-Categories                                                                                  |
| ---------------------- | ----------------------------------------------------------------------------------------------- |
| `INVOICE_DISPUTE`      | `PRICING`, `SHORT_PAYMENT`, `RETURNS_DAMAGES`, `GENERAL`                                        |
| `INTERNAL_NOTE`        | `APPROVAL_CREDIT_MEMO`, `APPROVAL_WRITE_OFF`, `APPROVAL_DISPUTE_RESOLUTION`, `GENERAL_INTERNAL` |
| `INVOICE_NOT_RECEIVED` | `NOT_RECEIVED`, `COPY_REQUEST`, `POD_REQUEST`                                                   |
| `BALANCE_INQUIRY`      | `BALANCE_QUESTION`, `STATEMENT_REQUEST`                                                         |
| `BILLING_UPDATE`       | `ADDRESS_CHANGE`, `CONTACT_CHANGE`, `PAYMENT_METHOD_INQUIRY`                                    |
| `PAYMENT_PROMISE`      | `FIRM_COMMITMENT`, `STALLING_UNDER_REVIEW`                                                      |


**New classification output fields:**

```json
{
  "category": "INVOICE_DISPUTE",
  "sub_category": "PRICING",
  "categories": ["INVOICE_DISPUTE", "PAYMENT_PROMISE"],
  "confidence": 0.87,
  ...
}
```

- `category`: Primary label (one of 15 — backward-compatible)
- `sub_category`: Optional sub-label within the primary category
- `categories`: Multi-label list when email contains multiple intents

**Pros:**

- Backward-compatible: existing consumers that only read `category` are unaffected
- Primary taxonomy stays at 15 categories — proven classifier accuracy range
- Sub-categories provide Confluence-required granularity for SAP routing
- Multi-label via `categories` list addresses the Confluence multi-label requirement
- Fewer few-shot examples needed per primary category; sub-classification uses the same examples with refined instructions
- Progressive adoption: sub-categories can be empty initially and filled in as classifier accuracy improves

**Cons:**

- Two-level classification adds parsing complexity for consumers
- Sub-category accuracy may be lower than primary category accuracy (fewer training signals)
- Routing logic becomes: `category + sub_category -> action` (slightly more complex)

---

### Option C: Keep 15 Categories with Extended Metadata

**Description:** Keep the 15-category flat taxonomy unchanged. Map Confluence's granular categories to metadata fields in the classification intent output (`required_action`, `extracted_data`), not to taxonomy labels.

**Pros:**

- No taxonomy changes; maximum backward compatibility
- Simplest classifier prompt

**Cons:**

- Does not satisfy Confluence requirement for explicit dispute subtypes
- SAP routing for dispute types must parse free-text `required_action` instead of structured category
- Does not address multi-label requirement
- Divergence between Confluence and implementation persists

---

## Options Comparison


| Criteria                     | Option A: Flat 24           | Option B: Hierarchical              | Option C: Metadata Only    |
| ---------------------------- | --------------------------- | ----------------------------------- | -------------------------- |
| Confluence alignment         | Full                        | Full (via sub-categories)           | Partial                    |
| Backward compatibility       | Breaking (new categories)   | Non-breaking (`category` unchanged) | Full                       |
| Classification accuracy risk | Higher (more categories)    | Lower (15 primary + optional sub)   | Lowest                     |
| SAP routing precision        | Direct 1:1                  | 2-field lookup (category + sub)     | Requires free-text parsing |
| Multi-label support          | Requires separate mechanism | Built-in via `categories` list      | Not supported              |
| Prompt size increase         | ~60% more tokens            | ~20% more tokens                    | None                       |
| Implementation effort        | Medium                      | Medium                              | Low                        |
| Cold-start feasibility       | Lower (needs more examples) | Higher (progressive adoption)       | Highest                    |


---

## Decision Outcome

**Chosen Option:** Option B — Hierarchical Taxonomy with Primary + Sub-Label

### Rationale

1. **Backward compatibility**: The 15 primary categories are unchanged. Existing MCP server deployments, classifier prompts, and downstream consumers that read `category` continue to work without modification.
2. **Confluence alignment**: Every Confluence category maps to a `category + sub_category` pair. No PRD requirement is left unaddressed.
3. **Multi-label support**: The `categories` list field (new) enables multi-label classification for complex emails (e.g., dispute + promise to pay). This resolves the conflict with D4 in `requirements-review.md`.
4. **Classification accuracy**: Keeping 15 primary categories preserves the accuracy ceiling established in ADR-001. Sub-category classification is an incremental refinement that can be validated independently.
5. **Progressive adoption**: Sub-categories can be empty initially. As the classifier is fine-tuned with real data, sub-category accuracy improves without affecting the primary classification pipeline.
6. **SAP routing**: The ActionRouter agent can map `(category, sub_category)` pairs to specific SAP dispute reason codes, approval workflows, and document request types. This is more maintainable than parsing free-text intents.

### Multi-Label Decision

The `categories` list addresses the Confluence requirement for multi-label classification:

- `category` (string): The **primary** label — drives the main routing and response drafting
- `categories` (list): **All applicable** labels — enables the ReviewPresenter to show secondary intents and the ActionRouter to queue multiple actions
- Routing precedence: The primary `category` determines the main workflow; secondary labels in `categories` are informational or generate secondary action queue items

This supersedes D4 in `requirements-review.md` (single-label decision).

---

## Confluence-to-Taxonomy Mapping (Complete)


| Confluence Category                      | Primary (`category`)                          | Sub (`sub_category`)          | Notes                                                          |
| ---------------------------------------- | --------------------------------------------- | ----------------------------- | -------------------------------------------------------------- |
| Invoice Copy Request                     | `INVOICE_NOT_RECEIVED`                        | `COPY_REQUEST`                | Per requirements-review.md 3.3                                 |
| Proof of Delivery Request                | `INVOICE_NOT_RECEIVED`                        | `POD_REQUEST`                 | Document request, not invoice dispute                          |
| Account Statement Request                | `BALANCE_INQUIRY`                             | `STATEMENT_REQUEST`           | PDF statement, not just balance question                       |
| Payment Method / Banking Inquiry         | `BILLING_UPDATE`                              | `PAYMENT_METHOD_INQUIRY`      | Administrative, not payment action                             |
| Payment Confirmation / Remittance Advice | `PAYMENT_CONFIRMATION` or `REMITTANCE_ADVICE` | —                             | Local taxonomy already splits this correctly                   |
| Promise to Pay / Payment Delay           | `PAYMENT_PROMISE`                             | `FIRM_COMMITMENT`             | Explicit date commitment                                       |
| Stalling / Under Review                  | `PAYMENT_PROMISE`                             | `STALLING_UNDER_REVIEW`       | No firm commitment; follow-up needed                           |
| Dispute -- Pricing Issue                 | `INVOICE_DISPUTE`                             | `PRICING`                     | SAP dispute reason: pricing                                    |
| Dispute -- Short Payment / Quantity      | `INVOICE_DISPUTE`                             | `SHORT_PAYMENT`               | SAP dispute reason: quantity/amount                            |
| Dispute -- Returns / Damages             | `INVOICE_DISPUTE`                             | `RETURNS_DAMAGES`             | SAP dispute reason: returns                                    |
| Dispute -- General / Unspecified         | `INVOICE_DISPUTE`                             | `GENERAL`                     | SAP dispute reason: unspecified                                |
| Approval -- Credit Memo                  | `INTERNAL_NOTE`                               | `APPROVAL_CREDIT_MEMO`        | Internal approval workflow                                     |
| Approval -- Write-Off                    | `INTERNAL_NOTE`                               | `APPROVAL_WRITE_OFF`          | Internal approval workflow                                     |
| Approval -- Dispute Resolution           | `INTERNAL_NOTE`                               | `APPROVAL_DISPUTE_RESOLUTION` | Internal approval workflow                                     |
| Escalation / High-Risk                   | `ESCALATION_LEGAL`                            | —                             | Broadened from "legal only" to include high-risk accounts      |
| Non-AR / Informational                   | `AUTO_REPLY` or `UNCLASSIFIED`                | —                             | Auto-replies detected by rules; other non-AR classified by LLM |


---

## Impact on Existing Components


| Component                                                          | Change Required                                                                                      | Effort |
| ------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------- | ------ |
| **ADR-001** (EmailClassifier taxonomy)                             | Add note referencing ADR-008 for sub-categories                                                      | Low    |
| **requirements-review.md** D4                                      | Superseded by ADR-008 multi-label decision                                                           | Low    |
| **architecture-overview.md**                                       | Add sub-category field to EmailClassifier output description                                         | Low    |
| **EmailClassifier prompt** (`prompts/EmailClassifier.md`)          | Add `sub_category` and `categories` fields to JSON schema; add sub-category definitions and examples | Medium |
| **MCP Server `ClassificationResult`** (`models/email.py`)          | Add `sub_category`, `categories` fields with defaults                                                | Low    |
| **MCP Server classification prompt** (`tools/email_classifier.py`) | Update JSON schema and system prompt instructions                                                    | Medium |
| **MCP Server `CLASSIFICATION_CATEGORIES`** (`config.py`)           | Primary categories unchanged; add new `CLASSIFICATION_SUB_CATEGORIES` config                         | Low    |
| **ActionRouter prompt** (`prompts/ActionRouter.md`)                | Update action mapping to use `(category, sub_category)` pairs                                        | Medium |
| **State machine diagram**                                          | Add sub-category transitions                                                                         | Low    |


---

## Consequences

### Positive

- Full alignment with Confluence PRD taxonomy requirements
- Backward-compatible: primary `category` field unchanged
- Multi-label support via `categories` list resolves D4 conflict
- Progressive adoption: sub-categories can be empty initially
- SAP routing precision improved with 2-field lookup

### Negative

- Two-level classification increases prompt complexity (~20% more tokens)
- Sub-category accuracy may lag behind primary category accuracy at launch
- Consumers must handle optional `sub_category` field (null when not applicable)
- Routing logic becomes `(category, sub_category) -> action` rather than `category -> action`

### Mitigation

- **Sub-category accuracy**: Start with sub-categories only for high-impact categories (INVOICE_DISPUTE, INTERNAL_NOTE). Add others progressively.
- **Consumer complexity**: Provide a helper function that returns the full action mapping from `(category, sub_category)` pair.
- **Prompt size**: Sub-category examples reuse primary category examples with sub-label annotations — minimal token increase.

---

## Related Decisions

- **[ADR-001](ADR-001-email-categorization-approach.md)**: Establishes the 15-category taxonomy and hybrid rule+LLM approach. ADR-008 extends this with sub-categories.
- **[ADR-004](ADR-004-agent-design.md)**: ActionRouter agent must support `(category, sub_category)` routing.
- **Requirements Review D4**: Superseded. Multi-label classification adopted via `categories` list.

---

## References

- [Confluence: Basic use case and Fiori UI](https://serrala.atlassian.net/wiki/spaces/SAA/pages/6332284990) — 16-category taxonomy source
- [Confluence: Collections Email Agent PRD](https://serrala.atlassian.net/wiki/spaces/SAA/pages/6333104138) — structured JSON output requirements
- [Confluence: UC 2](https://serrala.atlassian.net/wiki/spaces/SAA/pages/6327959630) — problem statement and business requirements

---

## Change Log


| Date       | Author                                | Change                    |
| ---------- | ------------------------------------- | ------------------------- |
| 2026-04-08 | AR Email Management Architecture Team | Initial decision document |
| 2026-04-09 | AR Email Management Architecture Team | Status updated to Accepted — `ClassificationResult.sub_category` and `categories` fields implemented in `outlook-mcp-server` (`models/email.py`); classifier prompt updated. ActionRouter routing logic for sub-categories pending as part of the CodeMie pipeline (ADR-004) |


---

*Part of the AR Email Management Domain — Financial System Modernization Project*