# AR Email Management Architecture

AI-powered email triage and response drafting for Accounts Receivable collections management.

## Overview

Accounts Receivable teams in enterprise financial organizations process 50-200+ inbound emails per day across collections, disputes, payment confirmations, and general correspondence. This volume, handled manually, leads to:

- **Delayed responses** — emails sit in shared inboxes for hours or days, breaching SLA targets
- **Inconsistent categorization** — different team members classify the same dispute type differently, causing downstream reporting errors
- **Cognitive overload** — AR specialists spend 60-70% of their time reading, classifying, and drafting routine replies instead of managing high-value escalations
- **Missed follow-ups** — payment promises and dispute acknowledgements fall through the cracks when threads are not tracked systematically

This solution uses AI (via CodeMie) to automatically classify inbound emails, extract customer intent, draft context-aware responses using SAP correspondence templates, and route everything through a human approval step before any action is taken. **Dispute management** is the primary highlighted use case: disputes communicated by customers via email are currently reviewed, interpreted, and logged into SAP FS2 or S/4 manually — leading to delays, missed disputes, and inconsistent categorization.

The system is a **decision-support layer, NOT an autonomous agent**. It must NOT send emails automatically without human approval, update ERP records independently, or escalate accounts without human review.

## System Context

| System | Role | Integration |
|--------|------|-------------|
| **Microsoft Outlook** | Inbound/outbound email channel for the AR team | Microsoft Graph API (OAuth 2.0 application permissions) |
| **CodeMie** | AI processing engine — classification, drafting, routing | REST API, A2A (JSON-RPC 2.0), Workflows |
| **SAP FS2 / S/4** | ERP system of record — invoices, disputes, customer master data | RFC/API, SAP correspondence templates |
| **Alevate** | AR platform — collections management UI, approval workflows | SDK/API (headless + interactive) |
| **PingOne** | Identity provider — authentication and tenant isolation | OIDC, JWT bearer tokens |
| **Audit Store** | Processing audit trail and state management | PostgreSQL |

## Architecture Approach

**Multi-agent pipeline with workflow orchestration**: Specialized CodeMie assistants are chained via A2A (agent-to-agent) calls, orchestrated by a CodeMie workflow with a PAUSED state for human approval.

### Pipeline Components

Order matches [ADR-004](decisions/ADR-004-agent-design.md), agent prompts, and `implementation-plans/assistants/00-orchestrator-multi-agent.md`: **thread summary is produced before classification** so the classifier receives `thread_summary`.

```
Email Ingestion Service (Path A) ──► ThreadSummarizer → EmailClassifier → ResponseDrafter → ActionRouter → ReviewPresenter → Approval UI (SAP/Alevate)
        │
        └── Path B/C: CodeMie Orchestrator (MCP fetch) ──► same AI pipeline from ThreadSummarizer onward
```

| Component | Type | Responsibility |
|-----------|------|----------------|
| **Email Ingestion Service** | External microservice | Path A: Graph API bridge — webhooks/polling, fetches content, submits to CodeMie |
| **Orchestrator** | CodeMie assistant | Path B/C: fetches email and thread via Outlook MCP; no classification or summarization ([implementation-plans/assistants/](implementation-plans/assistants/)) |
| **ThreadSummarizer** | CodeMie assistant | Reconstructs and summarizes thread context for long email chains; output feeds EmailClassifier |
| **EmailClassifier** | CodeMie assistant | Categorizes email (15 primary categories + sub_category / multi-label per ADR-008), extracts intent with confidence score |
| **ResponseDrafter** | CodeMie assistant | Generates reply using SAP correspondence templates + AI-generated content |
| **ActionRouter** | CodeMie assistant | Maps classification to SAP/Alevate action type and parameters |
| **ReviewPresenter** | CodeMie assistant | Formats output for human approval UI with confidence, reasoning, draft, and suggested action |
| **Approval UI** | SAP / Alevate UI | Human reviews, edits, approves, or rejects the AI recommendation |

### Trigger & Calling Paths

- **Alevate path (Path A)**: Interactive (browser UI) + Headless (SDK API) — invokes CodeMie Assistants API with PingOne JWT; automatic pipeline via Email Ingestion Service webhook
- **SAP path (Path B)**: Headless only — invokes CodeMie via PAT Gateway token exchange and the A2A API endpoint
- **UI-triggered MCP path (Path C)**: AR specialist selects email in Serrala/Alevate UI → UI acquires Microsoft Entra delegated token via MSAL.js PKCE → calls CodeMie Assistants API with `X-Graph-Token` header → CodeMie assistant invokes Outlook MCP Server → Graph API read with delegated permissions. See [ADR-006](decisions/ADR-006-ui-triggered-email-processing-delegated-mcp.md).

## Key Features

- **Email categorization** — 15-category taxonomy covering disputes, payment promises, reminders, escalations, and more
- **Intent extraction with confidence** — Numeric confidence score (0-1) per classification; low-confidence emails are escalated automatically
- **AI-drafted responses** — Generated using SAP correspondence templates combined with AI-produced content, respecting tone and language constraints
- **Human-in-the-loop approval** — Every AI-generated response or system action passes through an explicit approval step before execution
- **Full audit trail** — Every classification, draft, action, and approval decision is logged with reasoning, confidence, and approver identity
- **Thread context management** — Progressive summarization for long email threads that exceed the LLM context window
- **SAP correspondence template integration** — Templates retrieved from SAP are used as the basis for response drafting
- **Completeness tracking** — Every email thread has a logged outcome; silent gaps are not permitted

## Quality Requirements

| Quality Attribute | Requirement | Target |
|-------------------|-------------|--------|
| **Performance** | Email processing SLA from receipt to ready-for-review | < 2 minutes |
| **Availability** | System uptime (excluding planned maintenance) | 99.5% |
| **Scalability** | Emails processed per inbox per day | 200+ |
| **Security** | PII handling, field-level encryption for financial data | GDPR compliant |
| **Compliance** | EU AI Act assessment, audit trail retention | EU AI Act (not high-risk), 7-year audit retention |
| **Accuracy** | Email classification accuracy target | > 90% product/NFR target (validated against human labels); ADR-001 design driver is 95%+ combined (rules + LLM) at maturity |
| **Escalation** | Maximum auto-processing without human escalation | Confidence threshold >= 0.75 |

## Documentation Structure

```
ar-mail-management/
├── README.md                                          # This file — domain overview and index
├── requirements-review.md                             # Requirements analysis and UC traceability matrix
├── codemie-analysis.md                                # CodeMie capabilities analysis
├── integration-review.md                              # Integration architecture review
├── research-notes.md                                  # Focused research findings
├── architecture-overview.md                           # Narrative system architecture description
├── data-privacy.md                                    # GDPR/PII handling and EU AI Act compliance
├── review-notes.md                                    # Self-review checklist and findings
├── implementation-plans/                              # CodeMie assistant specs, workflow, setup
│   ├── architecture.md
│   ├── workflow.md
│   ├── codemie-assistant-setup.md
│   └── assistants/                                    # Orchestrator + 5 pipeline agents
├── skills/                                            # CodeMie skills (MCP tools, taxonomy)
├── decisions/
│   ├── README.md                                      # ADR index for this domain
│   ├── ADR-001-email-categorization-approach.md       # Classification strategy decision
│   ├── ADR-002-human-in-the-loop-design.md            # Approval flow design decision
│   ├── ADR-003-thread-context-management.md           # Thread history storage and injection
│   ├── ADR-004-agent-design.md                        # Single vs. multi-agent vs. workflow decision
│   ├── ADR-005-outlook-integration-pattern.md         # Outlook/Graph API connectivity pattern (webhook push)
│   ├── ADR-006-ui-triggered-email-processing-delegated-mcp.md  # UI-triggered path via X-Graph-Token + Outlook MCP
│   ├── ADR-007-mcp-pii-redaction-strategy.md           # Presidio + response levels on Outlook MCP Server
│   └── ADR-008-taxonomy-reconciliation.md             # Hierarchical taxonomy vs Confluence PRD
├── diagrams/
│   ├── ar-mail-context.mermaid                        # C4 System Context diagram
│   ├── ar-mail-diagrams.drawio                        # Combined draw.io (one tab per diagram)
│   ├── flows/
│   │   ├── ar-mail-flow-email-processing.mermaid      # End-to-end processing flow
│   │   ├── ar-mail-flow-approval-ui.mermaid           # Approval interaction sequence
│   │   ├── ar-mail-flow-ui-trigger-mcp.mermaid        # Path C: UI-triggered MCP sequence diagram
│   │   └── ar-mail-flow-pii-redaction.mermaid         # PII / sampling / tool-response minimization (ADR-007)
│   ├── components/
│   │   ├── ar-mail-component-diagram.mermaid          # System component boundaries
│   │   └── ar-mail-context-injection-diagram.mermaid  # Context assembly and injection
│   └── states/
│       ├── ar-mail-email-category-state-machine.mermaid  # Category transitions
│       └── ar-mail-approval-routing-state-machine.mermaid
├── prompts/
│   ├── EmailClassifier.md                             # Classifier system prompt
│   ├── ThreadSummarizer.md                            # Summarizer system prompt
│   ├── ResponseDrafter.md                             # Drafter system prompt
│   ├── ActionRouter.md                                # Router system prompt
│   └── ReviewPresenter.md                             # Presenter system prompt
└── UC-ai-Instructions/
    └── ar-mail-management-agent-prompt.md             # Agent task prompt (source of requirements)
```

## Quick Start

### 1. Understand the Business Problem

Start with this README for the high-level overview, then read [`requirements-review.md`](requirements-review.md) for the detailed requirements analysis and UC traceability matrix.

### 2. Review the Architecture

Read [`architecture-overview.md`](architecture-overview.md) for the full narrative system architecture, including the end-to-end email processing flow, component descriptions, integration architecture, context and memory design, and audit trail.

### 3. Understand Key Decisions

Review the [Architecture Decision Records](decisions/README.md) for the rationale behind classification approach, approval flow, thread management, agent design, and Outlook integration:
- [ADR-001: Email Categorization Approach](decisions/ADR-001-email-categorization-approach.md)
- [ADR-002: Human-in-the-Loop Design](decisions/ADR-002-human-in-the-loop-design.md)
- [ADR-003: Thread Context Management](decisions/ADR-003-thread-context-management.md)
- [ADR-004: Agent Design](decisions/ADR-004-agent-design.md)
- [ADR-005: Outlook Integration Pattern](decisions/ADR-005-outlook-integration-pattern.md) — automatic webhook push path
- [ADR-006: UI-Triggered Email Processing via Delegated MCP](decisions/ADR-006-ui-triggered-email-processing-delegated-mcp.md) — on-demand pull path via `X-Graph-Token`
- [ADR-007: MCP PII Redaction Strategy](decisions/ADR-007-mcp-pii-redaction-strategy.md) — Presidio + `PII_RESPONSE_LEVEL` on Outlook MCP Server
- [ADR-008: Taxonomy Reconciliation](decisions/ADR-008-taxonomy-reconciliation.md) — hierarchical taxonomy and multi-label alignment with Confluence PRD

### 4. Review Privacy and Compliance

Read [`data-privacy.md`](data-privacy.md) for the GDPR/PII handling approach and EU AI Act compliance assessment.

## Implementation Status

**Phase 1 — Design & Architecture** (current)

Domain docs and ADRs define the target architecture. Reference implementation work has started in this repo’s **`outlook-mcp-server`** package (Outlook MCP: ADR-006 tool surface, ADR-007 PII controls); the full CodeMie multi-agent deployment remains pending.

| Milestone | Status |
|-----------|--------|
| Requirements review and UC traceability | In progress |
| CodeMie capabilities analysis | In progress |
| Integration architecture review | In progress |
| Architecture documentation and diagrams | In progress |
| ADR authoring (ADR-001 through ADR-008) | In progress (006–008 Accepted per [decisions/README.md](decisions/README.md)) |
| System prompt design (5 pipeline agents + Orchestrator pattern) | In progress |
| Self-review and consistency check | Planned |

## Monitoring & Operations

### Key Metrics

| Metric | Description | Target |
|--------|-------------|--------|
| **Emails processed / hour** | Throughput of the email processing pipeline | Proportional to inbox volume (200+/day) |
| **Average handling time (AHT)** | Time from email receipt to approved action | < 5 minutes (including human review) |
| **Classification accuracy** | % of emails correctly categorized (vs. human labels) | > 90% |
| **Escalation rate** | % of emails routed to human review due to low confidence | < 15% |
| **Approval turnaround** | Time from AI recommendation to human approval/rejection | < 30 minutes (business hours) |
| **Missed follow-up rate** | % of threads with no logged outcome | 0% (completeness tracking) |
| **Error rate** | % of outbound responses requiring post-send correction | < 2% |

### Operational Dashboard

```
Email Volume ──→ Classification Accuracy ──→ Escalation Rate
     ↓                    ↓                       ↓
  Throughput        Confidence Distribution    Human Review Queue
     ↓                    ↓                       ↓
  AHT Trends       Category Distribution     Approval Turnaround
```

## Security & Compliance

| Framework | Scope | Key Controls |
|-----------|-------|--------------|
| **GDPR** | Email PII (sender addresses, names, potentially bank details in body) | Data minimization, retention limits, right to erasure, processing basis documented |
| **EU AI Act** | AI system assessment (Steps 1-5) | Not high-risk; personal data processing controls; no prohibited practices; anonymized training data |
| **SOC 2** | Audit trail and access control | Immutable audit logs, 7-year retention, tenant-level isolation, user-level access via Alevate Policy Service |

See [`data-privacy.md`](data-privacy.md) for the full compliance assessment.

## Deployment View

The solution deploys on **Azure AKS** alongside the existing CodeMie infrastructure:

| Component | Deployment | Notes |
|-----------|------------|-------|
| **Email Ingestion Service** | AKS pod (dedicated namespace) | Graph API bridge microservice |
| **CodeMie Assistants** | Existing CodeMie AKS deployment | Orchestrator (Path B/C) + 5 pipeline assistants; see [implementation-plans/assistants/](implementation-plans/assistants/) |
| **PAT Gateway** | Existing multi-tenancy infrastructure | SAP token exchange (Multi-Tenancy ADR-003 — not `decisions/ADR-003`, which is thread context) |
| **Audit Store** | PostgreSQL (managed) | Shared or dedicated schema per tenant |
| **Azure Key Vault** | Existing instance | Graph API credentials, encryption keys |

## Risks & Technical Debt

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| **Graph API rate limits** | Email ingestion throttled during high-volume periods | Medium | Implement exponential backoff, batch fetching, monitor quota usage |
| **LLM hallucination in drafts** | AI generates factually incorrect response content | Medium | Human-in-the-loop approval catches errors; confidence scoring flags uncertain drafts; SAP template anchoring reduces free-form generation |
| **Token expiry mid-processing** | Pipeline fails partway through multi-step processing | Low | Token refresh before pipeline start; retry with fresh token on 401; idempotent processing ensures safe retry |
| **Multi-language accuracy** | Classification and drafting quality degrades for non-English emails | Medium | Start with English-only; add language detection and language-specific prompt variants in Phase 2 |
| **Graph API webhook renewal** | Webhook subscriptions expire every 3 days; missed renewal causes silent email loss | Medium | Automated renewal service; polling fallback; monitoring for subscription health |
| **SAP system unavailability** | Cannot fetch customer data or correspondence templates | Low | Cached last-known data; graceful degradation (draft without SAP context, flag for review) |
| **Dual OAuth2 consent in UI (Path C)** | AR specialist must consent to both PingOne and Microsoft Graph in the browser; UX friction if not handled gracefully | Medium | Lazy consent triggered on email selection (not at app load); MSAL.js silent refresh before each call; clear error messaging for failed consent |

## Glossary

| Term | Definition |
|------|------------|
| **AR** | Accounts Receivable — the process of managing money owed to the company by customers |
| **AHT** | Average Handling Time — mean time from email receipt to completed action |
| **SAP FS2** | SAP Financial Services (Collections and Disbursements) — the ERP module for collections management |
| **SAP S/4** | SAP S/4HANA — the next-generation ERP system |
| **CodeMie** | EPAM AI/Run Codemie — the AI engine supporting Assistants API, Workflows, A2A chaining, and Skills |
| **A2A** | Agent-to-Agent — CodeMie's JSON-RPC 2.0 protocol for chaining assistant calls |
| **PAT Gateway** | Personal Access Token Gateway — token exchange service that converts SAP PATs to CodeMie-compatible JWTs (Multi-Tenancy ADR-003) |
| **MCP** | Model Context Protocol — protocol for connecting AI models to external data sources and tools |
| **PingOne** | PingIdentity's cloud identity platform — OIDC provider for authentication and tenant isolation |
| **Graph API** | Microsoft Graph API — RESTful API for accessing Microsoft 365 services including Outlook email |
| **LiteLLM** | LLM proxy layer providing unified API access to multiple LLM providers with tenant isolation |

## Key Architecture Decisions

| ADR | Title | Status | Impact |
|-----|-------|--------|--------|
| [ADR-001](decisions/ADR-001-email-categorization-approach.md) | Email Categorization Approach | Proposed | High — Classification strategy affects accuracy and escalation rates |
| [ADR-002](decisions/ADR-002-human-in-the-loop-design.md) | Human-in-the-Loop Design | Proposed | High — Approval flow design affects user experience and compliance |
| [ADR-003](decisions/ADR-003-thread-context-management.md) | Thread Context Management | Proposed | High — Thread history strategy affects AI quality and token costs |
| [ADR-004](decisions/ADR-004-agent-design.md) | Agent Design | Proposed | High — Single vs. multi-agent decision shapes the entire pipeline |
| [ADR-005](decisions/ADR-005-outlook-integration-pattern.md) | Outlook Integration Pattern (Webhook Push) | Proposed | High — Graph API Bridge with webhook + polling for automatic processing |
| [ADR-006](decisions/ADR-006-ui-triggered-email-processing-delegated-mcp.md) | UI-Triggered Email Processing via Delegated MCP | Accepted | High — On-demand trigger path with `X-Graph-Token` header relay to Outlook MCP Server |
| [ADR-007](decisions/ADR-007-mcp-pii-redaction-strategy.md) | MCP PII Redaction Strategy | Accepted | High — Presidio + response minimization on Outlook MCP (GDPR Art. 5(1)(c)) |
| [ADR-008](decisions/ADR-008-taxonomy-reconciliation.md) | Taxonomy Reconciliation with Confluence PRD | Accepted | High — Hierarchical taxonomy + multi-label; aligns local model with PRD |

## Next Steps

### Phase 1: Design & Architecture (current)
- Complete all architecture documentation and ADRs
- Finalize system prompts for all 5 pipeline agents and Orchestrator setup
- Validate against UC requirements (traceability matrix)
- Architecture review and approval

### Phase 2: Foundation & Integration (Weeks 1-4)
- Provision Email Ingestion Service on AKS
- Configure CodeMie assistants (Orchestrator + pipeline) and workflow
- Establish Graph API OAuth credentials and webhook subscriptions
- Set up audit store schema
- Integration testing with Alevate headless API path

### Phase 3: Classification & Drafting (Weeks 5-8)
- Deploy ThreadSummarizer, then EmailClassifier with initial taxonomy (pipeline order)
- Deploy ResponseDrafter
- Integrate SAP correspondence templates
- Accuracy validation against labeled email dataset

### Phase 4: Approval & Production (Weeks 9-12)
- Build approval UI integration (Alevate + SAP)
- Deploy ActionRouter and ReviewPresenter
- End-to-end testing with live inbox (shadow mode)
- Production rollout with monitoring

## Where this folder lives

`ar-mail-management/` is tracked in this repository. Paths such as `../overview/plans/` refer to a **parent monorepo**; if those folders are missing, use [decisions/README.md — Repository layout](decisions/README.md#repository-layout-standalone-vs-monorepo) for standalone vs monorepo expectations.

## References

- [Microsoft Graph API — Mail](https://learn.microsoft.com/en-us/graph/api/resources/mail-api-overview)
- [Microsoft Graph API — Subscriptions (Webhooks)](https://learn.microsoft.com/en-us/graph/api/resources/webhooks)
- [CodeMie API Documentation](https://docs.codemie.com/) (internal)
- [EU AI Act — Official Text](https://eur-lex.europa.eu/eli/reg/2024/1689/oj)
- [GDPR — Official Text](https://eur-lex.europa.eu/eli/reg/2016/679/oj)
- [A2A Protocol Specification](https://google.github.io/A2A/) (reference for agent-to-agent patterns)
- Main project documentation: [`../overview/plans/`](../overview/plans/)
- C4 architecture diagrams: [`../overview/c4dsl/`](../overview/c4dsl/)

---

*Part of the Financial System Modernization Project — AR Email Management Module*
