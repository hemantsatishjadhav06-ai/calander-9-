# SM Bean launch decision — 13 October 2026

SM Bean is deployed and technically usable as a **supervised operator beta**.
Matching web and worker services run the reviewed `91bef9ec9ff42b47fed80db66ca572fc5b066107`
release. Unrestricted customer launch and the requested Neopolis campaign remain
blocked by production provider setup and actual human acceptance.

## Current deployment and acceptance

PR [11](https://github.com/hemantsatishjadhav06-ai/calander-9-/pull/11) merged the
exact tested tree into `main`. All six final CI jobs passed: **4,731 tests passed,
1 skipped, 194 subtests**. All six main-branch checks also passed on the exact
deployed commit; their separate pytest totals have not been inspected.
[Current CI evidence](evidence/2026-10-13/current-final-ci.json).

Web `aac80bcf-d891-4541-a312-ab5452c8ea13` and worker
`afc72c9f-7640-4273-9f12-d7dc9fd8b222` are native Railway **SUCCESS** deployments,
each with one replica and all 16 immutable source anchors verified. The old
worker and web were removed in that order. Ten migrations are present, no
migration is pending, and physical OAuth access/refresh plaintext counts are
zero with complete row visibility. One PostgreSQL worker lease and four actual
successful recurring-task heartbeats were verified. Public health returns 200;
a wrong-secret Telegram POST returns 403. **137 live anonymous production checks
passed**; these checks do not prove customer onboarding or external delivery.

Required private backups were verified: 110 CSV/manifest tables before migration
and 121 after migration, with matching source manifests. Daily native backups
retain six days, and previous snapshots remain. Auto deployment stays held;
web uses its normal required-backup release command and worker predeploy is empty.
[Current rollout](evidence/2026-10-13/current-native-rollout.json) ·
[Schema and backups](evidence/2026-10-13/current-native-schema-backups.json) ·
[Worker evidence](evidence/2026-10-13/current-native-worker.json).

The intended operator received organization-admin and workspace-manager scope
with the organization-scoped **Agency operator** custom role. Original company
ownership, Terms and email-verification state were preserved. Neopolis's saved
website alone was corrected to `https://neopolisinfra.com/`; the canonical
collector now succeeds. Other profile fields and factual-claim verification were
preserved. The trial bot is now connected to Neopolis through the encrypted
flow, its native identity and receiver were verified, and webhook readiness is
true on both services. Actual people and groups remain unpaired.

## Critical review across the business

| Perspective | Current assessment | Evidence still needed for unrestricted launch |
| --- | --- | --- |
| Client usability | Public production navigation, mobile layouts and fallback behavior pass. Local controlled portal/pairing checks pass. | A real client receives access, accepts their account and reviews an actual finished draft on a phone. |
| Agency operations | Real operator authority, matching worker, successful recurring cycles and exact review boundaries are verified. | A distinct real backup accepts access; team/client groups receive their intended notifications. |
| Security and privacy | Migrated schema, plaintext-token redaction, encrypted trial connection and wrong-secret rejection pass in production. | Exercise tenant boundaries with real accepted clients; rotate the supplied trial credential before customer use. |
| Creative quality and factual accuracy | Canonical source collection works; verified business claims remain zero. | Generate and review actual copy/images against current company facts. A source website or old photograph alone does not prove a claim. |
| Reliability and recovery | Single-worker lease, durable cycle success, cache and required backups are verified. | Demonstrate production recovery, held-send handling and an actual provider pilot; stored backups alone do not prove restoration. |
| Cost and capacity | One worker is operating; the agency budget remains a soft threshold. | Observe paid-job costs, latency, quotas and intended customer load before promising capacity or an SLA. |
| Integrations | Encrypted Neopolis trial-bot connection and native receiver are verified. | Personal/group pairing, real messages, per-channel permissions and a native social publication receipt. The trial bot cannot create child bots. |
| Support and commercial launch | Early-access policies state review boundaries and operating limits. | Actual human Terms/Google consent, support staffing and client acceptance. Test counts do not establish legal review or commercial readiness. |

The [50-criterion review](USER_REVIEW_2026-10-13.md) supplies the earlier detailed
user findings. Software roles and specialist workstreams do not represent 50
human employees or establish client approval of generated creatives.

## Remaining blockers and exact actions

| Blocker | Required action |
| --- | --- |
| OpenRouter in Railway | Securely install the real key for the production services, or add `backboard.railway.com` to the existing cloud binding before forwarding it through the supported hosting API. Verify authentication inside the deployed app before paid work. Cloud authentication and credits do not supply the missing production key. Preserve existing Fal; metadata access passed, but inference remains unverified. |
| Gmail and human legal actions | The intended administrator personally signs in, accepts the presented Terms, then opens [Email operations](https://sm-bean-production-eb50.up.railway.app/ops/email/) and completes Google consent. Verify actual email delivery before invitations. No acceptance or consent was fabricated. Published legal pages retain draft-policy notices; human/legal review and final operator details remain required before commercial launch. |
| Client and backup access | Send the already-authorized invitations through the protected flow after mailbox setup. Preserve separate client/internal scopes and assign backup only after genuine acceptance. Private addresses are excluded from these reports. |
| Telegram people and groups | The encrypted trial connection is complete. Real people use their personal pairing links; group admins create and link separate team/client groups. `@sammanager06_bot` reports `can_manage_bots=false`; per-company bot creation requires a capable manager and native human consent, or the supported BotFather/token flow. |
| Neopolis 19–25 October | After provider setup, run the real `listen → moments → plan → brief` workflow. Create new educational drafts, review actual copy/graphics/costs, then obtain exact human approval before scheduling. The week is still empty; no new drafts, schedule or publication were produced. |

## Historical investigation

The four earlier Git/CLI build failures occurred before this completed rollout.
Snapshot logs established unsupported Dockerfile secret mounts; the preliminary
unexplained-platform-outage diagnosis was superseded. The canonical recipe was
corrected and both full CI builds passed. The [parser investigation](RAILWAY_BUILD_BLOCKER_2026-10-13.md)
and earlier receipts are historical evidence, not current deployment blockers.
The researched registry fallback was unused; no publishing workflow/package was created.

Use the [current status](RELEASE_STATUS_2026-10-13.json) and current receipts for
this beta decision. Public launch remains conditional on the actual acceptance
above; the Neopolis worksheet is a plan, not a delivered campaign.
