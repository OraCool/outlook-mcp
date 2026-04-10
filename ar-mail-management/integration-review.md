# Integration Architecture Review

**Status:** Complete
**Date:** 2026-03-31
**Author:** Architecture Team
**Scope:** Review of existing Codemie-Serrala integration architecture as it applies to the AR Email Management solution

---

## 1. Executive Summary

This document reviews the existing integration architecture between Codemie (EPAM AI/Run), Serrala Alevate, and SAP, based on analysis of the multitenancy architecture decisions (ADR-001 through ADR-021). The goal is to identify how the AR email management solution fits within the established integration patterns, and to surface constraints, gaps, and design considerations that will influence the agent architecture (ADR-004) and Outlook integration pattern (ADR-005).

**Key conclusions:**

- Codemie operates as a **headless AI engine** (ADR-020); the AR email management UI lives in SAP/Alevate, not in Codemie.
- Two distinct calling paths exist: **Alevate** (PingOne JWT Bearer, ADR-002) and **SAP** (PAT Gateway token exchange, ADR-003). The email processing solution must support both.
- Tenant isolation is **JWT-native and stateless** (ADR-001, ADR-009, ADR-014, ADR-015). Tenant identity is encoded in the JWT `groups` claim as `application_tenant-{id}` and enforced at multiple layers: ORM query filtering, PostgreSQL schema routing, Elasticsearch alias filtering, and LiteLLM team isolation.
- **Microsoft Graph API OAuth tokens are separate from PingOne JWTs.** Outlook access requires a distinct OAuth 2.0 consent and token flow that does not exist in the current architecture. This is the primary integration gap for the AR email management solution.
- **No built-in approval UI exists in Codemie.** The human-in-the-loop approval workflow must be implemented in the SAP/Alevate UI layer, consuming Codemie's structured proposal output.
- The **zero-Codemie-code-changes** constraint (Phase 1) limits integration options to patterns that use existing Codemie capabilities: header propagation, MCP server extensibility, and the headless API contract.

---

## 2. Current Integration Landscape

### 2.1 System Topology

The Codemie platform is deployed as a headless AI engine within an AKS (Azure Kubernetes Service) cluster. It does not serve end-users directly. Instead, two upstream systems call Codemie's API:

```
                    +-----------------+
                    |    PingOne      |
                    | (Serrala OIDC)  |
                    +-------+---------+
                            |
              OIDC tokens   |   JWKS validation
           +----------------+----------------+
           |                                 |
  +--------v--------+              +---------v---------+
  | Alevate Platform |              |   PAT Gateway     |
  | (Serrala SaaS)   |              | (SpringBoot proxy)|
  |                  |              | in Alevate AKS    |
  | - Browser UI     |              +---------+---------+
  | - Headless API   |                        ^
  +--------+---------+                        |
           |                          +-------+-------+
           |                          |  SAP FS2/S4   |
           |                          | (PAT Bearer)  |
           |                          +---------------+
           |
  +--------v--------------------------------------------+
  |              Codemie AKS Cluster                    |
  |                                                     |
  |  Traefik -> oauth2-proxy (ForwardAuth) -> Codemie   |
  |  (ingress)  skip_jwt_bearer_tokens=true    API      |
  |              extra_jwt_issuers=pat-gw               |
  |                                                     |
  |  IDP_PROVIDER=oidc (OIDCIdp)                        |
  |  LiteLLM (JWT pass-through, team_id=tenant_id)      |
  |  Elasticsearch (tenant alias + permission filter)    |
  |  PostgreSQL (schema-per-tenant via search_path)      |
  +-----------------------------------------------------+
```

### 2.2 Alevate Integration Path (ADR-002)

The Alevate platform embeds Codemie AI features within its own UI. Alevate holds a PingOne JWT from the user's existing session and sends it directly to the Codemie API as a Bearer token.

**Authentication contract:**
- Same PingOne JWT sent in two headers: `Authorization: Bearer <jwt>` and `X-PingOne-Token: <jwt>`
- The `Authorization` header is consumed by oauth2-proxy and Codemie's `OIDCIdp` for authentication
- The `X-PingOne-Token` header is a propagation carrier for downstream MCP servers (ADR-012), because `Authorization` is on the `MCP_BLOCKED_HEADERS` list
- Token TTL: approximately 65 minutes; SDKs handle refresh
- `Content-Type: application/json` is required

**Capabilities:** Alevate can invoke Codemie assistants interactively (browser-based chat UI) or via the headless API (`POST /v1/assistants/{assistantId}/model` or `POST /v1/conversations`).

### 2.3 SAP Integration Path (ADR-003)

SAP communicates with Alevate using Personal Access Tokens (PATs) -- JWTs issued by Alevate's User Manager. These PATs have a different claim structure than PingOne JWTs and cannot be validated directly by Codemie.

**Token exchange flow:**
1. SAP sends an Alevate PAT JWT to the PAT Gateway
2. PAT Gateway performs 6-step validation against Alevate's User Manager
3. PAT Gateway mints a short-lived Codemie-compatible JWT (5-minute TTL, RS256, signed via Azure Key Vault)
4. Claim mapping: `created_by` -> `sub`, User Manager `email` -> `email`, `tenantId` -> `groups: ["application_tenant-{tenantId}"]`
5. Codemie validates the gateway-issued JWT via JWKS (the PAT Gateway exposes a `/.well-known/openid-configuration` endpoint)
6. oauth2-proxy accepts the PAT Gateway issuer via `--extra-jwt-issuers`

**Capabilities:** SAP can only invoke Codemie via the headless API. The primary endpoint is `POST /v1/a2a/assistants/{assistant_id}` (agent-to-agent). No interactive assistant UI is available from SAP.

**Infrastructure:** 3 replicas minimum with PodDisruptionBudget for HA. Estimated cost: $155-$320/month.

### 2.4 Headless API Contract (ADR-020)

Codemie operates as a headless AI engine for all production integrations. End-users never access Codemie directly -- they interact with their familiar SaaS platform (SAP or Alevate), which calls Codemie's API behind the scenes.

**Primary endpoints for the AR email management use case:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/a2a/assistants/{assistant_id}` | POST | Agent-to-agent execution (SAP path) |
| `/v1/assistants/{assistantId}/model` | POST | Call assistant model (Alevate path) |
| `/v1/conversations` | POST | Create conversation (thread-aware) |
| `/v1/conversations/{conversationId}` | GET | Retrieve conversation with history |
| `/v1/a2a/assistants/{assistant_id}/.well-known/agent.json` | GET | Agent Card discovery |

**Required headers:**
```
Authorization: Bearer <pingone-jwt>       (or PAT Gateway JWT for SAP path)
X-PingOne-Token: <pingone-jwt>            (for MCP token propagation)
Content-Type: application/json
X-Request-ID: <uuid>                      (correlation ID)
```

**Performance targets:** p50 < 300ms, p95 < 500ms, p99 < 1000ms. Rate limit: 100 req/min per tenant (configurable).

**Data flow principle:** Codemie does not store business data. Transaction data is processed in-memory and returned as structured proposals. The customer app stores results in its own SAP/ERP system.

---

## 3. Authentication Flows

### 3.1 Alevate-to-Codemie Flow (Browser User Session)

```
1. User logs in to Alevate via PingOne OIDC (Authorization Code flow)
2. PingOne issues a Frontend Token (JWT, ~65 min TTL)
   - Contains: sub, email, tenant (numeric string), tenants[], groups
   - Issuer: https://auth.{env}.serrala.cloud/as
3. Alevate UI/SDK passes the token to Codemie:
   - Authorization: Bearer <pingone-jwt>
   - X-PingOne-Token: <pingone-jwt>
4. Traefik forwards to oauth2-proxy (ForwardAuth)
   - oauth2-proxy: --skip-jwt-bearer-tokens=true
   - Validates JWT signature via PingOne JWKS endpoint
5. Codemie API receives the request
   - OIDCIdp extracts groups claim: ["application_tenant-{id}"]
   - Maps to Codemie project via User.project_names
   - Populates User object: sub, email, applications
6. Query-level scoping: WHERE project_name = :project
```

### 3.2 SAP-to-Codemie Flow (Headless, PAT Gateway)

```
1. SAP obtains an Alevate PAT (JWT issued by Alevate User Manager)
   - Contains: created_by (UUID), tenantId (Long)
2. SAP sends request to PAT Gateway:
   - Authorization: Bearer <alevate-pat>
3. PAT Gateway performs 6-step validation:
   a. JWT decode + signature check
   b. Expiry check
   c. User Manager introspection (user exists, active)
   d. Tenant membership validation
   e. Role/permission check
   f. Rate limiting
4. PAT Gateway mints Codemie-compatible JWT (5 min TTL, RS256):
   - sub: <created_by UUID>
   - email: <looked up from User Manager>
   - groups: ["application_tenant-{tenantId}"]
   - iss: <PAT Gateway issuer URL>
5. PAT Gateway forwards to Codemie:
   - Authorization: Bearer <codemie-jwt>
6. Traefik -> oauth2-proxy validates via PAT Gateway JWKS
   (registered via --extra-jwt-issuers)
7. Codemie OIDCIdp processes as standard OIDC JWT
```

### 3.3 Token Lifecycle Summary

| Token | Issuer | TTL | Refresh Strategy |
|-------|--------|-----|------------------|
| PingOne Frontend Token | PingOne AS | ~65 min | SDK refresh at 80% TTL elapsed (~52 min) |
| Alevate PAT | Alevate User Manager | Configurable (long-lived) | Manual rotation |
| PAT Gateway Codemie JWT | PAT Gateway | 5 min | Minted per-request; no refresh needed |
| Microsoft Graph API Token | Azure AD / Entra ID | ~60 min | **Not yet integrated** -- see Section 5 |

---

## 4. Tenant Isolation Model

### 4.1 Isolation Layers

Tenant isolation in the Codemie-Serrala integration is enforced across five independent layers, all driven by the same JWT identity:

| Layer | Isolation Mechanism | Boundary Type | ADR |
|-------|-------------------|---------------|-----|
| **L1: Authentication** | JWT signature validation via JWKS | Hard | ADR-009, ADR-011 |
| **L2: Application/Project** | `groups` claim -> `User.project_names` -> ORM WHERE clause | Logical | ADR-001, ADR-014 |
| **L3: Database** | Schema-per-tenant in PostgreSQL (`tenant_{tenant_id}`, `search_path` routing) | Physical | ADR-015 |
| **L4: Vector Search** | Elasticsearch tenant alias + permission filter + project scope + source scope | Physical + Logical | ADR-017 |
| **L5: LLM Routing** | LiteLLM JWT `team_id` claim -> per-tenant rate limits, budgets, model access | Logical | ADR-016 |

### 4.2 Tenant Identity Flow

```
JWT groups claim: ["application_tenant-{id}"]
    |
    v
OIDCIdp.extract_user() -> User.project_names = ["tenant-{id}"]
    |
    +-> ORM queries: WHERE project_name IN (:project_names)
    +-> PostgreSQL: SET search_path TO tenant_{id}
    +-> Elasticsearch: alias filter on tenant_{id}
    +-> LiteLLM: team_id = tenant_{id}
```

### 4.3 Implications for AR Email Management

- **Tenant = Company.** Each Serrala customer (company) maps to one Codemie project. Email processing is scoped to the tenant's project.
- **Per-inbox isolation is not built in.** If a single company has multiple AR inboxes (e.g., regional inboxes), all inboxes under the same tenant share the same Codemie project. Inbox-level isolation would need to be implemented at the application layer (e.g., tagging conversations with an inbox identifier).
- **User identity flows through.** The `sub` and `email` from the JWT are available in the Codemie `User` object for audit trail purposes. Every AI classification, draft, and action can be attributed to the user who initiated the processing.
- **LLM cost attribution is per-tenant.** LiteLLM's JWT-based team isolation (ADR-016) means that all email processing LLM calls for a tenant are tracked and rate-limited together. High-volume email processing for one tenant cannot starve another tenant's LLM access.

### 4.4 Phased Isolation Roadmap

| Phase | Isolation Level | Description |
|-------|----------------|-------------|
| **Phase 1 (MVP)** | Shared Codemie instance, query-level scoping | Single Codemie deployment, tenant scoped via JWT `groups` claim and ORM WHERE clause. No schema-per-tenant yet. |
| **Phase 2** | Row-Level Security or schema routing | PostgreSQL RLS or Alevate-native schema routing (ADR-015) for database-enforced isolation. |
| **Phase 3** | Full schema-per-tenant | `tenant_{tenant_id}` schemas in PostgreSQL, Elasticsearch tenant aliases, LiteLLM JWT team isolation. |

---

## 5. Outlook Auth Flow

### 5.1 The Gap: Graph API OAuth vs. PingOne JWT

The current integration architecture provides two JWT types (PingOne and PAT Gateway), both scoped to Codemie authentication. **Neither token grants access to Microsoft Graph API.**

Microsoft Graph API requires an OAuth 2.0 token issued by **Azure AD (Entra ID)**, not by PingOne. The token must carry Microsoft Graph-specific scopes (e.g., `Mail.Read`, `Mail.ReadWrite`, `Mail.Send`) and be issued for the Microsoft Graph resource (`https://graph.microsoft.com`).

This means:

1. **Separate consent is required.** A Graph API OAuth 2.0 application registration must be created in the Serrala Azure AD tenant (or the customer's tenant, depending on the deployment model). The AR team must consent to the application accessing their mailbox.

2. **The Graph API token is a different identity boundary.** PingOne authenticates the user to Codemie; Azure AD authenticates the application (or user) to Microsoft 365. These are independent trust domains.

3. **Token propagation via `X-PingOne-Token` does not help for Graph API.** The MCP header relay mechanism (ADR-012) propagates the PingOne JWT to custom MCP servers. A Graph API OAuth token would need its own propagation path.

### 5.2 Possible Token Acquisition Models

| Model | Description | Applicability |
|-------|-------------|---------------|
| **Application permissions** (client_credentials) | A service principal with `Mail.Read`, `Mail.Send` scopes; no per-user consent. Admin grants access to specific mailboxes. | Preferred for automated email processing. The service runs without user interaction. |
| **Delegated permissions** (authorization_code) | User grants consent via OAuth redirect; token scoped to their mailbox. Requires refresh token management. | Suitable for interactive scenarios (Alevate UI user triggers email processing). |
| **On-behalf-of (OBO)** | Alevate backend exchanges PingOne JWT for a Graph API token via Azure AD OBO flow. Requires trust between PingOne and Azure AD. | Possible but adds complexity; requires Azure AD to trust PingOne as an identity source. |

### 5.3 Architectural Implication

The Outlook integration must be designed with the understanding that **Graph API authentication is entirely separate from the Codemie authentication flow.** The solution architecture (ADR-005) must define:
- Where the Graph API OAuth token is obtained and stored
- How the token is refreshed (Graph API tokens expire in ~60 minutes)
- Whether the token is managed by Codemie (via MCP server), by an external service, or by the calling application (SAP/Alevate)

---

## 6. Approval UI Location

### 6.1 Codemie Has No Built-In Approval UI

Codemie is a headless AI engine (ADR-020). It provides:
- **Assistant execution** -- processes input, returns structured proposals
- **Workflow engine** -- orchestrates multi-step processing with PAUSED state support
- **Admin UI** -- for configuration and monitoring only (not for end-user workflows)

Codemie does **not** provide:
- An end-user-facing approval screen
- A notification system for pending approvals
- An approval/reject action endpoint (approvals are business logic, not AI logic)

### 6.2 Approval Flow Architecture

The human-in-the-loop approval for AR email management must be implemented in the **SAP/Alevate UI layer**:

```
1. Email arrives -> processed by Codemie (classification, draft, action proposal)
2. Codemie returns structured output:
   {
     "classification": { "category": "INVOICE_DISPUTE", "confidence": 0.89 },
     "draft_response": { "subject": "...", "body": "...", "tone": "formal" },
     "proposed_action": { "type": "LOG_DISPUTE", "sap_params": { ... } },
     "reasoning": "...",
     "requires_approval": true
   }
3. SAP/Alevate stores the proposal in its own database
4. SAP/Alevate presents the proposal in its approval UI
5. Human reviewer approves, edits, or rejects
6. If approved:
   - SAP/Alevate sends the email (via Graph API or its own email service)
   - SAP/Alevate executes the SAP action (log dispute, update payment date, etc.)
7. Audit trail recorded in SAP/Alevate
```

### 6.3 Workflow PAUSED State

Codemie workflows support a `PAUSED` state where execution halts until an external signal resumes it. This could be used to represent the "waiting for human approval" step:
- Workflow executes classification and drafting steps
- Workflow enters PAUSED state with the proposal as output
- External system (SAP/Alevate) retrieves the paused workflow output
- After human approval, the external system resumes the workflow or takes action independently

**Open question:** Whether the PAUSED state mechanism is suitable for production approval workflows, or whether the calling application should simply treat each Codemie API call as stateless (call Codemie, get proposal, handle approval entirely externally). This decision affects ADR-002 (human-in-the-loop design) and ADR-004 (agent design).

---

## 7. Headless API Pattern for Email Processing

### 7.1 How ADR-020 Enables Automated Email Processing

The headless API pattern (ADR-020) is directly applicable to the AR email management use case. An automated service can call Codemie without user interaction, provided it holds a valid JWT:

**Automated processing flow:**
```
1. Email Monitor Service detects new email in Outlook (via Graph API)
2. Service extracts email content, metadata, thread context
3. Service calls Codemie API:
   POST /v1/a2a/assistants/{classifier_assistant_id}
   Authorization: Bearer <jwt>
   Content-Type: application/json
   X-Request-ID: <uuid>
   {
     "query": "<email content + thread context>",
     "context": { ... }
   }
4. Codemie returns classification + proposal
5. Service stores result for human review in SAP/Alevate
```

### 7.2 JWT for Automated Services

The automated email processing service needs a JWT to call Codemie. Two options exist within the current architecture:

| Approach | Token Source | TTL | Codemie Changes |
|----------|-------------|-----|-----------------|
| **Alevate headless client** | PingOne `client_credentials` grant -> PingOne JWT with tenant context | ~65 min | None (ADR-002 path) |
| **SAP headless client** | Alevate PAT -> PAT Gateway -> Codemie JWT | 5 min (per request) | None (ADR-003 path) |

For a **background email processing service** that runs continuously (monitoring the inbox and submitting emails to Codemie), the Alevate headless client approach (PingOne `client_credentials`) is more appropriate because:
- The service runs without a user session
- `client_credentials` tokens can be refreshed programmatically at 80% TTL
- Multi-tenant switching requires obtaining a fresh token with the target tenant context
- The PAT Gateway path (5-min TTL, per-request mint) adds unnecessary overhead for high-frequency calls

### 7.3 Batch vs. Real-Time Processing

The headless API pattern supports both:
- **Real-time:** Webhook notification from Graph API triggers immediate Codemie API call
- **Batch:** Polling service collects emails at intervals and submits them as a batch

The API rate limit (100 req/min per tenant, configurable) must be considered for high-volume batch processing scenarios.

---

## 8. Architectural Constraints for Agent Design

The following constraints from the existing integration architecture directly affect the agent design choices in ADR-004:

### 8.1 Zero Codemie Code Changes (Phase 1)

This is the **primary constraint**. All ADRs (002, 003, 011, 012, 020) are designed around the principle that Codemie core code is not modified. The AR email management solution must use:
- Existing API endpoints (`/v1/a2a/assistants/`, `/v1/conversations`, `/v1/assistants/{id}/model`)
- Existing MCP server extensibility (custom MCP servers deployed alongside Codemie)
- Existing header propagation (`X-PingOne-Token`, `X-Tenant-Id`, `X-User-Id`)
- Existing workflow engine (if workflow-based orchestration is chosen)

**Implication for agent design:** The solution cannot add new Codemie API endpoints, modify the OIDCIdp, or change the LLM routing logic. Multi-agent orchestration must use existing Codemie primitives (chaining conversations, workflow nodes, or external orchestration).

### 8.2 JWT-Native Tenant Encoding (Stateless Validation)

Every API call must carry a valid JWT with tenant context. There is no session state on the Codemie side.

**Implication:** If the email processing pipeline involves multiple sequential Codemie API calls (e.g., classify, then draft, then route), each call must carry the JWT. Token expiry must be monitored, especially for long-running thread processing.

### 8.3 MCP_BLOCKED_HEADERS Immutability

The `Authorization` header is blocked from propagation to MCP servers. The `X-PingOne-Token` header is the side-channel for propagating user identity to custom MCP servers.

**Implication:** If a custom MCP server needs to call Microsoft Graph API, it cannot receive the Graph API OAuth token via the `Authorization` header. A custom header (e.g., `X-Graph-Token`) or environment-based configuration would be needed, similar to how `X-PingOne-Token` works for PingOne tokens.

### 8.4 Token Expiry Handling

| Token | TTL | Risk for Email Processing |
|-------|-----|--------------------------|
| PingOne Frontend Token | ~65 min | Long thread processing may exceed TTL |
| PAT Gateway JWT | 5 min | Adequate for single-request classification; too short for multi-step workflows |
| Graph API Token | ~60 min | Must be refreshed for long-running inbox monitoring |

**Implication:** The email processing service must implement token refresh for all three token types. The PAT Gateway's 5-minute TTL means each step in a multi-step SAP-initiated workflow effectively requires a fresh token.

### 8.5 Per-Tenant LLM Routing

LiteLLM's JWT-based team isolation means that LLM model access, rate limits, and budgets are enforced per-tenant.

**Implication:** High-volume email processing tenants may need custom LLM budget allocations. The AR email management assistant(s) consume from the same tenant LLM budget as all other Codemie assistants for that tenant.

### 8.6 Synchronous Request-Response Only

All Codemie API endpoints are synchronous. There is no built-in webhook or callback mechanism for asynchronous result delivery.

**Implication:** If email processing takes longer than the API timeout (e.g., complex thread analysis), the calling service must handle timeouts and retries. The `PAUSED` workflow state is a partial workaround, but resumption is also synchronous.

### 8.7 Data Sovereignty

Per ADR-020, Codemie does not store business data. Email content processed through Codemie is handled in-memory and returned as proposals. The calling application (SAP/Alevate) is responsible for storing results.

**Implication:** Email content, classification results, and draft responses must be stored by the AR email management service, not by Codemie. Codemie stores only execution metadata (token usage, latency, conversation ID).

---

## 9. Gaps and Open Questions

### 9.1 Critical Gaps

| # | Gap | Impact | Owner | Target Date |
|---|-----|--------|-------|-------------|
| G1 | **Graph API OAuth token acquisition and management** is not addressed in any existing ADR. The AR email solution is the first use case requiring non-PingOne OAuth tokens. | Blocks Outlook integration | Architecture Team | ADR-005 |
| G2 | **Graph API token propagation to MCP servers.** If a custom Outlook MCP server is used, how does it receive the Graph API token? `Authorization` is blocked; `X-PingOne-Token` carries a PingOne JWT, not a Graph token. | Blocks MCP-based Outlook integration option | Architecture Team | ADR-005 |
| G3 | **Approval UI implementation pattern.** Codemie has no approval UI. How does the SAP/Alevate UI discover pending approvals, present them, and record decisions? Is this a polling model (check for PAUSED workflows) or an event-driven model (Codemie notifies SAP/Alevate)? | Blocks ADR-002 (human-in-the-loop design) | Architecture Team + Alevate Team | ADR-002 |
| G4 | **Multi-inbox support within a single tenant.** If a company has multiple AR inboxes (e.g., `ar-germany@company.com`, `ar-france@company.com`), how is inbox-level scoping achieved within a single Codemie project? | Affects data model design | Architecture Team | Architecture Overview |

### 9.2 Open Questions

| # | Question | Context | Decision Venue |
|---|----------|---------|----------------|
| Q1 | Should the email processing service be a dedicated microservice or a Codemie MCP server? | Trade-off between operational independence and tight Codemie integration. See ADR-005 options A, B, C. | ADR-005 |
| Q2 | Can Codemie workflows chain multiple assistants (classifier -> drafter -> router) in a single execution, or does multi-step processing require external orchestration? | Affects ADR-004 (agent design). If Codemie workflows support multi-step, the pipeline can run inside Codemie. Otherwise, an external orchestrator is needed. | ADR-004 |
| Q3 | Is the `PAUSED` workflow state suitable for production approval workflows with SLA requirements (e.g., "approve within 4 hours")? Does Codemie support timeout or escalation on PAUSED workflows? | If not, the calling application must implement its own timeout and escalation logic. | ADR-002 |
| Q4 | What happens to in-flight email processing when a PingOne token expires mid-pipeline? Does Codemie return a specific error code that the calling service can retry on? | ADR-012 defines `ERR_TOKEN_EXPIRED` for MCP servers, but the behavior at the Codemie API level needs confirmation. | Architecture Team |
| Q5 | Can a single Codemie assistant be invoked by both the Alevate path (ADR-002) and the SAP path (ADR-003) simultaneously, or do they need separate assistant configurations? | Both paths produce valid OIDC JWTs with the same `groups` claim format, so theoretically the same assistant should work. Confirm with Codemie team. | Codemie Team |
| Q6 | How are SAP correspondence templates retrieved and injected into the LLM context? Is this a Codemie data source, an MCP tool call, or context provided by the calling application in the API request body? | Affects context injection architecture and ADR-003 (thread context management). | ADR-003, ADR-005 |
| Q7 | What is the maximum payload size for the A2A endpoint? Long email threads with full history may exceed limits. | ADR-020 specifies 1MB request / 5MB response for the execute endpoint. Confirm whether the A2A endpoint has the same limits. | Codemie Team |

---

## 10. Recommendations

### 10.1 For ADR-004 (Agent Design)

1. **Prefer external orchestration over Codemie-internal workflows for Phase 1.** The zero-code-changes constraint and the need for Graph API token management favor a pattern where an external service orchestrates the email processing pipeline and calls Codemie's headless API for AI-specific steps (classification, drafting).

2. **Design for both calling paths from day one.** The classifier and drafter assistants should be invokable via both the Alevate headless API (ADR-002) and the SAP A2A endpoint (ADR-003). Use the same assistant configuration; the JWT difference is handled at the ingress layer.

3. **Treat Codemie as stateless.** Do not rely on Codemie's conversation state for cross-step context. Instead, assemble the full context (thread summary, customer data, previous AI actions) in the calling service and pass it in each API request.

### 10.2 For ADR-005 (Outlook Integration Pattern)

1. **Evaluate the external microservice option (Option B) seriously.** It naturally separates Graph API token management from Codemie authentication, supports both calling paths, and avoids the MCP_BLOCKED_HEADERS limitation for Graph API tokens.

2. **Use application permissions (client_credentials) for Graph API.** Automated email processing does not have an interactive user session. Application permissions with admin consent to specific mailboxes are simpler and more reliable than delegated permissions for background processing.

3. **Address Graph API token storage as a first-class concern.** The token must be stored securely (Azure Key Vault or Kubernetes secret), refreshed automatically, and scoped to the minimum required permissions (`Mail.Read`, `Mail.ReadWrite`, `Mail.Send`).

### 10.3 For ADR-002 (Human-in-the-Loop Design)

1. **Implement approval entirely in SAP/Alevate.** Do not depend on Codemie's PAUSED workflow state for production approval workflows. The approval UI, timeout logic, escalation, and audit trail should be owned by SAP/Alevate.

2. **Define a clear proposal schema.** The structured output from Codemie (classification, draft, proposed action, reasoning, confidence) becomes the input to the approval UI. This schema must be stable and versioned.

### 10.4 General Recommendations

1. **Engage the Codemie team early** to confirm assumptions about the A2A endpoint behavior, workflow PAUSED state capabilities, and multi-assistant chaining support.

2. **Plan for Phase 1 constraints but design for Phase 3.** The MVP should work within the zero-code-changes constraint, but the architecture should anticipate schema-per-tenant isolation and Kafka-based event-driven processing that later phases will enable.

3. **Establish a correlation ID convention.** Use `X-Request-ID` headers across all services (email monitor, Codemie, SAP, Alevate) to enable end-to-end tracing of email processing events.

---

## Appendix A: ADR Cross-Reference Matrix

| ADR | Title | Relevance to AR Email Management |
|-----|-------|----------------------------------|
| ADR-001 | Codemie Multi-Tenancy Strategy | Defines project-per-tenant isolation model; scopes all email processing to tenant |
| ADR-002 | Alevate-to-Codemie SDK/API Authentication | Alevate calling path for email processing; PingOne JWT Bearer pattern |
| ADR-003 | SAP PAT-to-Codemie Token Exchange Gateway | SAP calling path for headless email processing; PAT Gateway token exchange |
| ADR-009 | Direct JWT Authentication | Foundation for stateless JWT validation in Codemie; eliminates Keycloak dependency |
| ADR-011 | PingOne OIDC Integration (Keycloak-Free) | Confirms generic OIDC support; PingOne as sole IdP |
| ADR-012 | PingOne Token Propagation to Custom MCP | MCP header relay mechanism; relevant if Outlook integration uses an MCP server |
| ADR-013 | PingOne-Keycloak Integration for MCP Validation | Superseded by ADR-011; confirms MCP servers receive identity via headers, not JWT |
| ADR-014 | Tenant-Project Relationship Model | 1:1 tenant-to-project mapping (Phase 1); affects inbox-to-project scoping |
| ADR-015 | Data Isolation via Schema Routing | Schema-per-tenant PostgreSQL; Phase 3 target for email data isolation |
| ADR-016 | LiteLLM Tenant Isolation | Per-tenant LLM budgets and rate limits; affects email processing throughput |
| ADR-017 | Elasticsearch Hybrid Tiered Index Strategy | Vector search isolation; relevant if email content is indexed for RAG |
| ADR-019 | Kafka-Based Tenant Onboarding | Event-driven provisioning; may be extended for email processing event streams |
| ADR-020 | Headless API Integration Pattern | Primary integration contract for AR email management; API-first design |
| ADR-021 | Traefik Gateway API Migration | Ingress layer migration; affects oauth2-proxy wiring for JWT validation |

---

## Appendix B: Token Flow Comparison

```
ALEVATE PATH (Interactive or Headless):
  User -> PingOne (OIDC) -> Frontend Token (JWT, 65 min)
       -> Alevate UI/SDK
       -> Authorization: Bearer <jwt> + X-PingOne-Token: <jwt>
       -> Traefik -> oauth2-proxy -> Codemie API
       -> OIDCIdp: groups -> project -> WHERE clause

SAP PATH (Headless Only):
  SAP -> Alevate PAT (User Manager JWT)
      -> PAT Gateway (validate + mint, 5 min JWT)
      -> Authorization: Bearer <codemie-jwt>
      -> Traefik -> oauth2-proxy (extra_jwt_issuers) -> Codemie API
      -> OIDCIdp: groups -> project -> WHERE clause

GRAPH API PATH (Not Yet Implemented):
  Service -> Azure AD (client_credentials or auth_code)
          -> Graph API Token (OAuth 2.0, ~60 min)
          -> https://graph.microsoft.com/v1.0/...
          -> Mail.Read, Mail.Send scopes
          [Separate identity domain from PingOne/Codemie]
```

---

*Part of the AR Email Management Domain -- Financial System Modernization Project*
