# SM Bean: CTO handoff for reliable agency automation

Updated 12 October 2026, Asia/Kolkata. Repository: `calander-9-`; baseline main `05ca828`; local branch `codex/openrouter-agency-readiness`.

The product prepares brand content for human review, then delivers the approved content at the approved time. Agents cannot approve publication, schedule unapproved content, reconcile an uncertain delivery or send inbox replies. **Confirm brief & create draft** starts creative work. **Approve & schedule** authorizes delivery of the finished revision; ordinary **Approve** alone leaves it unscheduled.

**Deployment and the real-provider pilot remain unverified.** Railway credentials and an authenticated production session are unavailable. Read-only production probes returned proxy errors, which do not establish that production is down. No actual production post was approved, scheduled or published during this work. Local model, website, channel and publishing tests use controlled substitutes; they do not prove provider credits, permissions, account identity, premium graphics or real delivery.

Read [Implementation status](CTO_IMPLEMENTATION_STATUS.md) for all 15 critical-review findings, [Guided post creation](GUIDED_POST_CREATION.md) for staff operations and [Neopolis launch audit](NEOPOLIS_LAUNCH_AUDIT.md) for backend evidence. The 11 October handover's release/check counts are historical, not the final validation result for this implementation.

## Prepared implementation

- The overview's **Start guided post** action and the legacy creation handler enter the same conversation. Focused questions, source evidence and a scoped human brief confirmation precede draft work.
- **Verified facts** records claim category, source URL/note, verifier, verification time and expiry. A usable claim requires a current permitted human verifier and a current expiry. Legacy brand facts remain unverified background notes; they are not silently attested or used as authoritative commercial claims.
- Photo provenance distinguishes an owner-attested project photo, an unverified image and an illustrative image. Attestations bind the current file/version identity and named project. Generated pictures remain illustrative. The image actually used determines a code-owned AI-generated or unverified-photo caption disclosure, included in full, shortened and channel-specific text before final review. A changed source, file, photo attestation or draft revision requires fresh source review; an attestation is a person's claim, not independent verification of the property.
- Staff can replace or clear a photo and choose brand/fresh style for a revision. The updated choice is stored and acknowledged. Final per-account captions/comments and the graphic undergo exact-payload review; essential text loss blocks handoff. Revision still requires human publication approval.
- Task-specific durable heartbeats distinguish successful publisher, agency and confirmation processing from task registration. Readiness separately exposes saved configuration, blockers, failed work and observed processing. It explicitly leaves live identity, permissions, credits and public media access to the pilot.
- Same-thread receipts show each destination, revision, posting time, delivery state and available native ID/link. **Delivery outcome unknown** and **Expired — needs review** are distinct holds. Human recovery is bound to the exact attempt and content. Parent-post hold records prevent editing or removing/readding a destination from silently bypassing an unresolved attempt.
- Delivery lateness is configurable. The default is 24 hours; the supported range is one minute to seven days. Expired delivery returns through human account inspection and fresh review, not an automatic resend. “Publish now” acknowledges queueing rather than promising a one-minute delivery.
- Autopilot settings include a lead and a different backup. Approval checks run every 15 minutes, alert the lead within one hour of the proposed deadline and the backup within 30 minutes, and escalate overdue review. Alerts respect current roles, preferences, deduplication and a shared per-user daily cap; registration alone does not prove live receipt.
- Reports freeze period counts and separately labeled current backlog. Missing analytics, immature posts, insufficient history and a zero baseline receive distinct explanations. Budget/provider failures leave a useful recorded-count report. Creative rankings require successful metrics captured within seven days and at least five measured posts on the same account; chosen designer references remain available.
- **Outcomes** records manual campaign/date/event totals for enquiries, qualified enquiries and completed site visits, optionally linked to scoped approved/published content. There are no personal lead-data fields. Writes require a current authorized human and repeat submissions are idempotent. These are events, not unique people, inferred attribution or automatic conversion rates.
- Usage retains validated provider-reported model cost where available and estimates otherwise, including failures. The monthly budget is a soft threshold with no in-flight reservation or hard invoice ceiling. Pricing, privacy and support now describe model/image/platform charges, processor uncertainty and deadline ownership explicitly.

This update adds schema migrations for claim/outcome records, photo attestations, backup/source review, task heartbeats and durable delivery holds. Apply every migration in the reviewed cumulative implementation. The earlier 11 October bundle does not by itself contain the 12 October product changes.

## Production activation

Use OpenRouter with its own key and configuration; an OpenRouter key does not belong in `ANTHROPIC_API_KEY`. Keep credentials in Railway's secure variable editor and out of issues, documents, commits and logs. The supplied key's validity, balance and model access have not been established by this review.

| Action | Owner | Required evidence |
|---|---|---|
| Review the final cumulative implementation and validation record; deploy the same reviewed code to `sm-bean` and `sm-bean-worker`, then apply all migrations. | CTO | Both services identify the reviewed commit; migrations and startup checks complete. |
| On both services set `STUDIO_PROVIDER=openrouter`, securely set `OPENROUTER_API_KEY`, use an available namespaced `STUDIO_MODEL` such as `anthropic/claude-sonnet-4.5`, and keep `STUDIO_WEB_SEARCH=false`. | CTO | A real structured agent answer and visual role succeed; record model, usage and provider cost. This proposed model must be confirmed as supported by the account. OpenRouter web research remains disabled. |
| Check model credits, routing/retention/training settings and image-service access. Supply verified photos or configure `FAL_KEY` for generated illustrations. | CTO / privacy owner | Active processors/settings are documented; an approved sample graphic or explicit fallback appears; charges match provider records. |
| Drain the baseline worker before the first singleton-lease deployment; reserve one extra PostgreSQL connection for its lease. Start one worker replica with `python manage.py run_worker` and the intended restart policy. | CTO | Task-specific publisher/agency/confirmation success advances, restart/overlap checks pass and an actual agency job completes. Multi-worker operation needs a separate validated plan. |
| Inspect the native identities of the selected brand accounts. Neopolis Facebook's documented Graph Page ID is `585141221346435`; the expected Instagram handle is `@neopolis_infra`. Verify the actual Instagram ID and permissions. Recheck the reported More Space `@morespace.ai` versus intended `@morespacehyd` mismatch. | Account owner | A live read-only account inspection matches the intended brand, followed by one approved real publication. Saved metadata and source scraping alone are insufficient. |
| Enter current claims under **Verified facts** with source and sensible expiry; attest authentic project assets to the exact file/project. | Brand owner / internal approver | Current price, availability, title/registration, launch and contact claims have an accountable verifier. Expired/changed claims and changed files block stale review. Historical default claims are not automatically approved. |
| Configure autopilot accounts, volume, pillars, planning time, budget, lead, backup and acceptable maximum delivery delay; use `Asia/Kolkata`. | Workspace owner | A weekly plan produces the requested volume or an explicit shortfall; drafts remain unapproved; lead/backup receive deadline notices. The On badge is a saved setting, not certification of automation. |
| Review queued approvals affected by the native-destination fingerprint change, including the two unapproved posts from 8 October. Choose current content and fresh future times. | Human approver | Fresh exact-content/destination/time approvals exist. Never bulk-restamp old approvals or approve an expired offer simply to clear a backlog. |
| Pilot the account-inspection recovery controls and the actual notification channel. | CTO + approver | Unknown delivery stays held; a person records an existing post or returns checked-absent content for fresh approval. No duplicate send occurs. A notification actually reaches the lead and backup. |

Historical approval links:

- [Neopolis approvals](https://sm-bean-production-eb50.up.railway.app/workspace/b1cb458c-cfaf-43cf-8e23-f5e18a9717c7/calendar/?mode=list&tab=approvals)
- [More Space approvals](https://sm-bean-production-eb50.up.railway.app/workspace/69b2cd29-340b-48af-8e3c-5fa6bd2e31de/calendar/?mode=list&tab=approvals)

## Controlled live pilot

1. A new operator follows the activation checklist: current verified facts, correct account, confirmed creative brief, human review, then actual native delivery. A vague request asks questions without starting the paid creative pipeline.
2. Run one educational, one authentic project/site-visit and one listing campaign. Check the exact copy, imagery, mobile layout and practical CTA against the designer's approved best work. Approve aesthetics as a person; renderer tests do not establish “perfect graphics.”
3. Change photo A to photo B and request a fresh layout in the same thread. Verify the stored replacement, acknowledgement, new revision and withdrawn approval. Check disclosure, selected draft, focus, reading position and photo upload in a real phone/keyboard session.
4. Leave a draft unapproved across its proposed time: it stays unsent. A person then checks the final destinations/content/time and uses **Approve & schedule**. Confirm the actual native ID/link and intended account exactly once.
5. Observe failure and recovery using a safe test configuration. An unknown outcome requires account inspection; an expired time requires review and a new future approval. A human-recorded receipt is labeled as such and is not an independent provider lookup. Editing content or destination rows must not clear the durable hold.
6. Verify live lead/backup reminders, failure alerts and task-specific processing after restart. Reports must show missed/held work and old backlog without rewriting historical period counts. Record a consented test enquiry from the existing inbox/CRM workflow under Outcomes; identify attribution as supplied by the person.
7. Compare recorded/estimated AI usage with actual model/image/platform charges. Agree acceptable delay and fallback coverage before time-sensitive campaigns or paid-service commitments.

A nonpreemptive model/image call can occupy the worker; priority and elapsed-time checks do not guarantee a strict delivery deadline. Use supervised monitoring during the pilot and isolate/cancel model work under a tested design before promising a hard latency SLA. The configured lateness limit is a hold policy, not an on-time delivery guarantee.

## Remaining operating and product limits

- Failed paid stages still need safe operator inspection/retry when bounded recovery is exhausted. Confirm once-only recovery and real alert receipt after deployment.
- A hard spending ceiling would require reservation/reconciliation of concurrent and unreported charges. Current pricing promises a soft limit and separate external billing.
- Manual Outcomes is a compact aggregate ledger, not a CRM, unique-person funnel or automatic WhatsApp/website attribution system. Agree the campaign/source attribution procedure with the sales team.
- Old status histories are not fully reconstructable. Reports identify period events and the observation time of current status/backlog; older reports without those snapshots do not fabricate new history.
- Privacy copy does not certify provider terms, cross-border arrangements, retention or training policies. The operator must validate the active configuration for client work.
- Verified claim records, prompts and source guards do not prove every free-text statement true. Without current claims the prompts ask the owner; human factual review remains essential.
- Verify expired client-link re-entry, actual email delivery and the manual posting fallback. Early-access support is not a guaranteed emergency campaign-monitoring service.
- X needs credentials and paid API credits; LinkedIn Company Pages need the approved app/product/admin flow. Code support is separate from this workspace's live permissions. Optional channels do not replace the Neopolis Meta pilot.
- Meta webhooks improve inbox latency; polling remains a backstop. Blog publication needs website-repository/deploy access and a live canonical page/sitemap check. Search Console and IndexNow remain optional for the social pilot; indexing itself is an external outcome. Existing Search Console data older than 490 days is pruned.
- `release --verify` still requires interpretation: fixture checks and readiness are not a paid-provider/live-campaign acceptance gate. Do not equate successful deployment, task registration or saved configuration with verified production operation.

## Final validation record

Final 12 October validation: **3,854 passed, 1 skipped** in **460.49 seconds** on Python 3.12.14, Django 5.2.17 and PostgreSQL 16. The skip is the Redis-only cache assertion under local-memory test settings. CI-pinned Ruff lint/format, mypy, Django system checks, migration drift and the CSS build passed. Separately, all 30 DOM checks, 24 Chromium interaction checks and seven actual guided Django browser-flow checks passed. Focused runs overlap the repository total and are not added to it.

The prepared regressions cover guided intake, changed source/photo/style choices, claim/photo expiry and identity, human approval, receipts/holds, worker health, deadline reminders, costs, reporting, freshness, outcomes and activation. They use local controlled providers and do not establish live credit balance, account permissions, durable Railway processing, premium generated images or actual social delivery. No production credentials, settings, workspaces or posts were changed during this work.
