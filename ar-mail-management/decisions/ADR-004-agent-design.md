# ADR-004: Agent Design

**Status:** Proposed
**Date:** 2026-03-31
**Decision Makers:** AR Email Management Architecture Team
**Technical Story:** Need to decide the architecture for the AI processing pipeline: whether to use a single monolithic assistant, a multi-agent pipeline with specialized agents, or a workflow-based approach with LLM nodes. The choice impacts accuracy, latency, auditability, and development team autonomy.

---

## Context and Problem Statement

The AR Email Management pipeline must perform multiple distinct tasks for each inbound email: classify the email into a category, summarize the thread history, draft a response, determine the appropriate action (SAP booking, escalation, follow-up), and present the result for human approval. Each task has different accuracy requirements, different prompt engineering needs, and different failure modes.

A single assistant approach bundles all responsibilities into one LLM call with a complex prompt. While simple to deploy, this creates a monolithic system where a classification error cascades into an incorrect draft and wrong action routing, with no per-step confidence tracking to detect the failure. A multi-agent approach separates responsibilities but introduces orchestration complexity and inter-agent communication overhead.

CodeMie provides two relevant mechanisms: **Assistants** (autonomous agents with tool access, invokable via A2A protocol) and **Workflows** (deterministic step sequences with branching, PAUSED state support, and integration with external APIs). The question is how to combine these mechanisms for the AR email pipeline while supporting both Alevate (interactive) and SAP (headless-only) integration paths.

## Decision Drivers

- **Per-Step Accuracy**: Each pipeline step (classify, summarize, draft, route) should have independent accuracy tracking and confidence scoring
- **Auditability**: Each step must produce a logged, inspectable output for compliance and debugging
- **Latency Budget**: Total pipeline latency should be <15 seconds end-to-end (excluding human approval wait time)
- **SAP Headless Support**: The pipeline must be invokable via `POST /v1/a2a/assistants/{assistant_id}` without interactive UI
- **Team Autonomy**: Different team members should be able to develop and test individual agents independently
- **Failure Isolation**: A failure in one step (e.g., response drafting) should not corrupt the outputs of previous steps (classification, summarization)
- **Reusability**: Individual agents (e.g., EmailClassifier) may be reused in other pipelines beyond AR Email Management

---

## Considered Options

### Option 1: Multi-Agent Pipeline via A2A (Recommended)

**Description:** Five specialized agents chained in sequence: EmailClassifier, ThreadSummarizer, ResponseDrafter, ActionRouter, and ReviewPresenter. Each agent is a CodeMie Assistant with a focused system prompt and tool access, invoked via the A2A (Agent-to-Agent) protocol endpoint. A CodeMie Workflow orchestrates the sequence, providing deterministic step ordering, conditional branching, and the PAUSED state for human approval.

**Agent Responsibilities:**

| Agent | Input | Output | Tools |
|---|---|---|---|
| EmailClassifier | New email + thread summary | Category + confidence | Rule engine lookup |
| ThreadSummarizer | Previous summary + new email | Updated summary | None (pure LLM) |
| ResponseDrafter | Classification + summary + SAP context | Draft response | SAP data retrieval |
| ActionRouter | Classification + draft | Suggested SAP action | SAP action catalog |
| ReviewPresenter | All outputs assembled | Queue item for approval | Queue API |

**Pros:**
- ✅ Independent confidence tracking per step: each agent outputs a confidence score that can be monitored and alerted on
- ✅ Each agent has a focused prompt (single responsibility), producing better accuracy than a multi-task prompt
- ✅ Agents are reusable independently: EmailClassifier can serve other pipelines that need email classification
- ✅ Per-step audit trail: every agent invocation is logged with input, output, latency, and confidence
- ✅ Parallel development: different team members can develop and test agents independently
- ✅ Failure isolation: if ResponseDrafter fails, classification and summarization outputs are preserved

**Cons:**
- ❌ Higher latency: serial A2A calls add ~1-2 seconds per agent (5 agents = ~5-10s overhead)
- ❌ More complex orchestration: workflow must handle inter-agent data passing, error handling, and retries
- ❌ JWT/header propagation across A2A chain requires careful configuration (PingOne token must flow through)

**Cost:** 5 LLM calls per email (though ThreadSummarizer uses GPT-4o-mini). Total: ~$0.008-0.015 per email.

---

### Option 2: Single Assistant

**Description:** One CodeMie Assistant handles the entire pipeline in a single LLM call. The system prompt includes instructions for classification, summarization, drafting, and action routing. The assistant produces a structured JSON output containing all results.

**Pros:**
- ✅ Lowest latency: single LLM call (3-5 seconds total)
- ✅ Simplest deployment: one assistant, one prompt, one A2A endpoint
- ✅ Single context window: all information available to all tasks simultaneously
- ✅ No inter-agent communication overhead

**Cons:**
- ❌ Prompt overload: a single prompt handling 5 distinct responsibilities is difficult to engineer and maintain
- ❌ No per-step confidence: the assistant outputs a single result; if classification is wrong, the draft is wrong, with no signal indicating which step failed
- ❌ Single point of failure: any prompt regression affects all pipeline outputs simultaneously
- ❌ Harder to debug: when output is incorrect, must determine which of 5 responsibilities failed
- ❌ Not reusable: the monolithic assistant is specific to the AR email pipeline
- ❌ Testing is all-or-nothing: cannot unit test classification independently from drafting

**Cost:** 1 LLM call per email, but with larger context: ~$0.005-0.010 per email.

---

### Option 3: Workflow with LLM Nodes

**Description:** A CodeMie Workflow with deterministic step sequencing. Some steps are rule-based (deterministic routing), and some steps invoke LLM nodes for specific tasks (classification, drafting). The LLM nodes are lightweight tool calls within the workflow engine, not full CodeMie Assistants.

**Pros:**
- ✅ Deterministic control flow: workflow engine handles sequencing, branching, and error handling
- ✅ Uses CodeMie workflow PAUSED state natively for human approval
- ✅ Mix of rule-based and LLM steps: rule steps are fast and cheap, LLM steps only where needed
- ✅ Workflow definition is version-controlled and inspectable

**Cons:**
- ❌ Less flexible than A2A: workflow LLM nodes have limited tool access compared to full Assistants
- ❌ Workflow definition is static: adding a new step requires updating the workflow definition (vs. adding a new agent)
- ❌ LLM nodes in workflows may not support the same prompt engineering capabilities (system prompts, few-shot examples) as full Assistants
- ❌ Agents are not reusable outside the workflow; they exist only as workflow nodes

**Cost:** Similar to multi-agent: multiple LLM calls, but potentially cheaper due to simpler node prompts: ~$0.006-0.012 per email.

---

## Options Comparison Table

| Criteria | Multi-Agent via A2A | Single Assistant | Workflow with LLM Nodes |
|---|---|---|---|
| Per-step confidence | Yes (each agent) | No (single output) | Partial (LLM nodes only) |
| Latency | 8-15s (serial agents) | 3-5s (single call) | 6-12s (sequential nodes) |
| Prompt quality | High (focused prompts) | Low (overloaded prompt) | Medium (node prompts) |
| Auditability | High (per-agent logs) | Low (single output) | Medium (per-node logs) |
| Reusability | High (agents independent) | None | None (workflow-specific) |
| Team autonomy | High (parallel development) | None (single prompt) | Medium (node-level work) |
| Failure isolation | High (per-step) | None | Medium (per-node) |
| SAP headless support | Yes (A2A endpoint) | Yes (A2A endpoint) | Yes (workflow API) |
| Development complexity | High | Low | Medium |
| Cost per email | $0.008-0.015 | $0.005-0.010 | $0.006-0.012 |

---

## Decision Outcome

**Chosen Option:** Option 1 - Multi-Agent Pipeline via A2A, with a hybrid enhancement: use a CodeMie **Workflow** as the orchestrator with **A2A calls** to specialized Assistants at each LLM step.

### Rationale

1. **Per-step confidence is non-negotiable**: In a financial domain, knowing that classification was 95% confident but response drafting was only 70% confident is critical information for the human approver. A single assistant (Option 2) cannot provide this.
2. **Audit trail depth**: Each agent invocation generates a separate log entry with input, output, latency, model version, and confidence. This satisfies compliance requirements for traceability of AI-generated financial communications.
3. **Focused prompts produce better results**: A classifier prompt optimized for classification outperforms a multi-task prompt that must also handle summarization, drafting, and routing. Research consistently shows that single-task prompts outperform multi-task prompts in accuracy.
4. **Reusability**: The EmailClassifier agent can be reused for other email processing pipelines (e.g., incoming vendor emails, support tickets). A monolithic assistant cannot be decomposed.
5. **Workflow as orchestrator**: Using a CodeMie Workflow to sequence the A2A calls combines the best of Options 1 and 3. The workflow provides deterministic control flow, branching, and PAUSED state, while A2A calls provide full Assistant capabilities (tool access, rich prompts) at each step.

### Implementation Summary

**Pipeline Architecture:**

```
[Inbound Email]
       |
  [CodeMie Workflow - Orchestrator]
       |
       ├── Step 1: A2A → EmailClassifier Agent
       │   └── Output: category, confidence, rule_id (if rule-matched)
       |
       ├── Step 2: A2A → ThreadSummarizer Agent
       │   └── Output: updated thread summary
       |
       ├── Step 3: [Branch] If category == AUTO_REPLY → Skip to Step 5 (no draft needed)
       |
       ├── Step 4: A2A → ResponseDrafter Agent
       │   └── Input: classification + summary + SAP context
       │   └── Output: draft response text
       |
       ├── Step 5: A2A → ActionRouter Agent
       │   └── Output: suggested SAP action (booking code, escalation target, follow-up date)
       |
       ├── Step 6: A2A → ReviewPresenter Agent
       │   └── Output: formatted queue item for human approval
       |
       ├── Step 7: PAUSED → Wait for human approval (ADR-002)
       |
       └── Step 8: [Resume] Execute approved action (send email via Graph API, trigger SAP action)
```

**SAP Headless Path:**
- SAP triggers the pipeline via `POST /v1/a2a/assistants/{assistant_id}` with the email payload
- The A2A-invoked workflow receives the SAP-originated JWT transparently via the PAT Gateway (Multi-Tenancy ADR-003)
- Human approval at Step 7 occurs within SAP's workflow task interface (ADR-002)
- The workflow resume signal comes from SAP's task completion callback

**Inter-Agent Data Passing:**
- Workflow context carries all outputs from previous steps
- Each A2A call includes relevant prior outputs as structured input (not raw pipeline dump)
- Example: ResponseDrafter receives `{ classification: {...}, summary: "...", sap_context: {...} }`, not the full pipeline state

---

## Consequences

### Positive

✅ Per-step confidence tracking enables targeted quality improvement (focus on the weakest agent)
✅ Full audit trail per agent invocation satisfies financial compliance requirements
✅ Focused prompts per agent produce higher accuracy than monolithic prompts
✅ Agents are independently testable, deployable, and reusable
✅ Workflow orchestrator provides deterministic control flow with PAUSED state for human approval
✅ Pipeline is extensible: adding a new step (e.g., SentimentAnalyzer) requires only adding a new agent and workflow step

### Negative

❌ Higher total latency (8-15 seconds) compared to single assistant (3-5 seconds)
❌ Orchestration complexity: workflow must handle A2A call failures, timeouts, and retries
❌ JWT/header propagation across A2A chain must be configured correctly to maintain identity context
❌ 5 LLM calls per email increases cost compared to single-call approach

### Mitigation Strategies

**For latency:**
- Parallelize where possible: EmailClassifier and ThreadSummarizer can run in parallel (classifier uses previous summary, not updated one)
- Use GPT-4o-mini for ThreadSummarizer (faster inference, lower cost for an extractive task)
- Target: <12 seconds average pipeline latency with parallelization

**For orchestration complexity:**
- CodeMie Workflow engine handles retry logic, timeout, and error routing natively
- Each A2A call has a 10-second timeout with one retry; if both fail, workflow routes to manual handling
- Circuit breaker pattern: if an agent fails 3 times in 5 minutes, route all emails to manual queue

**For JWT propagation:**
- Follow Multi-Tenancy ADR-012 (PingOne Token Propagation to Custom MCP) for A2A header forwarding
- Workflow orchestrator propagates the originating JWT to each A2A call automatically
- Integration tests validate token propagation through the full 5-agent chain

**For cost:**
- ThreadSummarizer and ReviewPresenter use GPT-4o-mini (cheaper, sufficient for their tasks)
- AUTO_REPLY emails skip ResponseDrafter and ActionRouter (workflow branching), saving 2 LLM calls
- Estimated savings: 15-20% of emails skip drafting, reducing average cost per email

---

## Compliance & Security

**Security Controls:**
- Each A2A call carries the originating user's PingOne JWT; no elevation of privilege across agents
- Agent prompts and system instructions are stored in CodeMie's assistant configuration, not in client-facing code
- All agent inputs and outputs are logged in CodeMie's execution audit log
- Agents have least-privilege tool access: only ResponseDrafter has SAP data retrieval tools; only ReviewPresenter has queue API access

**Compliance Impact:**
- GDPR: Email content flows through the agent pipeline within the CodeMie tenant boundary. No external data sharing
- SOC 2: Per-agent audit trail provides granular evidence of AI processing steps for each email
- Financial Regulation: The PAUSED workflow state ensures no AI-generated action executes without human approval, regardless of which agent produced it

---

## Cost Analysis

| Component | Cost | Notes |
|---|---|---|
| EmailClassifier (GPT-4o) | ~$200-500/month | ~$0.003/email, 50K-100K emails/month |
| ThreadSummarizer (GPT-4o-mini) | ~$50-150/month | ~$0.001/email, cheaper model |
| ResponseDrafter (GPT-4o) | ~$150-400/month | ~$0.003/email, 80-85% of volume (AUTO_REPLY skipped) |
| ActionRouter (GPT-4o) | ~$100-250/month | ~$0.002/email, 80-85% of volume |
| ReviewPresenter (GPT-4o-mini) | ~$30-80/month | ~$0.001/email, formatting only |
| Workflow orchestration | ~$10-20/month | CodeMie workflow execution costs |
| **Total** | **~$540-1,400/month** | |

**Comparison:**
- Single Assistant (Option 2): ~$250-1,000/month (fewer calls but larger context per call)
- Workflow with LLM Nodes (Option 3): ~$400-1,200/month (similar call count, less capable)
- Multi-Agent Pipeline: Higher cost but significantly better accuracy, auditability, and reusability

---

## Related Decisions

- **[ADR-001](ADR-001-email-categorization-approach.md)**: EmailClassifier agent implements the hybrid rule + LLM classification approach
- **[ADR-002](ADR-002-human-in-the-loop-design.md)**: Workflow PAUSED state at Step 7 implements the human approval queue
- **[ADR-003](ADR-003-thread-context-management.md)**: ThreadSummarizer agent implements progressive summarization
- **[ADR-005](ADR-005-outlook-integration-pattern.md)**: Graph API Bridge triggers the workflow; approved email is sent via Graph API at Step 8
- **[ADR-006](ADR-006-ui-triggered-email-processing-delegated-mcp.md)**: UI-triggered pull path — uses a LangGraph ReAct agent (not CodeMie A2A) to invoke the Outlook MCP Server directly. ADR-004's CodeMie multi-agent pipeline applies to the webhook push path (ADR-005) only. The two paths share the same downstream agents after the initial email fetch step.
- **[Multi-Tenancy ADR-003](../../multytenancy/decisions/ADR-003-sap-pat-to-codemie-gateway.md)**: SAP PAT Gateway provides JWT for headless A2A invocation
- **[Multi-Tenancy ADR-012](../../multytenancy/decisions/ADR-012-pingone-token-propagation-to-custom-mcp.md)**: PingOne token propagation across A2A chain
- **[Multi-Tenancy ADR-020](../../multytenancy/decisions/ADR-020-headless-api-integration-pattern.md)**: Headless API pattern for SAP integration

**Dependencies:**
- This decision depends on: Multi-Tenancy ADR-003 (PAT Gateway), Multi-Tenancy ADR-012 (token propagation)
- This decision enables: ADR-001, ADR-002, ADR-003, ADR-005 (defines the pipeline that all other decisions operate within)

---

## References

- [CodeMie A2A Protocol Documentation](https://docs.codemie.com/a2a/overview) (internal)
- [CodeMie Workflow Engine](https://docs.codemie.com/workflows/overview) (internal)
- [Google A2A (Agent-to-Agent) Protocol](https://github.com/google/A2A)
- [Single-Task vs Multi-Task Prompting Performance (Anthropic Research)](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering)
- [Azure OpenAI GPT-4o Pricing](https://azure.microsoft.com/en-us/pricing/details/cognitive-services/openai-service/)

---

## Implementation Checklist

**Phase 1: Agent Development** (Weeks 1-3)
- [ ] Develop EmailClassifier assistant with hybrid rule + LLM prompt (ADR-001)
- [ ] Develop ThreadSummarizer assistant with progressive summarization prompt (ADR-003)
- [ ] Develop ResponseDrafter assistant with SAP data retrieval tool and response templates
- [ ] Develop ActionRouter assistant with SAP action catalog tool
- [ ] Develop ReviewPresenter assistant with queue API tool
- [ ] Unit test each agent independently with sample email inputs

**Phase 2: Workflow Orchestration** (Weeks 3-4)
- [ ] Define CodeMie Workflow with 8 steps (classify, summarize, branch, draft, route, present, pause, execute)
- [ ] Implement inter-agent data passing via workflow context
- [ ] Implement branching logic (AUTO_REPLY skip, UNCLASSIFIED escalation)
- [ ] Implement PAUSED state at Step 7 with approval/rejection resume handlers
- [ ] Configure JWT propagation across A2A calls

**Phase 3: Integration Testing** (Weeks 4-5)
- [ ] End-to-end test: Alevate path (email ingestion -> pipeline -> approval -> send)
- [ ] End-to-end test: SAP headless path (A2A invocation -> pipeline -> SAP approval -> send)
- [ ] Failure testing: agent timeout, LLM error, network failure at each step
- [ ] Latency profiling: measure per-agent and total pipeline latency
- [ ] JWT propagation validation through full 5-agent chain

**Phase 4: Monitoring & Optimization** (Week 6)
- [ ] Deploy per-agent accuracy and latency dashboards
- [ ] Configure circuit breaker and retry policies
- [ ] Optimize parallelization (classify + summarize in parallel)
- [ ] Cost monitoring: per-agent and per-email cost tracking

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
