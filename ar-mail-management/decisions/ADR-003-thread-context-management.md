# ADR-003: Thread Context Management

**Status:** Proposed
**Date:** 2026-03-31
**Decision Makers:** AR Email Management Architecture Team
**Technical Story:** Email threads in AR workflows can grow to 20+ messages over weeks or months. LLM context windows are limited and expensive. Need a strategy for injecting relevant thread context into agent prompts without exceeding token budgets or losing critical historical information.

---

## Context and Problem Statement

AR email threads are fundamentally conversational: a payment reminder leads to a customer response, which leads to a follow-up, a dispute, a resolution, and so on. A single AR case can generate a thread with 5-30 email messages spanning weeks. When the AI pipeline processes a new inbound email, it needs context from the thread to classify correctly (is this a follow-up dispute or a new issue?), draft an appropriate response (reference the correct invoice numbers, prior agreements), and route the correct action (escalate if customer reneged on a payment promise).

Passing the entire thread to every agent in the pipeline is wasteful and, for long threads, infeasible. A 20-message thread with average message length of 500 tokens represents 10,000 tokens of raw content. With system prompts, SAP context, and response generation, the total context easily exceeds 20K tokens, increasing both cost and latency. More critically, long contexts dilute LLM attention on the most recent and relevant messages.

The solution must balance completeness of historical context against the practical constraints of token budgets, LLM attention degradation on long contexts, and per-call cost. The strategy must also be consistent across all agents in the pipeline: the classifier, summarizer, response drafter, and action router should all operate from the same contextual understanding of the thread.

## Decision Drivers

- **Bounded Context Size**: Total token budget per agent call must be predictable and capped, regardless of thread length
- **Recency Bias**: The most recent 2-3 messages contain the immediate context for classification and response; older messages are less likely to be directly relevant
- **Historical Preservation**: Key facts from early messages (original invoice number, agreed payment terms, prior promises) must not be lost even as the thread grows
- **Cost Predictability**: Token consumption per email should be approximately constant, not proportional to thread length
- **Cross-Agent Consistency**: All agents in the pipeline should work from the same thread context representation
- **Latency**: Context preparation must not add significant latency to the pipeline

---

## Considered Options

### Option 1: Progressive Summarization (Recommended)

**Description:** A dedicated ThreadSummarizer agent produces a running summary of the email thread. For each new inbound email, the agent receives the previous summary plus the new message and produces an updated summary. The downstream agents receive: (a) the updated summary covering all historical messages, and (b) the last 3 emails in full text. The summary is persisted and updated incrementally with each new message in the thread.

**Pros:**
- ✅ Bounded context size: ~4K tokens for summary + ~3K tokens for last 3 emails, regardless of thread length
- ✅ Preserves recent detail (full text of last 3 messages) for accurate classification and response
- ✅ Historical context maintained through summary (key facts, agreements, invoice numbers extracted)
- ✅ Summary is reusable across all agents in the pipeline (compute once, share across EmailClassifier, ResponseDrafter, ActionRouter)
- ✅ Summary is also displayed to human approvers in the queue item detail view (ADR-002)
- ✅ Cost per email is approximately constant: one summary update LLM call + fixed context injection

**Cons:**
- ❌ Summary quality depends on LLM; lossy compression may drop details from early messages
- ❌ Additional LLM call per email for summary update (adds cost and latency)
- ❌ Summary errors compound over time (if a key fact is dropped from the summary, it is lost for all future interactions)

**Cost:** Additional LLM call per email for summary update: ~$0.001-0.003 per email (smaller context, shorter output than classification).

---

### Option 2: Full Thread Injection

**Description:** Pass the entire email thread (all messages, chronologically ordered) to each agent in the pipeline. No summarization or truncation. Rely on LLM's native ability to extract relevant information from long contexts.

**Pros:**
- ✅ No information loss; every detail from every message is available
- ✅ Simplest implementation: no summarization logic, no persistence of summaries
- ✅ LLM can draw on any historical detail when needed

**Cons:**
- ❌ Context window overflow for long threads (20+ messages = 10K+ tokens, exceeding practical limits when combined with system prompt and SAP context)
- ❌ Cost scales linearly with thread length: long threads cost 3-5x more per agent call
- ❌ Dilutes LLM attention: studies show accuracy degrades when relevant information is buried in long contexts ("lost in the middle" effect)
- ❌ Latency scales with context size: longer prompts take longer to process
- ❌ Unpredictable token consumption makes cost estimation difficult

**Cost:** Varies: $0.002-0.015 per email depending on thread length. Average increases over thread lifetime.

---

### Option 3: Retrieval-Based (RAG)

**Description:** Store each email message as a separate document in a vector database (e.g., Azure AI Search, Elasticsearch with embeddings). When processing a new email, embed the query (new message + classification task) and retrieve the top-K most semantically relevant messages from the thread history. Pass only these retrieved messages to the agent.

**Pros:**
- ✅ Scales to any thread length (retrieval is O(log n) on indexed messages)
- ✅ Relevance-based: retrieves messages most similar to the current query context
- ✅ Can work across threads if needed (e.g., retrieve relevant messages from other AR cases with the same customer)

**Cons:**
- ❌ Complex infrastructure: requires vector database, embedding pipeline, indexing on each new message
- ❌ Semantic similarity may miss important but non-similar messages (e.g., an early message setting payment terms is factually critical but lexically different from a dispute email)
- ❌ Overkill for 90% of threads: most AR threads have <10 messages, well within context limits
- ❌ Retrieval latency (~100-300ms per query) adds to pipeline latency
- ❌ Embedding and indexing cost for every email message

**Cost:** Vector database: $50-150/month. Embedding calls: ~$0.001 per email. Retrieval: ~$0.0005 per query.

---

## Options Comparison Table

| Criteria | Progressive Summarization | Full Thread Injection | Retrieval-Based (RAG) |
|---|---|---|---|
| Context size (tokens) | ~7K (bounded) | 2K-15K+ (unbounded) | ~5K (bounded, top-K) |
| Information completeness | High (summary + recent) | Complete | Variable (depends on retrieval) |
| Cost per email | ~$0.003 (constant) | $0.002-0.015 (varies) | ~$0.004 (constant + infra) |
| Latency overhead | ~1-2s (summary LLM call) | 0s (no preprocessing) | ~200ms (retrieval) |
| Long thread handling | Excellent | Poor (overflow) | Excellent |
| Implementation complexity | Medium | Low | High |
| Cross-agent reusability | High (summary shared) | N/A (each agent gets full) | Medium (retrieval per query) |
| Infrastructure requirements | LLM + summary storage | None additional | Vector DB + embedding pipeline |

---

## Decision Outcome

**Chosen Option:** Option 1 - Progressive Summarization

### Rationale

1. **Bounded context size**: The progressive summarization approach guarantees a predictable context budget regardless of thread length. This is critical for cost predictability and LLM performance. Full thread injection (Option 2) degrades on long threads, and most AR threads will grow over weeks.
2. **Recency + history balance**: The "last 3 emails in full + summary of earlier" pattern preserves the detail that matters most (recent exchanges) while retaining historical facts (invoice numbers, prior agreements, payment promises) through the summary.
3. **Cross-agent reuse**: The summary is computed once by the ThreadSummarizer agent and shared across all downstream agents (EmailClassifier, ResponseDrafter, ActionRouter, ReviewPresenter). This avoids redundant processing and ensures all agents have the same contextual understanding.
4. **Human reviewer value**: The thread summary is also displayed to the human approver (ADR-002), providing immediate context without requiring them to read the full thread. This directly improves approval workflow efficiency.
5. **Infrastructure simplicity**: Unlike RAG (Option 3), progressive summarization requires no vector database, no embedding pipeline, and no retrieval infrastructure. The only requirement is persisting the current summary alongside the thread metadata.

### Implementation Summary

**Token Budget Allocation (16K total per agent call):**

| Allocation | Tokens | Purpose |
|---|---|---|
| System prompt | 4,000 | Agent instructions, taxonomy definitions, few-shot examples |
| Last 3 emails (full text) | 3,000 | Recent context for classification and response |
| Thread summary | 2,000 | Historical context from earlier messages |
| SAP context | 4,000 | Customer data, invoice details, payment history from SAP |
| Response generation buffer | 3,000 | Space for LLM to generate the output |
| **Total** | **16,000** | |

**ThreadSummarizer Agent:**
- Input: previous summary (or empty for first email) + new email message
- Output: updated summary (structured format with sections: Key Facts, Agreements, Open Issues, Timeline)
- Summary format: structured Markdown with labeled sections, not free-form prose
- Max summary length: 2,000 tokens (enforced via prompt instruction)
- Persistence: summary stored in CodeMie workflow context, keyed by thread ID

**Summary Structure:**
```
## Key Facts
- Invoice: INV-2024-1234, Amount: EUR 45,000
- Customer: Acme Corp, Account: ACC-9876

## Agreements & Promises
- 2026-03-15: Customer promised payment by 2026-03-25

## Open Issues
- Dispute on line item 3 (shipping charges)

## Timeline
- 2026-03-10: Initial reminder sent
- 2026-03-12: Customer responded, requested invoice copy
- 2026-03-15: Invoice resent, customer promised payment
```

---

## Consequences

### Positive

✅ Predictable and bounded context size per agent call regardless of thread length
✅ Consistent context across all agents in the pipeline (single source of truth)
✅ Cost per email is approximately constant, enabling accurate budget forecasting
✅ Thread summary serves dual purpose: agent context and human reviewer context
✅ No additional infrastructure beyond LLM and summary storage

### Negative

❌ Lossy compression: details from early messages may be dropped from summary if deemed low-relevance by the summarizer
❌ Additional LLM call per email adds ~1-2 seconds latency and ~$0.001-0.003 cost
❌ Summary quality degradation risk: errors in early summaries compound as the thread grows (incorrect facts propagate)

### Mitigation Strategies

**For summary quality and compounding errors:**
- Structured summary format (Key Facts, Agreements, Open Issues, Timeline) forces the summarizer to preserve specific detail categories rather than free-form summarization
- Periodic full-thread re-summarization: every 10 messages, regenerate the summary from the full thread (not incrementally) to correct any accumulated errors
- Human approvers can flag incorrect summaries, triggering a re-summarization

**For additional latency:**
- ThreadSummarizer runs as the second agent in the pipeline (after EmailClassifier); its output is cached and reused by all downstream agents
- Summary update can be parallelized with classification if the classifier does not need the updated summary (classifier uses previous summary + new email)

**For cost of additional LLM call:**
- Summary update uses a smaller, cheaper model (GPT-4o-mini) since the task is extractive rather than generative
- For threads with <4 messages, skip summarization and inject all messages in full text (below the 3,000-token last-3-emails budget)

---

## Implementation Notes

**MCP tooling (implemented):** The `get_thread(conversation_id)` and `summarize_thread(conversation_id)` MCP tools are implemented in `outlook-mcp-server` and use Graph API `conversationId` as the thread key — matching the thread correlation strategy described in ADR-005. The ThreadSummarizer agent pipeline (ADR-004) that orchestrates these tools is pending CodeMie implementation.

---

## Compliance & Security

**Security Controls:**
- Thread summaries are stored within the CodeMie tenant boundary; no cross-tenant access
- Summaries may contain PII from email content (customer names, invoice numbers); same data protection controls apply as for the source emails
- Summary storage follows the same retention policy as email thread metadata

**Compliance Impact:**
- GDPR: Thread summaries are derived data from emails processed under legitimate business interest. Right-to-erasure requests must include deletion of associated summaries
- SOC 2: Summary generation and storage are logged as part of the workflow execution audit trail
- Data Minimization: Summaries are designed to extract only business-relevant facts (invoices, amounts, dates, agreements), not reproduce full email content

---

## Cost Analysis

| Component | Cost | Notes |
|---|---|---|
| Summary LLM calls (update) | ~$100-300/month | ~$0.001-0.003 per email, 50K-100K emails/month |
| Summary storage | ~$5-10/month | Small text payloads stored in CodeMie workflow context |
| Periodic re-summarization | ~$20-50/month | Full-thread re-summarization every 10 messages (~10% of volume) |
| **Total** | **~$125-360/month** | |

**Comparison:**
- Full Thread Injection (Option 2): $0 additional preprocessing cost, but $150-750/month higher classification/drafting costs due to larger contexts
- RAG (Option 3): $50-150/month vector DB + ~$50-100/month embedding costs = $100-250/month infrastructure
- Progressive Summarization: Moderate preprocessing cost, but lowest total pipeline cost due to bounded downstream contexts

---

## Related Decisions

- **[ADR-001](ADR-001-email-categorization-approach.md)**: EmailClassifier receives the thread summary as part of its context input for classification
- **[ADR-002](ADR-002-human-in-the-loop-design.md)**: Thread summary is displayed to human approvers in the queue item detail view
- **[ADR-004](ADR-004-agent-design.md)**: ThreadSummarizer is the second agent in the multi-agent A2A pipeline

**Dependencies:**
- This decision depends on: ADR-004 (ThreadSummarizer is a named agent in the pipeline)
- This decision enables: ADR-001 (provides context for classification), ADR-002 (provides summary for human review)

---

## References

- [Lost in the Middle: How Language Models Use Long Contexts (Liu et al., 2023)](https://arxiv.org/abs/2307.03172)
- [Azure OpenAI Token Pricing](https://azure.microsoft.com/en-us/pricing/details/cognitive-services/openai-service/)
- [Progressive Summarization for Long Documents (Maynez et al.)](https://arxiv.org/abs/2004.15002)
- [CodeMie Workflow Context Storage](https://docs.codemie.com/workflows/context) (internal)

---

## Implementation Checklist

**Phase 1: ThreadSummarizer Agent** (Weeks 1-2)
- [ ] Design summary prompt with structured output format (Key Facts, Agreements, Open Issues, Timeline)
- [ ] Implement incremental summary update logic (previous summary + new email -> updated summary)
- [ ] Implement summary length enforcement (max 2,000 tokens)
- [ ] Deploy ThreadSummarizer as CodeMie assistant with A2A endpoint

**Phase 2: Context Assembly** (Weeks 2-3)
- [ ] Implement context assembly module: summary + last 3 emails + SAP context within 16K token budget
- [ ] Implement token counting and truncation logic for oversized individual components
- [ ] Wire context assembly into EmailClassifier, ResponseDrafter, and ActionRouter agents
- [ ] Unit tests for context assembly at various thread lengths (1, 3, 10, 20, 30 messages)

**Phase 3: Summary Persistence & Re-summarization** (Weeks 3-4)
- [ ] Implement summary storage in CodeMie workflow context, keyed by thread ID
- [ ] Implement periodic re-summarization trigger (every 10 messages)
- [ ] Implement human-triggered re-summarization (from approval queue)
- [ ] Integration test: full pipeline with 20-message thread

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
