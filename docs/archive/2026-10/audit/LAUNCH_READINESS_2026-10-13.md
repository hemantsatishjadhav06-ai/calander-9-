# SM Bean release review — 13 October 2026

SM Bean now runs the reviewed release in matching native web and worker services
at `91bef9ec9ff42b47fed80db66ca572fc5b066107`. The application supports a
**supervised operator beta**. Production AI credentials, Gmail consent, real
client/group acceptance and a completed Neopolis campaign remain outstanding.
Historical fixtures and public-route checks do not establish those outcomes.

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
| Final PR11 CI | **4,731 passed, 1 skipped, 194 subtests**; all six jobs passed on `30e4d3e0f2e018ba7725fd80cf4384cd9dc8a7c1`. The deployed merge has the identical tree. [Current CI receipt](evidence/2026-10-13/current-final-ci.json). |
| Main CI on deployed source | All six jobs passed on exact native commit `91bef9ec9ff42b47fed80db66ca572fc5b066107`. [Run38417472520](https://github.com/hemantsatishjadhav06-ai/calander-9-/actions/runs/38417472520). Main-run pytest totals were not separately inspected. |
| Canonical/cloud full builds | Both full Docker builds completed. Cloud npm/hash-checked pip stages executed; runtime assertions verified absence of the mounted secret, CA overrides and `.env`. Native Railway Web/worker both use `/Dockerfile`. |
| Live anonymous production review | **137 checks passed**, covering actual public browser/layout/navigation/fallback behavior and route/header checks. These checks do not establish authenticated client, email, paid-provider or publication acceptance. |
| Native source and services | Web `aac80bcf-d891-4541-a312-ab5452c8ea13` and worker `afc72c9f-7640-4273-9f12-d7dc9fd8b222`: SUCCESS on the same full commit, all 16 file anchors verified per service, one us-west2 replica each. |
| Native schema/security | All ten required migrations applied; pending 0; all 18 required managed-bot columns present. Physical access/refresh counts for NULL or nonblank OAuth tokens are both 0, with complete row visibility. Effective compliant storage is enabled and refresh grace is integer 0. |
| Live worker/cache | Exactly one PostgreSQL singleton lease; four registered core schedules and four actual successful recurring-cycle heartbeats. Publisher, agency and confirmation health are current. Cache roundtrip and cleanup passed. |
| HTTPS and webhook protection | Public health returns 200 with database/cache healthy; a public wrong-secret Telegram POST returns 403. These checks are separate from the real trial receiver verification. |
| Required backups | Pre-migration: 110 CSV/manifest tables, 3,761,589 bytes, after old writers were removed. Normal second-Web release: 121 CSV/manifest tables, 3,763,642 bytes. Stored manifests match source. Both use repeatable-read read-only snapshots. Daily native backups retain six days; prior snapshots are preserved. |
| Telegram trial | Actual runtime identity, active encrypted Neopolis connection, ciphertext/decryption roundtrip and native receiver match passed. READY is true in Web/worker. Personal/group pairing, real messages and approvals remain unverified. |
| Operator and canonical source | Intended real operator scope is granted; company ownership and legal/email state preserved. Only the saved website changed to `https://neopolisinfra.com/`; the canonical collector succeeds. No business claims were promoted to verified. |

The single skipped full-suite case uses Redis-specific behavior. A separate
seven-test real-Redis run passed, as recorded in earlier evidence. Targeted
suite counts overlap the full suite and are not summed into 4,731.

## Completed production rollout

The old worker was removed before the old Web. Exact IDs, native REMOVED status,
absence of old/duplicate active deployments and fresh zero locked-task/publishing
claims were checked before one authorized marker PUT. The native image had
already verified all 16 immutable file hashes and its full Git/deployment
identity. The marker was consumed and verified absent before the required
backup and migration command.

A second Web deployment then used the normal `python manage.py release --verify`
command with Telegram readiness enabled. The matching new leased worker started
after Web source/schema/readiness verification. Each service now has exactly
one matching active deployment. Automatic deployment remains held for controlled
operator releases; worker predeploy is empty. Existing encryption, storage,
database, cache and Fal configuration was preserved.

[Current rollout](evidence/2026-10-13/current-native-rollout.json) ·
[Current schema/backups](evidence/2026-10-13/current-native-schema-backups.json) ·
[Current worker](evidence/2026-10-13/current-native-worker.json) ·
[Current encrypted bot](evidence/2026-10-13/current-telegram-neopolis.json) ·
[Operator/source preparation](evidence/2026-10-13/current-neopolis-operator-website.json).

## Remaining acceptance and critical limits

OpenRouter authentication and positive credits passed through the cloud proxy,
but `OPENROUTER_API_KEY` is still absent in Railway. A proxy reference is not a
portable raw key. Install it securely for the production services, or extend
the saved binding to the authorized hosting destination before forwarding it.
Verify authentication inside the app before paid work. Existing Railway Fal
passed authenticated model metadata; billing scope and actual inference remain
unverified. An earlier cloud request to `api.fal.ai` was outside its saved
binding and does not establish an invalid underlying key.

The Gmail mailbox is unconnected. Human Terms acceptance, Google consent and
actual email delivery remain undone. Published legal pages retain draft-policy
notices; human/legal review and final operator details remain prerequisites for
commercial launch. The intended administrator can complete the normal
[Email operations](https://sm-bean-production-eb50.up.railway.app/ops/email/)
flow after personally accepting the presented Terms. Automation did not accept
Terms or verify anyone's email. Send the authorized client/team invitations
only after delivery works; assign a distinct backup after genuine acceptance.

The trial `@sammanager06_bot` is connected through encrypted workspace storage
and its receiver is verified. It reports `can_manage_bots=false`. Real people
still need their personal pairing links, and group administrators must create
and link separate client/team groups. A capable manager plus native consent, or
the supported BotFather/token flow, is required for new company bots. No child
bots, groups, approval messages or real human approvals were fabricated.
Replace the trial credential securely before customer use.

The real operator has organization-admin and workspace-manager scope with an
organization-scoped **Agency operator** role: built-in manager permissions plus
workspace-settings authority. Original company ownership remains intact. The
website-only canonical correction preserves other profile fields, approval
policy and legal/email state. Canonical collection and existing Facebook/
Instagram source reads are preparation evidence; verified business claims remain
zero. They do not prove generated campaign quality or consent to publication.

The **19–25 October 2026** Neopolis week, in Asia/Kolkata, remains empty. No new
model-generated drafts, approved schedule or publication were created. Once the
production provider works, run the actual `listen → moments → plan → brief`
workflow, review genuine copy/media and actual costs, then obtain exact human
approval before scheduling. The [worksheet](NEOPOLIS_WEEK_2026-10-19.md) contains
proposals, not delivered posts.

Stored backups do not establish a successful production restore. A single
healthy worker does not establish capacity, paid-service quotas, an SLA or
staffed support. Complete the supervised client pilot, production recovery and
native-publication checks before widening launch. The
[CTO decision](CTO_LAUNCH_DECISION_2026-10-13.md) and
[50-criterion review](USER_REVIEW_2026-10-13.md) retain these user/business limits.
Configurable software roles do not represent 50 human employees.

## Historical evidence

Earlier PR10 validation and pre-release reports described the healthy older
`05ca828b2be22d4c3a65fbdf67404961e0f13124` services. Those old services are now
removed. Four Git/CLI diagnostic builds failed before activation because the
Railway parser rejected optional `type=secret` mounts. Snapshot-scoped logs
superseded the preliminary unexplained-platform-outage diagnosis. The canonical
recipe was corrected; optional cloud CA mounts remain in a separate generated
recipe. TLS and artifact-hash verification remain enforced. The own-image
registry fallback was researched and unused.

Earlier receipts remain dated snapshots: local 49-check controlled portal/
Telegram review, local 73-check marketing review, 17 marketing tests, 30 DOM
checks, focused OAuth/schema suites, isolated container smoke and recipe-only
checks. [Earlier recipe receipt](evidence/2026-10-13/launch-fix-verification.json)
and [parser investigation](RAILWAY_BUILD_BLOCKER_2026-10-13.md) are historical;
their pending/older-source fields do not describe the current rollout. Use the
curated current receipts and [machine status](RELEASE_STATUS_2026-10-13.json)
for the present beta decision.

## Cloud environment

Reusable installation/start instructions and secure bindings are maintained in
environment settings separately from these production receipts. Frozen npm,
hash-checked Python, PostgreSQL/Redis checks and the generated cloud recipe are
part of the development workflow. Saving a draft does not execute or publish it;
a new cloud task still needs its own startup validation. Keep credentials in
secure settings and preserve existing `.env` keys.
