# CodeMie Assistant Setup — AR Email Management Pipeline

## Overview

Step-by-step guide for creating the AR Email Management assistants and wiring them into a CodeMie workflow.

**Corrected pipeline** (6 assistants, not 5):

```
Orchestrator (MCP fetch)
  → ThreadSummarizer
  → EmailClassifier
  → ResponseDrafter (conditional skip)
  → ActionRouter
  → ReviewPresenter
  → Human Approval (interrupt_before)
```

**Source prompts**: `ar-mail-management/prompts/`
**Skills**: `ar-mail-management/skills/`
**Diagrams**: `ar-mail-management/diagrams/`
**ADRs**: `ar-mail-management/decisions/`

> **Important**: The agent output schemas in `architecture-overview.md` are outdated. Use the schemas in this document, which were built from the actual prompt files.

---

## Architecture Clarification

### Trigger Paths

| Path                              | Trigger                                         | Email input to CodeMie                  | MCP needed?                                          |
| --------------------------------- | ----------------------------------------------- | --------------------------------------- | ---------------------------------------------------- |
| **Path B — SAP UI**               | SAP Fiori / Alevate UI calls CodeMie API        | `message_id(s)` + `X-Graph-Token`       | **Yes** — Orchestrator uses MCP to fetch email       |
| **Path C — Alevate UI** (ADR-006) | User selects email in browser UI                | `message_id` + `X-Graph-Token`          | **Yes** — Orchestrator uses MCP with delegated token |
| **Path A — Webhook** (ADR-005)    | Email Ingestion Service (external microservice) | Full email content (no token needed)    | No — content arrives pre-fetched in payload          |

**Key insight**: Both SAP UI (Path B) and Alevate UI (Path C) pass `message_id(s)` + `X-Graph-Token` — not email content. The token identifies the user and their mailbox; without it the Outlook MCP Server cannot authenticate against the correct inbox. The **Orchestrator** assistant uses the token to call `get_email` and `get_thread` via MCP before ThreadSummarizer runs.

### MCP Authentication by Path

| Path                | Graph API token source                                    | Token carrier to MCP                                      |
| ------------------- | --------------------------------------------------------- | --------------------------------------------------------- |
| SAP UI (Path B)     | Entra access token acquired by SAP UI via SAP/Entra integration | `X-Graph-Token` header → `{{graph_token}}` in context store |
| Alevate UI (Path C) | User-delegated PKCE token acquired by MSAL.js in browser | `X-Graph-Token` header → `{{graph_token}}` in context store |
| Webhook (Path A)    | App-level token held by Email Ingestion Service           | Not passed to CodeMie — used by the service directly      |

---

## Phase 0 — Create the 2 CodeMie Skills

Skills are shared knowledge modules attached to multiple assistants. Create these **before** the assistants.

Navigate to **Skills → + Create Skill** for each one.

### Skill 1: AR Email Taxonomy

| Field            | Value                                                                                                                                                                                                       |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Name**         | `ar-taxonomy`                                                                                                                                                                                               |
| **Description**  | Complete 15-category AR email taxonomy with sub-categories, approval routes, urgency, tone mappings, override rules, and escalation conditions. Used by EmailClassifier, ActionRouter, and ReviewPresenter. |
| **Instructions** | Paste full contents of `ar-mail-management/skills/ar-taxonomy-skill.md`                                                                                                                                     |

**Attach to**: EmailClassifier, ActionRouter, ReviewPresenter

**Why**: The taxonomy (15 categories, sub-categories, approval routes, override rules) is referenced by 3 of the 5 pipeline agents. A centrally-maintained skill means updating the taxonomy propagates to all 3 agents without republishing each assistant.

### Skill 2: Outlook MCP Tools

| Field            | Value                                                                                                                                                                                   |
| ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Name**         | `ar-mcp-tools`                                                                                                                                                                          |
| **Description**  | How to use the Outlook MCP Server tools: get_email, get_thread, get_attachments, search_emails. Covers the standard fetch sequence, field mapping to context store, and error handling. |
| **Instructions** | Paste full contents of `ar-mail-management/skills/ar-mcp-tools-skill.md`                                                                                                                |

**Attach to**: Orchestrator only

**Why**: The Orchestrator is the only assistant that calls MCP tools. Separating the tool usage guide as a skill keeps the Orchestrator system prompt focused on orchestration logic rather than tool API documentation.

---

## Architecture Patterns

Two integration patterns are supported. The 5 specialist assistants (ThreadSummarizer → ReviewPresenter) are **shared and reusable** in both patterns. Only the orchestrator differs.

### Pattern A — Workflow-based pipeline

CodeMie's workflow engine drives the pipeline sequentially through YAML-defined states. The "Orchestrator" assistant is the email-fetcher entry point only — it does not call downstream agents. The engine handles transitions, branching, context propagation, and the human-approval checkpoint (`interrupt_before`).

**Use when**: Automated batch processing, SAP UI / Alevate UI triggers, production deployments requiring a hard human-approval checkpoint.

**Setup**: Create 6 assistants + 1 workflow. See [workflow.md](workflow.md).

### Pattern B — Sub-assistant orchestration

One true Orchestrator assistant fetches the email via MCP tools and then calls the 5 specialist assistants as sub-assistants (tools) in sequence. Context is passed manually between calls. Human approval is conversational — the user replies in the chat.

**Use when**: Interactive chat sessions, ad-hoc email processing, prototype / exploratory use, or when a conversational approval flow is preferred over a hard checkpoint.

**Setup**: Create 6 assistants (same as Pattern A) + 1 multi-agent orchestrator. See [assistants/00-orchestrator-multi-agent.md](assistants/00-orchestrator-multi-agent.md).

| | Pattern A — Workflow | Pattern B — Sub-agent |
|--|----------------------|-----------------------|
| Pipeline driven by | CodeMie workflow engine (YAML) | Orchestrator LLM reasoning |
| Context propagation | Automatic via context store | Manual — orchestrator passes to each sub-assistant |
| Human approval | `interrupt_before` checkpoint (hard) | Conversational (soft) |
| Conditional branching | Declarative YAML condition | LLM decision in orchestrator |
| Best for | Production, automated triggers | Interactive sessions, prototyping |

---

## Phase 1 — Create the 6 Shared Assistants

These assistants are used in **both patterns**. Navigate to **Assistants → + Create Assistant** in CodeMie for each one.

| # | Assistant | File | Skills | Temperature | Patterns |
|---|-----------|------|--------|-------------|---------|
| 1 | ThreadSummarizer | [assistants/01-thread-summarizer.md](assistants/01-thread-summarizer.md) | — | 0 | A + B |
| 2 | EmailClassifier | [assistants/02-email-classifier.md](assistants/02-email-classifier.md) | `ar-taxonomy` | 0 | A + B |
| 3 | ResponseDrafter | [assistants/03-response-drafter.md](assistants/03-response-drafter.md) | — | 0.3 | A + B |
| 4 | ActionRouter | [assistants/04-action-router.md](assistants/04-action-router.md) | `ar-taxonomy` | 0 | A + B |
| 5 | ReviewPresenter | [assistants/05-review-presenter.md](assistants/05-review-presenter.md) | `ar-taxonomy` | 0 | A + B |

> ResponseDrafter is the only agent at temperature > 0. All others run at 0 for deterministic output.

### Pattern A only — Workflow entry point

| # | Assistant | File | Skills | MCP Server | Temperature |
|---|-----------|------|--------|------------|-------------|
| 0 | Orchestrator | [assistants/00-orchestrator.md](assistants/00-orchestrator.md) | `ar-mcp-tools` | Outlook MCP | 0 |

> MCP is configured in the **assistant UI** (Available tools → External tools → Manual Setup) — not in the workflow YAML. See the MCP Server Setup section in [assistants/00-orchestrator.md](assistants/00-orchestrator.md) for the exact steps.

### Pattern B only — Multi-agent orchestrator

| # | Assistant | File | Skills | Sub-assistants | MCP Server | Temperature |
|---|-----------|------|--------|----------------|------------|-------------|
| 0 | AR Orchestrator | [assistants/00-orchestrator-multi-agent.md](assistants/00-orchestrator-multi-agent.md) | `ar-mcp-tools` | All 5 above | Outlook MCP | 0 |

> Sub-assistants are added in the assistant UI: Tools section → Sub-assistant field → search and add all 5.

---

## Phase 2 — Create the Workflow (YAML)

See **[workflow.md](workflow.md)** for the complete workflow YAML, trigger payloads, and SLA configuration.

Navigate to **Workflows → + Create Workflow** → **Workflow Config → YAML tab**, then paste the YAML from `workflow.md`.

### How context flows between states

CodeMie's context store is a key-value store that persists across all states. When an assistant outputs valid JSON, **all root-level keys automatically become `{{variable}}` placeholders** available in every subsequent state. No manual wiring needed — structured JSON output from each agent populates the shared context.

### State flow

```
fetch-email (Orchestrator)
  ↓ error? → end
  ↓
summarize-thread (ThreadSummarizer)
  ↓
classify-email (EmailClassifier)
  ↓ no-draft category? → route-actions-nodraft → present-review
  ↓ draft category?    → draft-response → route-actions → present-review
                                                           ↓
                                                     human-approval [interrupt_before]
                                                           ↓
                                                          end
```

> Full YAML, trigger payloads, and SLA config: see [workflow.md](workflow.md)

---

## Phase 3 — Workflow Input (Trigger Payload)

See **[workflow.md → Trigger Payloads](workflow.md)**. Payload structure differs by trigger path:

| Path | Includes |
|------|----------|
| Path B — SAP UI | `message_id`, `graph_token`, `customer_id`, `customer_context`, `invoice_data` |
| Path C — Alevate UI | Same as Path B; `graph_token` acquired via MSAL.js PKCE |
| Path A — Webhook | Full `email`, `email_body`, `thread_emails` (no `graph_token` needed) |

---

## Phase 4 — Get Assistant IDs

After creating each assistant, copy its ID from **Assistants → View Details** (or the URL). Replace the `REPLACE_WITH_*` placeholders in the YAML.

```yaml
assistants:
  - id: orchestrator
    assistant_id: <copy from Assistants → View Details>

  - id: thread-summarizer
    assistant_id: <copy from Assistants → View Details>

  - id: email-classifier
    assistant_id: <copy from Assistants → View Details>

  - id: response-drafter
    assistant_id: <copy from Assistants → View Details>

  - id: action-router
    assistant_id: <copy from Assistants → View Details>

  - id: review-presenter
    assistant_id: <copy from Assistants → View Details>
```

Also replace `https://YOUR_OUTLOOK_MCP_SERVER/mcp` with the actual deployed URL of the Outlook MCP Server.

---

## Phase 5 — Approval SLA Configuration

See **[workflow.md → Approval SLA Configuration](workflow.md)**.

CodeMie does not enforce timeouts natively. Configure SLA escalation externally (Alevate workflow engine or external scheduler) based on the `approval_route` value in the review package. Timeouts must **escalate, never auto-approve** (ADR-002).

---

## Risk & Mitigation Summary

| Risk                                                      | Mitigation                                                                             |
| --------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| `architecture-overview.md` schemas are wrong for 3 agents | Use schemas in this document (built from actual prompts)                               |
| `draft_subject`/`draft_body` undefined on no-draft path   | Context store keys will be absent/null — ReviewPresenter handles null draft gracefully |
| `actions[]` is an array (1-N items)                       | ReviewPresenter groups per-invoice actions; approval UI must render N actions          |
| `categories[]` is an array (ADR-008 multi-label)          | Defined as `"type": "array"` in output_schema — no special handling needed             |
| ResponseDrafter temperature must be 0.3                   | Set in both the assistant settings and the YAML `temperature: 0.3` field               |
| SLA enforcement not native to CodeMie                     | Must be handled by Alevate or external scheduler (see Phase 5)                         |

---

## Phase 6 — Outlook MCP Server Connection

The Outlook MCP server is attached to the **Orchestrator assistant** through the CodeMie **assistant UI** — not in the workflow YAML. The full setup steps are in [assistants/00-orchestrator.md → MCP Server Setup](assistants/00-orchestrator.md).

### When MCP is needed

| Path | Email source | MCP needed? |
|------|-------------|-------------|
| **Path B — SAP UI** | SAP passes `message_id` + `X-Graph-Token` | **Yes** — Orchestrator fetches email via MCP |
| **Path C — Alevate UI** | User selects email; `X-Graph-Token` via MSAL.js | **Yes** — Orchestrator fetches email via MCP |
| **Path A — Webhook** | Email Ingestion Service passes full email content | **No** — content arrives in trigger payload |

### Where to configure it

Navigate to: **Assistants → Orchestrator → Edit → Available tools → External tools → Manual Setup**

See [assistants/00-orchestrator.md](assistants/00-orchestrator.md) for the JSON config block and full step-by-step instructions.

### Available MCP Tools (Orchestrator only)

| Tool | Purpose |
|------|---------|
| `get_email` | Fetch a single email by Graph message ID |
| `get_thread` | Fetch all emails in a conversation thread |
| `get_attachments` | List attachment metadata for a message |
| `search_emails` | KQL search across the mailbox |

---

## Architecture Gaps — Proposed Actions

The `architecture-overview.md` Functional Gap Matrix (lines 258-272) identifies gaps between the PRD requirements and the current implementation. Below is an action plan for each gap, categorized by when to address it.

### Before CodeMie Setup (Blocking)

These gaps affect what CodeMie assistants produce and must be resolved in the prompt schemas before wiring up the workflow.

| Gap                                               | Location to fix                                 | Action                                                                                                                                                                         |
| ------------------------------------------------- | ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----- |
| **`thread_id` not in ClassificationResult**       | `prompts/EmailClassifier.md` output schema      | Add `thread_id` as a pass-through field — the classifier receives it in input context and must echo it in output so downstream agents and the audit trail can reference it     |
| **`sender_company` not extracted**                | `prompts/EmailClassifier.md` → `extracted_data` | Add `sender_company` extraction rule to the classifier prompt; update `output_schema` in the workflow YAML                                                                     |
| **`currency` not extracted**                      | `prompts/EmailClassifier.md` → `extracted_data` | Add `currency` extraction alongside `disputed_amount`; already available in the email body in most cases                                                                       |
| **`due_date` not extracted**                      | `prompts/EmailClassifier.md` → `extracted_data` | Add `due_date` (invoice due date) distinct from `promised_date` (customer's payment promise date)                                                                              |
| **`priority` is nested** (`intent.urgency`)       | `prompts/EmailClassifier.md` output schema      | Promote to top-level field — the prompt already outputs `priority: HIGH/MEDIUM/LOW`; confirm it is also at the root level (not only inside `intent`)                           |
| **`summary` not in ClassificationResult**         | `prompts/EmailClassifier.md` output schema      | Already present in prompt output as top-level `summary` field; confirm it is included in the CodeMie `output_schema` block for the classify-email state                        |
| **Multi-label `categories[]` and `sub_category`** | MCP `ClassificationResult` model                | ADR-008 adds these fields but the MCP model hasn't been updated; update `outlook-mcp-server/src/outlook_mcp/models/` to include `categories: list[str]` and `sub_category: str | None` |

### Phase 1 Backlog (Non-blocking for CodeMie setup, required for production)

| Gap                                            | Action                                                                                                                                                                                                                   |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Language detection**                         | `language` field already exists in EmailClassifier prompt output; the MCP `ClassificationResult` model needs `language: str` field added                                                                                 |
| **`suggestedActions` in ClassificationResult** | ActionRouter already produces `actions[]`; if the PRD requires `suggestedActions` in the classifier output too, add a lightweight version to EmailClassifier (category-based suggestions only, not the full action plan) |
| **Mark as read / move / archive**              | Add `mark_as_read` and `move_email` MCP tools to the Outlook MCP Server; call them in the post-approval execution state of the workflow                                                                                  |

### Phase 2 Backlog (Operational scale)

| Gap                                     | Action                                                                                                                          |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| **Batch processing** (`classify_batch`) | Add a new `classify_batch` MCP tool; implement in `outlook-mcp-server/`; add a new workflow variant for bulk processing         |
| **Attachment content analysis**         | Currently out of scope; attachment metadata (filename, type) is surfaced to the approval UI but not analyzed by the AI pipeline |

### Not Gaps (Resolved by design)

| Item                  | Resolution                                                                                 |
| --------------------- | ------------------------------------------------------------------------------------------ |
| Idempotent processing | Belongs in Email Ingestion Service (Graph message ID deduplication), not in MCP or CodeMie |
| Audit trail           | Belongs in orchestrator/PostgreSQL audit store, not in MCP server                          |
| Near real-time sync   | Webhook path is separate infra (ADR-005 Graph API Bridge); MCP is pull-only by design      |
| `confidence` field    | Already implemented correctly in both prompt and MCP model                                 |

### Summary: What to do before creating CodeMie assistants

```
1. Update prompts/EmailClassifier.md — add to output schema:
   - thread_id (pass-through)
   - sender_company (new extraction)
   - extracted_data.currency
   - extracted_data.due_date
   - Confirm priority is top-level (not only inside intent)

2. Update MCP ClassificationResult model:
   - categories: list[str]
   - sub_category: str | None
   - language: str
   - priority: str (top-level)
   - summary: str

3. Then create CodeMie assistants using updated prompt schemas
```

---

## CodeMie Skills — Decision

**Verdict: Skills are not needed for the initial implementation.**

### What CodeMie Skills are

Skills are "reusable sets of instructions that get loaded into assistant context on-demand." They are markdown-based knowledge modules (up to 300KB) that:

- Can be attached to multiple assistants
- Load automatically when an assistant determines relevance
- Are updated in one place and propagate to all attached assistants

### Why skills don't add value for this pipeline

| Factor                         | Analysis                                                                                                                                                                                                |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Reuse pattern**              | The 5 agents form a linear pipeline; each has a unique, non-overlapping role. There is no shared instruction module that multiple agents need to load.                                                  |
| **System prompt completeness** | Each prompt in `ar-mail-management/prompts/` is already self-contained and purpose-built. They have been tuned for their specific task.                                                                 |
| **Activation mechanism**       | Skills activate based on LLM relevance detection. In a deterministic pipeline (temp=0 for 4/5 agents), automatic skill loading introduces unpredictability. System instructions are guaranteed to load. |
| **Complexity vs. benefit**     | Adding skills to a 5-agent linear pipeline adds a management layer without meaningful benefit over system instructions.                                                                                 |

### When Skills WOULD be useful for this project (future)

Consider skills in these scenarios:

1. **Multi-tenant variants**: If Serrala deploys the same pipeline for multiple tenants with different taxonomy subsets, a shared `AR Domain Knowledge` skill (containing the 15-category taxonomy, SAP terminology, currency rules) could be centrally maintained and attached to all tenant-specific assistant variants.

2. **Cross-cutting PII rules**: If the PII handling rules (ADR-007) need to be consistently applied across assistants AND updated frequently, extracting them as a `PII Handling Guidelines` skill lets you update in one place.

3. **Override rules maintenance**: If the 7 ActionRouter override rules change over time, a shared `AR Override Rules` skill allows updates without re-publishing each assistant.

### Conclusion

For the initial CodeMie setup: **use system instructions only** (paste each `prompts/*.md` file into its assistant's System Instructions field). Skills can be introduced in Phase 2 if tenant-specific variants or centralized rule management are required.

---

## Related Files

### Assistants & Skills

#### Workflow

| File | Purpose |
|------|---------|
| `implementation-plans/workflow.md` | **Authoritative**: complete workflow YAML, trigger payloads (Path A/B/C), SLA configuration |

#### Assistant Setup Files

| File | Purpose |
|------|---------|
| `implementation-plans/assistants/00-orchestrator.md` | Orchestrator — config, system instructions, output schema |
| `implementation-plans/assistants/01-thread-summarizer.md` | ThreadSummarizer — config, output schema |
| `implementation-plans/assistants/02-email-classifier.md` | EmailClassifier — config, output schema, escalation conditions E1-E7 |
| `implementation-plans/assistants/03-response-drafter.md` | ResponseDrafter — config, output schema, no-draft categories |
| `implementation-plans/assistants/04-action-router.md` | ActionRouter — config, output schema, 7 override rules, approval SLAs |
| `implementation-plans/assistants/05-review-presenter.md` | ReviewPresenter — config, output schema, decision buttons, PII rules |

#### Skills

| File                                              | Purpose                                                                                                                                       |
| ------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `ar-mail-management/skills/ar-taxonomy-skill.md`  | **Skill 1**: 15-category taxonomy, sub-categories, override rules, approval routes — attach to EmailClassifier, ActionRouter, ReviewPresenter |
| `ar-mail-management/skills/ar-mcp-tools-skill.md` | **Skill 2**: Outlook MCP tool usage guide (get_email, get_thread, etc.) — attach to Orchestrator only                                         |

#### System Prompt Sources

| File                                              | Purpose                                                       |
| ------------------------------------------------- | ------------------------------------------------------------- |
| `ar-mail-management/prompts/ThreadSummarizer.md`  | Assistant 1 system instructions                               |
| `ar-mail-management/prompts/EmailClassifier.md`   | Assistant 2 system instructions (needs gap fixes before use)  |
| `ar-mail-management/prompts/ResponseDrafter.md`   | Assistant 3 system instructions                               |
| `ar-mail-management/prompts/ActionRouter.md`      | Assistant 4 system instructions                               |
| `ar-mail-management/prompts/ReviewPresenter.md`   | Assistant 5 system instructions                               |

### Diagrams

| File                                                                                | Purpose                                                                |
| ----------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| `ar-mail-management/diagrams/flows/ar-mail-flow-email-processing.mermaid`           | End-to-end flow — both Path A (webhook) and Path B (SAP UI + MCP)      |
| `ar-mail-management/diagrams/flows/ar-mail-flow-sap-ui-trigger.mermaid`             | **New**: Path B full sequence — SAP UI → Orchestrator → MCP → pipeline |
| `ar-mail-management/diagrams/flows/ar-mail-flow-ui-trigger-mcp.mermaid`             | Path C — Alevate UI delegated token (X-Graph-Token)                    |
| `ar-mail-management/diagrams/flows/ar-mail-flow-action-routing-matrix.mermaid`      | All 15 category routing rules                                          |
| `ar-mail-management/diagrams/states/ar-mail-approval-routing-state-machine.mermaid` | Approval tier states & timeout escalation                              |

### ADRs

| File                                                                                  | Purpose                                           |
| ------------------------------------------------------------------------------------- | ------------------------------------------------- |
| `ar-mail-management/decisions/ADR-002-human-in-the-loop-design.md`                    | Approval workflow invariants (never auto-approve) |
| `ar-mail-management/decisions/ADR-005-outlook-integration-pattern.md`                 | Integration path options; webhook vs. MCP         |
| `ar-mail-management/decisions/ADR-006-ui-triggered-email-processing-delegated-mcp.md` | Path C — X-Graph-Token header propagation         |
| `ar-mail-management/decisions/ADR-007-mcp-pii-redaction-strategy.md`                  | PII controls on MCP tool results                  |
| `ar-mail-management/decisions/ADR-008-taxonomy-reconciliation.md`                     | Multi-label classification (categories[])         |
| `ar-mail-management/architecture-overview.md`                                         | Functional Gap Matrix (lines 258-272)             |
