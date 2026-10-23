# Neopolis launch audit: local implementation and remaining live gates

Updated 12 October 2026, Asia/Kolkata. Repository baseline: `calander-9-` main `05ca828`; prepared branch: `codex/openrouter-agency-readiness`.

## Launch decision

**The cumulative implementation is prepared locally. Production launch and the real-provider Neopolis pilot remain unverified.** Railway credentials and an authenticated production session are unavailable. No actual production post was approved, scheduled or sent during this work. Controlled source/model/publishing tests and local browser checks do not prove credits, permissions, premium graphics, deployed worker reliability or native delivery.

The final 12 October full repository run passed: **3,854 passed, 1 skipped** in **460.49 seconds** on Python 3.12.14, Django 5.2.17 and PostgreSQL 16. The skip is the Redis-only cache assertion under local-memory test settings. CI-pinned Ruff lint/format, mypy, Django system checks, migration drift and the CSS build passed. Separately, all 30 DOM checks, 24 Chromium interaction checks and seven actual guided Django browser-flow checks passed. The **3,574 passed, 1 skipped** result belongs to the 11 October baseline rehearsal. Final machine-readable evidence is in `CTO_VALIDATION.json` in the handoff.

The product rule remains **automatic generation, human approval, then automatic delivery at the approved time**. Guided-thread brief confirmation authorizes creative preparation. Final **Approve & schedule** authorizes the finished revision, destination and time; **Approve** alone leaves it unscheduled. Agents cannot approve publication, schedule unapproved content, reconcile delivery or send inbox replies.

## What is exercised locally

Neopolis fixtures use the saved brand defaults, `Asia/Kolkata`, documented Facebook Graph Page ID `585141221346435`, the Neopolis website URL and approval enforcement. The expected Instagram handle is `@neopolis_infra`; its actual numeric ID, live permissions and production configuration have not been inspected. Historical commercial defaults are unverified background notes, not current verified claims. The vertical rehearsal uses safe site-visit copy and an explicitly synthetic test photo.

| Area | Local evidence and its boundary |
|---|---|
| Complete post lifecycle | Real intake/job services, PostgreSQL, graphic renderer, human approval views/fingerprints, publisher dispatch/media/payload handling and scoped reporting. External source/model/social boundaries use controlled substitutes. |
| Human and tenant boundaries | Permission revocation, deactivation, cancellation/restart, moved references, disconnected/changed destinations, cross-workspace evidence and concurrent confirmations. Current roles are rechecked before mutation and recovery. |
| Guided entry and revisions | Home/compatibility entry enters the conversation; focused questions precede scoped confirmation. Photo keep/clear/replace and brand/fresh style persist on revision, with human reapproval. |
| Source and property trust | Fresh bounded website/Meta evidence remains untrusted. Structured claims require source, expiry and a current permitted human verifier. File/project photo attestations and generated/unverified caption disclosures are separately tested. Changed/expired evidence blocks stale source review. |
| Automatic planning | Recurring planning, disabled/archived work, recoverable skipped weeks, duplicate claims, requested-volume shortfalls and retained work after re-enable. |
| Worker and delivery recovery | Concurrent stage claims, obsolete revisions, fresh dispatch account checks, post-success persistence failures, durable unknown/expired holds and attempt/content-bound human recovery. |
| Durable processing evidence | Individual publisher, agency and confirmation heartbeats record start/success/failure. A bounded real worker-loop test uses PostgreSQL, the session lease, actual queue polling and real empty task bodies; it has no workspace or billable work. |
| Usage and reporting | Provider-reported/estimated costs, charged failures, cumulative fragments, malformed counters, timezone/tenant scope, soft budgets, period counts, older current backlog and explicit missing-metric reasons. Manual campaign events remain separate from automatic attribution. |
| Final content | Review covers actual outbound channel captions/comments and the graphic. Essential text loss and changed payloads block handoff; actual-used illustrative/unverified-photo notes precede review. |
| Browser behavior | Local Chromium interaction and actual Django guided-flow checks exercise entry, source consent, photo/file controls, state preservation, keyboard behavior and responsive pages. They use isolated data and synthetic callbacks, with external browser requests blocked. |

The successful site-visit rehearsal produced a **1080×1350 JPEG**, passed dashboard approval, assembled the approved Facebook caption/media URL, delivered once through the provider stub and generated a scoped report without More Space campaign content or account credentials. Editing approved content reopened the draft in the same thread, produced a new graphic, withdrew its approval fingerprint and sent only after fresh human approval.

The exported `neopolis-render-rehearsal.jpg` remains a **synthetic renderer example**, not an actual model-generated or owner-supplied brand photograph. It demonstrates type/layout execution, not premium aesthetics or truthful property depiction. Owner/designer acceptance needs actual project/site-visit, educational and listing samples with useful CTAs and phone-readable platform variants.

## Confirmed defects and prepared corrections

The original backend defect table is retained below, followed by the 12 October product corrections. These describe the cumulative local implementation, not deployment claims.

| Trigger and previous failure | Prepared correction |
|---|---|
| Two workers delivered the same active stage; both could make paid calls. A stale failure callback could overwrite a completed/new revision. | Agency/post stages claim only queued work under the row lock. Failure/usage completion is revision-scoped; obsolete queued revisions cannot conceal a stuck current job. |
| Autopilot was disabled after planning, or a prerequisite was restored after a skipped week. Existing briefs still started, or the week never resumed. | Fresh pause checks at planning, feeding and paid-stage boundaries; retained work resumes within bounded batches. Recoverable skipped weeks resume without duplicates. Explicit manual planning remains separate permission to prepare work while recurring autopilot is off. |
| Planning failed after writing some output, concurrent feeders competed, or only some requested drafts finished. | Incomplete parent-plan output cannot start creative work. Feeder claims respect workspace caps. Failed/short weeks show captured requested-versus-ready shortfalls; there is no unlimited paid top-up loop. |
| Membership, user status, budget, workspace status or chat revision changed during a model/source request. | Recheck job revision, active requester, current membership/permissions, eligibility and budget immediately before mutations/replies. Concurrent confirmations create one draft; no external call occurs under the new guard lock. |
| A foreign job could be attached to a visible message, or approval was withdrawn without changing brief state. | Source cards require matching workspace/conversation ownership. A withdrawn draft is naturally revisable when current channels are revisable; still-approved/scheduled work retains the human workflow. |
| A channel editor added a claim or first comment after original brand review. | Review exact final per-account captions/comments and graphic, bound to payload/graphic/revision/account fingerprints. Changed, oversized or unresolved-risk content stays held; correction remains bounded. |
| An approved SocialAccount row pointed to another native destination while its UUID remained unchanged. | Approval covers workspace, platform, native account ID and instance URL. Token refresh/display-name changes retain the native destination; identity changes require human reapproval. |
| A channel disconnected, changed destination or rotated its token after publisher claim. | Fresh destination/account checks precede dispatch. Disconnected/error destinations stay unsent, and rotated credentials are adopted safely. |
| A platform accepted a write but timed out or returned an ambiguous server error; retry could duplicate it. | Ambiguous write outcomes require inspection/reconciliation rather than automatic reupload. Clear pre-connect/rate-limit failures remain bounded retries; known asynchronous IDs remain available for confirmation. |
| Startup cleared locks belonging to a live singleton worker. | A dedicated PostgreSQL session lease precedes reclamation and remains through polling. Duplicate singleton startup fails and lease loss stops polling. `--keep-locks` opts out and requires a separately validated concurrent-worker design. |
| Cost-only failures, cumulative streaming fragments, cache/search-only work or sub-cent spend were lost. | Preserve validated provider-reported USD on successful/failed/stale run ledgers; billed/uncertain-cost failures do not automatically retry. Keep Decimal precision, time/tenant bounds and honest unknown-tariff estimates; reject malformed/extreme counters and credential echoes. |
| Home creation bypassed focused questions/source confirmation, and visible photo/style controls did not apply revisions. | Main and compatibility entry use guided creation. Photo replacement/clearing and brand/fresh direction persist with acknowledgement and fresh review. |
| Historical facts lacked accountable verification/expiry, while generated images could be mistaken for property proof. | Structured claims require current permitted verifier/source/expiry. Snapshots bind evidence and file/project attestations; generated assets remain illustrative. The actual used image determines code-owned AI/unverified-photo disclosure before full/short/channel review. Human factual/aesthetic judgment remains necessary. |
| Generic failure state hid unknown delivery; editing or readding a channel could bypass unresolved state. | Same-thread per-account receipts distinguish unknown and expired outcomes. Attempt/content-bound human actions and durable parent-post holds prevent ordinary edits or row replacement from silently releasing uncertainty. Human existing-post receipts are labeled as attestations, not independent provider checks. |
| Overdue promotions had no lateness policy, and “Publish now” promised a minute. | Queueing language replaces that promise. Default maximum lateness is 24 hours, configurable from one minute to seven days. Expired work requires account inspection, review and a new future approval. This hold policy does not guarantee on-time execution. |
| Generic recent-task completion and saved configuration could imply healthy automation. | Durable task-specific success/failure, readiness blockers and optional strict release checks expose missing processing evidence. Default release checks remain informational; recorded evidence and configuration do not replace a live pilot. |
| Quiet reports hid failures/backlog; stale analytics could still inform creative rankings. | Freeze period counts and separately observed current backlog; retain useful counts on provider/budget failure. Explain missing/young/insufficient/zero metrics separately. Measured evidence requires recent successful captures and mature same-account history; designer references remain separate. |
| Approval coverage, first value, business outcomes and customer expectations were incomplete. | Eligible lead/backup, 15-minute deadline checks, campaign activation milestones and manual no-personal-data outcome totals are implemented. Pricing/privacy/support describe soft costs, processor uncertainty and early-access operating responsibilities without invented guarantees. |

The detailed mapping of all 15 user-review findings is in [CTO implementation status](CTO_IMPLEMENTATION_STATUS.md). [Guided post creation](GUIDED_POST_CREATION.md) describes source/photo/style revisions, final review and receipts.

## Required new schema migrations

The 12 October follow-up adds **six migration files**. Apply these with the complete cumulative migration graph on the reviewed code; the earlier claim that there are no new schema migrations is retired.

| Migration | Purpose |
|---|---|
| [approvals 0005](../../../apps/approvals/migrations/0005_alter_approvalaction_action.py) | Human delivery reconciliation/account-check audit action choices. |
| [common 0003](../../../apps/common/migrations/0003_taskheartbeat.py) | Durable task-specific start/success/failure evidence. |
| [composer 0024](../../../apps/composer/migrations/0024_post_delivery_holds.py) | Parent-post durable delivery holds. |
| [media_library 0006](../../../apps/media_library/migrations/0006_mediaasset_authenticity_mediaasset_verified_at_and_more.py) | Photo authenticity, named project and human attestation fields. |
| [media_library 0007](../../../apps/media_library/migrations/0007_mediaasset_verified_asset_hash.py) | Attestation binding to current asset identity. |
| [studio 0004](../../../apps/studio/migrations/0004_agencysettings_backup_studiobrief_trust_snapshot_and_more.py) | Backup approver, trust snapshot, structured verified claims and manual campaign outcomes. |

Legacy facts/assets do not become automatically verified. Do not bulk attest old claims or images, restamp queued approvals or clear unknown holds to make migration/activation appear complete.

## Current local browser and worker evidence

- **24 Chromium interaction checks passed**, with no browser errors: desktop and 390px phone presentation, keyboard controls, real HTMX swaps, source disclosure/consent, selected draft context, reading position, focus, file preservation after validation and guarded delivery announcements/forms. Supporting Trust/Autopilot/Outcomes GETs fit both viewports. Project-photo and claim-renewal attestations were inspected unchecked, not submitted. The evidence records two targeted trust-control reruns after an accessible-image fallback fix.
- **Seven actual Django browser-flow checks passed**, with no page/HTTP errors: real login, page GETs and guided entry/answer/confirmation POSTs against isolated PostgreSQL. The required facts checkbox stopped unchecked submission; checked confirmation ran the real handler and produced a same-thread draft pending human review. Queue/source/graphic callbacks were synthetic; all non-local browser requests were blocked.
- **30 DOM state checks passed** for the thread script. These test controlled state transitions; they are separate from Chromium counts and the Python full-suite total. They do not certify a physical device or production accessibility journey.
- The new **bounded real singleton-worker rehearsal** runs the actual command for one second through the lease proxy, processes publisher/agency/confirmation empty cycles once each, persists three completed tasks and healthy heartbeats, and preserves their next recurring schedules. Timing/poll observation is controlled, while the queue runner, task bodies, lease and database are real. No workspace, AgencyJob or Post exists, so it performs no paid work or publishing. This closes the earlier mock-only worker-loop evidence gap without claiming a Railway soak/load test.

Browser JSON, verification notes and screenshots are under `agency-deliverables/user-flow-evidence/` in the final handoff. The worker rehearsal is [RealSingletonWorkerRehearsalTests](../../../apps/common/tests/test_delivery_worker_health.py). Local screenshots are not screenshots of deployed Railway.

## Production access evidence

Earlier read-only Railway health, Neopolis website and OpenRouter credential/credit metadata probes failed with **ProxyError** before usable responses. The uploaded OpenRouter credential was used only in an authorization header for its read-only metadata probe; it was not printed or included in artifacts. Its validity, balance and model access remain unknown. Subsequent read-only Railway home/health access also failed at the proxy; these failures do not establish that production is down.

No Railway credential, production database binding or usable live image-provider key is injected here. Production workspace settings, account identities, task success and actual publishing were neither verified nor changed. A draft cloud-network domain addition does not change this running environment or grant Railway access.

## Production launch gate

The CTO and Neopolis owner must complete these checks on the deployed cumulative code before claiming production readiness:

1. Review the final implementation and validation record; deploy the same reviewed commit to **both** services, apply every migration and verify durable media. **Pause/drain the old worker before the first lease-enabled rollout**; baseline code does not hold the lease. Reserve one extra PostgreSQL connection. Review queued approvals affected by destination/source changes, including the 8 October backlog; do not automatically restamp them.
2. Securely configure OpenRouter on both services, with its own key, supported namespaced model and `STUDIO_WEB_SEARCH=false`. Confirm credits, structured and visual role behavior, image-service access or consciously reviewed supplied-photo/background fallback, and actual charges. An OpenRouter key does not belong in `ANTHROPIC_API_KEY`.
3. Inspect actual Meta native identities, token lifetime and permissions. Confirm Neopolis Facebook Page `585141221346435` and actual Instagram ID/handle; separately resolve the reported More Space account mismatch. Saved metadata and read-only caption scraping do not prove publishing authorization or brand identity.
4. Verify current commercial/contact claims with source, expiry and a current permitted human, and attest actual project images to their exact file/project. Mark designer references. Set intended accounts, volume, pillars, planning time, soft budget, lead, different backup, acceptable delivery lateness and `Asia/Kolkata`.
5. Run the real guided flow: focused questions, visible website/channel evidence and warnings, explicit brief confirmation, actual model/caption/graphic generation, then photo/style revision. Check final facts and authentic imagery; approve three owner/designer campaign samples rather than inferring “perfect graphics” from a synthetic rehearsal. Complete the authenticated phone/keyboard journey.
6. Leave a draft unapproved past its proposed time: it must stay unsent. Then human-review exact graphic, captions/comments, destination and fresh future time; use **Approve & schedule**. Inspect the native ID/link and actual account exactly once. Repeat cycles without duplicates and verify a changed revision needs reapproval.
7. Rehearse recovery safely: unknown outcome remains held for account inspection; an existing-post record is a labeled human attestation, not independent provider confirmation. Checked-absent/expired recovery returns content for fresh review and future approval without sending. Editing or removing/readding a destination must not release the durable hold.
8. Observe successful publisher, agency and confirmation tasks after restart, an actual automatic draft, and live lead/backup/failure notification receipt. Compare period reports/current old backlog with actual native receipts. Carry a consented test enquiry through the existing sales workflow and record the agreed campaign attribution manually. Agree operating fallback, acceptable delay, privacy settings and support coverage before selling stronger promises.

`python manage.py live_verify --strict` or `python manage.py release --setup-brands --strict-verify` opts into critical verification. Default `--verify` remains best effort. Strict success requires selected recorded evidence but does not independently validate a human-attested receipt, premium graphics or a delivery SLA. See [live operations](../../LIVE_OPERATIONS.md) for rollout and rollback that pause/drain publishing while preserving approvals, source guards and unknown holds.

## Remaining operating limits

- The monthly budget is a soft threshold without concurrent/in-flight charge reservation. Some model/image failures lack returned cost metadata, and direct SDK retries can hide intermediate charges. Provider-reported ledger entries are not an invoice or hard spending ceiling; reconcile actual billing.
- A killed/repeatedly failed paid stage can require safe operator retry. There is no unlimited paid recovery loop. Confirm live alerts and once-only recovery rather than assuming that saved notification settings establish coverage.
- One worker uses a dedicated session lease; `--keep-locks` opts out and needs a separately validated multi-worker design. Nonpreemptive model/image work can delay publishing. The lateness hold improves stale-content safety but does not guarantee a strict delivery deadline or a Railway soak result.
- Claim/source/photo guards do not prove every generated sentence true. An owner-attested image is a human claim about property provenance. Humans must inspect current commercial facts, actual imagery, caption disclosures and final creative quality.
- Privacy copy identifies model/image processing but does not certify active provider retention, training, routing or cross-border policies. The operator must document the actual client-work configuration.
- Outcomes records manual aggregate campaign events without personal lead-data fields. It does not infer unique people, automatic website/WhatsApp attribution, CRM handoff or conversion/ROI. Agree sales ownership and attribution procedure; use existing inbox/CRM handling for actual personal enquiries.
- Report snapshots distinguish period events and current backlog observation. Earlier status history is not fully reconstructable and must not be invented. Measured memory needs successful captures within seven days, at least five measured same-account posts and three-day post maturity; designer references remain inspiration.
- Website reads are bounded, do not render JavaScript and reject unchecked redirects/compression. Unsupported/unavailable channels visibly fall back to stored successful publication history. Controlled tests do not establish live website/model/image/platform reachability.
- Facebook image publishing and both Instagram login flows have controlled provider contracts. Public media fetches, scopes and actual native delivery need the pilot. Video/Reels, carousels, first comments, asynchronous confirmation and optional networks are not certified by this image rehearsal; X credits and LinkedIn approvals remain separate gates.
- Rolling back to `05ca828` removes later source/expiry, durable-hold and lease protections. Pause/drain first, keep approval enforced and preserve unknown outcomes; schema readability alone is not safe rollback evidence.

## Validation record and historical baseline

Final 12 October validation: **3,854 passed, 1 skipped** in **460.49 seconds** on Python 3.12.14, Django 5.2.17 and PostgreSQL 16. The skip is the Redis-only cache assertion under local-memory test settings. CI-pinned Ruff lint/format, mypy, Django system checks, migration drift and the CSS build passed. Separately, all 30 DOM checks, 24 Chromium interaction checks and seven actual guided Django browser-flow checks passed. The full runner reported 1,161 warnings, which are not test failures. Focused and browser/DOM checks have separate scopes and must not be summed into the Python total.

Historical 11 October backend evidence, retained for provenance:

- Full repository run on Python 3.12.14 / Django 5.2.17 / local PostgreSQL 16: **3,574 passed, 1 skipped** in **467.37 seconds**. The skip concerned a Redis-specific filmstrip alias in a LocMem test environment; 1,099 warnings were not test failures.
- That total included 176 new baseline cases: 21 autopilot, 29 final-content, 69 usage, 15 thread/permission, 33 worker/publisher recovery, four vertical lifecycle and five native-destination cases. These are historical scope counts, not the current follow-up regression count.
- A separate selected 513-test publisher/worker/Meta run passed in 134.95 seconds with branch instrumentation. Its percentages are **retired as evidence of current source coverage**: later source/schema/UI changes invalidate their use as a current coverage claim. Nine module hashes were stable only during that historical run. Historical gaps included successful sustained lease-proxy polling; the later bounded real-loop test addresses that particular gap, not all live transport/soak behavior.
- Historical Ruff 0.15.9 checks/637-file formatting, mypy 775-file result, Django checks and migration drift passed for that earlier snapshot. They do not certify the later source, and the earlier “no schema migration” statement no longer applies.
- A malformed planner mock was corrected before the historical stable run. Its rejected payload and unstable earlier coverage profile do not supply current validation evidence.

Reproduce a current full run from the configured environment, using an isolated database:

```bash
DB_NAME=sm_bean_cto_full STUDIO_PROVIDER=anthropic .venv/bin/pytest -q --disable-warnings --maxfail=5 --reuse-db
```

`pyproject.toml` selects `config.settings.test`; PostgreSQL uses a separate `test_` database. External model/image/source/provider boundaries are guarded in tests. The final CTO handoff should contain the cumulative patch, this audit, operating/status guides, browser evidence, synthetic renderer example, authoritative validation JSON and checksums. It must contain no production credentials. This evidence establishes bounded local fault/concurrency/integration/UI behavior, not a production load test or paid-provider launch certification.
