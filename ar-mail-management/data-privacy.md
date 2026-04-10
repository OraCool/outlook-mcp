# AR Email Management — Data Privacy & Compliance

## Executive Summary

The AR Email Management solution processes personal data contained in inbound Accounts Receivable emails. This document defines the data privacy framework, GDPR compliance controls, and EU AI Act assessment for the solution.

The system processes email addresses, names, and potentially sensitive financial information (bank details, invoice amounts) that appear in customer emails. It uses AI (Large Language Models via CodeMie/LiteLLM) to classify emails and draft responses. The human-in-the-loop approval requirement is both a business design choice and a compliance control — it ensures that no AI-generated output reaches a customer or modifies an ERP record without human review.

Key compliance positions:
- **GDPR**: Processing basis is Article 6(1)(f) — legitimate interest (AR operations). Data minimization, retention limits, and right-to-erasure controls are implemented.
- **EU AI Act**: The system is classified as **not high-risk** under Annex III. It is a business workflow automation tool that makes recommendations to humans, not decisions about individuals. Personal data processing is governed by existing GDPR controls, and no prohibited AI practices are employed.

---

## Personal Data Inventory

### Data Categories Processed

| Data Category | Source | Examples | Sensitivity |
|---------------|--------|----------|-------------|
| **Email sender/recipient addresses** | Microsoft Outlook (Graph API) | john.doe@customer.com, ar-team@company.com | Personal data (GDPR Art. 4(1)) |
| **Email body content** | Microsoft Outlook (Graph API) | Names, addresses, bank details (IBAN/BIC), invoice amounts, payment references, free-form text | Potentially sensitive — may contain financial data |
| **Email metadata** | Microsoft Outlook (Graph API) | Subject line, timestamps, thread references, read receipts | Low sensitivity but linkable to individuals |
| **Customer master data** | SAP FS2/S4 | Company name, contact person name, billing address, phone number, customer account number | Personal data of contact persons |
| **Invoice data** | SAP FS2/S4 | Invoice numbers, amounts, due dates, payment terms, line items | Financial business data — personal if linked to individual customers |
| **AI classification results** | CodeMie pipeline | Category, confidence score, reasoning, extracted intent | Derived data — contains references to personal data |
| **AI-drafted responses** | CodeMie pipeline | Draft email text addressed to customer | Contains personal data (customer name, invoice references) |
| **Audit trail** | PostgreSQL audit store | Approver identity, decision, timestamp, all pipeline outputs | Contains personal data of both customers and internal users |

### Data Not Stored by the Solution

The following data passes through the pipeline but is **not persisted** by the AR Email Management solution:

- **Raw email content**: Remains in Microsoft Outlook. The solution reads emails via Graph API but does not copy full email bodies to its own storage. Thread summaries (which are condensed and factual) are stored; raw prose is not.
- **Email attachments**: Not downloaded or analyzed by the pipeline. Attachment metadata (filename, size) may appear in audit records.

---

## Data Processing Basis

### GDPR Article 6(1)(f) — Legitimate Interest

The processing of personal data in AR emails is based on the **legitimate interest** of the data controller (the company operating the AR function):

| Element | Assessment |
|---------|------------|
| **Purpose** | Efficient management of Accounts Receivable operations — classifying, responding to, and tracking customer correspondence related to invoices, payments, and disputes |
| **Necessity** | The processing is necessary for the stated purpose. Manual processing of 50-200+ emails/day is operationally unsustainable without tooling. AI classification and drafting directly serve this operational need. |
| **Balancing test** | The data subjects (customers sending emails to the AR inbox) have a reasonable expectation that their emails will be read, categorized, and responded to as part of normal business operations. AI-assisted processing does not change the outcome — it changes the efficiency. The human-in-the-loop approval ensures that no AI output reaches the customer without human review, preserving the same level of human judgment as manual processing. |

### Data Processing Agreements

| Partner | Agreement | Scope |
|---------|-----------|-------|
| **Microsoft** (Outlook/Graph API) | Microsoft Online Services DPA | Email storage and access via Graph API |
| **LLM Provider** (Azure OpenAI via LiteLLM) | Azure OpenAI Data Processing Terms | Email content submitted for classification and drafting — with explicit contractual guarantee that customer data is NOT used for model training |
| **EPAM / CodeMie** | CodeMie Data Processing Agreement | AI pipeline orchestration, prompt processing |
| **PingOne** | PingIdentity DPA | Identity tokens and user metadata |

---

## Data Minimization

### Principle: Process Only What Is Needed

| Control | Implementation |
|---------|----------------|
| **Inbox scope** | Only emails from the AR-designated mailbox are processed. Personal inboxes, shared calendars, and other mailboxes are not accessed. |
| **Attachment exclusion** | Attachments are not downloaded or analyzed unless explicitly invoice-related (future enhancement). Only attachment metadata is logged. |
| **Body content transience** | Raw email body content is read from Graph API, processed in memory, and not stored persistently. Thread summaries (factual, condensed) are stored; raw prose is not. |
| **Customer data scope** | Only AR-relevant customer master data is fetched from SAP: company name, contact person, billing address, open invoices, AR aging. Full customer records (credit history, internal notes) are not fetched. |
| **PII in LLM context** | Email content submitted to the LLM contains sender names and email addresses (necessary for classification). Internal SAP IDs, AR team member names, and internal notes are stripped from LLM submission where technically feasible. On Path C, the Outlook MCP Server may additionally redact PII before sampling (see Section Outlook MCP Server — PII Controls). |
| **MCP sampling PII redaction** | The **Outlook MCP Server** can pseudonymize, hash, or remove detected PII (Presidio) in email JSON **before** MCP sampling — opt-in via `PII_REDACTION_ENABLED` and the `[pii]` optional install + spaCy model. |
| **MCP tool response minimization** | `PII_RESPONSE_LEVEL` controls returned payloads: **full**, **minimal** (omits `body_content`), or **redacted** (minimal + Presidio on remaining fields). |
| **Audit trail PII** | Audit records store: email sender address (for traceability), classification results, draft text, and approver identity. They do NOT store the full raw email body. |

---

## Data Storage and Retention

| Data Type | Storage Location | Retention Period | Justification |
|-----------|-----------------|------------------|---------------|
| **Audit trail** (classification, drafts, actions, approvals) | PostgreSQL audit store (Azure managed) | **7 years** | Legal requirement for financial records; SOC 2 audit trail |
| **Thread summaries** | PostgreSQL audit store | **Duration of active AR case + 90 days** | Needed for ongoing thread context; purged after case closure + buffer period |
| **AI classification results** | Retained within audit trail | **7 years** (as part of audit trail) | Traceability: which AI classification led to which action |
| **AI-drafted responses** | Retained within audit trail | **7 years** (as part of audit trail) | Traceability: what was recommended vs. what was approved |
| **Raw email content** | **NOT stored by the solution** — remains in Microsoft Outlook | Per Outlook/Exchange retention policy (managed by IT) | Solution reads via Graph API but does not persist |
| **Customer master data cache** | In-memory cache (Redis/application cache) | **15-minute TTL** (cache only; source of truth is SAP) | Performance optimization; not a persistence layer |
| **Graph API OAuth tokens** | Azure Key Vault | **Until rotation** (rotated on expiry or security event) | Credential management |

### Data Deletion Process

When retention periods expire:
1. Automated job runs daily to identify expired records
2. Records are soft-deleted (marked as deleted, excluded from queries)
3. After 30-day soft-delete period, records are hard-deleted (physical removal)
4. Deletion is logged in a separate, immutable deletion audit log

---

## Access Control

### Tenant-Level Isolation

| Control | Implementation |
|---------|----------------|
| **JWT groups claim** | Every API request includes a PingOne JWT with tenant identifier in the `groups` claim. The audit store enforces tenant-level row filtering on all queries. |
| **CodeMie project isolation** | Each tenant's assistants and workflows are scoped to a CodeMie project. Cross-tenant data access is prevented at the CodeMie authorization layer. |
| **Database schema routing** | If Alevate schema-per-tenant isolation is active (ADR-015), audit data is stored in the tenant's schema. Otherwise, tenant_id column filtering is enforced. |

### User-Level Access

| Role | Permissions |
|------|------------|
| **AR Specialist** | View AI recommendations for emails in their assigned queue; approve/edit/reject recommendations; view audit trail for their own approvals |
| **AR Manager** | All AR Specialist permissions + view all team recommendations + view aggregate metrics + override rejected recommendations |
| **System Administrator** | Configure email ingestion (inbox, webhook), manage classification taxonomy, view system health metrics. No access to email content or customer data. |
| **Auditor** | Read-only access to audit trail (all tenants they are authorized for). Cannot approve, edit, or execute actions. |

### MCP Token Propagation

For CodeMie tools that access external systems (SAP, Alevate), the user's PingOne JWT is propagated via the `X-PingOne-Token` header (per ADR-012). This ensures that data access is performed with the user's delegated permissions, not a service account with broad access.

---

## Data Processing Location

| Component | Location | Data Residency |
|-----------|----------|----------------|
| Microsoft Outlook (Exchange Online) | Azure EU region (per tenant M365 configuration) | Email data stays in EU |
| Email Ingestion Service | Azure AKS, EU region | Processes email in EU; does not persist raw content |
| CodeMie AI pipeline | Azure AKS, EU region | LLM calls routed via LiteLLM to Azure OpenAI EU deployment |
| LLM Provider (Azure OpenAI) | Azure EU region (West Europe / North Europe) | Prompts and completions processed in EU; no data retention by Azure OpenAI for training |
| PostgreSQL audit store | Azure Database for PostgreSQL, EU region | All audit data stored in EU |
| Azure Key Vault | Azure EU region | Encryption keys and credentials stored in EU |
| PingOne | PingOne EU environment | Identity tokens issued from EU |

**No personal data is transferred outside the EU.** The LLM provider (Azure OpenAI) is contractually bound to process data in the configured EU region and not use customer data for model training.

---

## Right to Erasure (GDPR Article 17)

### Process for Customer Data Deletion Requests

When a data subject (customer contact person) exercises their right to erasure:

**Step 1: Request Receipt and Validation**
- Erasure request received via company's standard GDPR channel (not via AR inbox)
- Data Protection Officer (DPO) validates the request and identifies the data subject

**Step 2: Data Identification**
- Query audit store for all records containing the data subject's email address or name
- Identify thread summaries referencing the data subject
- Identify AI classification results and drafts referencing the data subject

**Step 3: Erasure Execution**
- **Audit trail records**: Pseudonymize the data subject's personal data (replace email address and name with a hash). The audit record structure is preserved for financial record-keeping compliance, but personal identifiers are removed.
- **Thread summaries**: Delete or redact references to the data subject in stored summaries
- **AI drafts**: Redact the data subject's name and contact details from stored draft texts
- **Customer master data cache**: Invalidate any cached entries for the data subject (cache TTL handles this within 15 minutes)

**Step 4: Confirmation**
- Log the erasure action in the deletion audit log (date, scope, operator)
- Confirm to the DPO that erasure is complete
- DPO confirms to the data subject

**Limitations**:
- Erasure does not extend to emails in Microsoft Outlook — these are managed by the company's IT/email retention policy
- Financial records required by law (e.g., invoice data in SAP) may be exempt from erasure under GDPR Article 17(3)(b) — legal obligation exemption
- The audit trail itself cannot be fully deleted if required for financial regulatory compliance; pseudonymization is used instead

---

## EU AI Act Compliance Assessment

### Step 1: AI System Identification

**Question**: Is this an AI system as defined by the EU AI Act?

**Answer**: **YES**

The AR Email Management solution uses Large Language Models (LLMs) to:
- Classify email content into categories (inference/prediction)
- Extract intent from natural language (content generation)
- Generate draft email responses (content generation)
- Determine recommended actions (decision support)

This falls squarely within the EU AI Act definition of an AI system: "a machine-based system that is designed to operate with varying levels of autonomy and that may exhibit adaptiveness after deployment and that, for explicit or implicit objectives, infers, from the input it receives, how to generate outputs such as predictions, content, recommendations, or decisions that can influence physical or virtual environments" (Article 3(1)).

### Step 2: Prohibited Practices (Article 5)

**Question**: Does the system employ any prohibited AI practices?

**Answer**: **CONFIRMED NOT APPLICABLE**

| Prohibited Practice | Assessment |
|---------------------|------------|
| **Subliminal manipulation** | Not applicable. The system classifies business emails and drafts replies — it does not attempt to manipulate individuals beyond their consciousness. |
| **Exploitation of vulnerabilities** | Not applicable. The system processes business correspondence, not vulnerable individuals. |
| **Social scoring** | Not applicable. The system categorizes emails by topic, not people by behavior or social status. |
| **Real-time remote biometric identification** | Not applicable. No biometric data is processed. |
| **Emotion recognition in workplace/education** | Not applicable. The system detects email intent (payment promise, dispute, etc.) not emotions. While `ESCALATION_LEGAL` detects tone, this is a safety escalation trigger (route to human), not emotion-based decision-making. |
| **Biometric categorization** | Not applicable. No biometric data is processed. |
| **Predictive policing** | Not applicable. Not a law enforcement system. |
| **Untargeted facial image scraping** | Not applicable. No image processing. |

### Step 3: High-Risk Categories (Annex III)

**Question**: Is this a high-risk AI system?

**Answer**: **NOT HIGH-RISK**

Assessment against Annex III categories:

| Annex III Category | Applicable? | Rationale |
|--------------------|-------------|-----------|
| 1. Biometrics | No | No biometric data processed |
| 2. Critical infrastructure | No | AR email management is not critical infrastructure (energy, water, transport, digital) |
| 3. Education and vocational training | No | Not an education system |
| 4. Employment, workers management | No | The system processes customer emails, not employee data or HR decisions |
| 5. Access to essential services | No | AR collections are business-to-business operations, not access to essential public/private services for individuals |
| 6. Law enforcement | No | Not a law enforcement system |
| 7. Migration, asylum, border control | No | Not applicable |
| 8. Administration of justice | No | Not applicable |

**Important nuance**: While the system processes financial data and makes recommendations that could affect business relationships (e.g., recommending dispute escalation or payment extension approval), it does so in a B2B context with full human oversight. The recommendations affect the **company's internal workflow**, not individual rights or access to services.

**Documentation requirement**: Even though the system is not high-risk, this assessment is documented and maintained as part of the compliance record. If the system's scope expands (e.g., to include automated credit decisions or consumer-facing communication), this assessment must be revisited.

### Step 4: Personal Data Processing

**Question**: Does the system process personal data?

**Answer**: **YES**

The system processes the following personal data:
- **Email addresses** of customers and their contact persons
- **Names** of customer contact persons (appearing in email signatures, body text, SAP master data)
- **Potentially bank details** (IBAN, BIC) when customers include payment information in email body
- **Invoice amounts and payment terms** linked to identifiable customers
- **Internal user data**: Approver identities (PingOne user IDs, names) in the audit trail

**GDPR controls apply** and are detailed in the earlier sections of this document (Sections 2-8).

### Step 5: Anonymized Training Data

**Question**: If model fine-tuning is performed, is only anonymized data used?

**Answer**: **YES (with conditions)**

| Scenario | Approach |
|----------|----------|
| **Primary approach (current)** | The solution uses pre-trained LLMs (Azure OpenAI via LiteLLM) with prompt engineering. No model fine-tuning is performed on customer data. LLM calls use zero-shot or few-shot prompting with synthetic examples. |
| **Future fine-tuning (if needed)** | If classification accuracy requires model fine-tuning, only anonymized email data will be used. Anonymization process: replace all personal identifiers (names, email addresses, company names, invoice numbers, amounts) with synthetic equivalents before inclusion in training data. The anonymization process will be documented and validated by the DPO before any fine-tuning begins. |
| **LLM provider guarantee** | Azure OpenAI's data processing terms contractually prohibit the use of customer prompts and completions for model training. This is a contractual control independent of our anonymization approach. |

---

## Risk Mitigation Controls

### PII Protection in LLM Context

| Control | Implementation |
|---------|----------------|
| **No PII in training data** | Pre-trained models only; no fine-tuning on customer data. If fine-tuning is ever performed, only anonymized data is used. |
| **LLM provider DPA** | Azure OpenAI contractual guarantee: customer data is NOT used for model training, NOT stored beyond the API call processing window. |
| **Prompt sanitization** | Internal SAP IDs, AR team member personal email addresses, and internal notes are stripped from LLM context before submission (where technically feasible without degrading classification accuracy). |
| **Server-side Presidio (Outlook MCP)** | When enabled, Microsoft Presidio redacts configurable entity types in sampling payloads; see [ADR-007](decisions/ADR-007-mcp-pii-redaction-strategy.md). |
| **Output validation** | AI-generated drafts are validated for completeness and format before presentation to human approver. The human approver serves as the final guard against PII leakage in outbound communications. |

### Field-Level Encryption for Financial Data

| Data | Encryption | Key Management |
|------|------------|----------------|
| Invoice amounts in audit trail | AES-256 field-level encryption | Azure Key Vault (customer-managed keys) |
| Bank details (if captured) | AES-256 field-level encryption | Azure Key Vault (customer-managed keys) |
| Customer email addresses in audit trail | Stored in cleartext (needed for query/traceability) | Access controlled via tenant isolation + RBAC |
| Approver identity | Stored in cleartext (needed for audit compliance) | Access controlled via RBAC |

### Token Propagation for Delegated Access

The MCP token propagation pattern (ADR-012) ensures that CodeMie tools accessing external systems (SAP, Alevate) operate with the **user's delegated permissions**, not a service account with broad access. This limits the blast radius of any token compromise and ensures that access control decisions are made at the source system level.

---

## Outlook MCP Server — PII Controls

The **Outlook MCP Server** (see [ADR-006](decisions/ADR-006-ui-triggered-email-processing-delegated-mcp.md), [ADR-007](decisions/ADR-007-mcp-pii-redaction-strategy.md)) applies additional controls at the MCP boundary:

### Layer 1 — Server-side PII redaction before LLM sampling

| Aspect | Detail |
|--------|--------|
| **Mechanism** | Optional **Microsoft Presidio** (`presidio-analyzer`) with configurable entity types (default: `EMAIL_ADDRESS`, `PERSON`, `PHONE_NUMBER`, `IBAN_CODE`, `CREDIT_CARD`, `IP_ADDRESS`, `LOCATION`). |
| **Strategies** | `pseudonymize` (indexed placeholders), `hash` (short SHA-256 hex per span), `remove` (`[REDACTED]`). |
| **Activation** | Environment flags `PII_REDACTION_ENABLED`, `PII_REDACTION_STRATEGY`, `PII_ENTITIES`; requires `pip install outlook-multi-tenant-mcp[pii]` and spaCy model `en_core_web_sm`. |
| **Scope** | Applied after HTML strip/truncation (`sanitize_email_json_for_prompt`) and **only to the payload embedded in MCP sampling** for `categorize_email` / `extract_email_data`. |
| **Fallback** | If Presidio is missing or the analyzer fails to initialize, sampling receives unredacted sanitized JSON and a warning is logged once — operators should fix the deployment. |

### Layer 2 — Data minimization in MCP tool responses

| Level | Behavior |
|-------|----------|
| `full` | Return complete email JSON (including `body_content`) — default / dev. |
| `minimal` | Omit `body_content` (and related full-body fields); truncate long `subject` / `body_preview`; keep identifiers and metadata needed for threading. |
| `redacted` | Start from `minimal`, then run the same Presidio pipeline on the remaining JSON. |

Applies to sampling tool responses and read tools (`get_email`, `list_inbox`, `search_emails`, `get_thread`) so orchestrators can run with reduced PII surface.

### Layer 3 — Logging and error hygiene

| Control | Detail |
|---------|--------|
| **MCP `ctx.log` / progress** | Messages passed through truncation and email-pattern scrubbing before emission. |
| **Graph / HTTP errors** | Client-visible error bodies and generic `graph_error` messages are shortened and email-like tokens masked. |

No persistent mailbox storage is added at the MCP layer; tokens remain transient per ADR-006.

**Diagram:** [ar-mail-flow-pii-redaction.mermaid](diagrams/flows/ar-mail-flow-pii-redaction.mermaid)

---

## Compliance Checklist

### EU AI Act Compliance Matrix

| Step | Requirement | Status | Control | Reference |
|------|-------------|--------|---------|-----------|
| 1 | AI System Identification | Assessed | System uses LLMs for classification and generation — confirmed as AI system | Section 9, Step 1 |
| 2 | Prohibited Practices | Cleared | No prohibited practices employed — documented assessment for all 8 categories | Section 9, Step 2 |
| 3 | High-Risk Assessment | Cleared | Not high-risk per Annex III — not in any listed category; documented rationale | Section 9, Step 3 |
| 4 | Personal Data Processing | Identified | Processes email PII and financial data — GDPR controls implemented | Sections 2-8 |
| 5 | Training Data Anonymization | Controlled | No fine-tuning on customer data; anonymization required if future fine-tuning | Section 9, Step 5 |
| -- | Human Oversight | Implemented | Human-in-the-loop approval for all AI outputs — no autonomous actions | Architecture Overview, ADR-002 |
| -- | Transparency | Implemented | AI confidence scores and reasoning visible to approver; system identified as AI-assisted | ReviewPresenter output |
| -- | Record-Keeping | Implemented | Full audit trail with 7-year retention | Section 5, Architecture Overview |
| -- | Data Governance | Implemented | GDPR basis documented, DPAs in place, data minimization enforced | Sections 2-5 |

### GDPR Compliance Matrix

| GDPR Requirement | Status | Control | Reference |
|------------------|--------|---------|-----------|
| Art. 5(1)(a) — Lawfulness, fairness, transparency | Implemented | Processing basis documented (Art. 6(1)(f)); AI-assisted nature disclosed | Section 3 |
| Art. 5(1)(b) — Purpose limitation | Implemented | Data processed only for AR email management | Section 4 |
| Art. 5(1)(c) — Data minimization | Implemented | Only AR-relevant data processed; raw email not stored | Section 4 |
| Art. 5(1)(d) — Accuracy | Implemented | Customer master data sourced from SAP (system of record); AI accuracy tracked | Architecture Overview |
| Art. 5(1)(e) — Storage limitation | Implemented | Defined retention periods with automated deletion | Section 5 |
| Art. 5(1)(f) — Integrity and confidentiality | Implemented | Field-level encryption, tenant isolation, RBAC, TLS 1.3 | Section 6, 10 |
| Art. 6 — Lawfulness of processing | Implemented | Legitimate interest basis with balancing test | Section 3 |
| Art. 13/14 — Information to data subject | Required | Privacy notice must reference AI-assisted email processing (responsibility of DPO/Legal) | -- |
| Art. 17 — Right to erasure | Implemented | Pseudonymization process for audit records; deletion for summaries | Section 8 |
| Art. 25 — Data protection by design | Implemented | Minimization, transient processing, encryption, access control | Sections 4-6 |
| Art. 28 — Processor obligations | Implemented | DPAs with Microsoft, Azure OpenAI, CodeMie, PingOne | Section 3 |
| Art. 30 — Records of processing activities | Required | This document serves as the initial ROPA entry; formal ROPA must be maintained by DPO | -- |
| Art. 32 — Security of processing | Implemented | Encryption, access control, audit logging, tenant isolation | Sections 6, 10 |
| Art. 35 — DPIA | Recommended | DPIA should be conducted before production deployment — AI processing of financial communications warrants formal assessment even if not legally required | -- |

---

## PII Edge Cases (Added 2026-04-08)

### PII in Non-Body Fields

Email subject lines frequently contain customer PII:
- Customer names: "RE: Payment from Acme Corp - John Smith"
- Invoice numbers: "Invoice #INV-2026-12345 overdue"
- Amounts: "RE: $50,000 balance inquiry"
- Combined: "RE: Dispute on Invoice #12345 - $10,500 - Acme Corp"

Attachment filenames may also contain PII:
- "Invoice_AcmeCorp_2026-03-15.pdf"
- "Payment_Proof_JSmith_IBAN_DE89370400440532013000.pdf"

**Current coverage in Outlook MCP Server (ADR-007):**

| Field | Presidio Redaction | Status |
|---|---|---|
| `body_content` | Yes (when PII_REDACTION_ENABLED) | Covered |
| `body_preview` | Yes | Covered |
| `subject` | Yes | Covered |
| `from.address` / `from.name` | Yes | Covered |
| `sender.address` / `sender.name` | Yes | Covered |
| `to_recipients[].address` / `to_recipients[].name` | Yes | Covered |
| **Attachment filenames** | **No** | **Gap** — filenames are returned by `get_attachments` without redaction |
| **Error messages** | Partial — email addresses scrubbed via regex | Limited — only in log sanitization, not in tool error responses |

**Recommendation:** Extend `email_json_for_tool_response()` in the MCP server's PII redactor to optionally redact attachment filename fields when `PII_RESPONSE_LEVEL=redacted`.

### Multi-Language PII Detection

Microsoft Presidio's Named Entity Recognition (NER) accuracy varies significantly by language:

| Language | PERSON Detection | LOCATION Detection | Notes |
|---|---|---|---|
| English | High (~95%) | High (~90%) | Primary supported language |
| German | Medium (~75-85%) | Medium (~70-80%) | Requires `de_core_news_sm` spaCy model (not installed by default) |
| French | Medium (~75-85%) | Medium (~70-80%) | Requires `fr_core_news_sm` spaCy model |
| Spanish | Medium (~70-80%) | Medium (~70-80%) | Requires `es_core_news_sm` spaCy model |
| Italian | Low-Medium (~65-75%) | Low-Medium (~65-75%) | Requires `it_core_news_sm` spaCy model |

**Current state:** The MCP server installs only `en_core_web_sm` via `[pii]` extra. Non-English PII detection relies on pattern-based recognizers (EMAIL_ADDRESS, PHONE_NUMBER, IBAN_CODE, CREDIT_CARD) which are language-independent, plus a Cyrillic text filter that suppresses false-positive PERSON/LOCATION detections.

**Known limitations:**
1. German compound names (e.g., "Müller-Schmidt") may not be detected as PERSON entities by English NER
2. French accented names (e.g., "Renée Côté") detection is inconsistent with English-only model
3. Mixed-language emails (common in multinational AR) may confuse single-language NER models

**Recommendations:**
1. For Phase 1 (English-only): Current implementation is adequate. Document that PII detection accuracy degrades for non-English content.
2. For Phase 2 (multi-language): Add spaCy model installation for DE/FR as optional extras (e.g., `pip install outlook-multi-tenant-mcp[pii-de,pii-fr]`). Extend Presidio AnalyzerEngine initialization to load language-specific models.
3. Pattern-based recognizers (EMAIL, PHONE, IBAN, CREDIT_CARD) remain effective across all languages and should be the primary defense for non-English emails.

---

*Part of the AR Email Management Domain — Financial System Modernization Project*
