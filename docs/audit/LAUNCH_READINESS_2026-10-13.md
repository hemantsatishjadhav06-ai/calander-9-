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
| Reproducible setup | Locked DOM-test dependencies, a CI UI job and an updated Tailwind dependency fix make UI checks reproducible. The current source manifest is generated from immutable committed Git blobs and includes the managed-bot migration/schema gate. |

## Current verification

| Check | Observed result |
| --- | --- |
| Clean full PostgreSQL suite | **4,676 passed, 1 skipped**, 31 warnings; 513.68 seconds. |
| Browser review | **49 checks passed** using Chromium, including real local passwordless portal sessions, revocation, personal pairing, managed consent UI, guided briefs and phone/tablet layouts. No JavaScript errors, failed requests or HTTP 5xx were observed. Telegram/model responses in this review were controlled fixtures. |
| DOM state tests | **30 passed** from the locked root npm dependencies. |
| Lint, formatting and types | Ruff passed; 743 Python files formatted; mypy passed across 858 source files. |
| Migration and Django checks | No migration drift; application system checks passed. |
| Dependency audits | No known vulnerabilities reported by pip-audit against the frozen Python lock or npm audit for the root and theme locks at review time. |
| CSS/static assets | Tailwind build and production collectstatic passed. |
| Current release inspector | **27 focused regressions passed**, including strict manifest checks and the managed-bot migration/schema requirement. |
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
was initially unavailable. The user subsequently saved Railway, OpenRouter and
fal secret bindings, which became available to the running environment.
Authenticated live inspection and rollout are the next stage; existing Railway
variables must be inspected and preserved rather than presumed missing.

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
