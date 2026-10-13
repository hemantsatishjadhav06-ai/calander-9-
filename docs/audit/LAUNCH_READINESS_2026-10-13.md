# SM Bean release review — 13 October 2026

The uploaded update has been integrated with the preceding security and
publishing repairs. The resulting release is a tested staging candidate.
Public launch and the real Neopolis calendar remain unverified until the live
acceptance below is completed. Historical reports and synthetic fixtures do
not establish current production behavior.

## What changed

| Area | Result |
| --- | --- |
| Uploaded release | Integrated cumulative Studio, agency, blog, X and Telegram changes while preserving the preceding portal, credential, upload and publishing protections. The original upload's archive, patch and Git bundle checksums matched its supplied manifest. |
| Client Telegram access | Passwordless clients pair their own Telegram identity from their existing portal. Revoked links stop access; submitted workspace/admin scope cannot expand authority. Personal, team-group and client-group setup are separate. |
| Per-company bots | A capable manager can reserve a unique child bot, request native human consent and connect it through an authenticated managed-bot event. Reservations expire and are bound to fresh tenant, actor and pairing authority. Tokens are encrypted; a bot cannot belong to multiple workspaces. BotFather remains the supported fallback. |
| Telegram privacy and removal | Current roles, tenant and pairing state are rechecked. Removing or re-pairing people, groups or bots invalidates stale queued actions. Private references and history retain their audience boundaries. |
| Content and approval | Final review is bound to the actual revision, destination, time, sources and scoped visual bytes. Unreadable or replaced cover/thumbnail media requires renewed review. Unsupported numbered commercial claims are blocked. |
| Scheduling and delivery | Proposed slots account for occupied targets. Unknown delivery outcomes remain held for inspection; missing native receipts do not become “Published”. Telegram retry delays retain their actual duration. |
| Paid work and workers | Worker lease checks protect social, bot, model, image and research calls. A worker that loses its dedicated PostgreSQL lease stops making external requests. Preparation consent and final post approval remain separate. |
| OAuth storage | A deliberate migration verifies existing access/refresh lookup checksums before clearing reusable plaintext. Existing client-held credentials continue to authenticate and rotate; new issuance stores checksums. Refresh grace is explicitly zero. Old issuer processes must be drained, and old private backups retain their original contents. |
| Reproducible setup | Locked DOM-test dependencies, a CI UI job and an updated Tailwind dependency fix make UI checks reproducible. Manifest v2 anchors 16 immutable committed source files, requires ten release migrations and verifies managed-bot schema and zero plaintext OAuth-token counts. |

## Current verification

| Check | Observed result |
| --- | --- |
| Integrated PostgreSQL suite before the final OAuth repair | Local: **4,676 passed, 1 skipped**, 31 warnings; 513.68 seconds. First GitHub CI: **4,679 passed, 1 skipped**, plus 194 subtests. The additional final repair is covered below and the updated PR runs the full CI suite again. |
| Browser review | **49 checks passed** using Chromium, including real local passwordless portal sessions, revocation, personal pairing, managed consent UI, guided briefs and phone/tablet layouts. No JavaScript errors, failed requests or HTTP 5xx were observed. Telegram/model responses in this review were controlled fixtures. |
| DOM state tests | **30 passed** from the locked root npm dependencies. |
| Lint, formatting and types | Ruff passed; 746 Python files formatted; mypy passed across 861 source files. |
| Migration and Django checks | No migration drift; application system checks passed. |
| Dependency audits | No known vulnerabilities reported by pip-audit against the frozen Python lock or npm audit for the root and theme locks at review time. |
| CSS/static assets | Tailwind build and production collectstatic passed. |
| OAuth storage repair | **153 focused PostgreSQL tests passed**, including 15 new seeded migration/legacy authentication, rotation, replay and revocation regressions; migration drift, types, formatting and deployment checks passed. |
| Current release inspector | **64 focused regressions passed**, including manifest v2 tamper checks, current schema, actual read-only PostgreSQL counts and hidden-row refusal. |
| Redis integration | **7 passed, 0 skipped**, including the default suite's skipped case, real cache round trips and filmstrip alias separation. Isolated Redis prefixes/test database were cleaned. |
| Production container | Passed: PostgreSQL/Redis health, secure login, authenticated calendar/agency/Telegram pages, collected assets, wrong-secret webhook 403, all migrations including Telegram 0002, worker success heartbeats, one lease, overlapping worker rejection and graceful lease release. Unprivileged runtime, immutable code and writable media checked. Internal network and synthetic records; no provider/public-bot calls. |
| Secret scan | Official checksum-verified Gitleaks 8.24.3: no findings in available Git history or current source. |

The default suite uses isolated memory caches, so its Redis-specific filmstrip
case is skipped. The full-suite warnings primarily concern test-setting
overrides. Targeted agent runs overlap this suite and are not added to its count.
The container build initially exhausted this sandbox's VFS disk; that interrupted
run is not a passing test result. The clean full run above completed after
task-owned unused build cache was removed.

## Production observations and open acceptance

The public SM Bean health endpoint reported healthy database/cache, and the
landing and login pages responded successfully. These requests do not identify
the deployed source or exercise authenticated workflows. The confirmed Railway
project is `66526b2a-6a09-43d8-bedb-ecfdd37f8d8a`; authenticated project control
was initially unavailable. After the user saved secret bindings, authenticated
inspection confirmed the SM Bean production web and worker at the older
`05ca828b2be22d4c3a65fbdf67404961e0f13124` source. Both automatic deployments
were held. Explicit hosts, trusted worker proxy, OpenRouter provider/model/key
and inactive Telegram setup were staged without restarting the old services.
Matching existing encryption, database, cache, storage and fal values were
preserved. The previous wildcard host configuration would fail the new release's
deployment check; the staged configuration passes it.

A native PostgreSQL snapshot and a repeatable-read application backup were
created and independently verified. The latter contains 110 CSV tables and a
matching manifest. Storage authentication, TLS, temporary-object cleanup and
anonymous backup-access denial were checked. A bounded, fail-closed operator
gate permits migration only after the old services are removed and database
work is drained. These observations precede the final rollout; final deployed
source/runtime receipts must be recorded separately.

OpenRouter authentication and positive credits were verified without generation.
The newly supplied cloud fal key was rejected, while the existing Railway key
was accepted for model metadata and preserved. Its billing scope does not expose
credits; actual inference still needs a real workflow. Replace the cloud fal
binding securely before using it outside the existing production services.

Production has no connected Gmail mailbox/refresh token, and Neopolis has only
one current member with no agency settings or backup approver. Invitations,
password resets and emailed client links therefore need a genuine mailbox
connection. The owner's email is unverified; mandatory verification was not
enabled blindly. Public launch requires that human setup, actual delivery and a
distinct current backup. Error-tracking service and admin IP restriction also
remain operator configuration choices; production deployment checks expose them.

The trial `@sammanager06_bot` passed a read-only identity check and reported
`can_manage_bots=false`. No live webhook was changed, child bot created,
group paired or message sent. Use a genuinely capable manager for native bot
creation, or create a company bot with BotFather and enter its token in the
encrypted workspace form. Telegram group creation and passive group membership
remain human/admin responsibilities. Replace the token shared in chat before
production use.

Before merging into an automatically deployed `main`, establish Railway rollout
control, drain the old worker, pause writes, take and verify the backup, migrate
once and deploy matching web/worker source with existing encryption keys intact.
See the [controlled rollout](../TELEGRAM_RAILWAY_ROLLOUT.md). Record exact source,
deployment and runtime receipts; public health alone is insufficient.

Then complete a real client pilot: current lead and distinct backup, separate
team/client groups, actual model/image output, current business facts, authentic
or clearly disclosed illustrative imagery, exact phone approval, delivered
notifications and a native social publication receipt. Verify email delivery,
shared storage, provider permissions, actual costs and held-send recovery. This
review does not establish those commercial or external-service outcomes.

## Critical user review and Neopolis

The [50-criterion user review](USER_REVIEW_2026-10-13.md) records the interface,
security, privacy, creative-quality and operating gaps, with browser evidence.
It distinguishes implemented controls from acceptance that still needs actual
people and external services. The software's configurable agency roles are not
a claim that 50 human employees participated or that generated creatives have
passed client review.

The [19–25 October Neopolis worksheet](NEOPOLIS_WEEK_2026-10-19.md) uses fresh
official-site context and separates company claims from verified facts. No live
Neopolis drafts, approvals, schedule or publication were changed. Production
access and paired actors are required to inspect existing work, run SM Bean's
`listen → moments → plan → brief` workers, review actual outputs and update the
remaining week. Topic suggestions in the worksheet are not generated posts.

## Cloud environment

The reusable setup draft includes hash-checked Python dependencies, frozen npm
dependencies, UI checks and safe local setup that preserves existing `.env`
keys. It also records PostgreSQL tests, worker/start instructions and the
current release gates. Saving the draft does not execute it or publish the
environment: review/save it in environment settings and publish it there.
Declare credentials securely through settings; never place their values in
Git, audit receipts or chat.
