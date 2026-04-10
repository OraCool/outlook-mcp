# ADR-007: Outlook MCP Server — PII Redaction Strategy

**Status:** Accepted  
**Date:** 2026-04-07  
**Decision Makers:** AR Email Management Architecture Team  
**Technical Story:** Define how the Outlook MCP Server minimizes personal data sent to LLMs via MCP sampling and in tool responses, to align with GDPR Article 5(1)(c) (data minimization) and defense in depth beyond Azure OpenAI DPA alone.

---

## Context and Problem Statement

[ADR-006](ADR-006-ui-triggered-email-processing-delegated-mcp.md) introduced the Outlook MCP Server for delegated Graph API reads. Tools `categorize_email` and `extract_email_data` embed email JSON in MCP **sampling** prompts, which the host forwards to an LLM (typically Azure OpenAI). Read tools (`get_email`, `list_inbox`, etc.) return full message payloads to the orchestrator.

Even when the LLM provider does not train on customer data (Microsoft DPA), **data minimization** still requires sending only what is necessary and limiting what downstream components (orchestrator, logs) observe.

---

## Decision Drivers

- GDPR Art. 5(1)(c) — data minimization for processor/controller deployments  
- Classification quality — AR workflows need invoice numbers, amounts, and intent cues; overly aggressive redaction degrades accuracy  
- Operability without new external APIs per email (latency, availability)  
- Optional install — `pip install outlook-multi-tenant-mcp[pii]` + spaCy model for environments that need NLP-based detection  
- Configurable behavior — production can enable redaction and tighten `pii_response_level` without code changes  

---

## Considered Options

### Option A: Presidio-based pseudonymization (chosen)

**Description:** Use [Microsoft Presidio](https://github.com/microsoft/presidio) (`presidio-analyzer`) to detect entities (e.g. `EMAIL_ADDRESS`, `PERSON`, `PHONE_NUMBER`, `IBAN_CODE`, `CREDIT_CARD`, `IP_ADDRESS`, `LOCATION`) in subject, body, preview, and address fields. Replace spans with indexed placeholders such as `[EMAIL_ADDRESS_1]`, `[PERSON_1]`, or strategies `hash` / `remove`.

**Pros:** Strong free-text detection; Microsoft-maintained; aligns with Azure ecosystem; no outbound PII API per message.  
**Cons:** Adds Python dependencies and `en_core_web_sm` (Docker/CI); NLP may miss edge cases or mis-label; Python 3.12+ wheel availability must be verified in CI images.

### Option B: Regex-only redaction

**Description:** Strip email-shaped strings and phone-like patterns without NLP.

**Pros:** Minimal footprint.  
**Cons:** Misses person names and context-only PII; high false-positive risk on invoice text.

### Option C: Azure AI Language PII API

**Description:** Call Azure Cognitive Services for PII detection on each payload.

**Pros:** Managed service accuracy.  
**Cons:** Extra latency, cost, failure domain, and another sub-processor for DPIA/schedules.

### Option D: No server-side redaction

**Description:** Rely on Azure OpenAI DPA and prompt instructions only.

**Pros:** No MCP code path.  
**Cons:** Does not satisfy minimization for orchestrator-visible tool outputs or sampling payloads; weaker log hygiene story.

---

## Decision Outcome

**Chosen:** **Option A** — Presidio-based redaction in the MCP server, **opt-in** via `PII_REDACTION_ENABLED=true`, with:

1. **Sampling path:** After `sanitize_email_json_for_prompt`, apply `redact_email_json_if_enabled` before `build_untrusted_email_user_text`.  
2. **Tool responses:** `PII_RESPONSE_LEVEL` = `full` | `minimal` | `redacted` — `minimal` omits `body_content` from returned email JSON; `redacted` applies minimization then Presidio on the remaining fields.  
3. **Logging / errors:** MCP log lines and client-facing Graph error snippets pass through `sanitize_client_error_message` (email pattern scrub + truncation).

If Presidio is not installed or the analyzer fails to initialize, redaction is skipped with a warning log (no crash).

**Implementation reference:** `outlook-mcp-server` package `outlook_mcp.pii`, settings in `config.py`, tests in `tests/test_pii_redactor.py`.

---

## Consequences

### Positive

- Clear, testable minimization at the MCP boundary  
- Configurable strategies and entity lists  
- Aligns documentation in `data-privacy.md` Section 11 with actual behavior  

### Negative

- Operators must install `[pii]` extra and `en_core_web_sm` for production redaction (Dockerfile updated accordingly)  
- Slight CPU cost per redacted payload  
- Pseudonymization may still leave relational cues (`[PERSON_1]` vs `[PERSON_2]`); not a substitute for DPIA or tenant policies  

### Related

- [ADR-006](ADR-006-ui-triggered-email-processing-delegated-mcp.md) — Outlook MCP scope and `X-Graph-Token`  
- [data-privacy.md](../data-privacy.md) — domain-wide privacy posture  

---

## Change Log

| Date       | Author                              | Change        |
| ---------- | ----------------------------------- | ------------- |
| 2026-04-07 | AR Email Management Architecture Team | Initial draft |
| 2026-04-09 | AR Email Management Architecture Team | Status updated to Accepted — Presidio integration, `PII_RESPONSE_LEVEL`, and all config flags fully implemented in `outlook-mcp-server` (`pii/redactor.py`, `config.py`) |

---

*Part of the AR Email Management Domain — Financial System Modernization Project*
