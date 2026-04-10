# ADR-002: Human-in-the-Loop Design

**Status:** Proposed
**Date:** 2026-03-31
**Decision Makers:** AR Email Management Architecture Team
**Technical Story:** Every AI-generated action in the AR email pipeline must be approved by a human before execution. Need to design the approval workflow that balances efficiency with oversight.

---

## Context and Problem Statement

The AR Email Management solution uses AI agents to classify emails, draft responses, and route actions. However, given the financial nature of AR communications (disputes, payment commitments, legal escalations), no AI-generated output should be sent to customers or trigger SAP actions without explicit human approval. This is both a business requirement (fiduciary responsibility) and a regulatory consideration (financial communications carry legal weight).

The approval workflow must support two integration paths: Alevate (interactive UI for AR specialists who process email queues throughout the day) and SAP (headless integration where approvals happen within SAP's own workflow interface). The workflow must handle varying urgency levels -- a legal escalation needs faster attention than a routine payment reminder acknowledgment.

A key technical constraint is that CodeMie workflows support a PAUSED state, where workflow execution halts at a designated step and resumes only when an external signal (API call) provides the approval decision. This mechanism is the natural integration point for human-in-the-loop, but the UX pattern around it (how humans interact with the paused workflow) is the subject of this decision.

## Decision Drivers

- **Efficiency**: AR specialists process hundreds of emails per day; the approval UX must enable batch processing, not one-at-a-time review
- **Urgency Routing**: Disputes and legal escalations must surface above routine items; time-sensitive items cannot be buried in a FIFO queue
- **Dual-Path Support**: Must work for both Alevate UI users and SAP headless users with consistent behavior
- **Audit Trail**: Every approval/rejection/edit must be logged with user identity, timestamp, and action taken
- **Timeout Handling**: Items that sit unreviewed must escalate, not silently expire
- **Edit Capability**: Approvers must be able to modify AI-generated drafts before sending, not just approve/reject

---

## Considered Options

### Option 1: Batch Queue with Priority Escalation (Recommended)

**Description:** AI pipeline outputs (classified email + drafted response + suggested action) are queued in an approval dashboard. AR specialists review items from the queue, sorted by priority. They can approve, edit-then-approve, or reject each item. Priority escalation moves urgent items (disputes, legal) to the top. The queue integrates with CodeMie's workflow PAUSED state: each queued item corresponds to a paused workflow execution that resumes on approval.

**Pros:**
- ✅ Efficient batch processing: specialists review 3-5x more items per hour than inline review
- ✅ Priority routing ensures disputes and legal escalations get immediate attention
- ✅ Uses existing CodeMie workflow PAUSED/resume mechanism (no custom orchestration)
- ✅ Works for both Alevate (visual queue) and SAP (API-driven queue with SAP workflow task)
- ✅ Edit capability: approver can modify drafted response before approval
- ✅ Full audit trail: approval actions logged against workflow execution ID

**Cons:**
- ❌ Context switch: reviewer sees the queue item, then must open the original email thread for full context
- ❌ Requires building approval dashboard UI in Alevate (or surfacing queue in SAP task list)
- ❌ Queue backlog risk during high-volume periods or staff absence

**Cost:** Dashboard development: included in Alevate UI sprint. SAP integration: 2-3 weeks for task list adapter.

---

### Option 2: Inline Review (In-Email)

**Description:** AI draft is shown as a sidebar or overlay panel next to the original email in Outlook. The AR specialist reviews the draft in the context of the email thread and approves/rejects directly from within the email client.

**Pros:**
- ✅ Full email context immediately available (no context switching)
- ✅ Natural workflow for AR specialists who live in Outlook
- ✅ Minimal training required; feels like a native Outlook feature

**Cons:**
- ❌ Requires developing and maintaining an Outlook add-in (Office JS / Add-in framework)
- ❌ Only works in Outlook; SAP users have no email client to embed into
- ❌ Harder to batch process: reviewing one email at a time
- ❌ Outlook add-in distribution requires IT admin consent and deployment via Microsoft 365 admin center
- ❌ Priority escalation not natural in an inbox view (relies on email flags or categories)

**Cost:** Outlook add-in development: 4-6 weeks. Ongoing maintenance: compatibility with Outlook updates.

---

### Option 3: Notification-Based (Async)

**Description:** When the AI pipeline completes, a notification is sent to the AR specialist via email or Microsoft Teams message. The notification includes the AI draft and an approve/reject action link. Clicking the link triggers the approval via API.

**Pros:**
- ✅ No UI development needed; leverages existing communication channels
- ✅ Works on mobile devices (Teams mobile app)
- ✅ Low implementation effort

**Cons:**
- ❌ Approval link security concerns: deep links with tokens are vulnerable to forwarding/phishing
- ❌ No edit capability without opening a separate UI
- ❌ Notifications can be missed, buried in inbox, or accidentally dismissed
- ❌ Audit trail harder to maintain (link clicks vs. authenticated API calls)
- ❌ No batch processing; each notification is a separate context switch
- ❌ SAP integration unclear (Teams notifications do not map to SAP workflow tasks)

**Cost:** Minimal development cost (~1 week), but security hardening adds 2-3 weeks.

---

## Options Comparison Table

| Criteria | Batch Queue (Priority) | Inline Review (Outlook) | Notification-Based (Async) |
|---|---|---|---|
| Batch efficiency | High (3-5x throughput) | Low (one at a time) | Low (one at a time) |
| Context availability | Medium (requires click-through) | High (email visible) | Low (summary only) |
| Alevate support | Native (dashboard) | No (Outlook only) | Partial (email/Teams) |
| SAP support | Native (task list API) | No | Unclear |
| Edit capability | Yes (in dashboard) | Yes (in sidebar) | No (approve/reject only) |
| Priority escalation | Built-in (queue sorting) | Manual (flags) | Manual (notification urgency) |
| Audit trail | Strong (workflow-linked) | Strong | Weak (link-based) |
| Development effort | Medium (3-4 weeks) | High (4-6 weeks) | Low + security (3-4 weeks) |
| Timeout/escalation | Built-in (queue monitoring) | Manual | Manual |

---

## Decision Outcome

**Chosen Option:** Option 1 - Batch Queue with Priority Escalation

### Rationale

1. **Dual-path support**: The batch queue model works for both Alevate (visual dashboard) and SAP (API-driven task queue). Inline review (Option 2) only works in Outlook, excluding SAP users entirely. This is a disqualifying constraint.
2. **Batch efficiency**: AR specialists process hundreds of emails per day. A queue model with keyboard shortcuts and bulk actions enables 3-5x higher throughput than reviewing one email at a time.
3. **Priority escalation**: Disputes and legal escalations have time-sensitive SLAs. A queue with priority sorting ensures these items are always visible at the top, rather than buried in chronological order.
4. **CodeMie integration**: The PAUSED workflow state maps directly to a queue item. Approval resumes the workflow; rejection terminates it. No custom orchestration layer is needed.
5. **Context tradeoff accepted**: The context switch (queue item to email thread) is mitigated by including the AI-generated thread summary and the last 3 emails directly in the queue item detail view.

### Implementation Summary

**Queue Structure:**
- Each queue item contains: workflow execution ID, email metadata, classification result, AI-drafted response, suggested action, priority level, creation timestamp, timeout deadline
- Priority levels: CRITICAL (disputes, legal - 30min timeout), HIGH (payment promises, escalations - 2hr timeout), STANDARD (all others - 4hr timeout)
- Timeout behavior: auto-escalate to supervisor queue (never auto-approve)

**Approval Actions:**
- **Approve**: Resume workflow with `APPROVED` status; AI draft is sent as-is
- **Edit + Approve**: Approver modifies the draft; resume workflow with `APPROVED` status and edited content
- **Reject**: Terminate workflow with `REJECTED` status; email flagged for manual handling
- **Reclassify**: Approver overrides the AI classification; workflow restarts from ResponseDrafter with new category

**Integration Points:**
- Alevate: Visual dashboard with queue table, detail panel, keyboard shortcuts (A=approve, E=edit, R=reject)
- SAP: Queue exposed as SAP Workflow tasks via REST API; approval/rejection actions via SAP task completion

---

## Consequences

### Positive

✅ Consistent approval workflow across both Alevate and SAP integration paths
✅ Priority escalation ensures time-sensitive items (disputes, legal) are never missed
✅ Batch processing capability enables AR specialists to handle high email volumes efficiently
✅ Full audit trail linking every approval decision to a user identity, timestamp, and workflow execution
✅ Timeout escalation prevents items from silently expiring in the queue

### Negative

❌ Context switching between queue view and full email thread adds cognitive overhead for reviewers
❌ Approval dashboard must be built and maintained in Alevate UI
❌ SAP task list adapter requires custom development to map CodeMie queue items to SAP workflow tasks
❌ Queue backlog during staff absence or peak periods requires supervisor monitoring

### Mitigation Strategies

**For context switching:**
- Queue item detail view includes: AI thread summary, last 3 email messages, SAP customer context, and classification confidence score
- One-click "Open in Outlook" link for cases requiring full email thread review
- Preview pane renders email HTML for visual inspection without leaving the queue

**For queue backlog:**
- Real-time queue depth monitoring with alerts when items exceed timeout thresholds
- Automatic escalation to supervisor queue on timeout (never auto-approve, never silently drop)
- Load balancing across AR specialist team via round-robin assignment with manual override

**For SAP integration complexity:**
- SAP task list adapter follows the Headless API Integration Pattern (Multi-Tenancy ADR-020)
- Adapter is stateless: reads queue via CodeMie API, writes approval decisions via CodeMie API

---

## Compliance & Security

**Security Controls:**
- Approval actions require authenticated session (PingOne JWT for Alevate, SAP JWT for SAP path)
- All approval/rejection/edit actions logged with: user ID, timestamp, workflow execution ID, action type, IP address
- Edited drafts stored alongside original AI draft for comparison audit
- No auto-approve under any circumstances; timeout always escalates

**Compliance Impact:**
- GDPR: Approvers see only emails within their assigned AR portfolio; no cross-tenant queue access
- SOC 2: Audit trail satisfies segregation of duties requirements (AI generates, human approves)
- Financial Regulation: Human approval before any customer-facing communication or SAP action satisfies fiduciary duty requirements

---

## Cost Analysis

| Component | Cost | Notes |
|---|---|---|
| Alevate Dashboard UI | $0/month (development cost) | Built into Alevate UI sprint; no separate infrastructure |
| SAP Task List Adapter | $0/month (development cost) | Stateless adapter; runs within existing SAP integration layer |
| Queue Storage (CodeMie) | ~$10-20/month | Workflow execution state stored in CodeMie; minimal incremental cost |
| Monitoring & Alerting | ~$20-30/month | Queue depth, timeout, and SLA monitoring |
| **Total** | **~$30-50/month** | Operational cost only; excludes development effort |

**Comparison:**
- Inline Review (Option 2): ~$100-200/month (Outlook add-in hosting) + higher development cost
- Notification-Based (Option 3): ~$10-20/month but significant security hardening cost
- Batch Queue: Lowest operational cost with best functionality

---

## Related Decisions

- **[ADR-001](ADR-001-email-categorization-approach.md)**: Classification output drives queue item priority (INVOICE_DISPUTE and ESCALATION_LEGAL are CRITICAL priority)
- **[ADR-004](ADR-004-agent-design.md)**: ReviewPresenter agent formats the queue item for display; workflow PAUSED state is the integration point
- **[ADR-005](ADR-005-outlook-integration-pattern.md)**: Graph API Bridge sends the approved response via Graph API after approval
- **[Multi-Tenancy ADR-020](../../multytenancy/decisions/ADR-020-headless-api-integration-pattern.md)**: SAP task list adapter follows the headless API integration pattern

**Dependencies:**
- This decision depends on: ADR-001 (classification drives priority), ADR-004 (workflow PAUSED state)
- This decision enables: ADR-005 (approval triggers email send via Graph API Bridge)

---

## References

- [CodeMie Workflow PAUSED State Documentation](https://docs.codemie.com/workflows/paused-state) (internal)
- [Human-in-the-Loop AI Design Patterns (Google PAIR)](https://pair.withgoogle.com/guidebook/patterns)
- [SAP Workflow API - Task Management](https://help.sap.com/docs/SAP_WORKFLOW)
- [Microsoft Graph API - Send Mail](https://learn.microsoft.com/en-us/graph/api/user-sendmail)

---

## Implementation Checklist

**Phase 1: Queue Backend** (Weeks 1-2)
- [ ] Define queue item data model (workflow ID, email metadata, classification, draft, priority, timeout)
- [ ] Implement priority assignment logic based on email classification category
- [ ] Implement timeout monitoring service with escalation rules
- [ ] Wire CodeMie workflow PAUSED state to queue item creation
- [ ] Wire approval/rejection API to CodeMie workflow resume/terminate

**Phase 2: Alevate Dashboard** (Weeks 3-4)
- [ ] Build queue list view with priority sorting, filtering, and search
- [ ] Build item detail panel with thread summary, email preview, and draft editor
- [ ] Implement approval/edit/reject/reclassify actions with keyboard shortcuts
- [ ] Add real-time queue depth indicator and SLA countdown timers

**Phase 3: SAP Integration** (Weeks 4-5)
- [ ] Build SAP task list adapter (REST API mapping CodeMie queue to SAP workflow tasks)
- [ ] Implement approval/rejection via SAP task completion callbacks
- [ ] Test end-to-end flow: SAP triggers email processing, queue item created, SAP user approves

**Phase 4: Monitoring & Hardening** (Week 6)
- [ ] Deploy queue depth and timeout monitoring dashboards
- [ ] Configure alerting for SLA breaches (items exceeding timeout without action)
- [ ] Load test queue with simulated high-volume periods (500+ items/hour)
- [ ] Document supervisor escalation procedures

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
