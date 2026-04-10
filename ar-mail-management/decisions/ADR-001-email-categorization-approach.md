# ADR-001: Email Categorization Approach

**Status:** Proposed
**Date:** 2026-03-31
**Decision Makers:** AR Email Management Architecture Team
**Technical Story:** Need to classify inbound AR emails into actionable categories reliably to enable automated response drafting and action routing.

---

## Context and Problem Statement

The AR Email Management solution processes inbound emails across Accounts Receivable workflows. Each email must be classified into one of several actionable categories so the downstream agents (response drafter, action router) can act on it appropriately. Classification accuracy directly impacts the quality of AI-generated drafts and the efficiency of the human approval workflow.

Inbound AR emails span a wide range of intents: payment confirmations, invoice disputes, extension requests, auto-replies, remittance advice, and more. Some of these are trivially classifiable (auto-replies follow deterministic patterns), while others require semantic understanding of business context (e.g., distinguishing a payment promise from a partial payment notification). The solution must handle both cases efficiently without over-investing LLM calls on trivial classifications.

The target taxonomy consists of 15 categories. Misclassification has different severity levels: classifying a dispute as a payment confirmation could lead to missed escalation deadlines, while misclassifying an auto-reply wastes human reviewer time but causes no business harm. The classification system must balance accuracy, cost, and latency.

## Decision Drivers

- **Accuracy**: Must achieve 95%+ combined classification accuracy across all categories to minimize human correction overhead
- **Cost Efficiency**: LLM calls are the primary cost driver; reducing unnecessary LLM invocations directly impacts operational cost
- **Latency**: Classification must complete within 2-3 seconds to keep total pipeline latency under 15 seconds
- **Maintainability**: The system must be adaptable as new email patterns emerge without full model retraining
- **Determinism**: Known patterns (auto-replies, out-of-office) should be classified identically every time, without LLM variability
- **Auditability**: Classification decisions must be traceable for compliance and debugging

---

## Considered Options

### Option 1: Hybrid Rule + LLM Classification (Recommended)

**Description:** A two-layer classification system. The first layer is a deterministic rule engine that matches known patterns (auto-reply headers, out-of-office keywords, known template signatures, bounce-back formats). Emails that match rules are classified immediately without an LLM call. The remaining emails pass to an LLM-based classifier that uses few-shot prompting with structured JSON output to assign one of the 15 taxonomy categories along with a confidence score.

**Pros:**
- ✅ Reduced LLM costs: 15-20% of email volume filtered by deterministic rules
- ✅ Deterministic handling of known patterns eliminates classification variability for trivial emails
- ✅ LLM focuses its context window and attention on genuinely ambiguous cases
- ✅ 95-99% combined accuracy (rules: ~100% on matched patterns, LLM: 92-97% on remainder)
- ✅ Rule layer adds <10ms latency; only LLM layer contributes meaningful processing time
- ✅ Rules are transparent and auditable; LLM outputs include confidence scores

**Cons:**
- ❌ Two systems to maintain: rule engine definitions and LLM prompt/few-shot examples
- ❌ Rule drift risk if email patterns change (e.g., new auto-reply formats from mail providers)
- ❌ Boundary cases where rule engine and LLM could disagree on classification

**Cost:** Rule engine: negligible compute. LLM layer: ~$0.002-0.005 per email (Azure OpenAI GPT-4o pricing for ~2K input + 200 output tokens).

---

### Option 2: Pure LLM Classification

**Description:** Send every inbound email to an LLM with few-shot examples and a structured output schema. The LLM classifies the email into one of the 15 taxonomy categories and returns a confidence score. No pre-filtering.

**Pros:**
- ✅ Single system to maintain; all classification logic lives in the prompt
- ✅ Handles novel and unexpected email patterns gracefully
- ✅ Simpler deployment: one agent, one prompt, one configuration

**Cons:**
- ❌ Higher cost: every email requires an LLM call, including trivially classifiable auto-replies
- ❌ Overkill for auto-replies and out-of-office messages (wastes tokens on deterministic content)
- ❌ 92-97% accuracy ceiling; LLM occasionally misclassifies edge cases
- ❌ LLM variability: same auto-reply email may receive slightly different confidence scores across runs
- ❌ Higher latency for every email (1-3 seconds even for trivial classifications)

**Cost:** ~$0.002-0.005 per email across 100% of volume (vs. 80-85% for hybrid).

---

### Option 3: ML Model (Fine-tuned Classifier)

**Description:** Train a dedicated text classification model (e.g., fine-tuned BERT or DistilBERT) on labeled AR email data. The model outputs one of the 15 categories with a confidence score. Deployed as a lightweight inference endpoint.

**Pros:**
- ✅ Fastest inference (~50ms per email vs. 1-3 seconds for LLM)
- ✅ Lowest per-call cost (~$0.0001 per email on dedicated GPU inference)
- ✅ Can achieve very high accuracy (97%+) with sufficient, high-quality training data

**Cons:**
- ❌ Requires labeled training data: minimum 500-1,000 examples per category (7,500-15,000 total)
- ❌ Does not generalize to new categories without retraining
- ❌ Ongoing retraining pipeline needed as email patterns evolve
- ❌ Cold start problem: no labeled data exists for AR Email Management domain yet
- ❌ Cannot leverage email context (thread history, SAP data) as effectively as LLM

**Cost:** Model training: $500-2,000 per training cycle. Inference: ~$200-400/month for dedicated GPU endpoint.

---

## Options Comparison Table

| Criteria | Hybrid Rule + LLM | Pure LLM | Fine-tuned ML Model |
|---|---|---|---|
| Accuracy | 95-99% combined | 92-97% | 97%+ (with good data) |
| Per-email cost | ~$0.002 (80-85% of volume) | ~$0.003 (100% of volume) | ~$0.0001 |
| Latency | <10ms (rules) / 1-3s (LLM) | 1-3s (all emails) | ~50ms |
| Cold start feasibility | High (rules + few-shot) | High (few-shot only) | Low (needs labeled data) |
| Maintenance burden | Medium (rules + prompts) | Low (prompts only) | High (retraining pipeline) |
| Novel pattern handling | Good (LLM layer) | Best | Poor (requires retraining) |
| Auditability | High (rules deterministic) | Medium (LLM outputs vary) | Medium (model is black box) |
| Time to production | 2-3 weeks | 1-2 weeks | 8-12 weeks (data + training) |

---

## Decision Outcome

**Chosen Option:** Option 1 - Hybrid Rule + LLM Classification

### Rationale

1. **Cold start feasibility**: No labeled training data exists for the AR Email Management domain. The hybrid approach works immediately with hand-crafted rules for known patterns and few-shot LLM prompting for the rest. A fine-tuned ML model (Option 3) is not viable at launch.
2. **Cost optimization**: The rule layer filters 15-20% of volume (auto-replies, out-of-office, bounces) at near-zero cost, saving an estimated 15-20% on LLM spend per month.
3. **Determinism where it matters**: Auto-reply and out-of-office detection should be 100% deterministic. These are high-volume, low-value emails that do not benefit from LLM reasoning.
4. **Accuracy ceiling**: The hybrid approach achieves higher combined accuracy (95-99%) than pure LLM (92-97%) because the rule layer eliminates an entire class of misclassification errors.
5. **Future migration path**: As labeled data accumulates from human approvals, the LLM layer can be partially replaced by a fine-tuned model (Option 3) for the most common categories, further reducing cost.

### Implementation Summary

**Rule Engine Layer:**
- Pattern matching on email headers (`X-Auto-Reply`, `Auto-Submitted`, `X-Autoreply`)
- Keyword detection for out-of-office patterns across 5 languages (EN, DE, FR, ES, IT)
- Known template signature matching (invoice portal auto-acknowledgments)
- Bounce-back detection via SMTP status codes in body
- Output: category + `rule_id` for audit trail

**LLM Classification Layer:**
- Azure OpenAI GPT-4o with few-shot prompting (5-7 examples per category)
- Structured JSON output: `{ "category": "...", "confidence": 0.0-1.0, "reasoning": "..." }`
- Confidence threshold: 0.75 -- below this, classify as `UNCLASSIFIED` and escalate to human
- System prompt includes the full 15-category taxonomy with definitions and examples

**Taxonomy (15 categories):**

| Category | Description |
|---|---|
| PAYMENT_REMINDER_SENT | Acknowledgment that payment reminder was received |
| INVOICE_NOT_RECEIVED | Customer claims invoice was not received |
| INVOICE_DISPUTE | Customer disputes invoice amount or validity |
| PAYMENT_PROMISE | Customer promises to pay by a specific date |
| PAYMENT_CONFIRMATION | Customer confirms payment was made |
| EXTENSION_REQUEST | Customer requests payment deadline extension |
| PARTIAL_PAYMENT_NOTE | Customer notes partial payment was sent |
| ESCALATION_LEGAL | Legal department involvement or legal threats |
| INTERNAL_NOTE | Internal team communication (not customer-facing) |
| UNCLASSIFIED | Below confidence threshold or unrecognized intent |
| REMITTANCE_ADVICE | Customer sends remittance/payment details |
| BALANCE_INQUIRY | Customer asks about outstanding balance |
| CREDIT_NOTE_REQUEST | Customer requests a credit note |
| AUTO_REPLY | Automated reply (out-of-office, auto-acknowledgment) |
| BILLING_UPDATE | Customer requests billing information change |

---

## Consequences

### Positive

✅ Immediate production readiness without labeled training data
✅ Reduced LLM costs through deterministic pre-filtering of trivial emails
✅ Higher combined accuracy than any single approach at launch
✅ Full audit trail with rule IDs and LLM confidence scores
✅ Natural migration path to fine-tuned models as data accumulates

### Negative

❌ Two systems (rule engine + LLM) increase maintenance surface area
❌ Rule drift requires periodic review as email provider auto-reply formats evolve
❌ Boundary cases between rule and LLM layers need careful handling to avoid conflicts

### Mitigation Strategies

**For rule drift:**
- Quarterly review of rule hit rates; rules with declining match rates are flagged for update
- Monitor false-positive rate on rule-classified emails through human approval feedback

**For boundary conflicts:**
- Rule engine takes priority (deterministic > probabilistic)
- Rules only fire on high-confidence patterns (explicit header presence, not fuzzy keyword matching)
- Unmatched-by-rules emails always go to LLM regardless of apparent simplicity

**For maintenance burden:**
- Rule definitions stored as structured configuration (YAML/JSON), not hardcoded
- LLM few-shot examples versioned alongside prompts in the CodeMie assistant configuration
- Dashboard tracking per-category accuracy enables targeted improvements

---

## Compliance & Security

**Security Controls:**
- Email content processed within CodeMie tenant boundary; no data leaves the tenant
- LLM classification prompts do not include customer PII beyond what is in the email body
- Classification results stored with audit metadata (timestamp, rule_id or LLM model version, confidence)

**Compliance Impact:**
- GDPR: Email content processed as part of legitimate business interest (AR management). No additional PII exposure beyond existing email handling
- SOC 2: Classification audit trail supports access monitoring and anomaly detection requirements
- Data Retention: Classification metadata follows the same retention policy as the source emails

---

## Cost Analysis

| Component | Cost | Notes |
|---|---|---|
| Rule Engine (compute) | ~$0/month | Negligible CPU; runs as part of existing service |
| LLM Classification (Azure OpenAI) | ~$200-500/month | Assumes 50,000-100,000 emails/month at ~$0.003/email for 80-85% of volume |
| Monitoring & Logging | ~$20-50/month | Azure Monitor / Application Insights |
| **Total** | **~$220-550/month** | |

**Comparison:**
- Pure LLM (Option 2): ~$250-650/month (15-20% higher LLM costs)
- Fine-tuned ML (Option 3): ~$700-2,400/month initially (training + inference endpoint), dropping to ~$200-400/month steady state
- Hybrid approach: Best cost at launch, competitive at steady state

---

## Related Decisions

- **[ADR-004](ADR-004-agent-design.md)**: EmailClassifier is the first agent in the multi-agent pipeline
- **[ADR-003](ADR-003-thread-context-management.md)**: Classification prompt receives thread summary as context input
- **[ADR-002](ADR-002-human-in-the-loop-design.md)**: UNCLASSIFIED emails route to the approval queue with elevated priority
- **[ADR-008](ADR-008-taxonomy-reconciliation.md)**: Extends this ADR's 15-category taxonomy with a `sub_category` field and multi-label `categories` list to align with the Confluence PRD; the 15 primary categories are unchanged (backward-compatible)

**Dependencies:**
- This decision depends on: ADR-004 (agent pipeline defines how classifier is invoked)
- This decision enables: ADR-002 (classification output drives approval queue priority routing), ADR-008 (extends this taxonomy)

---

## References

- [Azure OpenAI Service Pricing](https://azure.microsoft.com/en-us/pricing/details/cognitive-services/openai-service/)
- [Microsoft Graph API - Mail Resource](https://learn.microsoft.com/en-us/graph/api/resources/mail-api-overview)
- [Few-Shot Classification with LLMs (OpenAI Cookbook)](https://cookbook.openai.com/examples/classification_using_embeddings)
- [Email Header Analysis - Auto-Submitted (RFC 3834)](https://datatracker.ietf.org/doc/html/rfc3834)

---

## Implementation Checklist

**Phase 1: Rule Engine** (Weeks 1-2)
- [ ] Define rule configuration schema (YAML/JSON)
- [ ] Implement auto-reply header detection rules
- [ ] Implement out-of-office keyword detection (5 languages)
- [ ] Implement bounce-back SMTP status detection
- [ ] Unit tests for all rule patterns with sample emails

**Phase 2: LLM Classifier** (Weeks 2-4)
- [ ] Design system prompt with 15-category taxonomy and definitions
- [ ] Curate 5-7 few-shot examples per category (75-105 examples total)
- [ ] Implement structured JSON output parsing with confidence extraction
- [ ] Implement confidence threshold routing (>=0.75 classified, <0.75 UNCLASSIFIED)
- [ ] Integration test with CodeMie assistant via A2A endpoint

**Phase 3: Integration & Monitoring** (Weeks 4-5)
- [ ] Wire rule engine as pre-filter before LLM classifier in agent pipeline
- [ ] Deploy classification accuracy dashboard (per-category metrics)
- [ ] Configure alerting for accuracy drops below 90% on any category
- [ ] Document rule maintenance procedure and review cadence

---

## Change Log

| Date | Author | Change |
|------|--------|--------|
| 2026-03-31 | AR Email Management Architecture Team | Initial decision document |

---

## Review and Approval

**Reviewed by:**
- Pending review

**Approved by:**
- Pending approval

---

*Part of the AR Email Management Domain - Financial System Modernization Project*
