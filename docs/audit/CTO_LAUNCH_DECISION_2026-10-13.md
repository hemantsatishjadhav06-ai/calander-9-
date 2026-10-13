# SM Bean launch decision — 13 October 2026

The repaired application is a tested release candidate. Public launch is blocked:
Railway has not built or activated the new code, and real client/provider
acceptance is incomplete. The existing website remains healthy on its older
revision. Do not advertise the cumulative fixes as already live.

## Critical review across the business

| Perspective | Assessment | Required evidence before launch |
| --- | --- | --- |
| Client usability | Passwordless portal access and Telegram pairing passed local browser checks on phone/tablet. | A real invited client receives a link, pairs their own identity and reviews an actual finished draft. |
| Agency operations | Lead/backup boundaries, guided preparation, exact approval and held-send recovery are implemented. | The real team member accepts access; reminders reach distinct current people; a native publication is confirmed. |
| Security and privacy | Portal isolation, invitations, uploads, credential refresh and OAuth checksum storage have meaningful regressions. | Activate the reviewed web/worker and inspect migrated schema, zero reusable plaintext token counts and runtime source. |
| Creative quality and factual accuracy | Current claims and photo provenance are enforced; illustrative media receives disclosures. | Review actual model/image output against current Neopolis facts. Scraped company claims and old photos are not independent verification. |
| Reliability and recovery | Worker leases, uncertain-send holds and verified backups are in place. | Complete the live worker/provider pilot and a managed production recovery drill. Daily snapshots alone do not demonstrate restoration. |
| Cost and capacity | The agency budget is a soft threshold; external services have separate charges. | Observe actual job costs, delivery latency and the intended workload. One serial worker does not establish a high-volume SaaS SLA. |
| Integrations | Code supports several platforms; the trial Telegram identity is valid. | Check actual account permissions and native receipts for each advertised live channel. The trial bot cannot manage child bots. |
| Support and commercial launch | Early-access policies describe limits and responsibilities. | Confirm the actual operator/support arrangements and monitor the pilot. Technical tests do not establish legal review, staffed support or conversion performance. |

The [50-criterion review](USER_REVIEW_2026-10-13.md) contains the detailed user
findings. Eight specialist workstreams and software roles are not a claim that
50 human employees reviewed or delivered this product.

## Completed work

- Integrated the uploaded cumulative source while preserving the earlier audit
  repairs; PR [10](https://github.com/hemantsatishjadhav06-ai/calander-9-/pull/10)
  merged into `main` at `e630f34e1eaabe7ea4bfd8cb1b1ffe966d13a60f`.
- Final CI: **4,731 passed, 1 skipped**, 194 subtests; all six jobs passed.
  Additional local browser, Redis, DOM and focused security checks are recorded
  separately in the [readiness report](LAUNCH_READINESS_2026-10-13.md).
- Created the intended configured administrator through the normal Django
  command. A live password login reached the human Terms gate. Existing company
  ownership and memberships were preserved; no Terms or verification was forged.
- Verified private application backups and native PostgreSQL snapshots,
  including fresh backups after administrator creation. Enabled daily native
  backups with six-day retention and preserved earlier snapshots.
- Held automatic deployment, preserved existing encryption/storage/provider
  keys and kept the original web/worker running. Removed the mistakenly staged
  opaque OpenRouter references without triggering deployment.
- Saved reusable cloud installation/start instructions and the actual checkout
  declaration. This is draft persistence; the user still publishes the cloud
  environment through its settings.

## Remaining blockers and next actions

| Blocker | Exact next action |
| --- | --- |
| Railway build initialization | Diagnose the three failed deployment IDs in the [prepared ticket](RAILWAY_BUILD_BLOCKER_2026-10-13.md). All stopped at builder scheduling with no image or Docker/application output. No external ticket was sent. |
| Provider credential installation | Add `backboard.railway.com` to the existing cloud OpenRouter binding, or securely set the real key in both Railway services. Verify actual service authentication before paid jobs. Add `api.fal.ai` to the existing cloud fal binding for noncharging metadata checks; preserve the working Railway Fal value. |
| Gmail consent | Sign in with the configured administrator credentials, personally accept Terms, then use [Email operations](https://sm-bean-production-eb50.up.railway.app/ops/email/) → Connect Gmail and complete Google consent. Test actual sending before invitations. Cloud execution cannot operate the user's laptop or supply Google consent. |
| Client/team access | Send the two authorized invitations through the normal protected flow after deployment and mail setup. Client gets client scope; team member gets internal manager scope. Assign backup only after real acceptance. Addresses are retained privately. |
| Trial bot and identity | Supply `TELEGRAM_TRIAL_BOT_TOKEN` securely in cloud settings, or enter the token in the encrypted workspace form after activation. Pair actual people and separate client/team groups. `@sammanager06_bot` reports `can_manage_bots=false`; use BotFather or a capable manager with native human consent. |
| Neopolis 19–25 October | Run the real `listen → moments → plan → brief` workers after deployment, operator scope and provider setup. Create five new educational drafts, review actual graphics/copy/costs and retain exact human review before scheduling. No new draft, approved schedule or publication has been created yet. |

The own-container-image fallback was researched. No existing publicly pullable
SM Bean registry image was verified. New GHCR packages default to private;
temporary workflow credentials do not provide lasting Railway pull access.
Registry setup and verified image provenance are required before that path can
replace the controlled Git-source rollout. No package or publishing workflow
was created.

The [machine-readable status](RELEASE_STATUS_2026-10-13.json) and linked evidence
record the observed state. Main contains the repaired code; the public deployment
and actual Neopolis week remain pending these prerequisites.
