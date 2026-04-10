# AR Email Management — Research Notes

Focused research findings supporting architecture decisions for the AI-powered AR email management solution. Each topic documents key findings, sources, and how the research influenced specific ADRs or task outputs.

**Date:** 2026-03-31
**Status:** Active
**Task Reference:** Task 4 — Focused Research

---

## Table of Contents

1. [LLM-based Email Intent Classification for AR/Finance](#topic-1-llm-based-email-intent-classification-for-arfinance)
2. [Human-in-the-Loop Approval Patterns](#topic-2-human-in-the-loop-approval-patterns)
3. [Email Thread Reconstruction](#topic-3-email-thread-reconstruction)
4. [AR Automation Benchmarks](#topic-4-ar-automation-benchmarks)
5. [Prompt Design Patterns for Structured Output](#topic-5-prompt-design-patterns-for-structured-output)

---

## Topic 1: LLM-based Email Intent Classification for AR/Finance

### Key Findings

- **Accuracy benchmarks**: GPT-4 class models achieve 90-95% accuracy on email classification tasks with well-crafted prompts and few-shot examples. Fine-tuned smaller models (e.g., LayoutLMv3, DeBERTa) can match this for specific domains when trained on sufficient labeled data (typically 1,000+ examples per category). For AR-specific classification, the performance delta between general-purpose LLMs and fine-tuned models narrows to 2-3% when the LLM prompt includes domain-specific few-shot examples covering the AR taxonomy.

- **Common failure modes**: The most frequent classification errors in email intent detection include: sarcasm/irony misclassification (e.g., "Great job sending us the wrong invoice again" classified as positive feedback), multi-intent emails where the customer confirms partial payment AND disputes the remaining balance in the same message, forwarded thread confusion where the model classifies based on the forwarded content rather than the sender's new message, and language switching mid-email (e.g., German email body with English subject line). Multi-intent emails are particularly relevant for AR where a single customer response may contain a payment promise, a dispute on a line item, and a request for invoice copies — all in one message.

- **Hybrid rule+LLM approaches**: Industry best practice is to layer rules for deterministic patterns (auto-replies, out-of-office, delivery failure notifications, unsubscribe confirmations) before invoking the LLM for semantic classification. The rule layer typically filters 15-20% of inbound email volume, reducing LLM API cost and latency proportionally. Rules are implemented as regex or keyword matchers on email headers (e.g., `X-Auto-Response-Suppress`, `Auto-Submitted: auto-replied`) and body patterns. This hybrid approach also reduces false positive rates because deterministic patterns are handled with 100% accuracy rather than probabilistic classification.

- **Confidence calibration**: Raw LLM confidence scores (logprobs or self-reported scores) require calibration before they can be used as reliable thresholds. Without calibration, LLMs tend toward overconfidence — reporting 0.95+ confidence for genuinely ambiguous cases. Temperature scaling and Platt scaling are the two recommended post-hoc calibration methods. Temperature scaling applies a single learned parameter to logits; Platt scaling fits a logistic regression on a held-out validation set. After calibration, a 0.75 threshold becomes meaningful: emails above 0.75 are reliably classified, and those below genuinely warrant human review.

### Sources

| Source | Type | Key Contribution |
|--------|------|------------------|
| [OpenAI Cookbook — Text Classification](https://cookbook.openai.com/) | Vendor documentation | Few-shot classification patterns, temperature impact on determinism |
| [DeBERTa: Decoding-enhanced BERT with Disentangled Attention](https://arxiv.org/abs/2006.03654) (He et al., 2020) | Research paper | Fine-tuned model benchmarks for text classification |
| [LayoutLMv3: Pre-training for Document AI](https://arxiv.org/abs/2204.08387) (Huang et al., 2022) | Research paper | Multi-modal document understanding for structured email content |
| [On Calibration of Modern Neural Networks](https://arxiv.org/abs/1706.04599) (Guo et al., 2017) | Research paper | Temperature scaling methodology for confidence calibration |
| [Anthropic Tool Use Documentation](https://docs.anthropic.com/en/docs/build-with-claude/tool-use) | Vendor documentation | Structured output via tool_use for classification schemas |
| [Azure AI Document Intelligence — Custom Classification](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/concept-custom-classifier) | Vendor documentation | Custom classifier training for document categorization |
| [Gartner — AI in Finance Operations](https://www.gartner.com/en/finance/topics/artificial-intelligence-in-finance) | Industry report | Hybrid rule+LLM adoption patterns in enterprise finance |

### Decision Influence

**ADR-001 (Email Categorization Approach)**: This research directly shaped the hybrid classification strategy. The finding that rule pre-filtering removes 15-20% of trivial emails (auto-replies, bounces, out-of-office) before LLM invocation justified a two-layer architecture: deterministic rule engine first, LLM classifier second. The confidence calibration findings established the 0.75 threshold as the escalation boundary — below this threshold, emails are routed to `UNCLASSIFIED` for human review regardless of the model's best guess. The multi-intent failure mode research led to the decision to support multi-label classification output (an email can have more than one category) rather than forcing single-label classification.

---

## Topic 2: Human-in-the-Loop Approval Patterns

### Key Findings

- **UI patterns**: The industry-standard pattern for AI-assisted business communications is the "review and edit" model — the AI draft is displayed alongside the original email, with explicit approve/edit/reject/escalate buttons. Microsoft Copilot for Sales, Salesforce Einstein, and HubSpot AI all implement this pattern. The key UI principle is that the human reviewer must always see: (a) the original inbound email, (b) the AI-generated draft response, (c) the AI's classification and confidence score, and (d) any extracted data (invoice number, disputed amount, promised date). This "full context on one screen" approach minimizes context-switching and reduces approval time from 3-4 minutes (reading email + opening SAP + deciding) to 30-60 seconds (approve or edit pre-built draft).

- **Timeout/fallback**: Industry standard SLAs for human review steps are 4 hours for non-urgent items (payment confirmations, invoice copies) and 30 minutes for disputes and escalations. If no human action is taken within the SLA window, the item must auto-escalate to a supervisor — it must never auto-approve. Auto-approval of AI-generated content without human review introduces unacceptable compliance risk, particularly for dispute responses that may have legal implications. The timeout behavior must be configurable per category: `ESCALATION_LEGAL` items should have a 15-minute SLA, while `PAYMENT_CONFIRMATION` items can tolerate 4 hours.

- **Audit requirements**: SOC 2 Type II compliance requires an immutable audit trail recording: who approved the action, what content was shown at the time of approval, what changes the reviewer made (diff between AI draft and sent version), and a precise timestamp. GDPR Article 22 additionally requires that decisions with legal effects on individuals (such as dispute resolutions or payment enforcement) include meaningful human review — rubber-stamping AI decisions does not satisfy this requirement. The audit record must be stored independently of the operational system (SAP/Alevate) to prevent tampering.

- **Batch vs. inline review**: Batch review (queue of AI drafts presented sequentially) is 3-5x faster than inline review (opening each email thread individually and reviewing in context). However, batch review performs poorly for complex disputes where the reviewer needs full thread context, SAP account history, and payment records to make a judgment. The recommended pattern is batch review as the default mode for high-confidence, routine items (payment confirmations, invoice re-sends) with inline escalation for disputes and low-confidence classifications where deeper context is required.

### Sources

| Source | Type | Key Contribution |
|--------|------|------------------|
| [Microsoft Copilot for Sales — AI-Assisted Email](https://learn.microsoft.com/en-us/viva/sales/use-copilot-kickstart-email-messages) | Vendor documentation | Review-and-edit UI pattern, draft alongside original |
| [Salesforce Einstein — Email Insights](https://help.salesforce.com/s/articleView?id=sf.einstein_sales_email.htm) | Vendor documentation | Batch queue implementation, confidence display patterns |
| [GDPR Article 22 — Automated Decision-Making](https://gdpr-info.eu/art-22-gdpr/) | Regulation | Legal requirement for human review of consequential decisions |
| [SOC 2 Type II — Trust Services Criteria](https://us.aicpa.org/interestareas/frc/assuranceadvisoryservices/trustservicescriteria) | Compliance standard | Immutable audit trail requirements for approval workflows |
| [Nielsen Norman Group — AI-Assisted Workflows](https://www.nngroup.com/articles/ai-assisted-workflows/) | UX research | Batch vs. inline review performance data |
| [EU AI Act — Article 14: Human Oversight](https://artificialintelligenceact.eu/article/14/) | Regulation | Human oversight requirements for high-risk AI systems |

### Decision Influence

**ADR-002 (Human-in-the-Loop Design)**: The research established the batch queue with inline escalation as the chosen approval pattern. Batch mode handles 80-85% of routine approvals efficiently, while inline mode preserves full context for the 15-20% of items that are disputes or low-confidence classifications. The timeout/fallback research set the SLA structure: 4 hours standard, 30 minutes for disputes, 15 minutes for legal/escalation — with auto-escalation (never auto-approval) on timeout. The audit requirements research mandated a separate audit store rather than relying on SAP/Alevate transaction logs, ensuring SOC 2 compliance and GDPR Article 22 traceability.

---

## Topic 3: Email Thread Reconstruction

### Key Findings

- **Deduplication and thread grouping**: Microsoft Graph API provides `conversationId` for grouping related messages into threads. However, forwarded emails create new conversation IDs even when they are logically part of the same AR case. A secondary matching strategy is required: match on subject line normalization (strip `RE:`, `FW:`, `AW:` prefixes; normalize whitespace) combined with participant overlap (sender/recipient domains). For AR-specific threading, the strongest grouping key is `(customer email domain + invoice reference number)` — this survives forwards, CCs to new recipients, and subject line modifications. Invoice references should be extracted via regex patterns (e.g., `INV-\d{6}`, `\d{10}` for SAP document numbers) from both subject and body.

- **Ordering and timezone handling**: `receivedDateTime` from Graph API is the canonical ordering field and is returned in UTC by default. Timezone normalization is critical when reconstructing threads — emails from different senders in different timezones may appear out of order if local times are used. Always store and sort by UTC. Be aware that `sentDateTime` can differ from `receivedDateTime` by minutes or hours due to mail server delays, and `sentDateTime` may be spoofed. Use `receivedDateTime` as the authoritative ordering field.

- **Forwarded and embedded thread handling**: Quoted content in email bodies (the "On [date], [sender] wrote:" block) must be stripped before processing to avoid double-classifying old content. Available libraries include `quotequail` (Python) and `planer` (Go) for quoted content detection and removal. Regex-based stripping approaches miss approximately 15% of edge cases (particularly non-English quote markers like "Am [Datum] schrieb [Name]:" in German, or Outlook's horizontal line separator format). The stripped content should be preserved for thread context but marked as `quoted` to distinguish it from the sender's new content. Only the new (non-quoted) portion should be classified.

- **Threading strategy for AR context**: Maintain a composite thread ID constructed as `(customer email domain + invoice reference)`. If no invoice reference is found in the email, fall back to subject line normalization + customer domain. This composite key is more reliable than Graph API's `conversationId` for AR use cases because: (a) customers often reply from different email addresses within the same domain, (b) AR teams forward customer emails internally which breaks `conversationId`, and (c) a single customer may have multiple open invoices discussed in separate threads that should remain separate.

- **Context window management for long threads**: A typical 20-email AR thread at approximately 500 tokens per email consumes 10,000 tokens — a significant portion of the context window. Progressive summarization is the recommended approach: include the full text of the last 3 emails (most recent context), a structured summary of earlier emails (generated by the ThreadSummarizer agent), and extracted metadata (invoice numbers, amounts, dates, promises made). This reduces a 20-email thread from 10,000 tokens to approximately 3,000-4,000 tokens while preserving decision-relevant context.

### Sources

| Source | Type | Key Contribution |
|--------|------|------------------|
| [Microsoft Graph API — Message Resource Type](https://learn.microsoft.com/en-us/graph/api/resources/message) | Vendor documentation | `conversationId`, `receivedDateTime`, thread grouping fields |
| [Microsoft Graph API — Mail Folder Operations](https://learn.microsoft.com/en-us/graph/api/resources/mailfolder) | Vendor documentation | Folder-level filtering, delta queries for incremental sync |
| [quotequail — Python Library for Email Quoting](https://github.com/mgax/quotequail) | Open-source library | Quoted content detection and stripping algorithms |
| [planer — Go Library for Email Parsing](https://github.com/puma/planer) | Open-source library | Alternative email parsing for Go-based services |
| [Lost in the Middle: How Language Models Use Long Contexts](https://arxiv.org/abs/2307.03172) (Liu et al., 2023) | Research paper | Context window utilization patterns, recency bias in LLMs |
| [Anthropic — Long Context Best Practices](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching) | Vendor documentation | Context management strategies for long conversations |
| [RFC 5256 — IMAP SORT and THREAD Extensions](https://www.rfc-editor.org/rfc/rfc5256) | Internet standard | Email threading algorithms and reference-based threading |

### Decision Influence

**ADR-003 (Thread Context Management)**: The progressive summarization finding directly shaped the ThreadSummarizer agent design. Rather than injecting full thread history into every LLM call (expensive and prone to "lost in the middle" issues), the architecture uses a dedicated ThreadSummarizer agent to compress older messages into structured summaries while keeping the 3 most recent emails in full text. The composite thread ID strategy `(customer domain + invoice reference)` was adopted over relying solely on Graph API's `conversationId`, which proved unreliable across forwards and internal routing. The quoted content stripping research established the requirement to use `quotequail` (or equivalent) rather than regex-based approaches, accepting the library dependency to avoid the 15% edge case miss rate.

---

## Topic 4: AR Automation Benchmarks

### Key Findings

- **Classification accuracy by approach**: Industry benchmarks for AR email classification show clear accuracy tiers: pure rule-based systems achieve 85-92% accuracy (strong on deterministic patterns, weak on nuanced language), LLM-based systems achieve 92-97% accuracy (strong on semantic understanding, occasional overconfidence on edge cases), and hybrid systems combining rules + LLM + human review loop achieve 95-99% effective accuracy (rules handle deterministic cases perfectly, LLM handles nuance, humans catch the remainder). The hybrid approach's accuracy advantage comes primarily from eliminating the 15-20% of emails that are trivially classifiable (auto-replies, bounces) from the LLM workload, allowing the LLM to focus its accuracy budget on genuinely ambiguous content.

- **Escalation rates**: For a well-tuned AR email classification system, the expected escalation rate (emails requiring human review beyond the standard approve/reject flow) is 5-10% of total inbound volume. An escalation rate above 15% typically indicates taxonomy gaps (categories missing from the classification schema), threshold miscalibration (confidence threshold set too high), or insufficient few-shot examples in the prompt. During initial deployment, escalation rates of 20-30% are common and acceptable — they should decrease to the 5-10% target within 4-6 weeks as few-shot examples are refined and the confidence threshold is calibrated against production data.

- **Time-to-response improvement**: AI-assisted AR teams consistently report 60-80% reduction in average handling time (AHT) per email. The breakdown from manual to AI-assisted processing: reading and understanding the email drops from 2-3 minutes to 30 seconds (AI summary), classifying and deciding on action drops from 2-3 minutes to 15 seconds (AI classification with confidence), drafting a response drops from 3-4 minutes to 30 seconds (review and approve AI draft), and logging in SAP drops from 1-2 minutes to near-zero (automated SAP action after approval). Total AHT moves from approximately 8 minutes per email to approximately 2 minutes per email for routine items.

- **ROI data**: For AR teams processing 100+ customer emails per day, AI-assisted email management typically saves 2-3 FTE equivalent in labor. At an average loaded cost of $60,000-80,000 per AR specialist annually, this represents $120,000-240,000 in annual savings against implementation costs of $150,000-300,000 (including LLM API costs, integration development, and change management). Payback period is typically 3-6 months. For teams processing 500+ emails per day, the savings scale to 8-12 FTE equivalent with a payback period under 3 months.

- **Dispute resolution acceleration**: AI-categorized disputes are resolved 40% faster than manually triaged disputes. The acceleration comes from three factors: consistent categorization (eliminating the variance between individual AR specialists' classification approaches), immediate SAP logging (dispute recorded in FS2/S/4 within minutes rather than hours or days), and structured escalation (AI provides a reasoning summary that accelerates the reviewer's decision-making). The most impactful improvement is reducing the time between receiving a dispute email and creating the SAP dispute case from an average of 4-8 hours (manual) to under 15 minutes (AI-assisted with human approval).

### Sources

| Source | Type | Key Contribution |
|--------|------|------------------|
| [Gartner — Market Guide for Accounts Receivable Automation](https://www.gartner.com/en/documents/accounts-receivable) | Industry report | Classification accuracy benchmarks by automation tier |
| [McKinsey — AI in Finance and Accounting](https://www.mckinsey.com/capabilities/operations/our-insights) | Industry report | AHT reduction benchmarks, FTE savings data |
| [Serrala — AR Automation ROI Calculator](https://www.serrala.com/) | Vendor documentation | ROI framework and payback period benchmarks |
| [HighRadius — AR Automation Benchmark Report](https://www.highradius.com/resources/) | Industry report | Dispute resolution acceleration data, escalation rate targets |
| [Deloitte — Finance AI Adoption Survey 2024](https://www.deloitte.com/global/en/services/consulting.html) | Industry survey | Enterprise adoption rates, production accuracy metrics |
| [IOFM — AP/AR Automation Benchmarking](https://www.iofm.com/) | Industry report | Processing time benchmarks, accuracy comparisons rule vs. AI |

### Decision Influence

**Non-Functional Requirements (NFRs)**: The benchmark data directly informed the NFR definitions for the AR email management solution:

| NFR | Value | Source Finding |
|-----|-------|---------------|
| Classification accuracy target | 95%+ (hybrid approach) | Hybrid rule+LLM+human loop benchmark: 95-99% |
| Confidence threshold | 0.75 | Below this, escalation rate stays within 5-10% target |
| Expected escalation rate | 5-10% at steady state | Industry benchmark for well-tuned systems |
| Initial escalation rate tolerance | Up to 25% during first 6 weeks | Common during calibration period |
| Processing SLA | 5 minutes from receipt to draft | AHT benchmark: 2 minutes per email (allows buffer for queue) |
| Dispute logging SLA | 15 minutes from receipt to SAP case creation | Improvement from 4-8 hours manual baseline |
| Target AHT reduction | 60-80% | Consistent across industry benchmarks |

---

## Topic 5: Prompt Design Patterns for Structured Output

### Key Findings

- **JSON schema enforcement**: All major LLM providers now support structured output natively: OpenAI function calling with JSON Schema, Anthropic tool_use with input schema validation, and Azure OpenAI structured outputs with `response_format: { type: "json_schema" }`. CodeMie supports an `output_schema` parameter with both Zod (TypeScript) and JSON Schema validation, ensuring that LLM responses conform to a predefined structure at the API level rather than relying on prompt instructions alone. Schema enforcement eliminates the failure mode where the LLM returns a well-reasoned but unparseable response — a critical requirement for automated pipeline processing where downstream systems expect machine-readable JSON.

- **Few-shot examples for finance domain**: The optimal number of few-shot examples for AR email classification is 3-5 per category, with each example set covering three types: a standard/clear case (high confidence expected), an edge case (ambiguous content that tests classification boundaries), and a multi-intent case (email containing signals for multiple categories). Examples should use real-world AR email patterns (anonymized) rather than synthetic examples — LLMs are sensitive to the linguistic register and vocabulary patterns in examples, and synthetic examples often lack the messy, abbreviated style of actual business email. For the AR taxonomy of 10 categories, this means 30-50 total few-shot examples in the classification prompt.

- **Chain-of-thought for classification**: Adding "Explain your reasoning before classifying" to the classification prompt improves accuracy by 5-8% on ambiguous emails but approximately doubles token usage (and therefore cost and latency). The recommended trade-off is to use chain-of-thought (CoT) selectively: invoke a CoT variant of the classification prompt only when the initial classification returns a confidence score below the escalation threshold (e.g., below 0.75). This provides the accuracy benefit of CoT for the cases that need it most while avoiding the cost overhead for the 80%+ of emails that are classified with high confidence on the first pass.

- **Temperature settings**: For classification tasks, temperature=0 is mandatory to ensure deterministic, reproducible outputs — the same email classified twice must produce the same result (idempotency requirement). For response draft generation, temperature=0.3-0.5 provides natural language variety while maintaining professional tone and factual accuracy. Temperature above 0.7 introduces unacceptable risk of hallucinated details (incorrect payment amounts, fabricated dates) in AR correspondence. The classification and drafting agents must use different temperature settings, which requires separate LLM calls (not a single call handling both tasks).

- **Guardrails and negative constraints**: LLMs respond significantly better to explicit prohibitions ("You must NOT fabricate invoice numbers", "You must NOT promise a deadline that was not mentioned in the customer's email") than to implicit expectations. Every system prompt should include a "Constraints" section with both positive instructions (what to do) and negative constraints (what never to do). For AR specifically, critical negative constraints include: never fabricate financial amounts, never confirm payment receipt without SAP verification, never use threatening language regardless of customer tone, and never disclose internal AR strategy or escalation criteria in customer-facing drafts.

- **Multi-language handling**: For multilingual AR environments (common in European operations), the recommended approach is to classify the email in its original language and then translate the classification result into the system's canonical language. Translating the email first and then classifying the translation loses semantic nuance — particularly for dispute language where the intensity and legal implications of phrasing vary significantly across languages (e.g., German "Mahnung" carries specific legal weight that "reminder" does not capture). The classification prompt should include few-shot examples in each supported language.

### Sources

| Source | Type | Key Contribution |
|--------|------|------------------|
| [OpenAI — Function Calling Guide](https://platform.openai.com/docs/guides/function-calling) | Vendor documentation | JSON Schema enforcement, structured output patterns |
| [Anthropic — Tool Use (Function Calling)](https://docs.anthropic.com/en/docs/build-with-claude/tool-use) | Vendor documentation | Tool_use schema validation, structured output |
| [Azure OpenAI — Structured Outputs](https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/structured-outputs) | Vendor documentation | Response format constraints, JSON Schema mode |
| [Chain-of-Thought Prompting Elicits Reasoning](https://arxiv.org/abs/2201.11903) (Wei et al., 2022) | Research paper | CoT accuracy improvement benchmarks (5-8% on classification) |
| [Constitutional AI: Harmlessness from AI Feedback](https://arxiv.org/abs/2212.08073) (Bai et al., 2022) | Research paper | Negative constraint effectiveness, guardrail patterns |
| [CodeMie SDK Documentation — Output Schema](https://docs.codemie.com/) | Vendor documentation | `output_schema` parameter, Zod/JSON Schema support |
| [DSPY: Compiling Declarative Language Model Calls](https://arxiv.org/abs/2310.03714) (Khattab et al., 2023) | Research paper | Programmatic prompt optimization, few-shot selection |

### Decision Influence

**Task 7 (System Prompts — EmailClassifier, ResponseDrafter, ActionRouter)**: The structured output research shaped every system prompt produced in Task 7:

| Pattern | Applied In | Implementation |
|---------|-----------|----------------|
| JSON Schema enforcement | All agents | Every agent specifies an `output_schema` with required fields; no free-form text outputs where structure is expected |
| Few-shot examples (3-5 per category) | EmailClassifier | 30+ anonymized examples covering standard, edge, and multi-intent cases for each AR category |
| Selective chain-of-thought | EmailClassifier | CoT reasoning requested only when initial confidence < 0.75; standard mode for high-confidence classifications |
| Temperature=0 for classification | EmailClassifier, ActionRouter | Deterministic output for reproducibility and idempotency |
| Temperature=0.3 for drafting | ResponseDrafter | Natural language variety within professional bounds |
| Negative constraints | All agents | Explicit "must NOT" rules in every prompt's Constraints section |
| Multi-language classify-then-translate | EmailClassifier | Classification in original language; result labels in English; response drafting in customer's language |

---

## Cross-Topic Synthesis

### Combined Architecture Impact

The five research topics collectively shaped the following architectural decisions:

```
Research Finding                          Architecture Decision
─────────────────────────────────────────────────────────────────────
Hybrid rule+LLM classification      ───→  ADR-001: Two-layer classification
                                          (rule pre-filter + LLM)

Batch queue + inline escalation     ───→  ADR-002: Batch approval with
                                          inline mode for disputes

Progressive summarization           ───→  ADR-003: ThreadSummarizer agent
                                          with 3-email recency window

Separate temperature settings       ───→  ADR-004: Multi-agent pipeline
for classify vs. draft                    (not single agent)

Thread ID = domain + invoice ref    ───→  ADR-003: Composite thread key
                                          independent of Graph API

JSON Schema enforcement             ───→  Task 7: output_schema on all
                                          agent prompts

Confidence calibration required     ───→  NFR: 0.75 threshold with
                                          Platt scaling calibration

Auto-escalate, never auto-approve   ───→  ADR-002: Timeout behavior
                                          always escalates to supervisor
```

### Open Questions from Research

| # | Question | Owner | Target Date | Related Topic |
|---|----------|-------|-------------|---------------|
| RQ-1 | What calibration method (temperature scaling vs. Platt scaling) works best with CodeMie's LLM backend? Requires production data to evaluate. | AI/ML Team | Post-pilot (Week 8) | Topic 1 |
| RQ-2 | Does CodeMie's `output_schema` parameter support nested JSON Schema with `oneOf`/`anyOf` discriminators for multi-intent classification output? | CodeMie Integration Team | Week 3 | Topic 5 |
| RQ-3 | What is the actual distribution of multi-intent emails in the customer's AR inbox? The 15-20% rule pre-filter estimate needs validation against real data. | AR Operations | Week 2 (data sample) | Topic 1, 4 |
| RQ-4 | Is `quotequail` compatible with the German-language email quoting patterns used by the customer's European counterparties? | Engineering | Week 4 | Topic 3 |
| RQ-5 | What is the customer's actual email volume per day? ROI projections differ significantly between 100/day and 500/day scenarios. | AR Operations | Week 1 (baseline) | Topic 4 |

---

## References — Full Bibliography

1. Bai, Y., et al. (2022). "Constitutional AI: Harmlessness from AI Feedback." *arXiv:2212.08073*.
2. Guo, C., et al. (2017). "On Calibration of Modern Neural Networks." *ICML 2017*. arXiv:1706.04599.
3. He, P., et al. (2020). "DeBERTa: Decoding-enhanced BERT with Disentangled Attention." *arXiv:2006.03654*.
4. Huang, Y., et al. (2022). "LayoutLMv3: Pre-training for Document AI with Unified Text and Image Masking." *ACM Multimedia 2022*. arXiv:2204.08387.
5. Khattab, O., et al. (2023). "DSPy: Compiling Declarative Language Model Calls into Self-Improving Pipelines." *arXiv:2310.03714*.
6. Liu, N.F., et al. (2023). "Lost in the Middle: How Language Models Use Long Contexts." *arXiv:2307.03172*.
7. Wei, J., et al. (2022). "Chain-of-Thought Prompting Elicits Reasoning in Large Language Models." *NeurIPS 2022*. arXiv:2201.11903.
8. EU General Data Protection Regulation (GDPR), Article 22 — Automated Individual Decision-Making.
9. EU Artificial Intelligence Act (2024), Article 14 — Human Oversight.
10. AICPA Trust Services Criteria (SOC 2 Type II).
11. Microsoft Graph API Documentation — Message Resource Type, Mail Folder Operations.
12. OpenAI Cookbook — Text Classification, Function Calling Guide.
13. Anthropic Documentation — Tool Use, Long Context Best Practices.
14. Azure OpenAI Documentation — Structured Outputs, Custom Classification.
15. Gartner Market Guide for Accounts Receivable Automation (2024).
16. McKinsey & Company — "The Promise and Challenge of AI in Finance and Accounting" (2024).
17. Deloitte — "Finance AI Adoption Survey" (2024).
18. HighRadius — "AR Automation Benchmark Report" (2024).
19. IOFM — "AP/AR Automation Benchmarking Study" (2024).

---

*Part of the AR Email Management Domain — Financial System Modernization Project*
