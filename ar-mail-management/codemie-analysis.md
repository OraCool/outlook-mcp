# CodeMie Platform Analysis for AR Email Management

**Document Type:** Technical Analysis (Task 2 Output)
**Date:** 2026-03-31
**Author:** Architecture Team
**Status:** Complete

---

## 1. Executive Summary

This document analyzes the EPAM AI/Run CodeMie platform's capabilities in the context of the AR Email Management use case. The analysis evaluates whether CodeMie can serve as the AI orchestration engine for processing inbound Accounts Receivable emails, classifying intents, drafting responses, routing actions to SAP/Alevate, and supporting human-in-the-loop approval workflows.

**Key findings:**

- CodeMie provides three complementary primitives -- Assistants, Workflows, and A2A (Agent-to-Agent) -- that collectively support the multi-step email processing pipeline required by this use case.
- **No built-in Outlook/Microsoft Graph API integration exists.** An Outlook connector must be built or configured as part of this solution. This is the most significant gap and is addressed in ADR-005.
- The A2A protocol (JSON-RPC 2.0) enables multi-agent orchestration (classifier, drafter, router) without requiring a custom orchestration layer.
- The Workflow engine's PAUSED state and resume endpoint provide a native mechanism for human-in-the-loop approval, though the approval UI itself must live in SAP or Alevate.
- Thread-level context management is supported via conversation history and LangGraph state persistence, but long-thread summarization must be implemented at the application level.
- Both headless (SAP via PAT Gateway) and interactive (Alevate via browser OIDC) calling paths are fully supported, with distinct authentication flows and endpoint contracts.

**Recommendation:** Use a hybrid architecture combining CodeMie Workflows (for deterministic orchestration and human-in-the-loop) with specialized CodeMie Assistants invoked at LLM decision points (classification, drafting). The A2A protocol provides the inter-agent communication backbone. This recommendation directly feeds into ADR-004 (Agent Design).

---

## 2. Agent and Workflow Types

CodeMie exposes three distinct primitives for building AI-powered automation. Each has different strengths for the AR email processing pipeline.

### 2.1 Assistants API

**What it is:** Single-turn and multi-turn chat with AI agents. Each assistant is configured with a system prompt, a set of tools, and attached datasources.

**Relevant endpoints:**

- `POST /v1/assistants/{assistantId}/model` -- Call an assistant's underlying LLM with a message and receive a response.
- `POST /v1/conversations` -- Create a new conversation (thread).
- `GET /v1/conversations/{conversationId}` -- Retrieve conversation history.

**Applicability to AR email processing:**

- **Classification:** An `EmailClassifier` assistant can receive an email body and thread summary, then return a structured JSON classification (category, confidence, extracted intent). The `output_schema` parameter (Zod/JSON Schema) enforces structured output.
- **Drafting:** A `ResponseDrafter` assistant can take classification output plus customer context and produce a draft reply in the required tone. Few-shot examples can be embedded in the system prompt.
- **Limitation:** A single assistant call is stateless unless wrapped in a conversation. For multi-step pipelines (classify, then draft, then route), the calling application or a workflow must orchestrate the sequence.

**Assessment for this use case:** Assistants are the correct primitive for individual LLM decision points (classification, drafting, summarization) but are insufficient alone for end-to-end email processing orchestration.

### 2.2 Workflows (Multi-Step Pipelines)

**What it is:** YAML-defined automation pipelines with stateful execution. Workflows chain multiple steps, where each step can invoke an assistant, call an external tool, perform data transformation, or pause for human input.

**Relevant endpoints:**

- `POST /v1/workflows/{workflow_id}/executions` -- Start a workflow execution.
- `PUT /v1/workflows/{workflow_id}/executions/{execution_id}/resume` -- Resume a paused execution (human-in-the-loop).

**Execution lifecycle:**


| Status      | Meaning                                                           |
| ----------- | ----------------------------------------------------------------- |
| `RUNNING`   | Workflow is actively executing steps                              |
| `PAUSED`    | Workflow has reached a human-in-the-loop gate; waiting for resume |
| `SUCCEEDED` | All steps completed successfully                                  |
| `FAILED`    | A step failed; error details available in execution state         |
| `ABORTED`   | Workflow was cancelled externally                                 |


**Key capabilities:**

- **State-level execution tracking:** Each step in the workflow records intermediate outputs, enabling debugging and audit trail construction.
- **Human-in-the-loop via PAUSED state:** The workflow can pause at a designated approval step, expose the current state (draft email, classification, confidence score), and wait for a human to resume (with optional edits to the output). This is directly applicable to the approval gate required by this use case.
- **Structured output:** The `output_schema` parameter ensures each step produces machine-parseable JSON, not free-form text.

**Applicability to AR email processing:**

- A single workflow can encode the complete pipeline: receive email, classify, draft response, determine SAP/Alevate action, pause for approval, execute approved action.
- The PAUSED state at the approval step is a natural fit for the human-in-the-loop requirement (FR6).
- State-level tracking provides the audit trail required by FR9.
- The workflow engine handles failure, retry, and timeout semantics that would otherwise need custom implementation.

**Assessment for this use case:** Workflows are the recommended orchestration mechanism. They provide deterministic step sequencing, built-in approval gates, state persistence, and audit-friendly execution history. Individual LLM steps within the workflow invoke specialized assistants.

### 2.3 A2A (Agent-to-Agent) Protocol

**What it is:** A JSON-RPC 2.0 protocol for agent-to-agent communication. Each assistant can expose an A2A endpoint and advertise its capabilities via an agent card.

**Relevant endpoints:**

- `POST /v1/a2a/assistants/{assistant_id}` -- Send a JSON-RPC 2.0 request to an assistant.
- `GET /v1/a2a/assistants/{assistant_id}/.well-known/agent.json` -- Retrieve the assistant's agent card (capabilities, skills, input/output modes).

**Agent card structure:** The `.well-known/agent.json` endpoint exposes a structured description of what the agent can do, what inputs it accepts, and what outputs it produces. This enables runtime discovery and dynamic routing.

**Applicability to AR email processing:**

- The `EmailClassifier`, `ResponseDrafter`, and `ActionRouter` can each be deployed as separate A2A-capable assistants, discoverable by their agent cards.
- A workflow step can invoke an A2A assistant by its `assistant_id`, passing the current execution state as the JSON-RPC payload.
- Header propagation (`X-Tenant-ID`, `X-Correlation-ID`, `X-User-Context`) maintains tenant and user context across the agent chain, which is critical for multi-tenant deployments.
- **SAP headless path:** The SAP integration exclusively uses the A2A endpoint (`POST /v1/a2a/assistants/{assistant_id}`) because SAP connects through the PAT Gateway (ADR-003), which mints a short-lived CodeMie JWT and forwards the request to the A2A endpoint.

**Assessment for this use case:** A2A is the correct protocol for SAP-initiated headless invocations and for inter-agent communication within the pipeline. Combined with workflows, it provides both orchestration (workflow) and inter-agent communication (A2A).

### 2.4 Skills

**What it is:** Reusable, versioned prompt modules that can be attached to multiple assistants. A skill encapsulates a specific capability (e.g., "classify AR emails" or "draft formal reply") as a prompt template with optional tools.

**Applicability to AR email processing:**

- The classification prompt, drafting prompt, and action-routing logic can each be packaged as a CodeMie Skill.
- Skills can be versioned independently, enabling A/B testing of classification prompts without redeploying assistants.
- Multiple assistants can share the same skill, which supports the scenario where both the Alevate-invoked assistant and the SAP-invoked assistant use identical classification logic.

**Assessment for this use case:** Skills are a useful modularity mechanism for managing prompt versions but do not replace the need for assistants or workflows. They complement the recommended hybrid architecture.

### 2.5 Summary: Primitives Applicability Matrix


| Primitive      | Role in AR Email Pipeline                                   | Standalone Sufficient?                       |
| -------------- | ----------------------------------------------------------- | -------------------------------------------- |
| **Assistants** | Individual LLM decision points (classify, draft, summarize) | No -- requires orchestration                 |
| **Workflows**  | End-to-end pipeline orchestration with approval gates       | Yes, with assistant invocations at LLM steps |
| **A2A**        | SAP headless invocation; inter-agent communication          | No -- requires orchestration context         |
| **Skills**     | Reusable prompt versioning across assistants                | No -- supporting mechanism only              |


---

## 3. Outlook Connector Assessment

### 3.1 Current State

**No built-in Outlook/Microsoft Graph API integration exists in CodeMie.** There is no pre-configured MCP server, built-in tool, or native connector for reading emails from or sending emails via Microsoft Outlook/Exchange Online.

This means the AR Email Management solution must build or configure the Outlook connectivity layer as part of the implementation.

### 3.2 Integration Options Under Evaluation

Three options are being evaluated for ADR-005 (Outlook Integration Pattern):

**Option A: CodeMie MCP Server calling Graph API directly**

- A Model Context Protocol (MCP) server would be configured within CodeMie to expose Graph API operations (read mail, send mail, list folders) as tools available to assistants.
- The assistant would invoke `read_email` or `send_email` as tool calls within its conversation.
- **Auth consideration:** The Graph API requires an OAuth 2.0 token with `Mail.Read` and `Mail.Send` scopes. This token is distinct from the CodeMie PingOne JWT. The MCP server would need to handle Graph API token acquisition and refresh independently, or receive a propagated token via the `X-PingOne-Token` header relay pattern (ADR-012).
- **Gap:** ADR-012 (PingOne Token Propagation to Custom MCP) describes token propagation mechanics, but the Graph API OAuth token may require separate consent (different OAuth authority: Microsoft identity platform vs. PingOne). This needs architectural resolution.

**Option B: External microservice (Graph API bridge)**

- A standalone service monitors the AR team's Outlook inbox via Graph API (webhooks or polling).
- When a new email arrives, the service fetches the email content, resolves the thread, and submits the email to CodeMie for processing via the conversation API (`POST /v1/conversations`) or A2A endpoint (`POST /v1/a2a/assistants/{assistant_id}`).
- After CodeMie produces an approved response, the bridge service sends the email via Graph API.
- **Advantage:** Clean separation of concerns. The bridge service owns Graph API authentication and email lifecycle; CodeMie owns AI processing. Both Alevate and SAP paths can trigger processing through CodeMie without needing Graph API awareness.
- **Gap:** Requires deploying and operating an additional service.

**Option C: CodeMie Workflow with Graph API tool node**

- A CodeMie Workflow definition includes a dedicated step that makes an HTTP call to the Graph API to fetch email content.
- Subsequent workflow steps handle classification, drafting, and routing.
- **Advantage:** All orchestration lives in CodeMie; no external service needed.
- **Gap:** Depends on whether CodeMie's workflow engine supports arbitrary HTTP tool calls with OAuth 2.0 token management (token acquisition, refresh, scope management). This capability has not been confirmed.

### 3.3 New-Email Detection

Regardless of which option is chosen, the solution must detect new emails. Two mechanisms are available:


| Mechanism                                                        | Latency                  | Complexity                                                                                              | Reliability                                                            |
| ---------------------------------------------------------------- | ------------------------ | ------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| **Graph API Webhooks** (`/subscriptions`, change type `created`) | Near-real-time (seconds) | High: requires notification endpoint, subscription renewal every 3 days, change notification validation | High when properly maintained; silent failure on expired subscriptions |
| **Polling** (`/messages?$filter=receivedDateTime ge ...`)        | Minutes (configurable)   | Low: simple scheduled HTTP call                                                                         | High: no external dependencies beyond Graph API availability           |


The webhook vs. polling decision is documented in ADR-005.

### 3.4 Outlook Connector Recommendation

Based on the analysis, **Option B (External Microservice)** is the most architecturally sound choice for the following reasons:

1. It cleanly separates Graph API concerns (OAuth, webhook management, email threading) from AI processing concerns.
2. It supports both Alevate and SAP calling paths without requiring either to understand Graph API authentication.
3. It avoids dependency on unconfirmed CodeMie workflow capabilities (arbitrary HTTP calls with OAuth token management).
4. It aligns with the existing integration patterns documented in the multitenancy architecture (ADR-020 Headless API Integration Pattern).

This recommendation is formalized in ADR-005.

---

## 4. Tool Calls to External Systems

### 4.1 SAP Integration

**Integration path:** SAP connects to CodeMie exclusively via the PAT Gateway, which implements a 6-step token validation pipeline:

1. SAP sends a request with an Alevate Personal Access Token (PAT).
2. The PAT Gateway validates the PAT against Alevate's token endpoint.
3. The Gateway extracts tenant and user identity from the PAT claims.
4. The Gateway mints a short-lived CodeMie JWT (5-minute TTL).
5. The Gateway forwards the request to the CodeMie A2A endpoint with the minted JWT.
6. CodeMie processes the request and returns the response to the Gateway, which relays it to SAP.

**Endpoint:** `POST /v1/a2a/assistants/{assistant_id}` (JSON-RPC 2.0)

**Characteristics:**

- Headless only -- no interactive UI is available from SAP.
- Synchronous request-response pattern.
- 5-minute JWT TTL constrains processing time; long-running workflows may need token refresh or an asynchronous pattern.
- The A2A endpoint supports structured input/output, which is compatible with passing email classification results and action parameters.

**Implications for AR email processing:**

- When SAP triggers email processing (e.g., Scenario S5: unmatched payment detected in SAP), it must invoke the CodeMie pipeline via A2A.
- The 5-minute JWT TTL may be insufficient if the workflow includes a human-in-the-loop approval step (which could take hours). This requires either: (a) splitting the workflow into pre-approval and post-approval phases with separate A2A calls, or (b) using the workflow's asynchronous execution model where SAP polls for completion.
- The A2A request payload must include all context needed for processing (invoice details, customer ID, SAP case reference) because the SAP path has no conversation history.

### 4.2 Alevate Integration

**Integration paths:**


| Mode                         | Auth Flow                             | Endpoint                                                                                   |
| ---------------------------- | ------------------------------------- | ------------------------------------------------------------------------------------------ |
| **Interactive** (browser UI) | Browser OIDC via PingOne              | `POST /v1/assistants/{assistantId}/model`                                                  |
| **Headless** (API)           | `client_credentials` grant to PingOne | `POST /v1/assistants/{assistantId}/model` or `POST /v1/workflows/{workflow_id}/executions` |


**Headers:**

```http
Authorization: Bearer <pingone-jwt>
X-PingOne-Token: <pingone-jwt>
Content-Type: application/json
```

**Characteristics:**

- Both interactive and headless modes use the same PingOne JWT with 65-minute TTL.
- The `X-PingOne-Token` header enables downstream token propagation to MCP servers and custom tools.
- Alevate can invoke both assistants (direct LLM calls) and workflows (multi-step pipelines).
- SSE (Server-Sent Events) streaming is available for real-time response delivery in the interactive UI.

**Implications for AR email processing:**

- Alevate is the natural home for the human-in-the-loop approval UI. An AR analyst using Alevate can view the AI-drafted response, edit it, and approve/reject -- all within the Alevate SPA.
- The 65-minute JWT TTL is sufficient for most email processing workflows, including human review delays within a single session.
- Alevate can also trigger headless processing for batch scenarios (e.g., process all unread AR emails from overnight).

### 4.3 Integration Model Comparison


| Aspect           | SAP Path                                  | Alevate Path                    |
| ---------------- | ----------------------------------------- | ------------------------------- |
| **Protocol**     | A2A (JSON-RPC 2.0)                        | REST (Assistants/Workflows API) |
| **Auth**         | PAT Gateway minted JWT (5 min TTL)        | PingOne JWT (65 min TTL)        |
| **Mode**         | Headless only                             | Interactive + Headless          |
| **Streaming**    | JSON-RPC polling                          | SSE or polling                  |
| **Approval UI**  | Not available -- must callback to Alevate | Built-in (Alevate SPA)          |
| **Context**      | Must be passed in request payload         | Can use conversation history    |
| **Timeout risk** | High (5 min JWT)                          | Low (65 min JWT)                |


---

## 5. Memory and Context

### 5.1 Working Memory

CodeMie implements working memory via LangGraph state graph checkpoint persistence backed by PostgreSQL. This provides:

- **State persistence across workflow steps:** Each step's output is checkpointed, enabling resume-after-failure.
- **Token-windowed message batching:** LangGraph manages the context window by batching recent messages and truncating older ones based on token limits.

**Implication:** The workflow engine naturally maintains working memory for the duration of a single execution. For the email processing pipeline, this means classification output is available to the drafting step without explicit state passing.

### 5.2 Episodic Memory (Conversation History)

CodeMie stores raw conversation history and exposes it via `GET /v1/conversations/{conversationId}`. This provides:

- Full message history for a conversation thread.
- Messages include role (user/assistant/system), content, timestamps, and tool call records.

**Implication:** Email thread history can be managed as a CodeMie conversation. Each new email in a thread appends to the conversation, and the full history is available for context injection into subsequent LLM calls. However:

- There is no automatic summarization of long conversations. The `ThreadSummarizer` agent proposed in this architecture must be explicitly invoked to compress long threads.
- Conversation lookup is by `conversationId`, not by external identifiers (customer ID, invoice number). A mapping layer is needed to associate email threads with CodeMie conversations.

### 5.3 Semantic Memory (Vector Search)

CodeMie provides Elasticsearch-based vector search on datasources. Datasources can be attached to assistants, enabling retrieval-augmented generation (RAG).

**Potential use for AR email processing:**

- SAP correspondence templates could be indexed as a datasource, enabling the `ResponseDrafter` to retrieve the most relevant template based on the email classification.
- Historical email-response pairs could be indexed to provide few-shot examples dynamically.

**Limitation:** Semantic memory operates at the datasource level, not at the per-customer or per-thread level. It is useful for template retrieval but not for thread-specific context.

### 5.4 Long-Term Personal Memory

**Not implemented in CodeMie.** There is no built-in mechanism for storing and retrieving per-customer preferences, communication style notes, or dispute history across conversations.

**Implication:** Any customer-specific context (payment history, dispute patterns, preferred communication language) must be retrieved from SAP/Alevate at processing time and injected into the prompt. CodeMie does not learn or remember customer-specific patterns across sessions.

### 5.5 Context Window Management

- Context window size is configurable per LLM provider (Azure OpenAI, self-hosted models, etc.).
- Headers `X-Tenant-ID`, `X-Correlation-ID`, and `X-User-Context` can carry metadata across calls but do not affect the LLM context window directly.
- Token-windowed batching in LangGraph provides automatic truncation, but this may silently drop relevant earlier messages in a long email thread.

**Implication for architecture:** The `ThreadSummarizer` agent is essential for threads exceeding the context window. The architecture must define when summarization is triggered (e.g., thread length > N messages or token count > M tokens) and how the summary replaces raw history in the context. This is addressed in ADR-003 (Thread Context Management).

### 5.6 Memory Capabilities Summary


| Memory Type            | CodeMie Support                       | AR Email Use                            | Gap                                           |
| ---------------------- | ------------------------------------- | --------------------------------------- | --------------------------------------------- |
| **Working Memory**     | Full (LangGraph checkpoints)          | Workflow step state                     | None                                          |
| **Episodic Memory**    | Partial (raw conversation history)    | Thread history                          | No auto-summarization; no external ID mapping |
| **Semantic Memory**    | Partial (Elasticsearch vector search) | Template retrieval, historical examples | Not thread-specific                           |
| **Long-Term Personal** | Not implemented                       | Customer preferences, dispute history   | Must be retrieved from SAP/Alevate per call   |


---

## 6. Human-in-the-Loop

### 6.1 Built-in Capabilities

CodeMie's workflow engine provides native human-in-the-loop support through the following mechanisms:

**Workflow PAUSED state:**

- A workflow step can be configured to pause execution and wait for external input.
- When paused, the workflow's current state (including all intermediate outputs from prior steps) is persisted and available for inspection.
- A human reviewer can examine the state via the calling application's UI (Alevate or SAP).

**Resume endpoint:**

- `PUT /v1/workflows/{workflow_id}/executions/{execution_id}/resume` accepts a payload that can include modifications to the workflow state.
- The approver can edit the AI-drafted response, change the classification, or reject the action entirely before resuming.
- This is a true edit-and-approve pattern, not just approve/reject.

**Structured output enforcement:**

- The `output_schema` parameter (Zod/JSON Schema) ensures the data presented to the approver is structured and complete.
- The approver sees a well-defined data structure (category, confidence, draft text, proposed action) rather than free-form LLM output.

### 6.2 What Must Be Built Externally

**The approval UI itself does not exist in CodeMie.** CodeMie provides the API mechanics (pause, inspect state, resume with edits) but the visual interface for human reviewers must be built in the calling application:

- **Alevate path:** The approval UI is built within the Alevate SPA. Alevate queries the paused workflow execution, renders the draft/classification/action for review, and calls the resume endpoint upon approval.
- **SAP path:** SAP must implement an equivalent approval view. Because SAP is headless-only with respect to CodeMie, SAP's own UI layer must present the approval interface and call CodeMie's resume endpoint via the PAT Gateway.

### 6.3 Approval Flow Sequence

```
1. Email arrives -> Bridge service submits to CodeMie workflow
2. Workflow executes: classify -> draft -> determine action
3. Workflow reaches approval step -> status = PAUSED
4. Alevate/SAP polls or receives notification of PAUSED status
5. Approver reviews draft, confidence, reasoning in Alevate/SAP UI
6. Approver edits (optional) and approves/rejects
7. Alevate/SAP calls PUT /resume with approval payload
8. Workflow resumes -> executes approved action (send email, update SAP)
9. Workflow status = SUCCEEDED; audit trail recorded
```

### 6.4 Open Questions

- **Timeout behavior:** What happens if a PAUSED workflow is not resumed within a defined period? CodeMie does not appear to have a built-in timeout-and-escalate mechanism for paused workflows. This must be handled externally (e.g., a scheduled job that detects stale paused executions and escalates them). Documented as an open question for ADR-002.
- **Notification mechanism:** How does Alevate/SAP learn that a workflow has paused? Options include polling the execution status endpoint or configuring a webhook callback. The chosen approach affects approval latency.

---

## 7. Multi-Agent Support

### 7.1 Current Capabilities

CodeMie does not provide a built-in classifier-drafter-router orchestration pattern. There is no declarative way to define "run Agent A, then feed its output to Agent B, then to Agent C" as a single configuration.

However, multi-agent orchestration is achievable through two complementary mechanisms:

**A2A chaining:**

- Each specialized agent (classifier, drafter, router) is deployed as a separate CodeMie assistant with an A2A endpoint.
- An orchestrator (either a CodeMie workflow or an external service) invokes each agent sequentially via `POST /v1/a2a/assistants/{assistant_id}`.
- Header propagation (`X-Tenant-ID`, `X-Correlation-ID`, `X-User-Context`) maintains tenant context across the chain.

**Workflow with assistant invocations:**

- A CodeMie workflow defines the pipeline steps declaratively in YAML.
- Each LLM decision step invokes a specific assistant.
- Non-LLM steps (data retrieval, action execution, approval gates) are handled by workflow primitives.

### 7.2 Orchestration Architecture for AR Email Processing

The recommended multi-agent architecture for this use case:

```
Workflow: AR Email Processing Pipeline
  Step 1: [Tool] Receive email from bridge service
  Step 2: [Tool] Retrieve thread history (GET /v1/conversations/{id})
  Step 3: [Assistant] ThreadSummarizer -- compress thread if needed
  Step 4: [Assistant] EmailClassifier -- classify + extract intent
  Step 5: [Branch] If confidence < threshold -> escalate (skip to Step 8)
  Step 6: [Assistant] ResponseDrafter -- draft reply using classification + context
  Step 7: [Assistant] ActionRouter -- determine SAP/Alevate action
  Step 8: [Tool] ReviewPresenter -- format output for approval UI
  Step 9: [PAUSE] Human-in-the-loop approval gate
  Step 10: [Tool] Execute approved action (send email, update SAP)
  Step 11: [Tool] Record audit trail
```

Each `[Assistant]` step invokes a dedicated CodeMie assistant via A2A or direct model call. Each `[Tool]` step performs a deterministic operation. The `[PAUSE]` step leverages the workflow engine's native approval gate.

### 7.3 Agent Discovery

The A2A agent card mechanism (`GET /v1/a2a/assistants/{assistant_id}/.well-known/agent.json`) enables runtime discovery of agent capabilities. This is useful for:

- Validating that all required agents are deployed and available before starting a workflow execution.
- Dynamically routing to alternative agents (e.g., a language-specific classifier) based on email metadata.

### 7.4 Limitations

- **No dynamic routing based on agent cards:** The workflow step sequence must be defined at design time. Agent cards enable discovery but not dynamic pipeline reconfiguration at runtime.
- **Sequential invocation only within a single workflow:** There is no built-in support for parallel agent invocation (e.g., running classification and template retrieval simultaneously). If parallelism is needed, the external bridge service or a custom workflow step must implement it.
- **No shared memory across agents within a single A2A chain:** Each A2A call is independent. The workflow's state graph provides the shared context; individual A2A calls do not automatically see each other's outputs unless the workflow passes them explicitly.

---

## 8. Headless vs. Interactive

### 8.1 Endpoint Comparison


| Feature                  | Interactive (Alevate UI)         | Headless (Alevate API)                                                   | Headless (SAP A2A)                   |
| ------------------------ | -------------------------------- | ------------------------------------------------------------------------ | ------------------------------------ |
| **Auth mechanism**       | Browser OIDC via PingOne         | `client_credentials` grant to PingOne                                    | Alevate PAT validated by PAT Gateway |
| **Token TTL**            | 65 minutes                       | 65 minutes                                                               | 5 minutes                            |
| **Required headers**     | `Authorization: Bearer <jwt>`    | `Authorization: Bearer <jwt>` + `X-PingOne-Token: <jwt>`                 | `Authorization: Bearer <minted-jwt>` |
| **Primary endpoint**     | `POST /v1/assistants/{id}/model` | `POST /v1/assistants/{id}/model` or `POST /v1/workflows/{id}/executions` | `POST /v1/a2a/assistants/{id}`       |
| **Response delivery**    | SSE (streaming)                  | SSE or polling                                                           | JSON-RPC 2.0 (polling)               |
| **UI available**         | Yes (Alevate SPA)                | No (API only)                                                            | No                                   |
| **Workflow support**     | Yes                              | Yes                                                                      | Via A2A wrapper                      |
| **Conversation history** | Managed by CodeMie UI            | Must be managed by caller                                                | Not available (stateless)            |


### 8.2 Implications for AR Email Processing

**SAP headless path constraints:**

1. **5-minute JWT TTL:** The most restrictive constraint. A workflow that includes human approval cannot complete within 5 minutes. The architecture must split the flow: SAP initiates processing (classification, drafting), the workflow pauses for approval, and a separate mechanism (Alevate UI or a callback) handles the approval and resumes the workflow with a fresh token.
2. **No conversation history:** The SAP A2A call must include all necessary context in the request payload. There is no persistent conversation that SAP can append to across multiple interactions.
3. **JSON-RPC 2.0 protocol:** Responses are structured JSON, not streaming text. This is actually an advantage for machine-to-machine integration, as SAP receives a complete, parseable response.

**Alevate path advantages:**

1. **65-minute TTL:** Sufficient for most interactive review sessions. An AR analyst can review multiple drafts within a single session.
2. **SSE streaming:** Enables real-time display of LLM-generated draft text in the Alevate UI, improving user experience.
3. **Workflow invocation:** Alevate can directly start and monitor workflow executions, including pausing for approval and resuming with edits.

**Recommended dual-path architecture:**

- **Automated email processing:** The bridge service (Option B from Section 3) initiates workflow executions using Alevate headless credentials (65-minute TTL). This covers the common case where emails are processed automatically and queued for human review.
- **SAP-triggered processing:** When SAP detects events (e.g., unmatched payments -- Scenario S5), it initiates classification via A2A (5-minute TTL). The classification result is returned to SAP synchronously. If a response draft or action is needed, SAP delegates to Alevate for the full workflow including approval.
- **Human review and approval:** Always performed via Alevate UI, regardless of the initiating path. This avoids the 5-minute TTL constraint and provides a consistent approval experience.

---

## 9. Gaps and Recommendations

### 9.1 Critical Gaps


| #   | Gap                                                     | Impact                                                                                            | Recommended Mitigation                                                                                                     |
| --- | ------------------------------------------------------- | ------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| G1  | **No Outlook/Graph API connector**                      | Cannot read or send emails without custom development                                             | Build Graph API bridge service (ADR-005 Option B)                                                                          |
| G2  | **No long-term customer memory**                        | Cannot learn customer communication patterns over time                                            | Retrieve customer context from SAP/Alevate per call; consider future Elasticsearch index of customer interaction summaries |
| G3  | **No built-in approval UI**                             | Human-in-the-loop requires external UI development                                                | Build approval views in Alevate SPA and SAP UI                                                                             |
| G4  | **5-minute SAP JWT TTL vs. approval workflow duration** | SAP-initiated workflows cannot include human approval within a single token lifetime              | Split into classification (SAP A2A) and approval (Alevate workflow) phases                                                 |
| G5  | **No automatic thread summarization**                   | Long email threads may exceed context window, causing silent truncation                           | Implement `ThreadSummarizer` agent with explicit invocation when thread length exceeds threshold                           |
| G6  | **No conversation-to-email-thread mapping**             | CodeMie conversations are identified by internal ID, not by email thread ID or customer reference | Build mapping service or use conversation metadata to store external identifiers                                           |


### 9.2 Secondary Gaps


| #   | Gap                                                     | Impact                                                               | Recommended Mitigation                                                                                                                                                                                                               |
| --- | ------------------------------------------------------- | -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| G7  | **No parallel agent invocation in workflows**           | Classification and template retrieval cannot run simultaneously      | Accept sequential execution; latency impact is minimal for email processing (not real-time)                                                                                                                                          |
| G8  | **No built-in timeout/escalation for paused workflows** | Paused workflows could remain indefinitely without human action      | Implement external monitoring job that escalates stale paused executions. **Partially mitigated:** `GET /v1/analytics/agents-usage` and workflow execution listing can detect stale executions (see Section 11.3.3)                  |
| G9  | **No webhook notification for workflow state changes**  | Calling applications must poll for workflow completion/pause         | Implement polling with reasonable interval. **Partially mitigated:** `GET /v1/analytics/webhooks-invocation` provides webhook reliability metrics; workflow execution states endpoint enables efficient polling (see Section 11.3.3) |
| G10 | **No dynamic agent routing based on agent cards**       | Cannot automatically select language-specific classifiers at runtime | Define static routing in workflow definition; add language-specific branches as needed                                                                                                                                               |


### 9.3 Build vs. Configure Summary

> **Note:** This table reflects the initial analysis. An expanded table incorporating newly identified platform capabilities (guardrails, analytics, feedback, workflow output editing) is provided in **Section 11.6**.


| Component                              | Build       | Configure | Exists                                            |
| -------------------------------------- | ----------- | --------- | ------------------------------------------------- |
| Graph API bridge service               | X           |           |                                                   |
| Email thread to conversation mapping   | X           |           |                                                   |
| EmailClassifier assistant              |             | X         |                                                   |
| ResponseDrafter assistant              |             | X         |                                                   |
| ActionRouter assistant                 |             | X         |                                                   |
| ThreadSummarizer assistant             |             | X         |                                                   |
| ReviewPresenter formatting             | X           |           |                                                   |
| Approval UI (Alevate)                  | X           |           |                                                   |
| Approval UI (SAP)                      | X           |           |                                                   |
| AR email processing workflow (YAML)    |             | X         |                                                   |
| SAP correspondence template datasource |             | X         |                                                   |
| Stale workflow monitoring job          | X           |           |                                                   |
| Audit trail logging                    | X (partial) |           | Workflow state tracking + export (Section 11.3.7) |


---

## 10. Impact on Architecture Decisions

### 10.1 Impact on ADR-004: Agent Design

**Finding:** CodeMie supports all three options evaluated in ADR-004 (single assistant, multi-agent pipeline, workflow with LLM nodes).

**Recommendation:** The hybrid workflow + specialized assistants approach (Option 3: Workflow with LLM nodes) is the strongest fit because:

1. The workflow engine provides native orchestration, approval gates, and audit trail -- all critical requirements for this use case.
2. Specialized assistants at LLM decision points enable independent confidence tracking, prompt versioning (via Skills), and failure isolation.
3. The A2A protocol supports both SAP headless and Alevate interactive invocation paths.
4. No custom orchestration service needs to be built; the workflow engine handles step sequencing, state management, and failure recovery.

**Trade-off accepted:** The pipeline is sequential (no parallel agent invocation), but this is acceptable for email processing where latency requirements are minutes, not milliseconds.

### 10.2 Impact on ADR-005: Outlook Integration Pattern

**Finding:** No built-in Outlook integration exists. The three options differ primarily in where Graph API authentication and email lifecycle management are handled.

**Recommendation:** Option B (External Microservice / Graph API Bridge) is recommended because:

1. It cleanly separates Graph API concerns from CodeMie AI processing.
2. It avoids unconfirmed dependencies on CodeMie workflow HTTP tool capabilities (Option C).
3. It avoids coupling Graph API OAuth tokens to CodeMie's MCP tool execution context (Option A).
4. It naturally supports both webhook and polling for new-email detection, with the choice encapsulated within the bridge service.
5. It supports the dual-caller architecture: the bridge service submits emails to CodeMie regardless of whether the eventual approval comes from Alevate or SAP.

**Trade-off accepted:** An additional service must be deployed and operated. This is justified by the architectural clarity and the avoidance of tighter coupling between email infrastructure and AI processing.

### 10.3 Cross-Cutting Implications


| Decision Area     | CodeMie Finding                                            | Implication                                                                                                                                                |
| ----------------- | ---------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Audit trail**   | Workflow state-level tracking records intermediate outputs | Augment with explicit audit log writes at classification and approval steps; workflow state alone may not satisfy regulatory retention requirements        |
| **Idempotency**   | Workflow executions have unique IDs; state is checkpointed | Use email Message-ID as idempotency key in the bridge service to prevent duplicate processing                                                              |
| **Multi-tenancy** | `X-Tenant-ID` header propagated across all calls           | Tenant isolation is maintained across the agent chain; no additional work needed                                                                           |
| **Data privacy**  | Email content passes through CodeMie's LLM processing      | PII in email bodies is processed by the LLM provider; data residency and retention policies must be aligned with GDPR requirements (see `data-privacy.md`) |


---

## Appendix A: Key API Endpoint Reference


| Endpoint                                                                       | Method | Purpose                                    | Used By                               |
| ------------------------------------------------------------------------------ | ------ | ------------------------------------------ | ------------------------------------- |
| `/v1/a2a/assistants/{assistant_id}`                                            | POST   | Execute A2A request (JSON-RPC 2.0)         | SAP (via PAT Gateway), Workflow steps |
| `/v1/a2a/assistants/{assistant_id}/.well-known/agent.json`                     | GET    | Retrieve agent card (capabilities, skills) | Agent discovery, health checks        |
| `/v1/conversations`                                                            | POST   | Create a new conversation                  | Bridge service (new email thread)     |
| `/v1/conversations/{conversationId}`                                           | GET    | Retrieve conversation with full history    | Thread context retrieval              |
| `/v1/assistants/{assistantId}/model`                                           | POST   | Call assistant's LLM model                 | Alevate (interactive + headless)      |
| `/v1/workflows/{workflow_id}/executions`                                       | POST   | Start a workflow execution                 | Bridge service, Alevate headless      |
| `/v1/workflows/{workflow_id}/executions/{execution_id}/resume`                 | PUT    | Resume a paused workflow (approval)        | Alevate UI, SAP UI (via PAT Gateway)  |
| `/v1/workflows/{workflow_id}/executions/{execution_id}/output`                 | PUT    | Edit output of paused workflow state       | Approval UI (Edit+Approve flow)       |
| `/v1/workflows/{workflow_id}/executions/{execution_id}/output/request_changes` | PUT    | Request LLM-assisted output revision       | Approval UI (AI-assisted editing)     |
| `/v1/workflows/{workflow_id}/executions/{execution_id}/export`                 | GET    | Export complete execution (audit)          | Audit trail, compliance               |
| `/v1/guardrails`                                                               | GET    | List available guardrails                  | Platform setup                        |
| `/v1/guardrails/{guardrail_id}/apply`                                          | POST   | Apply guardrail to content                 | All 5 agents (PII, content safety)    |
| `/v1/guardrails/{guardrail_id}/assignments`                                    | PUT    | Bulk assign guardrail to entities          | Agent configuration                   |
| `/v1/analytics/summaries`                                                      | GET    | Summary dashboard metrics                  | Operational monitoring                |
| `/v1/analytics/llms-usage`                                                     | GET    | LLM token consumption and cost             | Cost tracking (ADR-001)               |
| `/v1/analytics/agents-usage`                                                   | GET    | Agent invocation counts                    | Pipeline health monitoring            |
| `/v1/conversation-analysis/trigger`                                            | POST   | Trigger automated quality analysis         | Classification quality monitoring     |
| `/v1/feedback`                                                                 | POST   | Create feedback entry                      | Approval outcome recording            |
| `/v1/conversations/{conversationId}/feedback`                                  | POST   | Final feedback on conversation             | Per-email feedback loop               |
| `/v1/assistants/system-prompt/validate`                                        | POST   | Validate system prompt                     | CI/CD prompt deployment               |
| `/v1/assistants/{assistantId}/evaluate`                                        | POST   | Evaluate assistant accuracy                | Pre-deployment testing                |


## Appendix B: Authentication Flow Summary

```
SAP Path:
  SAP -> [Alevate PAT] -> PAT Gateway -> [Validate PAT, Mint 5-min JWT]
       -> CodeMie A2A Endpoint -> [Process] -> Response -> PAT Gateway -> SAP

Alevate Interactive Path:
  Browser -> [PingOne OIDC] -> Alevate SPA -> [Bearer JWT, 65-min TTL]
          -> CodeMie Assistants/Workflows API -> [Process] -> SSE Response

Alevate Headless Path:
  Service -> [client_credentials] -> PingOne -> [JWT, 65-min TTL]
          -> CodeMie Assistants/Workflows API -> [Process] -> JSON Response

Graph API (Bridge Service):
  Bridge Service -> [OAuth 2.0 client_credentials or delegated]
                 -> Microsoft Identity Platform -> [Access Token]
                 -> Graph API (/me/messages, /me/sendMail) -> Email Data
```

---

## 11. Full API Inventory Analysis (303 Endpoints)

### 11.1 Methodology

A full inventory of the CodeMie API was extracted from the official Postman collection (`docs/codemie-api/Codemie.postman_collection.json`). The collection contains **303 endpoints across 47 categories**. Each endpoint was evaluated against the AR Email Management architecture to identify capabilities we leverage, capabilities we missed, and capabilities that are not relevant to this use case.

### 11.2 Endpoints Already Leveraged

The following endpoint groups are well-represented in our architecture (Sections 2--8 of this document):


| Category          | Key Endpoints                                    | Where Referenced |
| ----------------- | ------------------------------------------------ | ---------------- |
| **Assistants**    | `POST /v1/assistants/{id}/model`, CRUD           | Section 2.1, 4.2 |
| **Workflows**     | `/executions` (create, resume, abort), `/states` | Section 2.2, 6.1 |
| **A2A**           | `POST /v1/a2a/assistants/{id}`, `agent.json`     | Section 2.3, 4.1 |
| **Conversations** | CRUD, history                                    | Section 5.2      |
| **Skills**        | Conceptual reference to prompt modularity        | Section 2.4      |


### 11.3 Endpoints Not Leveraged — High Impact

The following CodeMie capabilities were **not referenced** in our architecture but could significantly strengthen the solution:

#### 11.3.1 Guardrails (7 endpoints)


| Endpoint                                        | Purpose                              |
| ----------------------------------------------- | ------------------------------------ |
| `GET /v1/guardrails`                            | List available guardrails            |
| `POST /v1/guardrails/{guardrail_id}/apply`      | Apply a guardrail to content         |
| `GET /v1/guardrails/assignments`                | Get guardrail-to-project assignments |
| `GET /v1/guardrails/{guardrail_id}/assignments` | Get specific guardrail assignments   |
| `PUT /v1/guardrails/{guardrail_id}/assignments` | Bulk assign guardrail to entities    |


**Relevance:** Our `data-privacy.md` designs PII handling at the prompt level (instructing agents to use `[CUSTOMER_NAME]` placeholders). CodeMie's built-in guardrails could provide a **platform-level safety net** that operates independently of prompt instructions:

- **PII redaction guardrail:** Automatically strip or mask PII before LLM processing, reducing reliance on prompt-level PII placeholders.
- **Content safety guardrail:** Prevent the ResponseDrafter from generating inappropriate content (threats, discriminatory language).
- **Output format guardrail:** Enforce JSON schema compliance on agent outputs, complementing the `output_schema` parameter.

**Recommendation:** Attach guardrails to all 5 AR email agents. This provides defense-in-depth for PII handling (prompt instructions + platform guardrail) and addresses EU AI Act compliance more robustly than prompt-only controls.

#### 11.3.2 Workflow Output Editing (2 endpoints)


| Endpoint                                                         | Purpose                                                  |
| ---------------------------------------------------------------- | -------------------------------------------------------- |
| `PUT /v1/workflows/{id}/executions/{eid}/output`                 | Edit output of last workflow state on `interrupt_before` |
| `PUT /v1/workflows/{id}/executions/{eid}/output/request_changes` | Request output changes with LLM assistance               |


**Relevance:** Our ADR-002 (Human-in-the-Loop Design) defines four approval outcomes: Approve, Edit+Approve, Reject, Escalate. The "Edit+Approve" flow currently assumes the human manually edits the draft text. The `request_changes` endpoint enables an **AI-assisted edit** workflow:

1. Approver reviews draft, types natural language feedback (e.g., "Make the tone more formal and add the invoice number")
2. `PUT .../output/request_changes` sends the feedback to the LLM
3. LLM revises the draft based on the feedback
4. Approver reviews the revised draft and approves

This is a significant UX improvement that reduces the editing burden on AR specialists while maintaining human control.

**Recommendation:** Add `request_changes` as a fifth approval outcome ("Request AI Revision") in ADR-002 and the approval UI sequence diagram.

#### 11.3.3 Analytics (39 endpoints)

Key endpoints relevant to AR email processing:


| Endpoint                                | Purpose                        | AR Email Use                                     |
| --------------------------------------- | ------------------------------ | ------------------------------------------------ |
| `GET /v1/analytics/agents-usage`        | Agent invocation counts        | Track which agents are most/least active         |
| `GET /v1/analytics/assistants-chats`    | Conversation volumes           | Monitor email processing throughput              |
| `GET /v1/analytics/llms-usage`          | LLM token consumption and cost | Validate $220--550/month cost estimate (ADR-001) |
| `GET /v1/analytics/tools-usage`         | Tool invocation metrics        | Track SAP/Graph API call patterns                |
| `GET /v1/analytics/users-activity`      | User activity tracking         | Monitor approver response times                  |
| `GET /v1/analytics/projects-spending`   | Cost per project               | AR email management cost allocation              |
| `GET /v1/analytics/summaries`           | Summary dashboard metrics      | Operational dashboard for AR team leads          |
| `GET /v1/analytics/webhooks-invocation` | Webhook reliability            | Monitor bridge service webhook health            |


**Relevance:** Our architecture defines KPIs (AHT reduction, classification accuracy, approval rate) in `architecture-overview.md` but does not specify how they are measured. CodeMie's analytics API provides **built-in instrumentation** for most of these KPIs without custom development.

**Recommendation:** Reference the analytics API in the architecture overview's monitoring section. Map each defined KPI to the specific analytics endpoint that provides the data.

#### 11.3.4 Conversation Analysis (2 endpoints)


| Endpoint                                 | Purpose                            |
| ---------------------------------------- | ---------------------------------- |
| `POST /v1/conversation-analysis/trigger` | Trigger automated quality analysis |
| `GET /v1/conversation-analysis/status`   | Get analysis status                |


**Relevance:** Could automate quality monitoring of email classification and response drafting. By triggering periodic conversation analysis on completed email processing workflows, the system can detect classification drift, response quality degradation, or emerging email patterns that the taxonomy doesn't cover.

**Recommendation:** Include conversation analysis in the continuous improvement feedback loop described in `architecture-overview.md`.

#### 11.3.5 Feedback API (5 endpoints)


| Endpoint                                                 | Purpose                        |
| -------------------------------------------------------- | ------------------------------ |
| `POST /v1/feedback`                                      | Create feedback entry          |
| `GET /v1/feedback`                                       | List feedback                  |
| `DELETE /v1/feedback`                                    | Delete feedback                |
| `POST /v1/conversations/{id}/feedback`                   | Final feedback on conversation |
| `PUT /v1/admin/users/{uid}/conversations/{cid}/feedback` | Admin update feedback          |


**Relevance:** Our prompts mention a "feedback loop for continuous model improvement" but do not specify the mechanism. CodeMie's feedback API provides a **native channel** for recording approval/rejection/edit signals:

- When an approver approves a draft as-is, record positive feedback on the conversation.
- When an approver edits a draft, record the edit delta as feedback (original vs. edited).
- When an approver rejects, record the rejection reason as negative feedback.
- Aggregate feedback data can drive prompt tuning, few-shot example selection, and confidence threshold adjustment.

**Recommendation:** Integrate the Feedback API into the approval workflow. Each approval decision should generate a feedback entry linking the conversation ID to the approval outcome.

#### 11.3.6 System Prompt Validation (1 endpoint)


| Endpoint                                     | Purpose                                  |
| -------------------------------------------- | ---------------------------------------- |
| `POST /v1/assistants/system-prompt/validate` | Validate system prompt before deployment |


**Relevance:** We have 5 production-ready system prompts (EmailClassifier, ThreadSummarizer, ResponseDrafter, ActionRouter, ReviewPresenter). This endpoint enables **CI/CD validation** of prompt changes before they affect live email processing.

**Recommendation:** Include prompt validation in the deployment pipeline. Any change to the 5 agent prompts should be validated via this endpoint before deployment.

#### 11.3.7 Workflow Export (1 endpoint)


| Endpoint                                         | Purpose                            |
| ------------------------------------------------ | ---------------------------------- |
| `GET /v1/workflows/{id}/executions/{eid}/export` | Export complete workflow execution |


**Relevance:** Our audit trail design (architecture-overview.md, Section "Audit Trail") requires logging every classification, draft, action, and approval. The workflow export endpoint provides a **single-call audit snapshot** of the entire execution, including all intermediate state outputs.

**Recommendation:** Use workflow export as the primary audit record. Store the exported execution alongside the custom audit log entries for a complete, tamper-evident record.

### 11.4 Endpoints Not Leveraged — Medium Impact


| Category                  | Key Endpoints                                | Potential Use                                                 | Recommendation                                                                  |
| ------------------------- | -------------------------------------------- | ------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| **Custom Nodes**          | `GET /v1/workflows/custom-nodes`, schema     | Pre-filter rules and thread lookup as reusable workflow nodes | Evaluate during implementation; may reduce bridge service scope                 |
| **Knowledge Base**        | `POST /v1/index/knowledge_base/file`         | Index SAP correspondence templates as a searchable datasource | Implement for ResponseDrafter template retrieval (semantic memory, Section 5.3) |
| **Tools API**             | `POST /v1/tools/{tool_name}/invoke`, schema  | Wrap SAP OData calls as CodeMie tools callable from workflows | Evaluate as alternative to direct SAP API calls from bridge service             |
| **Assistant Evaluation**  | `POST /v1/assistants/{id}/evaluate`          | Validate classification accuracy against labeled test sets    | Include in pre-deployment testing pipeline                                      |
| **Skills API** (detailed) | `POST /v1/skills`, import/export, categories | Version and manage prompts as first-class CodeMie entities    | Implement Skills for all 5 agent prompts for A/B testing capability             |
| **Logs API**              | `POST /v1/logs`                              | Query logs by target field for debugging                      | Reference in operational runbook                                                |
| **Metrics API**           | `POST /v1/metrics`                           | Submit custom email processing metrics                        | Complement built-in analytics with domain-specific KPIs                         |
| **Mermaid Diagram**       | `POST /v1/files/diagram/mermaid`             | Generate workflow visualizations from within CodeMie          | Minor: useful for documentation auto-generation                                 |
| **MCP Configs**           | `POST /v1/mcp-configs`, list                 | Manage MCP server configurations                              | Relevant if Graph API bridge is implemented as MCP server (ADR-005 Option A)    |


### 11.5 Endpoints Not Relevant to AR Email Processing

The following endpoint groups are not applicable to this use case and are excluded from recommendations:

- **IDE/CLI analytics** (cli-agents, cli-errors, cli-repositories, etc.) -- developer tool metrics, not email processing
- **Katas** (create, start, complete, leaderboard) -- training/gamification feature
- **Speech recognition** -- voice input, not applicable
- **Marketplace publishing** -- assistant/skill sharing, not relevant during initial implementation
- **Vendor import** -- external entity import, not needed for AR email
- **Admin/Application** -- platform administration, not architecture-relevant
- **Embeddings** -- direct embedding calls; handled transparently by assistants
- **LLM Proxy** (chat/completions, messages) -- raw LLM access; we use assistants instead

### 11.6 Revised Build vs. Configure Summary

Updated from Section 9.3 to reflect newly identified platform capabilities:


| Component                              | Build       | Configure | Exists (Newly Identified)            |
| -------------------------------------- | ----------- | --------- | ------------------------------------ |
| Graph API bridge service               | X           |           |                                      |
| Email thread to conversation mapping   | X           |           |                                      |
| EmailClassifier assistant              |             | X         |                                      |
| ResponseDrafter assistant              |             | X         |                                      |
| ActionRouter assistant                 |             | X         |                                      |
| ThreadSummarizer assistant             |             | X         |                                      |
| ReviewPresenter formatting             | X           |           |                                      |
| Approval UI (Alevate)                  | X           |           |                                      |
| Approval UI (SAP)                      | X           |           |                                      |
| AR email processing workflow (YAML)    |             | X         |                                      |
| SAP correspondence template datasource |             | X         |                                      |
| Stale workflow monitoring job          | X           |           |                                      |
| Audit trail logging                    | X (partial) |           | Workflow export (**new**)            |
| PII/content safety enforcement         |             |           | Guardrails (**new**)                 |
| AI-assisted draft editing              |             |           | Workflow `request_changes` (**new**) |
| KPI monitoring and dashboards          |             |           | Analytics API (**new**)              |
| Classification quality monitoring      |             |           | Conversation analysis (**new**)      |
| Approval feedback recording            |             |           | Feedback API (**new**)               |
| Prompt validation in CI/CD             |             |           | System prompt validation (**new**)   |


### 11.7 Impact Summary

The API inventory analysis reveals that **7 high-impact capabilities** exist in CodeMie that our initial architecture did not reference. Integrating these reduces the custom development footprint:

- **3 gaps partially mitigated:** G8 (stale workflow monitoring -- analytics provides visibility), G9 (webhook notification -- analytics tracks invocations), and audit trail completeness (workflow export).
- **2 new capabilities that enhance the approval flow:** Guardrails (defense-in-depth PII) and workflow `request_changes` (AI-assisted editing).
- **2 operational capabilities:** Analytics API (built-in KPI tracking) and Feedback API (native feedback loop).

The custom "Build" column shrinks from 8 items to 7 (audit trail moves to partial-exists), while the "Exists" column grows from 1 to 7 items.

---

## Related Documents

- **[ADR-004: Agent Design](decisions/ADR-004-agent-design.md)** -- Architecture decision for single vs. multi-agent vs. workflow approach
- **[ADR-005: Outlook Integration Pattern](decisions/ADR-005-outlook-integration-pattern.md)** -- Architecture decision for Graph API connectivity
- **[Integration Review](integration-review.md)** -- Detailed analysis of SAP/Alevate/CodeMie integration patterns
- **[Architecture Overview](architecture-overview.md)** -- Full system architecture narrative
- **[ADR-002 (Multitenancy): Alevate-to-CodeMie Authentication](../multytenancy/decisions/ADR-002-alevate-codemie-sdk-api-authentication.md)** -- PingOne JWT bearer pattern
- **[ADR-003 (Multitenancy): SAP PAT Gateway](../multytenancy/decisions/ADR-003-sap-pat-to-codemie-gateway.md)** -- PAT-to-JWT token exchange
- **[ADR-012 (Multitenancy): MCP Token Propagation](../multytenancy/decisions/ADR-012-pingone-token-propagation-to-custom-mcp.md)** -- Token relay to custom MCP servers
- **[ADR-020 (Multitenancy): Headless API Pattern](../multytenancy/decisions/ADR-020-headless-api-integration-pattern.md)** -- Complete developer contract for headless invocation

---

*Part of the AR Email Management Domain -- Financial System Modernization Project*