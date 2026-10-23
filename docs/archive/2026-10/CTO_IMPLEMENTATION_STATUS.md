# SM Bean: status of the 15 critical user-review findings

Updated 12 October 2026, Asia/Kolkata. Repository: `calander-9-`; baseline main `05ca828`; prepared local branch `codex/openrouter-agency-readiness`.

The critical review in `agency-deliverables/SM_BEAN_CRITICAL_USER_REVIEW.md` records the problems found before this follow-up implementation. This document maps those same 15 findings to the resulting behavior. **The implementation is prepared locally; deployment and the real-provider Neopolis pilot remain unverified.** Railway credentials and an authenticated production session are unavailable. No actual production post was approved, scheduled or published during this work.

Automatic preparation still ends at human review. Brief/source confirmation authorizes draft preparation; it does not approve publication. A human approves the final revision, native destination and time. Agents cannot approve, schedule unapproved content, reconcile delivery or send inbox replies.

Final 12 October validation: **3,854 passed, 1 skipped** in **460.49 seconds** on Python 3.12.14, Django 5.2.17 and PostgreSQL 16. The skip is the Redis-only cache assertion under local-memory test settings. CI-pinned Ruff lint/format, mypy, Django system checks, migration drift and the CSS build passed. Separately, all 30 DOM checks, 24 Chromium interaction checks and seven actual guided Django browser-flow checks passed. See the updated [Neopolis audit](NEOPOLIS_LAUNCH_AUDIT.md) and `CTO_VALIDATION.json` in the handoff. Controlled tests do not establish provider credits, permissions, premium aesthetics or real delivery.

## Findings and implementation

### 1. Main creation action bypassed the conversation — P1

**Prepared:** Agency home now starts guided creation. The compatibility creation handler enters that conversation as well. The account manager gathers missing information, shows a scoped source-backed brief and waits for explicit human confirmation before the creative pipeline starts. Autopilot is a separately configured planning workflow; its finished drafts still require human publication approval.

**Code:** [Agency home](../../../templates/studio/index.html), [creation handler](../../../apps/studio/views.py) `create`, [guided intake and confirmation](../../../apps/studio/jobtypes/chat.py) `_intake` / `_confirm`.

**Live acceptance:** A new operator starts from home, gives a vague site-visit request, answers focused questions and sees the correct account and source warnings before confirming. Creative generation does not start merely because the model suggests a brief or the person says an ordinary “yes.”

### 2. Photo and style revision choices were not applied — P1

**Prepared:** A revision can keep, clear or replace the supplied photo and choose brand/fresh style. These choices are persisted with the new revision and acknowledged in the conversation. A request for a new generated image can clear an old supplied photo. Changed content withdraws its review; locked delivery requires the appropriate withdrawal/reconciliation workflow first.

**Code:** [revision controls](../../../templates/studio/partials/thread.html), [chat revision](../../../apps/studio/jobtypes/chat.py) `_revise`, [revision services](../../../apps/studio/services.py) `_revision_choices` / `request_changes` / `new_angles`.

**Live acceptance:** Replace actual project photo A with photo B, request a fresh layout and inspect the new stored selection, resulting graphic, acknowledgement and fresh approval requirement on a phone as well as desktop.

### 3. Generated imagery could be mistaken for an authentic property photo — P1

**Prepared:** Photo provenance distinguishes illustrative, unverified and human-attested project imagery. A project attestation binds the named project and current file/version identity to a currently permitted verifier. Generated images remain illustrative. The render stage chooses a code-owned caption note from the image actually used: AI-generated or unverified-photo disclosure is carried into full, shortened and channel-specific delivery text before final review. A currently attested authentic photo or no picture has no such note.

**Code:** [photo provenance](../../../apps/studio/trust.py) `asset_stamp` / `photo_status`, [verification UI](../../../apps/studio/views_trust.py), [asset fields](../../../apps/media_library/models.py), [render and delivery text](../../../apps/studio/pipeline.py) `step_render` / `_with_visual_note`.

**Live acceptance:** The brand owner checks the original project image and attestation. Replacing the file invalidates old review. Inspect the final native caption and graphic: generated or unverified imagery must retain its disclosure. An owner's attestation is not an independent property verification.

### 4. Scraping and one checkbox did not establish current commercial facts — P1

**Prepared:** Verified facts now record a category, claim, source URL/note, verifier, verification time and expiry. Claims require a current active verifier with current organization/workspace authority; expired, revoked or changed evidence invalidates stale source review. Legacy brand facts remain unverified background notes. Fresh website/channel excerpts remain untrusted evidence rather than automatically verified claims. Prompts ask the owner when current commercial evidence is absent.

**Code:** [claim records](../../../apps/studio/models.py) `BrandClaim`, [claim authority and snapshots](../../../apps/studio/trust.py) `current_claims` / `verification_people` / `capture` / `blocker`, [source collector](../../../apps/studio/creative_sources.py), [brand prompts](../../../apps/studio/prompts.py), [prepublish source guard](../../../apps/approvals/gate.py).

**Live acceptance:** A permitted owner verifies actual price, availability, registration/title, dates and contact claims with a source and sensible expiry. Changed/expired claims stop stale approval/delivery. Humans must still check the final copy: this is not a deterministic semantic checker that proves every free-text claim true.

### 5. Timing language exceeded the architecture's guarantee — P1

**Prepared:** “Publish now” acknowledges queueing rather than promising a one-minute delivery. Maximum lateness defaults to 24 hours and is configurable from one minute to seven days. Expired content is held for review and a new future approval. Task priority and elapsed-time checks improve handling, but a nonpreemptive model/image call can still occupy the worker.

**Code:** [approval message](../../../apps/studio/services.py) `approve`, [lateness and expiry](../../../apps/publisher/delivery.py), [autopilot delay setting](../../../apps/studio/forms_agency.py), [publisher](../../../apps/publisher/engine.py).

**Live acceptance:** Measure actual delivery delay under the intended worker load; agree the acceptable campaign delay. Inspect the 8 October backlog using current facts and future times. A hold policy is not an on-time delivery SLA; strict deadlines need a separately tested execution/cancellation design.

### 6. The conversation lacked a complete and safe delivery receipt — P1

**Prepared:** Receipts show per-account revision, destination, scheduled/recorded time, state and available native ID/link. Unknown and expired outcomes have distinct human recovery controls, bound to the exact attempt/content. Parent-post durable holds resist editing and removing/readding destination rows. Existing-post reconciliation records a human's account inspection without sending; checked-absent recovery returns content for fresh human review and approval.

**Code:** [receipt builder](../../../apps/studio/chat.py) `_publication_receipts`, [receipt UI](../../../templates/studio/partials/thread_receipts.html), [attempt/parent holds and recovery](../../../apps/publisher/delivery.py), [human POST endpoints](../../../apps/publisher/views_delivery.py), [post hold field](../../../apps/composer/models.py).

**Live acceptance:** An approved post produces the intended native receipt exactly once. A safe failure rehearsal keeps unknown delivery held until account inspection. Human-recorded existing-post receipts are explicitly labeled; they are not independently provider-confirmed. A changed account, stale form or ordinary edit must not release a hold.

### 7. Green configuration did not prove healthy automation — P1

**Prepared:** Readiness separates blockers, saved configuration, failed work and observed processing. Durable heartbeats track successful publisher, agency and confirmation tasks individually. Default release verification remains informational; optional strict commands require critical checks and recent recorded model/delivery evidence. A human-attested receipt can satisfy recorded evidence, so operators must inspect its verification type and native account/link.

**Code:** [operational readiness](../../../apps/studio/readiness.py), [task-specific heartbeat and worker lease](../../../apps/common/background.py), [verification command](../../../apps/common/management/commands/live_verify.py), [release options](../../../apps/common/management/commands/release.py).

**Live acceptance:** Both services identify the reviewed commit, all migrations are applied and each expected task advances after restart. Observe an actual model-generated draft and human-approved delivery to the verified account. Saved settings, recurring task registration, fixture checks and key presence alone do not pass this gate.

### 8. Budget and pricing could imply an invoice ceiling — P1

**Prepared:** Validated provider-reported model costs are retained where available; estimates remain explicit otherwise, including recorded failed work. Spend displays retain cents. The monthly threshold is described as soft, with no reservation for concurrent/in-flight charges. Pricing identifies Agency Studio and Intelligence model costs, image costs, hosting and optional platform API charges without inventing new commercial terms.

**Code:** [usage cost handling](../../../apps/studio/llm.py) `validated_provider_cost` / `cost_for_run`, [soft budget](../../../apps/studio/budget.py), [spend display](../../../templates/studio/index.html), [pricing](../../../templates/pricing.html).

**Live acceptance:** Compare a small pilot's recorded/estimated usage with actual model and image invoices. Confirm credits and billing ownership. A hard spending ceiling remains unimplemented; it would require charge reservation and reconciliation, including unreported external charges.

### 9. A quiet report could hide failure and old approval backlog — P1

**Prepared:** Reports include requested, prepared, awaiting approval, approved/unscheduled, scheduled, published, failed and blocked counts. Period counts and their observation time are preserved; separately labeled current backlog includes older work. Failures, backlog and manual outcomes prevent an empty reassuring report. Missing results distinguish unavailable metrics, immature posts, insufficient measured history and zero baselines. Provider/budget failures preserve a recorded-count report.

**Code:** [report facts and fallbacks](../../../apps/studio/jobtypes/report.py) `operational_counts` / `current_backlog` / `performance_note` / `counts_report`, [report context](../../../apps/studio/reports.py), [report UI](../../../templates/studio/partials/report_card.html).

**Live acceptance:** A deliberately missed/held campaign appears with its next operating action; an old approval backlog appears separately from the requested historical period. Compare published counts with native receipts. Old state history is not fully reconstructable; reports identify current observations rather than inventing historical funnel transitions.

### 10. Human approval lacked deadline-aware backup coverage — P1 operations

**Prepared:** Autopilot stores a lead and a different eligible backup. Checks run every 15 minutes, notify the lead within one hour of the proposed deadline and the backup within 30 minutes, and escalate overdue review. Current roles/preferences, deduplication and a shared per-user daily cap govern notifications. Lead eligibility uses the current permitted verification/approval population.

**Code:** [coverage settings](../../../apps/studio/models.py) `AgencySettings`, [eligible leads and settings](../../../apps/studio/forms_agency.py), [deadline reminders](../../../apps/approvals/tasks.py), [trustworthy eligibility](../../../apps/studio/trust.py) `verification_people`.

**Live acceptance:** Lead and backup actually receive the chosen notification channel during a controlled deadline test; removing a role stops access/notifications. Agree the manual fallback and operator retry procedure. A saved backup or registered reminder does not establish availability or live receipt, and bounded paid-stage recovery is not universal automatic repair.

### 11. Privacy omitted model/image processors and overstated certainty — P1

**Prepared:** Privacy describes configured model/image processor use and conditional routing, rather than a blanket no-training/compliance guarantee. Pricing and support state the early-access operating responsibilities. Disclosure does not establish the active account's retention, training or cross-border arrangements.

**Code:** [privacy](../../../templates/legal/privacy.html), [support](../../../templates/legal/support.html), [pricing](../../../templates/pricing.html).

**Live acceptance:** The operator documents the active OpenRouter/model/image/storage routing and relevant provider policies/settings, and obtains the agency's approval for client work. Check that the published copy matches those settings before external customers rely on it.

### 12. “Perfect graphics” lacked real visual evidence — P2

**Prepared controls; aesthetic acceptance remains open:** Prompts use brand direction and curated references, distinguish authentic imagery from illustration and request crop-safe composition. Rendered typography, bounded image decoding and exact final-payload review block essential text loss. Supplied-photo/background fallback is explicit. These safeguards improve preparation; they do not prove premium design or named-property truth.

**Code:** [art direction](../../../apps/studio/prompts.py), [graphic pipeline and review](../../../apps/studio/pipeline.py), [image handling](../../../apps/studio/images.py), [curated memory](../../../apps/studio/memory.py).

**Live acceptance:** The owner/designer signs off three authentic campaign samples: project/site visit, education and listing. Each needs a specific hook, practical CTA, accurate imagery and readable intended platform variants. Compare with approved designer work on a phone. The synthetic renderer example is not a paid model sample or an actual project photograph.

### 13. Thread state and mobile accessibility needed a complete walkthrough — P2

**Prepared:** The thread script preserves applicable draft selection, revision and reading/form state during panel updates, while invalidating stale decisions when their source/draft changes. Backend/template/state regressions are available; the final validation record determines their result.

**Code:** [thread state script](../../../static/js/agency-thread.js), [thread controls](../../../templates/studio/partials/thread.html), [polling messages](../../../templates/studio/partials/thread_messages.html), [confirmation form](../../../templates/studio/partials/thread_creative_brief.html).

**Live acceptance:** Complete the authenticated phone/keyboard journey: focused answers, photo upload, source disclosure/inspection, brief confirmation, multi-draft selection, photo/style revision and final approval. Local state tests do not prove production browser, touch or assistive-technology behavior.

### 14. First campaign value and qualified outcomes were unclear — P2

**Prepared:** Onboarding leads through verified facts, a healthy selected account, a confirmed brief, human review and a recorded actual publication. Outcomes adds a compact manual aggregate ledger for enquiries, qualified enquiries and site visits by campaign/date, optionally linked to scoped approved/published content. It has no personal lead-data fields; current authorized human writes are tenant-scoped and repeat submissions are idempotent. Reports include these explicitly manual totals.

**Code:** [activation checklist](../../../apps/onboarding/checklist.py), [outcome records](../../../apps/studio/models.py) `CampaignOutcome`, [permissions/idempotency/totals](../../../apps/studio/outcomes.py), [Outcomes UI](../../../templates/studio/outcomes.html), [report integration](../../../apps/studio/jobtypes/report.py).

**Live acceptance:** A new operator delivers one useful approved campaign. A consented test enquiry reaches the intended sales owner through the existing inbox/CRM procedure and is manually recorded with agreed attribution. Record review time, revision count, delivery delay and qualified events before making savings/lead promises. This is not a new CRM, automatic attribution, unique-person funnel or ROI guarantee.

### 15. Creative memory and platform scope lacked honest evidence labels — P2

**Prepared:** Measured winners require successful metric captures within seven days, at least five measured posts on the same account and post maturity of at least three days. Stale metric rankings are excluded/reset without deleting designer-selected references. Memory separates chosen inspiration from measured evidence and shows freshness/limitations. Readiness describes saved account configuration separately from live permissions; platform copy distinguishes supported code from workspace setup.

**Code:** [fresh metric reader](../../../apps/studio/performance.py), [measured versus reference memory](../../../apps/studio/memory.py), [freshness cleanup](../../../apps/studio/jobtypes/learn.py), [memory UI](../../../templates/studio/memory.html), [account readiness](../../../apps/studio/readiness.py), [platform pricing explanation](../../../templates/pricing.html).

**Live acceptance:** Verify actual metric capture times and mature same-account history before using a winner claim. Mark designer references explicitly. Focus the first live pilot on Neopolis Meta; X credits, LinkedIn app approval and other network permissions remain separate setup/acceptance gates.

## Release and remaining live gates

Use [CTO readiness](CTO_AGENCY_READINESS.md) for the owner/action/evidence checklist, [guided creation](GUIDED_POST_CREATION.md) for staff operations and [live operations](../../LIVE_OPERATIONS.md) for opt-in strict verification and safe rollout/rollback.

1. Review the cumulative implementation and final root validation record, deploy the same reviewed commit to both services and apply all new migrations. Drain the old worker before the first singleton-lease rollout and reserve its extra PostgreSQL connection. Obtain fresh human approvals where destination/source fingerprints changed.
2. Configure OpenRouter securely on both services; verify the chosen model, structured/visual roles, credits and actual charges. Validate the image service or use owner-attested project assets. No live paid call has been made by this work.
3. Verify native brand identities and permissions, including the reported More Space Instagram mismatch. Website/channel evidence, saved metadata and release fixtures do not certify the destination.
4. Run the supervised Neopolis pilot: correct facts/assets, confirmed draft, authentic graphic review, unapproved-unsent check, one human-approved actual publication and native account inspection. Unknown/expired recovery must hold without duplicate sending.
5. Demonstrate live lead/backup alerts, task-specific processing/restart, historical-period/current-backlog reporting, consented sales handoff and manual outcome recording. Check the phone/keyboard workflow and actual invoices.

Passing optional strict verification means its selected recorded checks passed. It does not independently authenticate a human-attested receipt, certify premium graphics, establish a delivery SLA or replace the live pilot. Keep approval enforcement and unresolved durable holds during recovery or rollback. Wider commercial launch remains conditional on the external evidence above and on accurate pricing, privacy and support commitments.
