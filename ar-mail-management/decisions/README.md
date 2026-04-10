# AR Email Management - Architecture Decision Records

**Domain**: AR Email Management
**Last Updated**: 2026-04-09

---

## Overview

This directory contains all Architecture Decision Records (ADRs) specific to the **AR Email Management** domain, which handles AI-powered email processing for Accounts Receivable. The solution uses CodeMie (EPAM AI platform) with a multi-agent pipeline to classify inbound AR emails, draft responses, and route actions through human approval workflows. Two integration paths are supported: **Alevate** (interactive + headless) and **SAP** (headless-only via PAT Gateway). Microsoft Graph API provides Outlook connectivity.

---

## Decision Records

| ID | Title | Status | Date | Impact |
|----|-------|--------|------|--------|
| [ADR-001](ADR-001-email-categorization-approach.md) | Email Categorization Approach | Proposed | 2026-03-31 | High - Core classification strategy |
| [ADR-002](ADR-002-human-in-the-loop-design.md) | Human-in-the-Loop Design | Proposed | 2026-03-31 | High - Approval workflow foundation |
| [ADR-003](ADR-003-thread-context-management.md) | Thread Context Management | Proposed | 2026-03-31 | Medium - LLM context optimization |
| [ADR-004](ADR-004-agent-design.md) | Agent Design | Proposed | 2026-03-31 | High - Pipeline architecture |
| [ADR-005](ADR-005-outlook-integration-pattern.md) | Outlook Integration Pattern (Webhook Push) | Proposed | 2026-03-31 | High - Graph API Bridge; automatic email ingestion via webhook + polling |
| [ADR-006](ADR-006-ui-triggered-email-processing-delegated-mcp.md) | UI-Triggered Email Processing via Delegated MCP | **Accepted** | 2026-04-03 | High - On-demand pull path; `X-Graph-Token` header relay to Outlook MCP Server (Depends on Multi-Tenancy ADR-012) |
| [ADR-007](ADR-007-mcp-pii-redaction-strategy.md) | MCP PII Redaction Strategy | **Accepted** | 2026-04-07 | High - Presidio + `PII_RESPONSE_LEVEL` on Outlook MCP Server (Depends on ADR-006) |
| [ADR-008](ADR-008-taxonomy-reconciliation.md) | Taxonomy Reconciliation with Confluence PRD | **Accepted** | 2026-04-08 | High - Hierarchical taxonomy (primary + sub-category) aligning local 15-category taxonomy with Confluence 16-category PRD; multi-label support via `categories` list (Supersedes requirements-review.md D4) |

---

## Key Technologies

**AI/ML Platform**:
- CodeMie (EPAM AI platform) - Multi-agent orchestration
- Azure OpenAI - LLM inference for classification and drafting

**Email Integration**:
- Microsoft Graph API - Outlook email access (read, send, webhooks)
- Microsoft Entra ID - OAuth 2.0 for Graph API authentication

**Integration Paths**:
- Alevate - Interactive UI + headless API for AR specialists
- SAP - Headless-only integration via PAT Gateway

**Identity & Security**:
- PingOne - Identity provider for CodeMie authentication
- JWT token propagation across A2A agent chain

---

## Decision Themes

### 1. Email Classification Approach (ADR-001)

**Problem**: Inbound AR emails span a wide range of intents, from auto-replies to complex disputes.

**Decision**: Hybrid rule + LLM classification. Rule engine pre-filters deterministic patterns (15-20% of volume), LLM handles semantic classification into a 15-category taxonomy.

### 2. Human Approval Workflow (ADR-002)

**Problem**: Every AI-generated action must be reviewed and approved by a human before execution.

**Decision**: Batch approval queue with priority escalation. Uses CodeMie workflow PAUSED state. 4-hour timeout for standard items, 30 minutes for disputes/legal.

### 3. Thread Context Management (ADR-003)

**Problem**: Email threads can grow to 20+ messages, exceeding practical LLM context budgets.

**Decision**: Progressive summarization with last-3-emails-in-full strategy. ThreadSummarizer agent produces running summary with a fixed 16K token budget.

### 4. Agent Architecture (ADR-004)

**Problem**: Must decide between a monolithic assistant, a multi-agent pipeline, or a workflow-based approach.

**Decision**: Multi-agent pipeline via A2A, orchestrated by a CodeMie Workflow. Specialized agents (EmailClassifier, ThreadSummarizer, ResponseDrafter, ActionRouter, ReviewPresenter) chained through A2A calls.

### 5. Outlook Integration — Webhook Push Path (ADR-005)

**Problem**: Need to connect to Microsoft Outlook for automatic email ingestion via webhooks and response sending with support for both Alevate and SAP integration paths.

**Decision**: External microservice (Graph API Bridge) that monitors Outlook via webhooks with polling fallback and calls CodeMie's workflow/A2A API. Uses application-level `client_credentials` permissions.

### 6. UI-Triggered Email Processing Path (ADR-006)

**Problem**: AR specialists need an on-demand trigger to process specific emails from the Serrala/Alevate UI, bypassing the automated webhook path. No new infrastructure should be required.

**Decision**: Serrala/Alevate UI acquires a Microsoft Entra delegated token via MSAL.js PKCE and passes it as `X-Graph-Token` alongside the existing `X-PingOne-Token` in the CodeMie Assistants API call. A LangGraph ReAct assistant invokes the Outlook MCP Server as a tool; MCP-Connect Bridge relays `X-Graph-Token` (following Multi-Tenancy ADR-012 pattern) to the MCP server for delegated Graph API access.

### 7. MCP PII Redaction (ADR-007)

**Problem**: Email JSON includes PII; MCP sampling forwards text to host LLMs; tool results expose full bodies to orchestrators.

**Decision**: Optional **Microsoft Presidio** redaction on sampling payloads and **`PII_RESPONSE_LEVEL`** (`full` / `minimal` / `redacted`) on tool responses, implemented in the Outlook MCP Server reference package.

### 8. Taxonomy Reconciliation with Confluence PRD (ADR-008)

**Problem**: Confluence PRD defines 16 categories with granular dispute subtypes and internal approval categories. Local architecture (ADR-001) defines 15 categories. The taxonomies have diverged.

**Decision**: Hierarchical taxonomy — keep 15 primary categories (backward-compatible), add `sub_category` field for Confluence subtypes (4 dispute subtypes, 3 approval subtypes, POD/statement/payment-method inquiries). Multi-label support via `categories` list. Supersedes requirements-review.md D4 (single-label decision).

---

## Cross-Domain Dependencies

> **Note**: Multi-Tenancy ADRs reside in the `srl-agnt` parent repository under `multytenancy/decisions/`. The relative links below are navigable from that repository. If you are viewing this from the standalone `outlook-mcp` repo, these links will not resolve — refer to the parent repository directly.

**Depends On**:
- [Multi-Tenancy ADR-002](../../multytenancy/decisions/ADR-002-alevate-codemie-sdk-api-authentication.md): Alevate-CodeMie SDK API authentication
- [Multi-Tenancy ADR-003](../../multytenancy/decisions/ADR-003-sap-pat-to-codemie-gateway.md): SAP PAT-to-CodeMie gateway
- [Multi-Tenancy ADR-012](../../multytenancy/decisions/ADR-012-pingone-token-propagation-to-custom-mcp.md): PingOne token propagation to custom MCP — **template pattern for `X-Graph-Token` (ADR-006)**
- [Multi-Tenancy ADR-020](../../multytenancy/decisions/ADR-020-headless-api-integration-pattern.md): Headless API integration pattern

**Enables**:
- Future AR reporting dashboards via event-driven email processing metrics
- SAP workflow automation through headless A2A integration

---

## Implementation Status

| Component | Status | Notes |
|-----------|--------|-------|
| Email Classification Rules Engine | 📋 Pending | Pre-filter for auto-replies, known patterns |
| LLM Classification Agent | 📋 Pending | 15-category taxonomy with confidence scoring |
| Approval Queue Dashboard | 📋 Pending | Alevate UI + SAP integration |
| Thread Summarization Agent | 📋 Pending | Progressive summarization pipeline |
| A2A Agent Pipeline | 📋 Pending | 5-agent chain via CodeMie |
| Graph API Bridge Service | 📋 Pending | Webhook + polling fallback (ADR-005) |
| Outlook MCP Server | In progress | Reference package `outlook-mcp-server`: ADR-006 tools + ADR-007 PII (`[pii]` extra, env flags) |
| MSAL.js Graph consent in UI | 📋 Pending | Lazy consent + silent refresh for `X-Graph-Token` (ADR-006) |

**Legend**:
- 📋 **Pending**: Architecture proposed, awaiting approval

---

## Repository layout (standalone vs monorepo)

This folder may live in the **`outlook-mcp`** repository (sibling to `outlook-mcp-server/`) or inside a larger financial-platform monorepo. If paths below do not exist, treat them as **external** and copy the ADR template from your platform’s `overview/decisions/` (or keep a local `ADR-TEMPLATE.md` in this folder).

| Artifact | Typical monorepo path | In standalone `outlook-mcp` |
|----------|----------------------|----------------------------|
| ADR template | `overview/decisions/ADR-TEMPLATE.md` | Not present — use platform repo or local template |
| Central ADR index | `docs/architecture/ADR-INDEX.md` or `../../ADR-INDEX.md` | Not present — index is [this README](README.md) |
| Multitenancy ADRs | `multytenancy/decisions/ADR-00x-*.md` | See [Cross-Domain Dependencies](#cross-domain-dependencies); clone or link parent repo |

---

## Contributing

### Creating a New ADR

1. **Use the template**: Copy from `../../overview/decisions/ADR-TEMPLATE.md`
2. **Number sequentially**: Next ADR is `ADR-009`
3. **Follow naming**: `ADR-009-short-descriptive-title.md`
4. **Update this README**: Add to decision records table above
5. **Update ADR-INDEX**: Add to `../../ADR-INDEX.md`

### Review Checklist

Before accepting an ADR:
- [ ] Status is clear (Proposed/Accepted/Deprecated/Superseded)
- [ ] Context explains WHY decision is needed
- [ ] At least 2 options were considered with pros/cons
- [ ] Trade-offs are documented explicitly
- [ ] Consequences (positive AND negative) are listed
- [ ] Related decisions are cross-referenced
- [ ] Security/compliance impact assessed
- [ ] Cost analysis included (if applicable)

---

## Questions?

For questions about AR Email Management architecture decisions:
- **Technical Questions**: Contact AR Email Management Architecture Team
- **Security/Compliance**: Contact Security Architecture Team
- **Cross-Domain Impact**: Bring to Architecture Review Board

---

*Part of the AR Email Management Domain - Financial System Modernization Project - See [ADR Index](../../ADR-INDEX.md) for all decisions*
