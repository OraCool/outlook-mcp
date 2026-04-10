# AR Email Management Solution — Agent Prompt

> **How to use this document**  
> Copy the full content below and paste it as the task prompt for your AI coding
> assistant (CodeMie, GitHub Copilot Workspace, Cursor, Claude Code, etc.).  
> Replace all `[placeholder]` values before running.

---

## Context

We are building an **AI-powered Accounts Receivable (AR) email management solution**
for [Company Name], which uses **Serrala SAP** and **Alevate** as its AR platforms,
and **CodeMie** as the AI assistant/workflow engine.

**"We"** = the AR/finance team sending invoices and managing collections.  
**"Customer"** = the external client who owes payment.

The solution connects to the AR team's **Microsoft Outlook inbox** via the
**Microsoft Graph API**, processes inbound customer emails related to AR
(invoices, payment disputes, payment confirmations, etc.), generates AI-drafted
responses or system actions, and routes them through an **approval UI in
Serrala SAP or Alevate** before any action is taken.

**This system is a decision-support layer, NOT an autonomous agent.** It must NOT:
- Send emails automatically without human approval
- Update ERP records independently
- Escalate accounts without human review

The primary highlighted use case is **dispute management**: disputes communicated
by customers via email are currently reviewed, interpreted, and logged into
SAP FS2 or S/4 manually — leading to delays, missed disputes, and inconsistent
categorization.

**ADR numbering (read this before citing ADRs):** Numbers **ADR-001 … ADR-008** under `ar-mail-management/decisions/` are **this domain only** (classification, HITL, thread context, agents, Outlook, MCP, taxonomy). Integration authentication uses **different** records in the parent platform: **Multi-Tenancy ADR-002** (Alevate–CodeMie), **Multi-Tenancy ADR-003** (SAP PAT gateway), **ADR-012**, **ADR-020** under `docs/architecture/multytenancy/...` (paths as in TASK 3 below). Do not confuse domain ADR-002/003 with multitenancy ADR-002/003.

**Codemie assistants and workflows are invoked via the CodeMie SDK/API.**
Two calling contexts exist:
- **Alevate** — Can invoke CodeMie Assistants interactively (browser UI) or
  via headless API (**Multi-Tenancy ADR-002** pattern — SDK/API auth, not `ar-mail-management/decisions/ADR-002`, which is human-in-the-loop).
- **SAP** — Headless only. Uses the PAT Gateway token exchange (**Multi-Tenancy ADR-003**
  pattern — not domain ADR-003 thread context) to call CodeMie via the A2A API endpoint. No interactive assistant
  UI is available from SAP.

---

## Business Scenarios

The following table seeds the scope. The agent must validate, extend, and
reference these scenarios throughout all architecture and prompt deliverables.

| # | Scenario | Trigger | Expected Action |
|---|---|---|---|
| S1 | Payment overdue, no customer response | Invoice sent, no payment received, no inbound reply | Draft payment reminder email to customer |
| S2 | Customer claims invoice not received | Inbound: "We never received an invoice" | Re-send invoice; log event in SAP/Alevate |
| S3 | Customer promises to pay on a date | Inbound: "We will pay by [date]" | Update expected payment date in SAP/Alevate |
| S4 | Customer disputes invoice amount | Inbound: dispute or objection content | Flag for human review; draft acknowledgement reply; log dispute in SAP FS2/S/4 |
| S5 | Payment received but not matched in SAP | SAP event: unmatched incoming payment | Draft clarification request to customer |
| S6 | Customer requests invoice extension | Inbound: request for more time to pay | Draft response; route extension decision to approver |
| S7 | Customer confirms payment sent | Inbound: "We transferred the payment today" | Log confirmation; trigger SAP reconciliation check |
| S8 | Escalation / legal tone detected | Inbound: threatening or legal language | Escalate immediately to human; do not auto-draft |

---

## Functional Requirements

1. **Outlook Integration** — Access the AR team's Outlook mailbox via the
   **Microsoft Graph API** (OAuth 2.0 delegated or application permissions).
   Support read (inbound analysis) and send (after approval).

   **Integration specifics the architecture must address:**
   - **API**: Microsoft Graph API (`/me/messages`, `/me/mailFolders`,
     `/me/sendMail`) with OAuth 2.0 token obtained via PingOne (see **Multi-Tenancy**
     ADR-002 and ADR-020 in
     `docs/architecture/multytenancy/design/codemie-auth-integration/decisions/` — not ar-mail-management ADR-002).
   - **New-email detection**: Decide between **Graph webhook subscriptions**
     (`/subscriptions` with change type `created`) and **polling**
     (`/messages?$filter=receivedDateTime ge ...`). Document the choice in
     ADR-005.
   - **CodeMie connectivity model**: Decide whether CodeMie connects to
     Outlook directly (via a built-in tool or MCP server), or whether an
     **external intermediary service** fetches emails and feeds them to
     CodeMie via its Conversation or A2A API. Document in ADR-005.
   - **Dual calling context**: The solution must support two callers with
     different integration paths:
     - **Alevate** — Can invoke CodeMie Assistants interactively (browser UI
       path) OR via headless API (Multi-Tenancy ADR-020 pattern:
       `POST /v1/assistants/{assistantId}/model` or `POST /v1/conversations`
       with `Authorization: Bearer <pingone-jwt>` +
       `X-PingOne-Token: <pingone-jwt>`).
     - **SAP** — Headless only. Uses the PAT Gateway token exchange (Multi-Tenancy ADR-003
       pattern) to call CodeMie via
       `POST /v1/a2a/assistants/{assistant_id}` (agent-to-agent endpoint).
       No interactive assistant UI available.
   - **Relevant CodeMie API endpoints** (from OpenAPI 3.1.0 spec):
     - `POST /v1/a2a/assistants/{assistant_id}` — Execute A2A Request
     - `GET /v1/a2a/assistants/{assistant_id}/.well-known/agent.json` — Agent Card
     - `POST /v1/conversations` — Create conversation
     - `GET /v1/conversations/{conversationId}` — Get conversation with history
     - `POST /v1/assistants/{assistantId}/model` — Call assistant model

2. **Thread Awareness** — Group emails by customer identifier and invoice/case
   reference. Maintain the full communication history per customer thread.
   No email in a thread may be silently ignored.

3. **Email Categorization** — Classify each email in a thread using the taxonomy
   defined below. Validate the taxonomy, extend it where needed, and document
   the final version.

4. **Intent Extraction** — For each email, identify:
   - What the customer is stating or requesting
   - What action is required on our side
   - Confidence level (numeric, 0–1)

5. **Response Generation** — Draft a reply or a system action (SAP/Alevate data
   update). Drafts must follow tone and language constraints defined in the
   system prompts. Where applicable, use **SAP correspondence templates**
   retrieved from SAP as a basis for response drafting.

6. **Human-in-the-Loop Approval** — Every AI-generated response or system action
   must pass through an explicit approval step in the Serrala SAP or Alevate UI
   before execution. No action is taken autonomously.

7. **Completeness Tracking** — Every email thread must have a logged outcome:
   a drafted response, a system action, a deliberate "no action required"
   decision, or an escalation. Silent gaps are not permitted.

8. **Escalation** — Low-confidence classifications (below the defined threshold)
   or unrecognized intents must be routed to human review with a reasoning
   summary. They must never be silently dropped.

9. **Audit Trail** — Every AI classification, draft, and action must be logged
   with the reasoning, confidence score, and the identity of the approver.

10. **UC Requirements Traceability** — The architecture must cross-reference
    the Confluence UC requirements at
    `https://serrala.atlassian.net/wiki/spaces/SAA/pages/6327959630/UC+2+AR+-+AI+Agent+for+E-Mail+Handling+Collections+Management`.
    Every functional requirement and scenario in this prompt must be traceable
    to a UC requirement ID. Any UC requirements not covered by the scenarios
    in this prompt must be identified as gaps and documented in
    `requirements-review.md`.

11. **SAP Correspondence Templates** — The solution must support retrieving
    SAP correspondence templates for use in response drafting. The architecture
    must define how templates are fetched from SAP (API call, cached lookup, or
    injected as context) and how they are combined with AI-generated content.

12. **EU AI Act Compliance** — Document compliance with EU AI Act requirements
    in `data-privacy.md`, including: prohibited AI practices assessment,
    high-risk AI system categorization, personal data processing controls,
    and anonymized training data requirements. Use the checklist from the
    Confluence UC page as a starting point.

---

## Email Category Taxonomy (Seed — Validate and Extend)

| Category | Description |
|---|---|
| `PAYMENT_REMINDER_SENT` | We sent a reminder; awaiting customer response |
| `INVOICE_NOT_RECEIVED` | Customer claims they never received the invoice |
| `INVOICE_DISPUTE` | Customer disputes the amount or validity of an invoice |
| `PAYMENT_PROMISE` | Customer commits to paying by a specific date |
| `PAYMENT_CONFIRMATION` | Customer confirms payment has been sent |
| `EXTENSION_REQUEST` | Customer requests more time to pay |
| `PARTIAL_PAYMENT_NOTE` | Customer indicates only partial payment will be made |
| `ESCALATION_LEGAL` | Email contains threatening or legal language |
| `INTERNAL_NOTE` | Internal team communication within the thread (not from customer) |
| `UNCLASSIFIED` | Intent unclear; requires human review |

The state machine diagram (Task 5) must show valid transitions between
these categories across the lifecycle of a thread.

---

## Non-Functional Requirements

- **Language**: Handle at minimum [English / specify additional languages].
- **Confidence threshold**: Define a minimum score (e.g., 0.75) below which
  classification is escalated. Document the chosen value and rationale.
- **Processing SLA**: Emails must be processed within [X minutes] of receipt.
- **Data privacy / GDPR**: Email content contains PII. Document the data
  handling approach: what is stored, where, for how long, and who has access.
- **Availability**: Define expected uptime and degradation behavior when
  SAP/Alevate or Outlook is unavailable.
- **Idempotency**: Reprocessing the same email must not create duplicate
  actions or duplicate draft responses.

**Key metrics** (from UC requirements — track these in architecture):

| Goal | Metric |
|---|---|
| Increase AR Productivity | Emails processed per FTE per day / Average handling time (AHT) per email |
| Improve Accuracy & Reduce Risk | Error rate in outbound responses / Missed follow-up rate |
| Standardize Communication | SLA compliance rate |
| Reduce Cognitive Load | % reduction in manual drafting time |
| Maintain Full Control | % of emails sent with human approval |

---

## TASK 1 — Requirements Review

Review all requirements, scenarios, and the category taxonomy above.

- Identify any gaps, contradictions, or ambiguities.
- Identify scenarios that are missing from the table.
- Validate whether the category taxonomy is sufficient to cover all scenarios,
  or propose additions and removals with justification.
- **UC Requirements Cross-Reference**: Validate all requirements and scenarios
  against the Confluence UC page at
  `https://serrala.atlassian.net/wiki/spaces/SAA/pages/6327959630/UC+2+AR+-+AI+Agent+for+E-Mail+Handling+Collections+Management`.
  Create a traceability matrix in `requirements-review.md` mapping each
  scenario (S1–S8) and functional requirement (FR1–FR12) to the corresponding
  UC requirement. Flag any UC requirements not covered by this prompt.
- Produce `requirements-review.md` in
  `docs/architecture/ar-mail-management/` listing findings, decisions, and
  the traceability matrix.

---

## TASK 2 — CodeMie Analysis

Review [`../../epm-cdme/codemie`](../../epm-cdme/codemie) specifically for the
following questions. Document findings in `codemie-analysis.md`.

**Key CodeMie API endpoints to evaluate** (from OpenAPI 3.1.0 spec):
- `POST /v1/a2a/assistants/{assistant_id}` — Execute A2A Request (agent-to-agent)
- `GET /v1/a2a/assistants/{assistant_id}/.well-known/agent.json` — Agent Card discovery
- `POST /v1/conversations` — Create conversation
- `GET /v1/conversations/{conversationId}` — Get conversation with history
- `POST /v1/assistants/{assistantId}/model` — Call assistant model

**Authentication pattern** (per **Multi-Tenancy** ADR-002 and ADR-020 in
`docs/architecture/multytenancy/design/codemie-auth-integration/decisions/`):
```http
Authorization: Bearer <pingone-jwt>
X-PingOne-Token: <pingone-jwt>
Content-Type: application/json
```

Questions to answer:

- **Agent/workflow types**: Does CodeMie support multi-step email processing
  pipelines? What agent or workflow primitives are available? Can the A2A
  endpoint chain multiple assistants?
- **Outlook connector**: Is there an existing Outlook integration (MCP server
  or built-in tool), or does one need to be built? What auth model does it use?
  Can Graph API OAuth tokens be propagated via `X-PingOne-Token` / MCP
  header relay (ADR-012)?
- **Tool calls to external systems**: How does CodeMie invoke SAP and Alevate?
  Synchronous API calls? Event queues? Webhook callbacks? Does the
  `/v1/assistants/{assistantId}/model` endpoint support tool-call responses?
- **Memory and context**: Does CodeMie support thread-level context (passing
  conversation history across multiple LLM calls via
  `GET /v1/conversations/{conversationId}`)? What are the context window limits?
- **Human-in-the-loop**: Does CodeMie have a built-in approval/review step, or
  must this be implemented externally in the SAP/Alevate UI?
- **Multi-agent support**: Can CodeMie orchestrate multiple specialized
  assistants (classifier → drafter → router) via the A2A endpoint? Or does
  it support a single assistant model only?
- **Headless vs. interactive**: Document which CodeMie endpoints support
  headless (API-only) invocation vs. interactive (UI-based) invocation. This
  is critical for the SAP integration path (headless only).

---

## TASK 3 — Integration Architecture Review

Study [`docs/architecture/multytenancy`](docs/architecture/multytenancy) and
specifically the auth integration decisions in
[`docs/architecture/multytenancy/design/codemie-auth-integration/decisions/`](docs/architecture/multytenancy/design/codemie-auth-integration/decisions/)
to understand the existing integration context. Document findings in
`integration-review.md`.

**Critical ADRs to review (multitenancy — not `ar-mail-management/decisions/`):**
- **Multi-Tenancy ADR-002**: Alevate-to-CodeMie SDK/API Authentication (PingOne JWT Bearer)
- **Multi-Tenancy ADR-003**: SAP PAT-to-CodeMie Token Exchange Gateway
- **ADR-012**: PingOne Token Propagation to Custom MCP Server
- **ADR-020**: Headless API Integration Pattern (complete developer contract)

Questions to answer:

- How does CodeMie currently integrate with Serrala SAP and Alevate?
- What is the tenant isolation model — is this multi-tenant per company,
  per user, or per inbox?
- What is the auth/token flow for Outlook access in this architecture?
  Does it differ between the Alevate path (Multi-Tenancy ADR-002) and the SAP path (Multi-Tenancy ADR-003)?
- Where does the approval UI live — inside SAP/Alevate, or as a CodeMie
  component?
- How does the headless API pattern (ADR-020) apply to email processing
  automation — can an automated service call CodeMie without user interaction?
- Are there any architectural constraints that affect agent design choices
  in Task 7?

---

## TASK 4 — Focused Research

Research the following specific topics. Document findings and links in
`research-notes.md`.

- **LLM-based email intent classification** for AR and finance workflows:
  accuracy benchmarks, common failure modes, hybrid rule+LLM approaches.
- **Human-in-the-loop approval patterns** for AI-generated business
  communications: UI patterns, timeout/fallback strategies, audit requirements.
- **Email thread reconstruction**: deduplication, ordering, handling
  of forwarded or embedded threads.
- **AR automation benchmarks**: industry data on classification accuracy,
  escalation rates, and time-to-response improvement.
- **Prompt design patterns** for structured output from LLMs in business
  workflow contexts (JSON schema enforcement, few-shot examples for finance).

For each topic, document: key finding, source, and how it influenced a
decision in Task 5 or Task 7.

---

## TASK 5 — Architecture Documentation

Create the following files in `docs/architecture/ar-mail-management/`.
Follow the project's established documentation conventions defined in the
`arch-doc-creator` skill (`.claude/skills/arch-doc-creator/SKILL.md`).

### Required Documents

| File | Description |
|---|---|
| `README.md` | Solution overview, scope, and index of all documents (follow `.claude/skills/arch-doc-creator/references/readme-template.md`) |
| `requirements-review.md` | Output of Task 1 (includes UC traceability matrix) |
| `codemie-analysis.md` | Output of Task 2 |
| `integration-review.md` | Output of Task 3 |
| `research-notes.md` | Output of Task 4 |
| `architecture-overview.md` | Narrative description of the full system |
| `data-privacy.md` | GDPR/PII handling approach + EU AI Act compliance assessment |
| `decisions/README.md` | ADR index for this domain (follow `.claude/skills/arch-doc-creator/references/decisions-readme-template.md`) |
| `decisions/ADR-001-email-categorization-approach.md` | Classification strategy decision |
| `decisions/ADR-002-human-in-the-loop-design.md` | Approval flow design decision |
| `decisions/ADR-003-thread-context-management.md` | Thread history storage and injection |
| `decisions/ADR-004-agent-design.md` | Single vs. multi-agent vs. workflow decision |
| `decisions/ADR-005-outlook-integration-pattern.md` | Outlook/Graph API connectivity pattern decision |
| `decisions/ADR-006-ui-triggered-email-processing-delegated-mcp.md` | UI-triggered path; delegated Graph token + Outlook MCP |
| `decisions/ADR-007-mcp-pii-redaction-strategy.md` | MCP sampling / tool-response PII minimization |
| `decisions/ADR-008-taxonomy-reconciliation.md` | Taxonomy alignment with Confluence PRD |

### Required Diagrams (in `diagrams/` with type-based subfolders)

Diagrams are organized by type into subfolders. All Mermaid files use the
`ar-mail-{subject}.mermaid` naming convention. A combined draw.io file with
one tab per diagram must also be produced.

**System Context (mandatory first diagram — `diagrams/`):**

| File | Description |
|---|---|
| `ar-mail-context.mermaid` | C4 System Context: Outlook, CodeMie, SAP, Alevate, Audit Store, PingOne, Graph API — external boundaries before internals |

**Flow Diagrams (`diagrams/flows/`):**

| File | Description |
|---|---|
| `ar-mail-flow-email-processing.mermaid` | End-to-end email intake, classification, drafting, approval, and action flow |
| `ar-mail-flow-approval-ui.mermaid` | Sequence diagram of the human approval interaction in SAP/Alevate UI |

**Component / Architecture Diagrams (`diagrams/components/`):**

| File | Description |
|---|---|
| `ar-mail-component-diagram.mermaid` | System component boundaries: Outlook, Graph API, CodeMie agents, SAP, Alevate, audit store. Must show both the Alevate (interactive + headless) and SAP (headless-only via PAT Gateway) calling paths |
| `ar-mail-context-injection-diagram.mermaid` | How thread history and SAP data are assembled and injected per LLM call |

**State Diagrams (`diagrams/states/`):**

| File | Description |
|---|---|
| `ar-mail-email-category-state-machine.mermaid` | Category transitions across a thread lifecycle |

**Combined draw.io (`diagrams/`):**

| File | Description |
|---|---|
| `ar-mail-diagrams.drawio` | All diagrams above as tabs in a single draw.io XML file |

### ADR Template

Each ADR must follow the project's established template at
`.claude/skills/arch-doc-creator/references/adr-template.md`. The minimum
required sections are listed below. Read the full template before writing
any ADR — it contains placeholder guidance for every section.

```markdown
# ADR-XXX: [Short Descriptive Title]

**Status:** [Proposed | Accepted | Deprecated | Superseded]
**Date:** YYYY-MM-DD
**Decision Makers:** [Team/People who made the decision]
**Technical Story:** [Brief context — what triggered this decision?]

---

## Context and Problem Statement

[2-3 paragraphs: current situation, problems, constraints, requirements]

## Decision Drivers

- **[Driver 1]**: [Why this matters]
- **[Driver 2]**: [Why this matters]
- **[Driver 3]**: [Why this matters]

---

## Considered Options

### Option 1: [Name] (Recommended / Not Recommended)

**Description:** [Detailed description — include architecture implications,
integration points, and operational considerations. Not just a sentence.]

**Pros:**
- ✅ [Advantage 1]
- ✅ [Advantage 2]
- ✅ [Advantage 3]

**Cons:**
- ❌ [Disadvantage 1]
- ❌ [Disadvantage 2]
- ❌ [Disadvantage 3]

**Cost:** [If applicable]

---

### Option 2: [Name]

[Same structure as Option 1]

---

### Option 3: [Name]

[Same structure as Option 1]

---

## Options Comparison Table

| Criteria | Option 1 | Option 2 | Option 3 |
|---|---|---|---|
| Description | [Brief summary] | [Brief summary] | [Brief summary] |
| [Decision Driver 1] | [Rating/Assessment] | [Rating/Assessment] | [Rating/Assessment] |
| [Decision Driver 2] | [Rating/Assessment] | [Rating/Assessment] | [Rating/Assessment] |
| [Decision Driver 3] | [Rating/Assessment] | [Rating/Assessment] | [Rating/Assessment] |
| Cost | [Estimate] | [Estimate] | [Estimate] |
| Complexity | [Low/Med/High] | [Low/Med/High] | [Low/Med/High] |
| Pros and Cons Summary | [Key trade-off] | [Key trade-off] | [Key trade-off] |

---

## Decision Outcome

**Chosen Option:** [Option X: Name]

### Rationale

1. **[Driver 1 addressed]**: [How chosen option satisfies this driver]
2. **[Driver 2 addressed]**: [How chosen option satisfies this driver]
3. **[Trade-offs accepted]**: [What we're giving up and why it's acceptable]

### Implementation Summary

**Key Components:**
- [Component 1]: [Purpose]
- [Component 2]: [Purpose]

**Architecture Diagram:** [Reference to diagram if exists]

---

## Consequences

### Positive

✅ [Positive consequence 1]
✅ [Positive consequence 2]

### Negative

❌ [Negative consequence 1]
❌ [Negative consequence 2]

### Mitigation Strategies

**For [Negative Consequence 1]:**
- [How we'll mitigate this]

---

## Compliance & Security

**Security Controls:**
- [Control 1]
- [Control 2]

**Compliance Impact:**
- GDPR: [Impact]
- SOC 2: [Impact]
- ISO 27001: [Impact]

---

## Cost Analysis

| Component | Cost | Notes |
|---|---|---|
| [Component 1] | $X/month | [Details] |
| **Total** | **$Z/month** | |

---

## Related Decisions

- **[ADR-XXX](path)**: [How it relates]

**Dependencies:**
- This decision depends on: [ADR-XXX]
- This decision enables: [ADR-YYY]

---

## References

- [Links to documentation, research, vendor docs]

---

## Implementation Checklist

**Phase 1: [Name]** (Weeks 1-2)
- [ ] Task 1
- [ ] Task 2

---

## Change Log

| Date | Author | Change |
|------|--------|--------|
| YYYY-MM-DD | [Name] | Initial decision document |

---

## Review and Approval

**Reviewed by:**
- [Name], [Role] — [Date]

**Approved by:**
- [Name], [Role] — [Date]

---

*Part of the AR Email Management Domain — Financial System Modernization Project*
```

**Key requirements for ADRs in this domain:**
- Every ADR **must** include the **Options Comparison Table** (matrix format)
  with decision drivers as rows and options as columns. This enables quick
  cross-option comparison alongside the detailed per-option sections.
- Each option's description must be detailed enough to evaluate independently
  — include architecture implications, integration points, and operational
  considerations.
- The Compliance & Security section is mandatory (email PII, GDPR, audit).

### ADR-005: Outlook Integration Pattern

ADR-005 must evaluate these three options for how the solution connects to
Microsoft Outlook:

| Option | Description | Key Trade-off |
|---|---|---|
| **A: CodeMie Assistant with built-in Outlook MCP tool** | Configure a CodeMie MCP server (or built-in tool) that calls Microsoft Graph API directly. The assistant reads/sends email as a tool call within its conversation. | Simplest architecture; but couples Graph API auth to CodeMie's tool execution context and requires MCP token propagation (ADR-012) for OAuth scopes. |
| **B: External microservice (Graph API bridge)** | A dedicated service monitors Outlook via Graph API (webhooks or polling), fetches new emails, and calls CodeMie's conversation API (`POST /v1/conversations` or `POST /v1/a2a/assistants/{id}`) to submit them for processing. | Decouples email ingestion from AI processing; supports both Alevate and SAP paths natively; but adds a service to deploy and operate. |
| **C: CodeMie Workflow with Graph API tool node** | Use CodeMie's workflow engine with a dedicated Graph API tool node that fetches email content at a specific workflow step. Subsequent nodes handle classification, drafting, routing. | Leverages CodeMie's built-in orchestration; but depends on whether CodeMie workflows support external HTTP tool calls with OAuth token management. |

The ADR must also address:
- **Webhook vs. polling** for new-email detection (latency, Graph API
  subscription lifecycle management, renewal at 3-day expiry, notification
  endpoint hosting).
- **Dual-caller architecture**: How does the chosen option serve both
  Alevate (interactive UI + headless API) and SAP (headless-only via PAT
  Gateway)?
- **Auth flow**: How does the Graph API OAuth 2.0 token relate to the CodeMie
  PingOne JWT? Are they the same identity, or does the Outlook token require
  separate consent/configuration?

### Central Index Registration

After creating all ADRs:
1. Create `decisions/README.md` using the project template at
   `.claude/skills/arch-doc-creator/references/decisions-readme-template.md`.
   Populate the Decision Records table, Key Technologies, Decision Themes,
   and Cross-Domain Dependencies sections.
2. Add a new **"AR Email Management Domain"** section to
   `docs/architecture/ADR-INDEX.md` following the existing pattern (see
   Invoice Processing, Fraud Detection, Multi-Tenancy sections in that file).
   Register all five ADRs.

---

## TASK 6 — Self-Criticism and Reflection (Documentation Review)

After completing all documentation in Task 5, perform a structured
self-review pass before considering the work complete. This is mandatory —
do not skip it.

### 6.1 Completeness Check

- Every scenario (S1–S8) from the Business Scenarios table has a corresponding
  flow in at least one diagram. No scenario is undocumented.
- Every email category in the taxonomy appears in the state machine diagram.
  No category is an orphan.
- Every ADR contains: a clearly stated decision, at least 2 alternatives with
  pros and cons, and explicit positive and negative consequences.
- Every ADR contains the **Options Comparison Table** (matrix format with
  decision drivers as rows, options as columns).
- ADR-005 (Outlook integration pattern) addresses: webhook vs. polling,
  CodeMie connectivity model, and both Alevate and SAP calling paths.
- No document references a component or system that is not defined in the
  component diagram.
- All required diagrams exist and are valid Mermaid syntax.
- The system context diagram (`ar-mail-context.mermaid`) exists and is the
  first diagram produced.
- The draw.io file (`ar-mail-diagrams.drawio`) exists with one tab per
  Mermaid diagram.
- The `decisions/README.md` index exists and lists all five ADRs with status,
  date, and impact.
- The central `docs/architecture/ADR-INDEX.md` has been updated with the
  AR Email Management domain section.
- The `requirements-review.md` contains a UC requirements traceability matrix.

### 6.2 Consistency Check

- The email processing flow diagram uses the same system names and boundaries
  as the component diagram. No naming mismatches.
- The approval UI sequence matches the decision documented in ADR-002.
  No contradictions.
- The thread context management described in ADR-003 is visibly represented
  in the context-injection diagram.
- ADR-004 (agent design decision) is consistent with the agents described
  in Task 7 and their system prompts.
- The component diagram shows both calling paths: Alevate (interactive +
  headless) and SAP (headless via PAT Gateway). These match the integration
  patterns documented in ADR-005 and `integration-review.md`.
- Diagram file names follow the `ar-mail-{subject}.mermaid` convention.
- Diagrams are organized in type subfolders (`flows/`, `components/`, `states/`).

### 6.3 Non-Functional Requirements Coverage

- GDPR/PII handling is addressed in `data-privacy.md` and referenced
  in the architecture overview.
- EU AI Act compliance is assessed in `data-privacy.md`.
- The escalation path (low-confidence classification) is visible in the
  state machine and the email processing flow.
- The audit trail mechanism is described in `architecture-overview.md`
  and reflected in the component diagram.
- Idempotency is addressed in at least one ADR or architecture note.

### 6.4 Logic Gap Analysis

- Are there email intents that the taxonomy does NOT cover that appear
  in the business scenarios? If yes — add them or document the out-of-scope
  decision explicitly.
- Is there any step in the processing flow where an email could be silently
  dropped (no action, no log, no escalation)? If yes — fix it before
  considering the review done.
- Does the human-in-the-loop step have a defined timeout and fallback behavior?
  If not — document it as an open question with owner and target date.
- Are there any circular state transitions in the state machine that have
  no exit condition? If yes — fix or document.

### 6.5 Review Output

Produce `review-notes.md` in the same folder with:

- A checklist of all items above using: ✅ passed / ⚠️ gap found / ❌ failed
- For each ⚠️ or ❌: a short description of the issue, whether it was fixed
  inline or left as a documented open question, and rationale.
- A final section: `## Prompt Review` (populated after Task 7).

---

## TASK 7 — CodeMie Assistant / Workflow System Prompt Design

Design the AI assistant layer. This task depends on findings from Tasks 2 and 3.

### 7.1 Agent Design Decision (ADR-004)

Before writing any prompts, decide and justify one of the following
architectures. Document the decision in `decisions/ADR-004-agent-design.md`.

| Option | Description | When to choose |
|---|---|---|
| **Single assistant** | One LLM handles classification, drafting, and routing in a single call | If CodeMie supports rich tool use and context injection natively |
| **Multi-agent pipeline** | Specialized agents chained: ThreadSummarizer → Classifier → Drafter → Router → Presenter | If each step needs independent confidence tracking and can fail independently |
| **Workflow with LLM nodes** | Deterministic orchestration with LLM steps at specific decision points | If most steps are deterministic and only a few require language understanding |

**SAP constraint**: The SAP calling path is headless-only (API via PAT
Gateway, Multi-Tenancy ADR-003). The chosen architecture must support execution without
interactive assistant UI — the agent design decision must account for
headless-only invocation via `POST /v1/a2a/assistants/{assistant_id}`.

### 7.2 Candidate Agents / Nodes

Validate the following candidates against your CodeMie analysis. Merge,
split, or rename based on what CodeMie's architecture supports.

| Agent / Node | Responsibility |
|---|---|
| `ThreadSummarizer` | Reads full thread history → produces a concise context summary for injection into other agents (runs before classification) |
| `EmailClassifier` | Reads email + thread summary → outputs category + confidence + extracted intent as JSON |
| `ResponseDrafter` | Takes category + intent + customer/invoice context + SAP correspondence templates → drafts an email reply in approved tone |
| `ActionRouter` | Takes category + intent → determines SAP/Alevate action type and parameters |
| `ReviewPresenter` | Formats AI output (draft + reasoning + confidence) for the human approval UI |

### 7.3 System Prompt Files

For each agent or LLM workflow node selected in 7.1, produce a
**complete, production-ready system prompt** in:

`docs/architecture/ar-mail-management/prompts/[agent-name].md`

Each prompt file must follow this exact structure:

```markdown
# [Agent Name] — System Prompt

## Role and Persona
[Who is this agent? What is its job title / functional role?]

## Scope
### In scope
[What this agent handles]
### Out of scope
[What this agent must NOT handle or attempt — hard boundary]

## Input Format
[Exact structure of data this agent receives per call — use JSON schema or example]

## Output Format
[Strict output schema — prefer JSON for machine-readable outputs]
[If this agent produces email text: specify tone, length constraints, sign-off format]

## Decision Rules
[Explicit logic for edge cases — written as rules, not suggestions]
[Example: "If confidence < 0.75, always output category = UNCLASSIFIED regardless of best guess"]

## Escalation Conditions
[Enumerate all conditions under which this agent must flag for human review]
[Escalation output must include: reason, confidence, recommended next step]

## Constraints
- Tone: [formal / neutral / empathetic — specify]
- Language: [English only / multilingual — specify handling]
- Data: [List any fields this agent must never include in output — e.g., raw PII, internal SAP IDs]
- Hallucination guard: [What the agent must do when it lacks sufficient context]

## Few-Shot Examples
### Example 1 — Standard Case
Input: [...]
Output: [...]

### Example 2 — Edge Case
Input: [...]
Output: [...]
[Edge case must test an escalation condition or an ambiguous classification]
```

### 7.4 Context and Memory Design

Document the following in a new section of `architecture-overview.md`
titled **"Context and Memory Design"**:

- What data is injected into each agent call (thread summary, customer
  master data from SAP, invoice details, SAP correspondence templates,
  previous AI actions)?
- How is the `ThreadSummarizer` output used to manage long threads that
  exceed the model's context window?
- What is the maximum safe context length assumption, and how is it enforced?
- How is context assembled — who is responsible for it (CodeMie orchestrator,
  a custom service, the calling application)?

### 7.5 Prompt Self-Review

After writing all prompts, add a `## Prompt Review` section to
`review-notes.md` and answer each question with ✅ / ⚠️ / ❌:

- Does every prompt have a strict, machine-parseable output format
  (no free-form text where structured output is required)?
- Is escalation explicitly defined in every prompt, with a defined
  output structure for escalation cases?
- Do the few-shot examples in each prompt include at least one edge case
  drawn from the Business Scenarios table?
- Do the prompts collectively cover all taxonomy categories (15 primary + sub_category per ADR-008), with no
  category that could arrive in production but has no prompt handling it?
- Are there any overlapping responsibilities between agents that could
  cause conflicting outputs? If yes — resolve or document.
- Does the `ReviewPresenter` output contain enough information for a
  human approver to make a decision without needing to open the original
  email? If not — fix the output schema.

---

## Deliverables Summary

```
docs/architecture/ar-mail-management/
├── README.md
├── requirements-review.md
├── codemie-analysis.md
├── integration-review.md
├── research-notes.md
├── architecture-overview.md
├── data-privacy.md
├── review-notes.md
├── decisions/
│   ├── README.md
│   ├── ADR-001-email-categorization-approach.md
│   ├── ADR-002-human-in-the-loop-design.md
│   ├── ADR-003-thread-context-management.md
│   ├── ADR-004-agent-design.md
│   ├── ADR-005-outlook-integration-pattern.md
│   ├── ADR-006-ui-triggered-email-processing-delegated-mcp.md
│   ├── ADR-007-mcp-pii-redaction-strategy.md
│   └── ADR-008-taxonomy-reconciliation.md
├── diagrams/
│   ├── ar-mail-context.mermaid
│   ├── ar-mail-diagrams.drawio
│   ├── flows/
│   │   ├── ar-mail-flow-email-processing.mermaid
│   │   └── ar-mail-flow-approval-ui.mermaid
│   ├── components/
│   │   ├── ar-mail-component-diagram.mermaid
│   │   └── ar-mail-context-injection-diagram.mermaid
│   └── states/
│       └── ar-mail-email-category-state-machine.mermaid
└── prompts/
    ├── EmailClassifier.md
    ├── ThreadSummarizer.md
    ├── ResponseDrafter.md
    ├── ActionRouter.md
    └── ReviewPresenter.md
```

> **Completion criteria**: The task is done only when:
> 1. `review-notes.md` exists, all checklist items are ✅ or documented as
>    open questions, and the `## Prompt Review` section is complete with no
>    ❌ items left unresolved.
> 2. `decisions/README.md` exists with all domain ADRs indexed (001–008 as applicable).
> 3. `docs/architecture/ADR-INDEX.md` has been updated with the AR Email
>    Management domain section.
> 4. Every ADR includes an **Options Comparison Table**.
> 5. The system context diagram (`ar-mail-context.mermaid`) is the first
>    diagram in the set.
> 6. The draw.io file (`ar-mail-diagrams.drawio`) contains one tab per diagram.
> 7. `requirements-review.md` contains the UC requirements traceability matrix.
