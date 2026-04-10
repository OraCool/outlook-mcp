# ADR-006: UI-Triggered Email Processing via Delegated MCP

**Status:** Accepted
**Date:** 2026-04-03
**Decision Makers:** AR Email Management Architecture Team
**Technical Story:** Add a second trigger path for the AR email pipeline: an AR specialist in the Serrala/Alevate UI explicitly selects an email for on-demand AI processing. The UI calls the CodeMie Assistants API; a CodeMie assistant (LangGraph ReAct) invokes an Outlook MCP Server as a tool; the MCP server accesses Microsoft Graph API using the user's **delegated** OAuth token passed from the browser.

---

## Context and Problem Statement

ADR-005 established the **automatic push trigger path**: an external Graph API Bridge microservice monitors Outlook via webhooks/polling using application-level `client_credentials` permissions, and automatically submits new emails to the CodeMie workflow pipeline.

This is the right approach for unattended, high-volume processing of new arrivals. However, it does not cover a distinct and equally important use case: an AR specialist who is already working in the Serrala/Alevate UI wants to trigger AI processing for a **specific email** on-demand — for example:

- Re-processing an email that was previously skipped or marked as already handled
- Processing an email from a personal mailbox or non-monitored folder
- Triggering AI analysis on an older email that predates the Bridge's subscription window
- Testing the pipeline on a specific email without waiting for a webhook

ADR-005 considered (Option 1) using a CodeMie MCP tool for Outlook integration and **rejected it** for three reasons specific to the webhook/push model:

1. `Authorization` header is on `MCP_BLOCKED_HEADERS` — Graph token cannot propagate that way
2. Webhook subscription lifecycle is complex inside an MCP server
3. Push model (webhook fires → who invokes the MCP tool?) is ambiguous

**All three objections dissolve for the UI-triggered pull model:**

| ADR-005 Objection | Why It Dissolves for the UI Path |
|---|---|
| `Authorization` blocked | `X-PingOne-Token` pattern (ADR-012) proves a custom side-channel header works; introduce `X-Graph-Token` following the same mechanism |
| Webhook lifecycle complexity | No webhooks involved — the user triggers the call explicitly |
| Push model ambiguity | No push model — the UI initiates the call; the assistant decides when to invoke the tool |

The Multi-Tenancy ADR-012 already established the exact pattern needed: a custom header (`X-PingOne-Token`) carries a bearer token from the UI, through CodeMie's MCP-Connect Bridge, to a custom MCP server — where it is used as `Authorization: Bearer` for a downstream API call. The same mechanism applies to a Microsoft Graph token via `X-Graph-Token`.

**Trigger mechanism**: The Serrala/Alevate UI calls `POST /v1/assistants/{id}/chat` (CodeMie Assistants API, same as existing Path A in the component diagram). The CodeMie assistant's LangGraph ReAct engine invokes the Outlook MCP Server as a tool during its conversation turn. This is exactly the pattern ADR-012 documents: *"The Codemie Assistant Engine (LangGraph ReAct) executes MCP tools during conversation turns."*

---

## Decision Drivers

- **Reuse ADR-012 pattern**: No new infrastructure for token relay — `X-Graph-Token` header follows the established `X-PingOne-Token` side-channel mechanism
- **User-delegated permissions**: The Microsoft Graph token is acquired by the user's browser session (PKCE/OAuth2), so access is scoped to the user's authorized mailboxes — more restrictive than application-level permissions
- **No webhook complexity**: UI-triggered pull model avoids all webhook lifecycle issues that led to ADR-005's MCP rejection
- **Complement, not replace, ADR-005**: The automated webhook path (Bridge) and the on-demand assistant path must coexist; the same pipeline agents process emails from either trigger
- **`MCP_BLOCKED_HEADERS` must remain unchanged**: `X-Graph-Token` must not be on the blocked list — this is an intentional, documented side-channel following ADR-012's design rationale
- **Structured token expiry handling**: Entra access tokens (~1h TTL) may expire during a session; the same `ERR_TOKEN_EXPIRED` error contract pattern from ADR-012 applies

---

## Considered Options

### Option A: `X-Graph-Token` Custom Header Relay (Recommended)

**Description**: UI acquires a Microsoft Entra delegated access token via MSAL.js PKCE for `Mail.Read` scope. The token is sent as `X-Graph-Token` alongside the existing `X-PingOne-Token` in the CodeMie Assistants API call. The MCP-Connect Bridge relays `X-Graph-Token` to the Outlook MCP Server (because it is not on `MCP_BLOCKED_HEADERS`). The Outlook MCP Server uses it as `Authorization: Bearer` when calling Graph API.

**Pros:**
- ✅ No new infrastructure — follows exact ADR-012 pattern
- ✅ Token stays in browser memory only (never persisted server-side)
- ✅ User-delegated permissions — scoped to the specific user's mailbox access
- ✅ Works with all existing auth infrastructure (Traefik, oauth2-proxy, Gate 1)
- ✅ `MCP_BLOCKED_HEADERS` unchanged

**Cons:**
- ❌ UI must manage two independent OAuth2 sessions (PingOne + Microsoft Entra)
- ❌ Entra access token TTL (~1h) — UI must implement silent refresh before each assistant call
- ❌ `X-Graph-Token` contains a bearer token — must be redacted from all logs
- ❌ MSAL.js dependency in the Alevate/Serrala UI frontend

---

### Option B: Token Exchange Microservice

**Description**: UI acquires a Entra delegated token, exchanges it at a dedicated relay microservice for a short-lived reference token. The reference token is passed to CodeMie. The Outlook MCP Server resolves the reference to the actual Entra token at call time.

**Pros:**
- ✅ Actual Entra token is never sent over the wire to CodeMie
- ✅ Reference token can be invalidated server-side

**Cons:**
- ❌ New infrastructure to build, deploy, monitor (relay microservice)
- ❌ Introduces a stateful server-side token store — security surface area increases
- ❌ Contradicts the ADR-012 design rationale: the side-channel pattern was chosen specifically to avoid server-side token management
- ❌ More moving parts for the same security outcome

---

### Option C: OAuth On-Behalf-Of (OBO) Flow

**Description**: User authenticates with PingOne. The CodeMie backend performs an OBO exchange with Microsoft Entra (using a configured Entra client) to obtain a Graph token on behalf of the user. The Outlook MCP Server receives the OBO-derived token from CodeMie.

**Pros:**
- ✅ No second OAuth2 consent in the browser
- ✅ No `X-Graph-Token` header required

**Cons:**
- ❌ Requires PingOne-Entra federation or EPAM Codemie code changes to support OBO
- ❌ CodeMie backend must hold Microsoft Entra credentials — contradicts ADR-005's explicit goal: *"Graph API credentials never enter the CodeMie tenant boundary"*
- ❌ OBO requires user UPN matching between PingOne and Entra — complex cross-IdP identity mapping

---

## Options Comparison

| Criteria | Option A (X-Graph-Token) | Option B (Token Exchange) | Option C (OBO) |
|---|---|---|---|
| New infrastructure | None | Relay microservice | OBO endpoint |
| Token in CodeMie boundary | Transient (in-memory relay only) | Reference only | Yes (OBO token) |
| Graph API credentials in Codemie | No | No | Yes |
| Browser consent required | Yes (lazy, on-demand) | Yes | No |
| ADR-012 pattern reuse | ✅ Direct pattern match | ❌ Different mechanism | ❌ Different mechanism |
| EPAM Codemie changes required | No | No | Yes |
| Log redaction required | Yes (`X-Graph-Token`) | Reference only | Yes (OBO token) |
| Recommended | ✅ | ❌ | ❌ |

---

## Decision Outcome

**Chosen Option:** Option A — `X-Graph-Token` custom header relay

### Rationale

1. **Pattern consistency**: ADR-012 established `X-PingOne-Token` as a deliberate extensibility point for user-delegated token propagation. `X-Graph-Token` is the second instance of the same pattern — for a different identity system (Microsoft Entra vs. PingOne). Both share the same rationale: `Authorization` is blocked for security; a named custom header provides a documented side-channel.
2. **No CodeMie changes**: The MCP-Connect Bridge already has a header propagation allowlist mechanism. Adding `X-Graph-Token` requires only configuration — no EPAM code changes.
3. **Token boundary**: The Entra token exists only in the browser (memory), in the HTTP request headers (in-flight), and at the Outlook MCP Server (transient, during the Graph API call). It never persists server-side in the CodeMie platform — consistent with ADR-005's *"Graph API credentials never enter the CodeMie tenant boundary"*.
4. **ADR-005 preserved**: The webhook push path (Graph API Bridge, application-level credentials) is unchanged. This decision adds a pull path; it does not modify or replace the push path.

---

### Implementation Summary

#### Header Contract

The Serrala/Alevate UI sends three headers for UI-triggered email processing:

| Header | Value | Source | Notes |
|--------|-------|--------|-------|
| `Authorization` | `Bearer <pingone-jwt>` | PingOne session | For Codemie Gate 1 authentication; on `MCP_BLOCKED_HEADERS` — not propagated to MCP |
| `X-PingOne-Token` | `<pingone-jwt>` | PingOne session | Propagated to MCP servers by MCP-Connect Bridge (ADR-012); used for Alevate API calls |
| `X-Graph-Token` | `<entra-access-token>` | MSAL.js PKCE | NOT on `MCP_BLOCKED_HEADERS` → propagated to Outlook MCP Server; used as `Authorization: Bearer` for Graph API calls |

#### CodeMie Assistants API Call Contract

```http
POST /v1/assistants/{assistant_id}/chat
Authorization: Bearer <pingone-jwt>
X-PingOne-Token: <pingone-jwt>
X-Graph-Token: <entra-access-token>
Content-Type: application/json

{
  "message": "Process email <graph-message-id>",
  "propagate_headers": true
}
```

#### MCP Token Usage (Outlook MCP Server pseudocode)

```python
def handle_get_email_tool(context, message_id: str):
    graph_token = context.headers.get("X-Graph-Token")
    if not graph_token:
        raise MissingTokenError("X-Graph-Token not found in MCP context")

    claims = decode_jwt_unverified(graph_token)
    if claims["exp"] < time.time():
        return {
            "error": "token_expired",
            "code": "ERR_GRAPH_TOKEN_EXPIRED",
            "message": "Entra access token expired. Obtain a fresh token and retry.",
            "retry_after_ms": 0
        }

    response = requests.get(
        f"https://graph.microsoft.com/v1.0/me/messages/{message_id}",
        headers={"Authorization": f"Bearer {graph_token}"}
    )
    return response.json()
```

#### Scope of the Outlook MCP Server (Read Operations Only)

| MCP Tool | Graph API Endpoint | Delegated Scope |
|---|---|---|
| `get_email` | `GET /me/messages/{id}` | `Mail.Read` |
| `get_thread` | `GET /me/messages?$filter=conversationId eq '{id}'` | `Mail.Read` |
| `get_attachments` | `GET /me/messages/{id}/attachments` | `Mail.Read` |
| `search_emails` | `GET /me/messages?$search='{query}'` | `Mail.Read` |

**Write operations** (sending approved replies via `POST /users/{mailbox}/sendMail`) remain with the **existing Graph API Bridge** (ADR-005). The Bridge uses application-level `Mail.Send` permissions scoped to the shared AR mailbox. Delegated `Mail.Send` from the Outlook MCP Server would be limited to the user's personal mailbox — not appropriate for shared AR mailbox sending.

#### Token Expiry Error Contract

The Outlook MCP Server returns a structured error when the Entra token expires mid-processing:

```json
{
  "error": "token_expired",
  "code": "ERR_GRAPH_TOKEN_EXPIRED",
  "message": "Entra access token expired. Obtain a fresh token and retry.",
  "retry_after_ms": 0
}
```

The UI intercepts `HTTP 401` responses with `code: ERR_GRAPH_TOKEN_EXPIRED` and:
1. Calls `msal.acquireTokenSilent({scopes: ["Mail.Read"]})` to refresh the Entra token silently
2. If silent refresh fails (refresh token expired), shows the Microsoft consent/login prompt
3. Retries the CodeMie Assistants API call with the fresh `X-Graph-Token`

This mirrors the `ERR_TOKEN_EXPIRED` contract from ADR-012 for PingOne token expiry.

#### UI Authentication Model (Dual Consent)

Two independent OAuth2 sessions managed by the Serrala/Alevate UI:

1. **PingOne session** (existing): Authorization Code + PKCE via PingOne AS. Frontend Token (~65 min TTL). Established at app load (current behavior). Provides `Authorization` + `X-PingOne-Token`.
2. **Microsoft Entra session** (new): Authorization Code + PKCE via Microsoft Entra for `Mail.Read` scope. Access token (~1h TTL). Acquired **lazily** — triggered on-demand when the user selects an email for UI-triggered processing. Provides `X-Graph-Token`.

**Lazy consent**: The Graph consent prompt appears only when the user first triggers UI-based email processing, not at app load. This avoids consent fatigue and makes the permission request contextually meaningful.

**Silent refresh**: Before each CodeMie Assistants API call that includes `X-Graph-Token`, the UI calls `msal.acquireTokenSilent()`. If the cached token is still valid, no network round-trip occurs. If expired, MSAL.js silently uses the refresh token.

#### Coexistence with ADR-005 Webhook Path

| Dimension | Webhook Path (ADR-005) | UI-Triggered Path (this ADR) |
|---|---|---|
| Trigger | Graph API webhook notification | User action in Serrala/Alevate UI |
| CodeMie entry point | `POST /v1/workflows/{id}/executions` | `POST /v1/assistants/{id}/chat` |
| Permissions model | Application-level (`client_credentials`) | User-delegated (PKCE) |
| Token carrier | Service account JWT (bridge holds Entra creds) | `X-Graph-Token` header from browser |
| Email read via | Graph API Bridge (microservice) | Outlook MCP Server (tool call) |
| Email send via | Graph API Bridge (`/users/{mailbox}/sendMail`) | Graph API Bridge (unchanged — shared mailbox) |
| Audit `trigger_source` | `webhook_push` | `ui_pull` |
| Deduplication | Graph message ID (Bridge dedup) | Graph message ID (audit store lookup) |

Both paths can coexist; the same pipeline agents (EmailClassifier, ThreadSummarizer, etc.) process emails from either trigger after the initial email fetch step.

---

## Consequences

### Positive

✅ No new infrastructure components — token relay via MCP-Connect Bridge header allowlist (configuration change only)
✅ User-delegated permissions — access scoped to what the AR specialist can access in their Microsoft account
✅ Pattern consistency — `X-Graph-Token` is an intentional second instance of ADR-012's extensibility point
✅ Zero impact on ADR-005 webhook path — two parallel, independent trigger paths
✅ Audit trail via `trigger_source` field distinguishes automated vs. human-initiated processing
✅ Entra token stays in-memory only at all layers (browser, HTTP in-flight, MCP server) — not persisted

### Negative

❌ UI must manage two independent OAuth2 sessions (PingOne + Microsoft Entra) — frontend complexity
❌ Entra access token TTL (~1h) is a known gap — must handle expiry mid-processing via `ERR_GRAPH_TOKEN_EXPIRED` error contract
❌ `X-Graph-Token` is a bearer token — **must be redacted from all logs** (Traefik, oauth2-proxy, CodeMie API, MCP-Connect Bridge, Outlook MCP Server)
❌ MSAL.js dependency in the Alevate/Serrala UI — library coexistence with existing PingOne OIDC client must be verified
❌ Delegated `Mail.Read` for shared AR mailbox requires verification — Microsoft's behavior for delegate-access-via-Graph differs from individual mailbox access

### Mitigation Strategies

**Token expiry**: Outlook MCP Server checks `exp` claim before using token; returns structured `ERR_GRAPH_TOKEN_EXPIRED`; UI intercepts and calls `msal.acquireTokenSilent()` then retries once.

**Log redaction**: `X-Graph-Token` added to the log redaction list alongside `Authorization` and `X-PingOne-Token` at all layers.

**Dual consent UX**: On-demand consent popup on first use; MSAL.js handles silent refresh on subsequent calls; clear error messaging if consent is denied.

**Shared mailbox access**: Verify with Microsoft that a user with Outlook delegate access to the shared AR mailbox can read it via delegated `Mail.Read` Graph scope. If not, the UI-triggered path reads from the individual user's mailbox (not the shared team mailbox).

**MSAL.js coexistence**: Ensure MSAL.js and the PingOne OIDC client use isolated token caches (`CacheOptions.cacheLocation` and storage prefix isolation).

---

## Compliance & Security

**Token handling:**
- `X-Graph-Token` contains a Microsoft Entra access token with `oid`, `upn`, `scp` claims — must not be logged or stored at any layer
- The token exists only in: browser memory (MSAL.js cache), HTTP headers (in-flight, TLS-encrypted), and the Outlook MCP Server (transient, during the Graph API call duration)
- Consistent with ADR-005's principle: *"Graph API credentials never enter the CodeMie tenant boundary"* — the token passes through CodeMie in-memory only, not stored

**Application access policy:**
- The Entra application registration for the Serrala/Alevate UI should have an application access policy restricting delegated `Mail.Read` to the AR mailbox(es) — consistent with the application-level access policy on the Bridge (ADR-005)

**GDPR:**
- Email content fetched by the Outlook MCP Server is processed in-memory and passed to the CodeMie pipeline as tool result — no persistent storage at the MCP layer
- Same GDPR controls as the webhook path apply: data minimization, 7-year audit retention, right to erasure in summaries

---

## Related Decisions

- **[ADR-005](ADR-005-outlook-integration-pattern.md)**: The webhook push path this decision complements; this ADR explicitly resolves ADR-005's three MCP objections for the pull model
- **[ADR-004](ADR-004-agent-design.md)**: The CodeMie Assistants API (assistant with LangGraph ReAct) is the trigger entry point; the Outlook MCP tool is invoked during the assistant's conversation turn
- **[ADR-002](ADR-002-human-in-the-loop-design.md)**: Human approval requirement is unchanged — both trigger paths submit to the same PAUSED approval queue
- **[Multi-Tenancy ADR-012](../../multytenancy/design/codemie-auth-integration/decisions/ADR-012-pingone-token-propagation-to-custom-mcp.md)** _(in `srl-agnt` parent repo)_: **Template pattern** — `X-Graph-Token` mechanism is explicitly modeled on `X-PingOne-Token`; the MCP-Connect Bridge header allowlist mechanism is the same
- **[Multi-Tenancy ADR-009](../../multytenancy/design/codemie-auth-integration/decisions/ADR-009-direct-jwt-authentication.md)** _(in `srl-agnt` parent repo)_: Gate 1 behavior — `X-Graph-Token` is not on `MCP_BLOCKED_HEADERS` and passes through Traefik to CodeMie Assistants API
- **[Multi-Tenancy ADR-020](../../multytenancy/design/codemie-auth-integration/decisions/ADR-020-headless-api-integration-pattern.md)** _(in `srl-agnt` parent repo)_: Headless API integration pattern; the `propagate_headers: true` field in the request body enables MCP header relay

**Dependencies:**
- This decision **depends on**: Multi-Tenancy ADR-012 (MCP-Connect Bridge header propagation mechanism), Multi-Tenancy ADR-009 (Gate 1 header pass-through), Multi-Tenancy ADR-020 (Assistants API call contract)
- This decision **enables**: On-demand processing of specific emails from the Serrala/Alevate UI; future attachment processing via MCP; multi-mailbox UI search

---

## Implementation Checklist

### Phase 1 — Outlook MCP Server (Weeks 1-2)

- [ ] Scaffold Outlook MCP Server with `get_email`, `get_thread`, `get_attachments`, `search_emails` tools
- [ ] Implement `X-Graph-Token` header reading from MCP context
- [ ] Implement `exp` claim check: return `ERR_GRAPH_TOKEN_EXPIRED` if expired
- [ ] Implement Graph API calls with delegated token (`Authorization: Bearer <graph-token>`)
- [ ] Add `X-Graph-Token` to log redaction middleware
- [ ] Register Outlook MCP Server in CodeMie platform
- [ ] Request EPAM to add `X-Graph-Token` to MCP-Connect Bridge header propagation allowlist

### Phase 2 — UI Integration (Weeks 2-3)

- [ ] Add MSAL.js dependency to Serrala/Alevate UI frontend
- [ ] Configure MSAL.js with Microsoft Entra app registration (delegated `Mail.Read` scope)
- [ ] Implement lazy Graph consent: trigger PKCE flow on user's first email selection
- [ ] Implement `acquireTokenSilent` call before each CodeMie Assistants API call
- [ ] Attach `X-Graph-Token` header to CodeMie call alongside `Authorization` and `X-PingOne-Token`
- [ ] Verify MSAL.js and PingOne OIDC client use isolated token caches

### Phase 3 — Error Handling & Integration Testing (Week 3-4)

- [ ] Implement SDK-side `ERR_GRAPH_TOKEN_EXPIRED` intercept and retry flow
- [ ] End-to-end test: UI selects email → Graph token acquired → CodeMie called → MCP reads email → pipeline processes → approval queue
- [ ] Verify `X-Graph-Token` is redacted in all log outputs (Traefik, CodeMie API, MCP-Connect Bridge, Outlook MCP Server)
- [ ] Verify `trigger_source: "ui_pull"` appears in audit store for UI-triggered emails
- [ ] Verify deduplication: UI-triggered + webhook-triggered processing of the same email produces correct audit behavior

---

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| MCP-Connect Bridge propagation allowlist — must confirm EPAM can add `X-Graph-Token` without Bridge code change | **Medium** | Confirm with EPAM before Phase 1 begins; this is the critical path dependency |
| Delegated `Mail.Read` for shared AR mailbox | Medium | Verify with Microsoft that delegate-access-via-Graph works for the AR shared mailbox; fall back to personal mailbox if not |
| Entra + PingOne token TTL mismatch — dual expiry at different times | Low-Medium | Independent error contracts (`ERR_TOKEN_EXPIRED` and `ERR_GRAPH_TOKEN_EXPIRED`) handled separately by UI |
| MSAL.js + PingOne OIDC client coexistence in SPA | Low | Token cache isolation via separate `CacheOptions.cacheLocation` prefix |
| `trigger_source` field not in existing audit schema | Low | ADR-006 specifies adding `trigger_source` to the `event_data` JSONB field in the "Email received" audit event |

---

## Cost Analysis

| Component | Cost | Notes |
|---|---|---|
| Outlook MCP Server | ~$0/month (runs on existing AKS node pool) | Small, stateless service sharing existing cluster |
| MSAL.js in UI | $0 | Client-side library, no server cost |
| Graph API calls (delegated) | ~$0/month | Included in Microsoft 365 license |
| MCP-Connect Bridge config change | $0 | Configuration only, no new infrastructure |
| **Total** | **~$0/month marginal** | The Outlook MCP Server reuses existing AKS capacity |

---

## Change Log

| Date | Author | Change |
|------|--------|--------|
| 2026-04-03 | AR Email Management Architecture Team | Initial decision document |
| 2026-04-09 | AR Email Management Architecture Team | Status updated to Accepted — `X-Graph-Token` relay, token expiry handling, and all four read MCP tools implemented in `outlook-mcp-server` |

---

## Review and Approval

**Reviewed by:**
- AR Email Management Architecture Team

**Approved by:**
- AR Email Management Architecture Team (2026-04-09)

---

*Part of the AR Email Management Domain - Financial System Modernization Project*
