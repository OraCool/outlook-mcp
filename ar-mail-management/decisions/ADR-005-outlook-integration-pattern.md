# ADR-005: Outlook Integration Pattern

**Status:** Proposed
**Date:** 2026-03-31
**Decision Makers:** AR Email Management Architecture Team
**Technical Story:** Need to connect to Microsoft Outlook for email ingestion (reading inbound AR emails) and sending (dispatching approved responses). Three integration patterns are available, each with different trade-offs around architecture coupling, authentication complexity, and operational overhead.

---

## Context and Problem Statement

The AR Email Management pipeline starts with an inbound email arriving in an Outlook mailbox and ends with an approved response being sent from the same mailbox. The integration must support two trigger models: **push** (new email arrives, pipeline starts automatically) and **pull** (user in Alevate or SAP selects an email for processing on-demand). It must work for both Alevate (interactive + headless) and SAP (headless-only) integration paths.

Microsoft Graph API is the standard programmatic interface for Outlook access. It supports both reading and sending emails, webhook subscriptions for new email notifications, and granular OAuth permission scopes. However, Graph API authentication uses Microsoft Entra ID (formerly Azure AD), which is a separate identity system from PingOne (the identity provider for CodeMie). This dual-identity reality is a key architectural constraint: the service that calls Graph API must hold Microsoft Entra credentials, while the service that calls CodeMie must hold PingOne credentials.

The webhook subscription lifecycle is another consideration. Graph API webhooks have a maximum 3-day expiry and require an HTTPS endpoint for validation. The subscribing service must manage subscription creation, renewal, and validation token handling. If the subscribing service is a CodeMie MCP tool or workflow node, these lifecycle concerns become entangled with AI pipeline logic.

## Decision Drivers

- **Separation of Concerns**: Email ingestion (Graph API interaction) should be decoupled from AI processing (CodeMie pipeline)
- **Dual-Identity Support**: Must cleanly handle two separate identity providers (Entra ID for Graph API, PingOne for CodeMie)
- **Push and Pull Models**: Must support both automatic processing on new email and on-demand processing triggered by user action
- **Webhook Lifecycle**: Subscription creation, renewal, and validation must be managed reliably without coupling to AI pipeline availability
- **Dual-Path Support**: Must work for both Alevate and SAP integration paths
- **Operational Independence**: Email ingestion scaling and availability should be independent of AI pipeline scaling

---

## Considered Options

### Option 1: CodeMie Assistant with Outlook MCP Tool

**Description:** Configure a CodeMie MCP (Model Context Protocol) server that wraps Microsoft Graph API calls. The CodeMie assistant invokes the MCP tool to read emails and send responses. Webhook subscriptions are managed by the MCP server. Authentication to Graph API flows through MCP token propagation (Multi-Tenancy ADR-012).

**Pros:**
- ✅ Simplest architecture: no external service; everything runs within CodeMie
- ✅ No additional infrastructure to deploy or monitor
- ✅ Native tool call from assistant: email read/send feels like any other tool invocation

**Cons:**
- ❌ Couples Graph API authentication to CodeMie tool execution context; MCP token propagation (ADR-012) is designed for PingOne tokens, not Microsoft Entra tokens
- ❌ Graph API OAuth scope (Mail.Read, Mail.Send) differs from PingOne identity; mapping user-delegated Graph tokens through MCP requires custom bridging
- ❌ MCP server must handle webhook subscription lifecycle (creation, renewal, validation), mixing infrastructure concerns with tool logic
- ❌ Webhook notification endpoint must be exposed from within the CodeMie MCP server, which may not support inbound HTTP listeners
- ❌ Push model (automatic processing on new email) requires a trigger mechanism external to the MCP tool (who calls the assistant when a webhook fires?)

**Cost:** No additional infrastructure. MCP development: 3-4 weeks including auth bridging.

---

### Option 2: External Microservice -- Graph API Bridge (Recommended)

**Description:** A dedicated microservice (Graph API Bridge) handles all Microsoft Graph API interactions. It monitors Outlook mailboxes via webhook subscriptions (primary) and polling (fallback), fetches email content, pre-processes it (deduplication, thread correlation, metadata enrichment), and calls CodeMie's workflow or A2A API to trigger the AI pipeline. For sending approved responses, the bridge receives the approved draft from the pipeline and sends it via Graph API.

**Pros:**
- ✅ Clean separation: email ingestion is decoupled from AI processing
- ✅ Supports both Alevate and SAP paths: bridge calls the same CodeMie API regardless of originating integration
- ✅ Independent scaling: bridge scales based on email volume; CodeMie scales based on AI processing demand
- ✅ Separate Graph API OAuth consent: application-level permissions (client_credentials flow), not user-delegated. Simpler, more reliable, no per-user consent required
- ✅ Pre-processing capability: deduplication, thread correlation, and metadata enrichment happen before AI pipeline, reducing wasted LLM calls
- ✅ Webhook subscription lifecycle managed independently: subscription renewal, validation, and failure handling are isolated from AI pipeline concerns
- ✅ Pull model supported: Alevate/SAP can also call the bridge to trigger processing of a specific email on-demand

**Cons:**
- ❌ Additional service to deploy, monitor, and maintain
- ❌ Infrastructure cost: compute, networking, monitoring for the bridge service
- ❌ Additional network hop: email data travels from Graph API to bridge to CodeMie (adds ~50-100ms latency)

**Cost:** ~$100-200/month for compute (Azure App Service or AKS pod) + monitoring.

---

### Option 3: CodeMie Workflow with Graph API Tool Node

**Description:** A CodeMie Workflow includes a tool node that makes HTTP calls to Graph API. The workflow starts with a "fetch email" step (HTTP tool call to Graph API), processes the email through the agent pipeline, and ends with a "send response" step (HTTP tool call to Graph API). Authentication is handled via tool node configuration with Graph API OAuth tokens.

**Pros:**
- ✅ Leverages CodeMie workflow orchestration for the entire pipeline including email I/O
- ✅ No separate service: all logic lives in the workflow definition
- ✅ Workflow engine handles retries and error routing for Graph API calls

**Cons:**
- ❌ Depends on CodeMie workflows supporting external HTTP tool calls with OAuth token management (client_credentials flow with token refresh)
- ❌ Webhook subscription management unclear: who creates and renews Graph API webhook subscriptions if the workflow is the consumer?
- ❌ Chicken-and-egg problem for push model: the workflow must be triggered when a new email arrives, but the webhook notification must be received by something that can start the workflow
- ❌ Graph API OAuth tokens in workflow tool configuration create a management burden (rotation, refresh, scope changes)
- ❌ No pre-processing: every email, including duplicates and already-processed messages, triggers a full workflow execution

**Cost:** No additional infrastructure. But wasted workflow executions on duplicates/already-processed emails increase CodeMie cost.

---

## Options Comparison Table

| Criteria | MCP Tool | Graph API Bridge | Workflow Tool Node |
|---|---|---|---|
| Separation of concerns | Low (coupled) | High (decoupled) | Low (coupled) |
| Push model (webhook) | Unclear (MCP listener?) | Clean (bridge hosts endpoint) | Unclear (chicken-and-egg) |
| Pull model (on-demand) | Yes (tool call) | Yes (bridge API) | Partial (manual trigger) |
| Auth complexity | High (Entra + PingOne in MCP) | Low (separate identity per system) | Medium (Entra in workflow) |
| Alevate support | Yes | Yes | Yes |
| SAP support | Indirect (via A2A) | Yes (bridge calls A2A) | Partial (workflow API) |
| Pre-processing | No | Yes (dedup, thread, enrich) | No |
| Webhook lifecycle | Complex (in MCP) | Clean (in bridge) | Unclear |
| Infrastructure cost | $0/month | $100-200/month | $0/month |
| Operational independence | No | Yes | No |

---

## Decision Outcome

**Chosen Option:** Option 2 - External Microservice (Graph API Bridge)

### Rationale

1. **Clean identity separation**: The bridge holds Microsoft Entra credentials for Graph API and PingOne credentials for CodeMie. These never cross boundaries. MCP tool approach (Option 1) would require bridging two identity systems within the MCP token propagation layer, which was not designed for this purpose.
2. **Webhook lifecycle management**: Graph API webhooks expire after 3 days and require HTTPS validation. The bridge service hosts the webhook endpoint, handles renewal, and manages validation tokens. Neither MCP tools nor workflow nodes are designed to act as inbound HTTP servers.
3. **Push model clarity**: When a new email arrives, Graph API sends a webhook notification to the bridge. The bridge fetches the email, pre-processes it, and calls CodeMie's workflow API. This is a clean, well-understood pattern. Options 1 and 3 both have a "who triggers the pipeline?" ambiguity.
4. **Pre-processing value**: The bridge can deduplicate emails (webhook notifications can fire multiple times), correlate thread IDs, extract metadata, and filter out already-processed messages before calling CodeMie. This prevents wasted LLM calls on duplicate or irrelevant emails.
5. **Operational independence**: The bridge can be scaled, deployed, and monitored independently of CodeMie. If the AI pipeline is down for maintenance, the bridge queues emails. If email volume spikes, the bridge scales without affecting AI pipeline resources.

### Implementation Summary

**Webhook Configuration:**
- Primary: Graph API webhook subscriptions
  - Resource: `/users/{mailbox}/messages`
  - Change type: `created`
  - Expiration: 3 days (maximum for mail resources)
  - Auto-renewal: bridge renews 12 hours before expiry
  - Notification URL: `https://bridge.example.com/api/graph/notifications`
  - Validation: lifecycle notification handling with `validationToken` query parameter
- Fallback: Polling every 60 seconds
  - Query: `/users/{mailbox}/messages?$filter=receivedDateTime ge {last_check}&$orderby=receivedDateTime`
  - Activated when webhook delivery fails 3 consecutive times
  - Deactivated when webhook delivery resumes

**Dual-Caller Architecture:**
- The bridge service calls CodeMie via two endpoints depending on context:
  - Alevate context: `POST /v1/workflows/{workflow_id}/executions` (starts the full pipeline workflow)
  - SAP context: `POST /v1/a2a/assistants/{assistant_id}` (invokes the pipeline via A2A, which internally triggers the same workflow)
- Bridge authenticates to CodeMie using a service account PingOne JWT (headless pattern, Multi-Tenancy ADR-020)

**Auth Flow (Two Separate Identity Providers):**

| System | Identity Provider | Auth Flow | Credentials |
|---|---|---|---|
| Microsoft Graph API | Microsoft Entra ID | OAuth 2.0 client_credentials | Application ID + client secret |
| CodeMie | PingOne | Service account JWT | Client ID + client secret |

- These are completely separate identity systems
- The bridge service holds both sets of credentials
- Graph API tokens are NOT the same as PingOne JWTs
- No token exchange or bridging between the two systems

**Graph API Permissions (Application-level, not user-delegated):**
- `Mail.Read` -- Read mail in all mailboxes (scoped to specific mailboxes via application access policy)
- `Mail.Send` -- Send mail as any user (scoped to specific mailboxes)
- `offline_access` -- Refresh tokens for long-running service

**Email Send Flow (after human approval):**
- Workflow Step 8 (post-approval) calls the bridge via REST API with the approved draft
- Bridge sends via Graph API: `POST /users/{mailbox}/sendMail`
- Bridge logs send confirmation and returns status to workflow

---

## Consequences

### Positive

✅ Clean separation of email ingestion and AI processing with independent scaling
✅ Reliable webhook lifecycle management isolated from AI pipeline concerns
✅ Pre-processing eliminates wasted LLM calls on duplicates and irrelevant messages
✅ Both push (webhook) and pull (on-demand API) models supported cleanly
✅ Single bridge service supports both Alevate and SAP integration paths
✅ Graph API credentials never enter the CodeMie tenant boundary

### Negative

❌ Additional microservice to deploy, monitor, and maintain (increases operational surface area)
❌ Infrastructure cost: ~$100-200/month for compute and monitoring
❌ Additional network hop adds ~50-100ms latency to email fetch operations
❌ Bridge service becomes a single point of failure for email ingestion (requires HA deployment)

### Mitigation Strategies

**For operational overhead:**
- Bridge is a small, stateless service (single Docker container) with a well-defined API surface
- Standard health checks, readiness probes, and auto-restart via Kubernetes
- Monitoring via Azure Monitor with alerts on webhook failure rate and processing latency

**For single point of failure:**
- Deploy 2+ replicas behind a load balancer for high availability
- Webhook notifications include a `clientState` field for idempotency; duplicate notifications are safely ignored
- Polling fallback activates automatically if webhook delivery fails

**For infrastructure cost:**
- Bridge runs on Azure App Service Basic tier (~$55/month) or as a lightweight AKS pod (shared node pool)
- Cost is small relative to total pipeline cost (~$540-1,400/month for AI agents)

---

## Compliance & Security

**Security Controls:**
- Graph API credentials (Entra ID application secret) stored in Azure Key Vault, not in bridge configuration files
- PingOne service account credentials stored in Azure Key Vault
- Bridge service runs with a managed identity for Key Vault access
- All communication over HTTPS (TLS 1.2+); webhook endpoint validated via Graph API validation token
- Application access policies restrict Graph API permissions to specific AR mailboxes (not org-wide)
- Bridge logs all email fetch and send operations with correlation IDs for audit

**Compliance Impact:**
- GDPR: Email content transits through the bridge in-memory only; no persistent storage of email content in the bridge service. Thread metadata (message IDs, timestamps) may be cached for deduplication
- SOC 2: Bridge access logs satisfy monitoring requirements; separate credentials per system satisfy segregation of duties
- Data Residency: Bridge deployed in the same Azure region as the Graph API tenant and CodeMie instance

---

## Cost Analysis

| Component | Cost | Notes |
|---|---|---|
| Bridge compute (Azure App Service B1) | ~$55/month | 1 instance; scale to 2 for HA ($110/month) |
| Monitoring (Azure Monitor) | ~$20-30/month | Logs, metrics, alerts |
| Key Vault (credential storage) | ~$5/month | Graph API + PingOne secrets |
| Graph API calls | ~$0/month | Included in Microsoft 365 license (no per-call charge) |
| **Total (single instance)** | **~$80-90/month** | |
| **Total (HA, 2 instances)** | **~$135-145/month** | |

**Comparison:**
- MCP Tool (Option 1): $0/month infrastructure, but higher development cost and auth complexity risk
- Workflow Tool Node (Option 3): $0/month infrastructure, but unresolved webhook and push-model issues
- Graph API Bridge: Modest cost for clean architecture, operational independence, and reliable webhook handling

---

## Related Decisions

- **[ADR-004](ADR-004-agent-design.md)**: Bridge triggers the CodeMie workflow defined in ADR-004; approved responses flow back through the bridge for Graph API send
- **[ADR-002](ADR-002-human-in-the-loop-design.md)**: After human approval (ADR-002), the workflow calls the bridge to send the approved response
- **[ADR-001](ADR-001-email-categorization-approach.md)**: Bridge pre-processing can apply initial rule-based filtering before emails reach the classification agent
- **[ADR-006](ADR-006-ui-triggered-email-processing-delegated-mcp.md)**: Complementary UI-triggered pull path for on-demand processing of specific emails. ADR-006 explicitly resolves this ADR's three MCP objections (Authorization header blocking, webhook lifecycle, push model ambiguity) for the pull model. Email send for both paths still routes through this bridge.
- **[Multi-Tenancy ADR-003](../../multytenancy/decisions/ADR-003-sap-pat-to-codemie-gateway.md)**: SAP path uses PAT Gateway; bridge uses headless API pattern
- **[Multi-Tenancy ADR-012](../../multytenancy/decisions/ADR-012-pingone-token-propagation-to-custom-mcp.md)**: Token propagation considerations for MCP-based alternatives (rejected but documented)
- **[Multi-Tenancy ADR-020](../../multytenancy/decisions/ADR-020-headless-api-integration-pattern.md)**: Bridge authenticates to CodeMie following the headless API integration pattern

**Dependencies:**
- This decision depends on: ADR-004 (defines the workflow/A2A endpoints the bridge calls), Multi-Tenancy ADR-020 (headless API pattern)
- This decision enables: ADR-001 (email ingestion feeds classification), ADR-002 (approved response sent via bridge)

---

## References

- [Microsoft Graph API - Mail Resource](https://learn.microsoft.com/en-us/graph/api/resources/mail-api-overview)
- [Microsoft Graph Webhooks (Change Notifications)](https://learn.microsoft.com/en-us/graph/webhooks)
- [Microsoft Graph Application Access Policies](https://learn.microsoft.com/en-us/graph/auth-limit-mailbox-access)
- [Microsoft Entra ID - Client Credentials Flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-client-creds-grant-flow)
- [CodeMie A2A API Documentation](https://docs.codemie.com/a2a/overview) (internal)
- [Multi-Tenancy ADR-020 - Headless API Integration Pattern](../../multytenancy/decisions/ADR-020-headless-api-integration-pattern.md)

---

## Implementation Checklist

**Phase 1: Bridge Service Foundation** (Weeks 1-2)
- [ ] Scaffold bridge microservice (Node.js/Python, Dockerfile, health checks)
- [ ] Implement Microsoft Entra ID OAuth client_credentials flow with token caching and refresh
- [ ] Implement PingOne service account JWT acquisition for CodeMie authentication
- [ ] Store both credential sets in Azure Key Vault; bridge accesses via managed identity
- [ ] Deploy to Azure App Service (or AKS pod) with HTTPS endpoint

**Phase 2: Email Ingestion** (Weeks 2-3)
- [ ] Implement Graph API webhook subscription management (create, renew, validate)
- [ ] Implement webhook notification handler (receive notification, fetch email, deduplicate)
- [ ] Implement polling fallback (60-second interval, delta query with `$filter`)
- [ ] Implement pre-processing: thread correlation (using `conversationId`), metadata extraction
- [ ] Wire push model: webhook -> fetch -> pre-process -> call CodeMie workflow API

**Phase 3: Email Sending & Pull Model** (Weeks 3-4)
- [ ] Implement email send endpoint (receives approved draft from workflow, sends via Graph API)
- [ ] Implement pull model API: Alevate/SAP can POST email ID to trigger processing of a specific email
- [ ] Implement send confirmation logging and error handling (bounce detection)
- [ ] End-to-end test: inbound email -> pipeline -> approval -> send response

**Phase 4: High Availability & Monitoring** (Week 5)
- [ ] Deploy second replica for HA; configure load balancer
- [ ] Implement webhook failure detection and automatic polling fallback activation
- [ ] Deploy monitoring dashboards (webhook health, email processing rate, send success rate)
- [ ] Configure alerting for: webhook subscription expiry, Graph API errors, CodeMie call failures
- [ ] Document runbook for bridge operational procedures

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
